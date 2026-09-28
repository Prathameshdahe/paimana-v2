"""The nightly job `second_opinion`: the LLM second opinion (llm/second_opinion.py) on the riskiest projects whose
current evidence has none yet, fitted in between the chat answers.

batch_keys() orders the Critical, High and Watch projects by when they were last asked (never first), then by
tier and the riskiest first. The job works in the plain view (second_opinion.pack's default: the pack without the
model's numbers, the opinion every official reads); the developer's numbers view is asked for on demand. run(keys, limit) takes them in turn and, for each, builds the evidence pack and skips it
when it is not scored, has no evidence about the project itself (second_opinion.has_evidence: nothing but the status
line and the model) or was already asked under the current PROMPT_VERSION for its evidence_hash and LLM model: an
opinion accepted or rejected under it, or a rejection under it noted on an older prompt's accepted opinion
(last_rejected), so a rejection is not asked again every night, only when the evidence or the prompt changes. An
accepted opinion that fails a check tightened since (second_opinion._accepted) is due again: it is no longer served.
Otherwise it waits while a chat request uses the LLM (client.wait_chat_idle, at most PAUSE_MAX_S) and asks
(second_opinion.generate as a background job: the gate lets chat requests go first, also between an opinion's first
ask and its retry; fresh, so an opinion made under an older prompt is redone), until `limit` projects were asked
(SECOND_OPINION_PER_RUN, default 15). LM Studio down, busy past the waits, or the stop flag (stop(): the scheduler
sets it at shutdown and when a run overruns its time limit; checked between projects, inside the waits and before
each ask) ends the run early (status 'partial', or 'error' when nothing was asked); the projects done keep their
opinions. One run at a time (a module lock: a second call returns busy); a run given keys records
db.record_job('second_opinion', ...) with counts only (per status and concern level): the projects it asked are
logged, never stored in the summary, which officials of every scope read in /api/jobs and /api/live/status.

Speed on the laptop (qwen2.5-coder-14b, about 3 to 4 tokens/s out): an opinion is one call of 20 to 40 s when LM
Studio is free, about twice that with the retry, so a run of 15 takes about 5 to 15 minutes.
"""
import logging
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
STOPPED = "the run was stopped (shutdown, or past the job's time limit)"
_lock = threading.Lock()
_stop = threading.Event()   # the stop flag (module docstring)
log = logging.getLogger(__name__)


def stop() -> None:
    """Set the stop flag: the run in flight ends at its next check, and no ask starts (wakes a gate wait)."""
    _stop.set()
    client.LLM_GATE.wake()


def resume() -> None:
    """Clear the stop flag (after the stopped run's thread has ended)."""
    _stop.clear()


def stopping() -> bool:
    return _stop.is_set()


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
    row = db.second_opinion(key, so.evidence_hash(p), so._model())   # noqa: SLF001 - the model the opinion is keyed by
    if row is None:
        return "due"
    if (row.get("last_rejected") or {}).get("prompt_version") == so.PROMPT_VERSION:
        return "up_to_date"   # a rejection under this prompt, noted on an older prompt's accepted opinion
    if row.get("prompt_version") != so.PROMPT_VERSION:
        return "due"
    # an accepted opinion that a check tightened since rejects is not served (so.cached), so it is redone
    return "due" if row.get("status") == "ok" and not so._accepted(row, p) else "up_to_date"


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
            if _stop.is_set():
                stopped = STOPPED
                break
            why = due(key)
            if why != "due":
                stats[why] += 1
                continue
            if not client.wait_chat_idle(PAUSE_MAX_S, stop=_stop):
                stopped = f"a chat answer kept the LLM busy for {PAUSE_MAX_S:.0f} s"
                break
            out = so.generate(key, interactive=False, fresh=True, stop=_stop)
            if out["status"] in ("llm_unavailable", "stopped"):
                stopped = out["detail"]
                break
            asked.append(key)
            stats[out["status"]] += 1
            stats["llm_ms"] += out.get("llm_ms") or 0
            if out["status"] == "ok":
                stats[f"concern_{out['concern']}"] += 1
        llm_ms = stats.pop("llm_ms", 0)
        counts = {"asked": len(asked), **stats, "llm_seconds": round(llm_ms / 1000, 1),
                  "seconds": round(time.time() - t0, 1), "stopped": stopped}
        if keys:
            log.info("second opinion run asked %d project(s): %s", len(asked), ", ".join(asked) or "none")
            db.record_job("second_opinion", started, "ok" if stopped is None else "partial" if asked else "error",
                          counts)
        return {**counts, "keys": asked}
    finally:
        _lock.release()


def batch() -> dict:
    return run(batch_keys(), limit=per_run())
