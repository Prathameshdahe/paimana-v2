"""The nightly job `second_opinion`: the LLM second opinion (llm/second_opinion.py) on the riskiest projects whose
current evidence has none yet, fitted in between the chat answers.

batch_keys() orders the Critical, High and Watch projects by when they last got an opinion (never first), then by
tier and the riskiest first. run(keys, limit) takes them in turn and, for each, builds the evidence pack and skips it
when it is not scored, has no evidence about the project itself (second_opinion.has_evidence: nothing but the status
line and the model) or already has an opinion, accepted or rejected, under the current PROMPT_VERSION for its
evidence_hash and LLM model (a rejection is not asked again every night: only when the evidence or the prompt
changes). Otherwise it waits while a chat request uses the LLM (client.wait_chat_idle, at most PAUSE_MAX_S) and asks
(second_opinion.generate as a background job: the gate lets chat requests go first; fresh, so an opinion made under
an older prompt is redone), until `limit` projects were asked (SECOND_OPINION_PER_RUN, default 15). LM Studio down, or
busy past the waits, ends the run early (status 'partial', or 'error' when nothing was asked); the projects done keep
their opinions. One run at a time (a module lock: a second call returns busy); a run given keys records
db.record_job('second_opinion', ...), with the counts per status and concern level.

Speed on the laptop (qwen2.5-coder-14b, about 3 to 4 tokens/s out): an opinion is one call of 20 to 40 s when LM
Studio is free, about twice that with the retry, so a run of 15 takes about 5 to 15 minutes.
"""
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone

from backend import db, serving
from llm import client
from llm import second_opinion as so

RISKY_TIERS = ("Critical", "High", "Watch")
PAUSE_MAX_S = 600.0
_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("SECOND_OPINION_JOB", "1") != "0"


def per_run() -> int:
    return int(os.environ.get("SECOND_OPINION_PER_RUN", 15))


def busy() -> bool:
    return _lock.locked()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def due(key: str) -> str:
    """'due', or why the job skips the project: 'not_scored', 'no_evidence' or 'up_to_date'."""
    p = so.pack(key)
    if p is None:
        return "not_scored"
    if not so.has_evidence(p):
        return "no_evidence"
    row = db.second_opinion(key, so.evidence_hash(p), client.LLM_CHAT_MODEL)
    return "up_to_date" if row and row.get("prompt_version") == so.PROMPT_VERSION else "due"


def batch_keys() -> list[str]:
    """The Critical, High and Watch projects, least recently opined first (never first), then by tier, then the
    riskiest (p_any_2q; the Watch tier has none) and key."""
    last = db.second_opinion_times()
    rank = {t: i for i, t in enumerate(RISKY_TIERS)}
    rows = [r for t in RISKY_TIERS for r in serving.in_tier(t)]
    return [r["project_key"] for r in sorted(rows, key=lambda r: (
        last.get(r["project_key"]) or "", rank[r["tier"]], -(r["p_any_2q"] or 0), r["project_key"]))]


def run(keys: list[str], limit: int | None = None) -> dict:
    """Ask for the second opinions of these projects that are due (module docstring), at most limit; a call while
    one runs returns busy."""
    if not _lock.acquire(blocking=False):
        return {"busy": True}
    started, t0 = _now(), time.time()
    try:
        stats, asked, stopped = Counter(), [], None
        for key in keys:
            if limit is not None and len(asked) >= limit:
                break
            why = due(key)
            if why != "due":
                stats[why] += 1
                continue
            if not client.wait_chat_idle(PAUSE_MAX_S):
                stopped = f"a chat answer kept the LLM busy for {PAUSE_MAX_S:.0f} s"
                break
            out = so.generate(key, interactive=False, fresh=True)
            if out["status"] == "llm_unavailable":
                stopped = out["detail"]
                break
            asked.append(key)
            stats[out["status"]] += 1
            stats["llm_ms"] += out.get("llm_ms") or 0
            if out["status"] == "ok":
                stats[f"concern_{out['concern']}"] += 1
        llm_ms = stats.pop("llm_ms", 0)
        out = {"asked": len(asked), "keys": asked, **stats, "llm_seconds": round(llm_ms / 1000, 1),
               "seconds": round(time.time() - t0, 1), "stopped": stopped}
        if keys:
            db.record_job("second_opinion", started, "ok" if stopped is None else "partial" if asked else "error",
                          out)
        return out
    finally:
        _lock.release()


def batch() -> dict:
    return run(batch_keys(), limit=per_run())
