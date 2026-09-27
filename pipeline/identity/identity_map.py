"""Persistent project identity map.

Rules this module enforces:

1. Keys are minted once and never renumbered. The map on disk is read first;
   a rebuild only mints keys for rows it has never seen.
2. Resolution is idempotent per source row: (report_type, period, row_id)
   always returns the key it was given the first time.
3. Minting order is deterministic (rows are sorted before minting), so a
   from-scratch rebuild over the same inputs reproduces the same keys.
4. Nothing is deleted. A wrong split is fixed with `merge(loser, winner)`;
   the loser stays in the table with status="merged" and every lookup on it
   resolves to the winner through `canonical()`.
5. Uncertain matches are recorded with review_status="review" and linked
   provisionally to the best candidate. Downstream training must filter
   `review_status == "accepted"`; the app shows review links with a badge.
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from rapidfuzz import fuzz

from .config import IdentityConfig
from .normalize import name_tokens, normalize_code, normalize_name

PROJECT_COLS = [
    "project_key", "canonical_name", "name_norm", "code", "sector", "state",
    "agency", "ministry", "original_cost_cr", "sanction_year",
    "first_seen_period", "first_seen_report", "last_seen_period",
    "status", "merged_into", "created_run_id", "created_at",
]
ALIAS_COLS = [
    "source_report_type", "source_period", "source_row_id", "source_name",
    "source_code", "project_key", "match_score", "match_method",
    "review_status", "run_id", "resolved_at",
]

PRE_RANK = 200          # top candidates by raw shared tokens before IDF re-ranking
MAX_CANDIDATES = 30     # candidates actually scored per row
NUMERIC_MISMATCH_CAP = 0.60  # "package 1" vs "package 4": name similarity capped here


TOKEN_FUZZ = 85  # two tokens count as the same word at this fuzz.ratio


def fuzzy_jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    """Token overlap where near-identical tokens (typos) count as matches."""
    if not a or not b:
        return 0.0
    exact = a & b
    ra, rb = sorted(a - exact), sorted(b - exact)  # sorted: set order depends on the hash seed
    matched = len(exact)
    used: set[int] = set()
    for ta in ra:
        for j, tb in enumerate(rb):
            if j not in used and fuzz.ratio(ta, tb) >= TOKEN_FUZZ:
                used.add(j)
                matched += 1
                break
    return matched / (len(a) + len(b) - matched)


def name_similarity(a_norm: str, b_norm: str) -> float:
    """0.4 character-level (order-insensitive) + 0.6 token-level overlap.
    Differing package/phase numbers cap the score."""
    if not a_norm or not b_norm:
        return 0.0
    ta, tb = frozenset(a_norm.split()), frozenset(b_norm.split())
    char = 0.6 * fuzz.token_set_ratio(a_norm, b_norm) / 100.0 + 0.4 * fuzz.token_sort_ratio(a_norm, b_norm) / 100.0
    sim = 0.4 * char + 0.6 * fuzzy_jaccard(ta, tb)
    na = {t for t in ta if t.isdigit()}
    nb = {t for t in tb if t.isdigit()}
    if na and nb and not (na <= nb or nb <= na):
        sim = min(sim, NUMERIC_MISMATCH_CAP)
    return sim


@dataclass
class Resolution:
    project_key: str
    score: float
    method: str
    review_status: str  # accepted | review


def _period_str(v) -> str:
    ts = pd.Timestamp(v)
    return ts.strftime("%Y-%m-%d")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _txt(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s if s and s.lower() not in {"nan", "none", "na", "nil"} else None


class IdentityMap:
    def __init__(self, cfg: IdentityConfig | None = None, run_id: str | None = None):
        self.cfg = cfg or IdentityConfig()
        self.run_id = run_id or datetime.now(timezone.utc).strftime("RUN-%Y%m%d-%H%M%S")
        self._projects: dict[str, dict] = {}
        self._aliases: dict[tuple[str, str, str], dict] = {}
        self._token_index: dict[str, set[str]] = defaultdict(set)
        self._code_index: dict[str, set[str]] = defaultdict(set)
        self._next_seq = 1
        self._load()

    # ------------------------------------------------------------------ io
    def _load(self) -> None:
        cfg = self.cfg
        if cfg.projects_path.exists():
            pdf = pd.read_parquet(cfg.projects_path)
            for rec in pdf.to_dict("records"):
                self._index_project(rec)
            seqs = [int(k[len(cfg.key_prefix):]) for k in self._projects]
            self._next_seq = (max(seqs) + 1) if seqs else 1
        if cfg.aliases_path.exists():
            adf = pd.read_parquet(cfg.aliases_path)
            for rec in adf.to_dict("records"):
                self._aliases[self._alias_key(rec["source_report_type"],
                                              rec["source_period"],
                                              rec["source_row_id"])] = rec

    def save(self) -> None:
        cfg = self.cfg
        cfg.root.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.projects_frame(), cfg.projects_path)
        self._atomic_write(self.aliases_frame(), cfg.aliases_path)

    @staticmethod
    def _atomic_write(df: pd.DataFrame, path: Path) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        df.to_parquet(tmp, index=False)
        os.replace(tmp, path)

    def _audit(self, event: str, **payload) -> None:
        self.cfg.root.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id,
               "event": event, **payload}
        with open(self.cfg.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    # --------------------------------------------------------------- frames
    def projects_frame(self) -> pd.DataFrame:
        if not self._projects:
            return pd.DataFrame(columns=PROJECT_COLS)
        return pd.DataFrame(list(self._projects.values()))[PROJECT_COLS]

    def aliases_frame(self, canonical: bool = False) -> pd.DataFrame:
        if not self._aliases:
            return pd.DataFrame(columns=ALIAS_COLS)
        df = pd.DataFrame(list(self._aliases.values()))[ALIAS_COLS]
        if canonical:
            df = df.assign(project_key=df["project_key"].map(self.canonical))
        return df

    # ------------------------------------------------------------ indexing
    def _index_project(self, rec: dict) -> None:
        rec["_tokens"] = frozenset(str(rec.get("name_norm") or "").split())
        self._projects[rec["project_key"]] = rec
        if rec.get("status", "active") != "active":
            return
        for tok in rec["_tokens"]:
            self._token_index[tok].add(rec["project_key"])
        code = rec.get("code")
        if code:
            self._code_index[code].add(rec["project_key"])

    def _unindex_project(self, key: str) -> None:
        rec = self._projects[key]
        for tok in str(rec.get("name_norm") or "").split():
            self._token_index[tok].discard(key)
        if rec.get("code"):
            self._code_index[rec["code"]].discard(key)

    @staticmethod
    def _alias_key(report_type, period, row_id) -> tuple[str, str, str]:
        return (str(report_type), _period_str(period), str(row_id))

    # ---------------------------------------------------------- key logic
    def canonical(self, key: str) -> str:
        """Follow merged_into until an active project."""
        seen = set()
        while key in self._projects and self._projects[key].get("merged_into"):
            if key in seen:
                raise RuntimeError(f"merge cycle at {key}")
            seen.add(key)
            key = self._projects[key]["merged_into"]
        return key

    def _mint(self) -> str:
        key = f"{self.cfg.key_prefix}{self._next_seq:0{self.cfg.key_width}d}"
        self._next_seq += 1
        return key

    def merge(self, loser: str, winner: str, reason: str = "") -> None:
        loser, winner = self.canonical(loser), self.canonical(winner)
        if loser == winner:
            return
        self._unindex_project(loser)
        rec = self._projects[loser]
        rec["status"] = "merged"
        rec["merged_into"] = winner
        w = self._projects[winner]
        # winner inherits earliest first_seen and latest last_seen
        w["first_seen_period"] = min(w["first_seen_period"], rec["first_seen_period"])
        w["last_seen_period"] = max(w["last_seen_period"], rec["last_seen_period"])
        for f in ("code", "sector", "state", "agency", "ministry",
                  "original_cost_cr", "sanction_year"):
            if w.get(f) in (None, "") and rec.get(f) not in (None, ""):
                w[f] = rec[f]
        self._audit("merge", loser=loser, winner=winner, reason=reason)

    # --------------------------------------------------------- scoring
    def _candidates(self, tokens: frozenset[str], code: str | None) -> set[str]:
        cands: set[str] = set()
        if code and code in self._code_index:
            cands |= self._code_index[code]
        n_active = max(1, len(self._projects))
        shared: Counter = Counter()
        idf: dict[str, float] = {}
        for tok in tokens:
            keys = self._token_index.get(tok)
            if not keys or len(keys) > max(50, n_active * 0.5):
                continue  # token carries no information
            idf[tok] = math.log(n_active / len(keys)) + 1e-3
            shared.update(keys)  # C-speed
        th = self.cfg.thresholds.min_shared_tokens
        # ties break on key so a cold build gives the same result under any hash seed
        ranked = sorted(shared.items(), key=lambda kc: (-kc[1], kc[0]))[:PRE_RANK]
        top = [k for k, c in ranked if c >= th]
        # re-rank the top slice by IDF-weighted overlap so rare tokens dominate
        def weight(k: str) -> float:
            name_toks = self._projects[k]["_tokens"]
            return sum(w for t, w in idf.items() if t in name_toks)
        top.sort(key=lambda k: (-weight(k), k))
        cands.update(top[:MAX_CANDIDATES])
        return {k for k in cands if self._projects[k].get("status", "active") == "active"}

    def _score(self, row: dict, cand: dict) -> tuple[float, str, bool]:
        w = self.cfg.weights
        parts: list[tuple[float, float]] = []  # (weight, value)
        name_sim = name_similarity(row["name_norm"], cand["name_norm"] or "")
        parts.append((w.name, name_sim))
        code_match = None
        if row["code"] and cand.get("code"):
            code_match = 1.0 if row["code"] == cand["code"] else 0.0
            parts.append((w.code, code_match))
        if row["cost"] is not None and _num(cand.get("original_cost_cr")) is not None:
            a, b = row["cost"], _num(cand["original_cost_cr"])
            prox = 1.0 - min(abs(a - b) / max(a, b, 1e-9), 1.0)
            parts.append((w.cost, prox))
        for field_name, weight in (("state", w.state), ("sector", w.sector), ("agency", w.agency)):
            rv, cv = row[field_name], _txt(cand.get(field_name))
            if rv and cv:
                parts.append((weight, 1.0 if normalize_name(rv) == normalize_name(cv) else 0.0))
        if row["year"] is not None and _num(cand.get("sanction_year")) is not None:
            parts.append((w.year, max(0.0, 1.0 - abs(row["year"] - _num(cand["sanction_year"])) / 3.0)))
        total_w = sum(p[0] for p in parts)
        score = sum(p[0] * p[1] for p in parts) / total_w if total_w else 0.0
        if code_match == 0.0:
            # Two different vetted codes are two projects: never link, not even for review.
            score = min(score, self.cfg.thresholds.review - 1e-3)
        method = "code_exact" if code_match == 1.0 else "name_attrs"
        code_conflict = code_match == 1.0 and name_sim < self.cfg.thresholds.code_conflict_name_sim
        return score, method, code_conflict

    # --------------------------------------------------------- resolution
    def _row_view(self, r: pd.Series) -> dict:
        c = self.cfg.columns
        name = _txt(r.get(c.name))
        return {
            "name": name,
            "name_norm": normalize_name(name),
            "tokens": name_tokens(name),
            "code": normalize_code(_txt(r.get(c.code))),
            "sector": _txt(r.get(c.sector)),
            "state": _txt(r.get(c.state)),
            "agency": _txt(r.get(c.agency)),
            "ministry": _txt(r.get(c.ministry)),
            "cost": _num(r.get(c.original_cost_cr)),
            "year": _num(r.get(c.sanction_year)),
        }

    def resolve_batch(self, df: pd.DataFrame,
                      manual: pd.DataFrame | None = None) -> pd.DataFrame:
        """Resolve every source row to a project_key.

        Returns `df` with columns project_key, match_score, match_method,
        review_status appended. Rows already in the alias table are returned
        unchanged (idempotent). `manual` may carry
        (source_report_type, source_period, source_row_id, project_key) overrides.
        """
        c = self.cfg.columns
        for col in (c.source_report_type, c.source_period, c.source_row_id, c.name):
            if col not in df.columns:
                raise KeyError(f"input is missing required column {col!r}")
        manual_idx: dict[tuple, str] = {}
        if manual is not None and len(manual):
            for rec in manual.to_dict("records"):
                manual_idx[self._alias_key(rec["source_report_type"], rec["source_period"],
                                           rec["source_row_id"])] = rec["project_key"]

        # deterministic order: period, report type, row id
        order = df.sort_values([c.source_period, c.source_report_type, c.source_row_id],
                               kind="mergesort").index
        out = {"project_key": {}, "match_score": {}, "match_method": {}, "review_status": {}}
        now = datetime.now(timezone.utc).isoformat()

        for idx in order:
            r = df.loc[idx]
            akey = self._alias_key(r[c.source_report_type], r[c.source_period], r[c.source_row_id])
            cached = self._aliases.get(akey)
            if cached is not None and (akey not in manual_idx or cached["match_method"] == "manual"):
                res = Resolution(cached["project_key"], cached["match_score"], "alias_cache",
                                 cached["review_status"])
            elif akey in manual_idx:
                target = manual_idx[akey]
                if str(target).upper() == "NEW":
                    res = self._mint_from_row(self._row_view(r), akey, "manual", "accepted")
                else:
                    if target not in self._projects:
                        raise KeyError(f"manual link to unknown project_key {target!r}")
                    self._touch_project(self.canonical(target), self._row_view(r), akey[1])
                    res = Resolution(target, 1.0, "manual", "accepted")
                self._audit("manual", row=akey, project_key=res.project_key)
            else:
                res = self._resolve_new(self._row_view(r), akey)
            if res.method != "alias_cache":
                self._record_alias(akey, r, res, now)
            out["project_key"][idx] = self.canonical(res.project_key)
            out["match_score"][idx] = res.score
            out["match_method"][idx] = res.method
            out["review_status"][idx] = res.review_status

        result = df.copy()
        for k, v in out.items():
            result[k] = pd.Series(v)
        return result

    def _resolve_new(self, row: dict, akey: tuple) -> Resolution:
        th = self.cfg.thresholds
        best_key, best_score, best_method, best_conflict = None, -1.0, "", False
        code_key, code_score, code_conflict = None, -1.0, False
        for k in sorted(self._candidates(row["tokens"], row["code"])):
            score, method, conflict = self._score(row, self._projects[k])
            if score > best_score:
                best_key, best_score, best_method, best_conflict = k, score, method, conflict
            if method == "code_exact" and score > code_score:
                code_key, code_score, code_conflict = k, score, conflict
        if best_key is not None and best_score >= th.review:
            status = "accepted" if (best_score >= th.accept and not best_conflict) else "review"
            if status == "accepted":
                self._touch_project(best_key, row, akey[1])
            return Resolution(best_key, round(best_score, 4), best_method, status)
        # Below the review threshold, but a printed code matched an existing
        # project. Codes are strong evidence unless the name contradicts them.
        if code_key is not None:
            if not code_conflict:
                return Resolution(code_key, round(code_score, 4), "code_exact", "review")
            new_status, new_method = "review", "code_conflict"
        else:
            new_status, new_method = "accepted", "new"
        return self._mint_from_row(row, akey, new_method, new_status)

    def _mint_from_row(self, row: dict, akey: tuple, method: str, status: str) -> Resolution:
        key = self._mint()
        self._index_project({
            "project_key": key, "canonical_name": row["name"], "name_norm": row["name_norm"],
            "code": row["code"], "sector": row["sector"], "state": row["state"],
            "agency": row["agency"], "ministry": row["ministry"],
            "original_cost_cr": row["cost"], "sanction_year": row["year"],
            "first_seen_period": akey[1], "first_seen_report": akey[0],
            "last_seen_period": akey[1], "status": "active", "merged_into": None,
            "created_run_id": self.run_id, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._audit("mint", project_key=key, name=row["name"], report=akey[0], period=akey[1],
                    method=method)
        return Resolution(key, 1.0, method, status)

    def _touch_project(self, key: str, row: dict, period: str) -> None:
        rec = self._projects[key]
        rec["last_seen_period"] = max(rec["last_seen_period"], period)
        for f, v in (("code", row["code"]), ("sector", row["sector"]), ("state", row["state"]),
                     ("agency", row["agency"]), ("ministry", row["ministry"]),
                     ("original_cost_cr", row["cost"]), ("sanction_year", row["year"])):
            if rec.get(f) in (None, "") and v not in (None, ""):
                rec[f] = v
                if f == "code":
                    self._code_index[v].add(key)

    def _record_alias(self, akey: tuple, r: pd.Series, res: Resolution, now: str) -> None:
        c = self.cfg.columns
        self._aliases[akey] = {
            "source_report_type": akey[0], "source_period": akey[1], "source_row_id": akey[2],
            "source_name": _txt(r.get(c.name)), "source_code": _txt(r.get(c.code)),
            "project_key": res.project_key, "match_score": res.score,
            "match_method": res.method, "review_status": res.review_status,
            "run_id": self.run_id, "resolved_at": now,
        }

    # ---------------------------------------------------------- helpers
    def review_queue(self) -> pd.DataFrame:
        """Rows a human should confirm; resolve them by adding to manual_links."""
        df = self.aliases_frame()
        return df[df["review_status"] == "review"].sort_values("match_score")

    def keys(self, active_only: bool = True) -> Iterable[str]:
        for k, rec in self._projects.items():
            if not active_only or rec.get("status", "active") == "active":
                yield k
