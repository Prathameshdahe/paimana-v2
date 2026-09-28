"""tests/chat_eval.jsonl stays a valid evaluation set (python -m llm.eval): 12 questions per role, known tools and
check kinds, and the router alone still picks the expected tools for every one (no LLM)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.access import make_viewer  # noqa: E402
from llm import eval as chat_eval  # noqa: E402
from llm import router, tools  # noqa: E402

KINDS = {"count", "top_group", "first_project", "last_completion", "worst_agency", "mentions", "not_mentions", "card"}


def test_the_question_set():
    qs = chat_eval.load()
    assert len(qs) >= 36 and len({q["id"] for q in qs}) == len(qs)
    by_role = {r: sum(q["role"] == r for q in qs) for r in ("public", "ministry_official", "ipmd_analyst")}
    assert by_role == {"public": 12, "ministry_official": 12, "ipmd_analyst": 12}
    assert len({q.get("ministry") for q in qs if q["role"] == "ministry_official"}) == 1
    assert sum(bool(q.get("llm")) for q in qs) >= 12
    for q in qs:
        assert set(q["tools"]) <= set(tools.TOOLS) and q["checks"]
        assert all(c["kind"] in KINDS for c in q["checks"]), q["id"]


def test_the_router_picks_the_expected_tools():
    for q in chat_eval.load():
        v = make_viewer(q["role"], q.get("ministry"), q.get("agency"))
        messages = list(q.get("messages") or []) + [{"role": "user", "content": q["question"]}]
        r = router.route(v, messages, q.get("project_key"))
        routed = {c["tool"] for c in r.calls} | ({r.detail} if r.detail else set())
        assert routed == set(q.get("route", q["tools"])), (q["id"], r.calls, r.detail)
