"""llm/rag.py: filters before ranking (visibility, scope, kinds, project), reciprocal rank fusion, the fingerprint
and embedding reuse, keyword-only fallback, markdown chunking, and the real chunks' public/official split. The
embedder is a fake (hashed bag of words); LM Studio is never called."""
import hashlib
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.access import Viewer  # noqa: E402
from llm import client, rag  # noqa: E402

DIM = 64
SYNONYMS = {"frozen": "stalled", "works": "progress"}  # what the fake embedder "understands" and TF-IDF does not


def hash_vectors(texts):
    out = np.zeros((len(texts), DIM), np.float32)
    for i, t in enumerate(texts):
        for w in re.findall(r"[a-z]+", t.lower()):
            w = SYNONYMS.get(w, w)
            out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(n > 0, n, 1)


def chunk(id_, kind, vis, text, key=None, **kw):
    return rag._chunk(id_, kind, vis, kw.pop("title", id_), text, kw.pop("source", "test"), project_key=key, **kw)


CHUNKS = [
    chunk("help:0", "help", "public", "The Watch tier: the reports give no anticipated completion date."),
    chunk("help:1", "help", "public", "The Stalled badge: no progress for two quarters; the tier stays."),
    chunk("doc:0", "doc", "official", "Internal method note: SHAP drivers explain the Watch tier order."),
    chunk("project:PRJ-A", "project", "public", "Alpha bridge in Karnataka. Land acquisition delay on the highway.",
          "PRJ-A"),
    chunk("project:PRJ-B", "project", "public", "Beta highway in Kerala. Land acquisition pending for the bypass.",
          "PRJ-B"),
    chunk("news:1:PRJ-A", "news", "official", "Villagers protest land acquisition for the Alpha bridge.", "PRJ-A",
          url="https://example.org/a"),
    chunk("event:PRJ-B:land:1", "event", "public", "Beta highway remark: land acquisition not complete.", "PRJ-B",
          official_source="Project report remarks, QR_2019.pdf p. 12"),
    chunk("glossary:0", "glossary", "public", "Delay categories: land, forest, court case, contractor."),
]
OFFICIAL = {c["id"] for c in CHUNKS if c["visibility"] == "official"}
PUBLIC, IPMD = Viewer("public"), Viewer("ipmd_analyst")


@dataclass(frozen=True)
class ScopedViewer:  # an agency or ministry official without the serving lookup: role and keys are all rag reads
    role: str
    keys: frozenset


@pytest.fixture
def env(tmp_path, monkeypatch):
    rag.reset()
    monkeypatch.setattr(rag, "RAG_DIR", tmp_path / "rag")
    monkeypatch.setattr(client, "_down_at", -1e9)
    state = {"fp": "fp1", "chunks": CHUNKS, "builds": 0, "embedded": []}
    monkeypatch.setattr(rag, "fingerprint", lambda: state["fp"])

    def build_chunks():
        state["builds"] += 1
        return [dict(c) for c in state["chunks"]]

    def embed(texts, **kw):
        state["embedded"] += list(texts)
        return hash_vectors(texts)
    monkeypatch.setattr(rag, "build_chunks", build_chunks)
    monkeypatch.setattr(client, "embed", embed)
    yield state
    rag.reset()


def ids(hits):
    return [h["id"] for h in hits]


# ------------------------------------------------------------------ filters before ranking

def test_public_never_sees_official_chunks(env):
    rag.ensure_index(background=False)
    for q in ("SHAP drivers method note", "villagers protest land acquisition", "Watch tier", "Alpha bridge"):
        hits = rag.search(q, PUBLIC, k=10)
        assert hits and not OFFICIAL & set(ids(hits)), q
    assert rag.search("villagers protest", PUBLIC, kinds={"news"}) == []
    assert rag.search("SHAP drivers", PUBLIC, kinds={"doc"}) == []
    assert ids(rag.search("villagers protest", IPMD, k=1)) == ["news:1:PRJ-A"]
    assert "doc:0" in ids(rag.search("SHAP drivers method note", IPMD))


def test_official_source_only_for_officials(env):
    rag.ensure_index(background=False)
    pub = rag.search("remark land acquisition not complete", PUBLIC, kinds={"event"})
    off = rag.search("remark land acquisition not complete", IPMD, kinds={"event"})
    assert pub[0]["source"] == "test" and off[0]["source"].endswith("p. 12")
    assert set(pub[0]) == {"id", "kind", "title", "text", "source", "url", "date", "project_key", "score"}


def test_agency_scope_filters_project_chunks(env):
    rag.ensure_index(background=False)
    agency = ScopedViewer("agency_official", frozenset({"PRJ-A"}))
    hits = rag.search("land acquisition highway Kerala Beta", agency, k=10)
    assert hits and all(h["project_key"] in (None, "PRJ-A") for h in hits)
    assert "news:1:PRJ-A" in ids(hits) or "project:PRJ-A" in ids(hits)
    assert {"project:PRJ-B", "event:PRJ-B:land:1"} <= set(ids(rag.search("land acquisition Kerala Beta", IPMD,
                                                                            k=10)))
    assert rag.search("Beta", agency, project_key="PRJ-B") == []


def test_kind_and_project_filters(env):
    rag.ensure_index(background=False)
    hits = rag.search("tier", IPMD, k=10, kinds={"help"})
    assert hits and {h["kind"] for h in hits} == {"help"}
    hits = rag.search("land acquisition", IPMD, k=10, project_key="PRJ-B")
    assert hits and {h["project_key"] for h in hits} == {"PRJ-B"}
    assert rag.search("", IPMD) == [] and rag.search("tier", IPMD, k=0) == []


# ------------------------------------------------------------------ ranking

def test_rrf_order():
    fused = rag.rrf([[1, 2, 3], [3, 1]])
    assert [i for i, _ in fused] == [1, 3, 2]
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62) and fused[2][1] == pytest.approx(1 / 62)
    assert [i for i, _ in rag.rrf([[5], [6]])] == [5, 6]  # a tie keeps the order of first appearance
    assert rag.rrf([]) == []


def test_meaning_match_needs_embeddings(env, monkeypatch):
    rag.ensure_index(background=False)
    assert rag.current().dense_ready
    # no word of the question is in any chunk: only the embedder can find the Stalled badge
    assert ids(rag.search("frozen works", PUBLIC, k=1)) == ["help:1"]

    def down(texts, **kw):
        raise client.LLMConnectionError("LM Studio unreachable")
    monkeypatch.setattr(client, "embed", down)
    rag._query_failed_at = -1e9
    assert rag.search("frozen works", PUBLIC) == []                      # keywords only: nothing matches
    assert "help:0" in ids(rag.search("Watch tier", PUBLIC))            # and keyword questions still work
    assert time.monotonic() - rag._query_failed_at < rag.QUERY_RETRY_S


def test_lexical_fallback_when_embeddings_fail(env, monkeypatch):
    def down(texts, **kw):
        raise client.LLMConnectionError("LM Studio unreachable")
    monkeypatch.setattr(client, "embed", down)
    idx = rag.ensure_index(background=False)
    assert idx is not None and not idx.has_emb.any() and not idx.dense_ready
    assert ids(rag.search("Watch tier", PUBLIC, k=1)) == ["help:0"]
    assert (rag.RAG_DIR / "chunks.parquet").exists() and not (rag.RAG_DIR / "embeddings.npy").exists()
    # LM Studio back: the next check (after the retry wait) embeds the same chunks without re-chunking them
    monkeypatch.setattr(client, "embed", lambda texts, **kw: hash_vectors(texts))
    monkeypatch.setattr(rag, "CHECK_S", 0)
    monkeypatch.setattr(rag, "_embed_failed_at", -1e9)
    idx = rag.ensure_index(background=False)
    assert idx.has_emb.all() and env["builds"] == 1


def test_rag_embed_off_never_calls_the_embedder(env, monkeypatch):
    monkeypatch.setattr(rag, "EMBED", False)
    idx = rag.ensure_index(background=False)
    assert env["embedded"] == [] and not idx.has_emb.any()
    assert ids(rag.search("Watch tier", PUBLIC, k=1)) == ["help:0"] and env["embedded"] == []


def test_search_never_raises_without_an_index(env, monkeypatch):
    def broken():
        raise RuntimeError("gold files missing")
    monkeypatch.setattr(rag, "build_chunks", broken)
    monkeypatch.setattr(rag, "WAIT_S", 5)
    t0 = time.monotonic()
    assert rag.search("Watch tier", PUBLIC) == []      # the failed build ends the wait early
    assert time.monotonic() - t0 < 5
    while rag._build_lock.locked():
        time.sleep(0.01)
    assert rag.current() is None and time.monotonic() - rag._build_failed_at < 5
    with pytest.raises(RuntimeError, match="gold files missing"):  # the CLI and tests see the error
        rag._build_failed_at = -1e9
        rag.ensure_index(background=False)


# ------------------------------------------------------------------ staleness and reuse

def test_fingerprint_staleness_and_embedding_reuse(env, monkeypatch):
    rag.ensure_index(background=False)
    assert env["builds"] == 1 and len(env["embedded"]) == len(CHUNKS)
    assert all(t.startswith(rag.DOC_PREFIX) for t in env["embedded"])
    rag.ensure_index(background=False)          # within CHECK_S: not even checked
    monkeypatch.setattr(rag, "CHECK_S", 0)
    rag.ensure_index(background=False)          # checked, same fingerprint: nothing to do
    assert env["builds"] == 1

    changed = [dict(c) for c in CHUNKS]
    changed[3]["text"] = "Alpha bridge in Karnataka. Land acquisition complete; work resumed."
    env["chunks"], env["fp"] = changed, "fp2"
    idx = rag.ensure_index(background=False)
    assert env["builds"] == 2 and idx.fingerprint == "fp2"
    assert len(env["embedded"]) == len(CHUNKS) + 1          # only the changed chunk was embedded again
    assert "resumed" in rag.search("work resumed", IPMD, k=1)[0]["text"]

    rag.reset()                                  # a restart: the saved index is current, so it is only loaded
    monkeypatch.setattr(rag, "CHECK_S", 0)
    idx = rag.ensure_index(background=False)
    assert env["builds"] == 2 and idx.fingerprint == "fp2" and idx.dense_ready
    assert idx.rows[0]["project_key"] is None and idx.rows[6]["official_source"].endswith("p. 12")
    assert idx.emb.dtype == np.float16


def test_background_build_serves_when_done(env):
    rag.ensure_index(background=True)
    hits = rag.search("Watch tier", PUBLIC)       # waits for the first index (WAIT_S)
    assert "help:0" in ids(hits)
    deadline = time.monotonic() + 10
    while rag._build_lock.locked() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert rag.current().has_emb.all()


# ------------------------------------------------------------------ chunking

def test_md_chunks_bounds_headings_and_fences():
    words = " ".join(f"w{i}" for i in range(800))
    md = "\n".join([
        "# Guide", "intro text [a link](https://example.org) and **bold**", "",
        "## Short one", "a few words here", "", "## Empty parent", "### Child", "child text " * 30, "",
        "## Long one", words, "", "## Code", "```", "# not a heading", "```", "tail " * 200])
    title, chunks = rag.md_chunks(md)
    assert title == "Guide"
    sizes = [rag._words(t) for _, t in chunks]
    assert all(n <= rag.MAX_WORDS for n in sizes)
    # a chunk is small only when the next one could not be added to it
    assert all(a >= rag.MIN_WORDS or a + b > rag.MAX_WORDS for a, b in zip(sizes, sizes[1:]))
    assert sizes[0] >= rag.MIN_WORDS  # the small sections merged into the first piece of the long one
    text = "\n".join(t for _, t in chunks)
    assert "a link" in text and "https://" not in text and "**" not in text
    assert "# not a heading" in text and not any("not a heading" in t for t, _ in chunks)
    assert any("Empty parent > Child" in t for t, _ in chunks)


def test_project_card_is_plain_public_facts():
    r = {"key": "PRJ-X", "name": "Test Road", "sector": "Roads & Highways", "state": "Kerala",
         "ministry": "Ministry of Road Transport & Highways", "agency": "NHAI", "tier": "High", "stalled": True,
         "p_any_2q": 0.4321, "anticipated_cost_cr": 1234.56, "original_cost_cr": 1000.0, "expenditure_cr": None,
         "physical_progress_pct": 55.0, "anticipated_completion": "2027-03-31", "scheduled_completion": None,
         "slip_to_date_months": 12.0, "obs_period": "2026-07-01", "flags": ["land", "early_notice"],
         "sanction_date": None}
    text = rag.project_card(r, ["Land for the project is not fully acquired yet."])
    assert "Risk tier: High." in text and "43%" in text and "Rs 1,234.6 crore" in text and "March 2027" in text
    assert "Stalled" in text and "Land for the project" in text and "early notice" in text
    assert "spent" not in text and "None" not in text
    assert "Watch" in rag.project_card({**r, "tier": "Watch", "p_any_2q": None}, [])


def test_research_chunks_from_the_sweep_and_the_agent(tmp_path, monkeypatch):
    import sqlite3

    import pandas as pd
    facts = pd.DataFrame([
        {"fact_id": "f1", "project_key": "PRJ-A", "category": "natural_event", "direction": "negative", "severity": 2,
         "event_date": pd.Timestamp("2026-08-01"), "date_precision": "month", "published_date": pd.Timestamp(
             "2026-08-19"), "status": "unknown", "summary": "Water burst into the tail race tunnel; work stopped.",
         "headline": "Search operation ends at the project", "source": "Water Power", "url": "https://x.org/1",
         "live": True},
        {"fact_id": "f2", "project_key": "PRJ-B", "category": "land", "direction": "positive", "severity": None,
         "event_date": None, "date_precision": None, "published_date": None, "status": "resolved",
         "summary": "Land handed over.", "headline": None, "source": None, "url": "https://x.org/2", "live": False}])
    facts.to_parquet(tmp_path / "research_facts.parquet")
    pd.DataFrame([{"project_key": "PRJ-A", "researched_on": "2026-09-28", "latest_status": "Unit-1 in 2027."},
                  {"project_key": "PRJ-B", "researched_on": "2026-09-28", "latest_status": None}]).to_parquet(
        tmp_path / "research_projects.parquet")
    dbp = tmp_path / "app.db"
    with sqlite3.connect(dbp) as con:
        con.execute("CREATE TABLE research_facts (project_key, category, direction, severity, event_date, summary, "
                    "headline, source, url)")
        con.executemany("INSERT INTO research_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            ("PRJ-A", "land", "negative", 2, "2026-07", "A duplicate of the sweep's URL.", "h", "s", "https://x.org/1"),
            ("PRJ-A", "contractor", "negative", 3, "2026-09-01", "Contractor terminated.", "Contract ends", "Paper",
             "https://x.org/3")])
    monkeypatch.setattr(rag, "RESEARCH_FACTS", tmp_path / "research_facts.parquet")
    monkeypatch.setattr(rag, "RESEARCH_PROJECTS", tmp_path / "research_projects.parquet")
    monkeypatch.setenv("PAIMANA_DB", str(dbp))
    out = {c["id"]: c for c in rag.research_chunks({"PRJ-A": ("Alpha hydro", "Alpha hydro (PRJ-A, Power)"),
                                                     "PRJ-B": ("Beta road", "Beta road (PRJ-B)")})}
    agent_id = "research:" + hashlib.sha256(b"PRJ-A|https://x.org/3").hexdigest()[:12]
    assert set(out) == {"research:f1", "research:f2", agent_id, "research:PRJ-A:status"}  # the duplicate URL went
    f1 = out["research:f1"]
    assert f1["visibility"] == "public" and f1["url"] == "https://x.org/1" and f1["date"] == "2026-08"
    assert "a live blocker" in f1["text"] and "severity 2 of 3" in f1["text"]
    assert "Water Power, 2026-08-19" in f1["text"] and out[agent_id]["date"] == "2026-09-01"
    assert out["research:f2"]["title"] == "Land handed over." and "None" not in out["research:f2"]["text"]
    assert "Unit-1 in 2027." in out["research:PRJ-A:status"]["text"]


# ------------------------------------------------------------------ the real chunks

@pytest.fixture(scope="module")
def real_chunks(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PAIMANA_DB", str(tmp_path_factory.mktemp("nodb") / "absent.db"))
        chunks = rag.build_chunks()
        assert not Path(rag.db.path()).exists()  # reading the app database never creates it
        yield chunks


def test_real_chunks_visibility(real_chunks):
    by_kind = {}
    for c in real_chunks:
        by_kind.setdefault(c["kind"], set()).add(c["visibility"])
    assert {"help", "doc", "project", "event", "external", "glossary"} <= set(by_kind)
    assert by_kind["help"] == by_kind["project"] == by_kind["event"] == {"public"}
    assert by_kind["doc"] == {"official"} and by_kind.get("news", {"official"}) == {"official"}
    docs = {c["source"] for c in real_chunks if c["kind"] == "doc"}
    assert "README.md" in docs and not any("PROJECT_DOCUMENTATION" in d or "mock" in d for d in docs)
    public = [c for c in real_chunks if c["visibility"] == "public"]
    assert not any(re.search(r"(?:shap|p95|p05|tier_rank)|FP/[A-Z]{2}/", c["text"], re.I)
                   for c in public if c["kind"] in ("project", "external", "help"))
    assert all(c["id"].startswith("parivesh:") for c in real_chunks
               if c["kind"] == "external" and c["visibility"] == "official")
    card = next(c for c in real_chunks if c["id"] == "project:PRJ-000698")
    assert "Pipalkoti" in card["text"] and "%" in card["text"] and card["project_key"] == "PRJ-000698"
    assert all(c["official_source"] and ".pdf" in c["official_source"] and ".pdf" not in c["source"]
               for c in real_chunks if c["kind"] == "event")


def test_real_index_redacts_sources_for_the_public(real_chunks):
    idx = rag.build_index(real_chunks, "test")
    pub = idx.search("land acquisition pending", PUBLIC, k=5, kinds={"event"})
    off = idx.search("land acquisition pending", IPMD, k=5, kinds={"event"})
    assert pub and ids(pub) == ids(off)
    assert all(".pdf" not in h["source"] for h in pub) and all(".pdf" in h["source"] for h in off)
    top = idx.search("Pipalkoti", PUBLIC, k=3)  # the name finds the card first (title ranking)
    assert ids(top)[0] == "project:PRJ-000698" and {h["project_key"] for h in top} == {"PRJ-000698"}
    karnataka = idx.search("land acquisition Karnataka", PUBLIC, k=5, kinds={"event"})
    assert sum("Karnataka" in h["text"] for h in karnataka) >= 3  # events carry their project's state
