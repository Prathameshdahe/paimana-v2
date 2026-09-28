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


def test_a_card_passes_a_check_but_not_the_answer_text():
    """The eval reports the answer text on its own: a number or a project that only a card carries passes the
    check (the tools found it) but not the text check (the written answer did not say it)."""
    count = {"kind": "count"}
    stats = [{"type": "stats", "rows": [{"name": "Odisha", "n": 12}]}]
    assert chat_eval.judge(count, 12, "There are some Critical projects [1].", stats, "") == (True, False)
    assert chat_eval.judge(count, 12, "There are 12 Critical projects [1].", stats, "") == (True, True)
    assert chat_eval.judge(count, 0, "There are none [1].", [], "") == (True, True)
    first = {"kind": "first_project"}
    card = [{"type": "projects", "items": [{"key": "PRJ-000698"}]}]
    assert chat_eval.judge(first, ("PRJ-000698", "Vishnugad Pipalkoti HEP"), "Here they are [1].", card, "") == (
        True, False)
    assert chat_eval.judge({"kind": "card", "type": "projects"}, None, "", card, "") == (True, None)
    assert chat_eval.judge({"kind": "mentions", "any": ["Watch"]}, None, "The Watch tier [1].", [], "") == (True, True)
    s = chat_eval.summary([{"routing_ok": True, "tools_ok": True, "checks_ok": True, "text_checked": True,
                            "text_ok": False, "first_card_s": 0.1, "done_s": 1.0},
                           {"routing_ok": True, "tools_ok": True, "checks_ok": True, "text_checked": False,
                            "text_ok": True, "first_card_s": 0.1, "done_s": 1.0}], llm=False)
    assert s["checks"] == "2/2" and s["text_checks"] == "0/1"


def test_every_check_kind_gets_its_expected_value():
    """expect() reads each API-backed check's value as the question's viewer; worst_agency reads the hidden bias from
    serving (the API sends it to the developer only), so it needs the question too."""
    from backend import serving  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from backend.main import app  # noqa: PLC0415
    q = next(q for q in chat_eval.load() if any(c["kind"] == "worst_agency" for c in q["checks"]))
    with TestClient(app) as api:
        got = chat_eval.expect(api, q, {"kind": "worst_agency"})
    scope = make_viewer(q["role"], q.get("ministry"), q.get("agency")).scope
    ranked = [p for p in serving.agency_matrix(scope=scope)["points"] if not p["hidden"] and p["schedule_bias"]]
    assert got == max(ranked, key=lambda p: p["schedule_bias"])["agency"]
