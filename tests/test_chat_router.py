"""llm/router.py over the real served portfolio: a table of questions -> the tool calls, their arguments and the
projects they name, by role; names outside the viewer's scope match nothing; follow-ups take the previous turn's
project or the open one; fast. No LLM."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.access import Viewer  # noqa: E402
from llm import router, tools  # noqa: E402

PIPALKOTI, TAPOVAN, BHADRAK, DARBHANGA_AIRPORT = "PRJ-000698", "PRJ-000911", "PRJ-002711", "PRJ-004957"
VIEWERS = {"public": Viewer("public"), "ipmd": Viewer("ipmd_analyst"),
           "coal": Viewer("ministry_official", ministry="Ministry of Coal"),
           "pg": Viewer("agency_official", agency="POWERGRID")}

# (role, question, tools in order, projects named, arguments of the first call that must hold)
TABLE = [
    ("public", "How many Critical projects are in Kerala?", ["search_projects"], [],
     {"tier": "Critical", "state": "Kerala"}),
    ("public", "how many projects are there", ["portfolio_stats"], [], {"group_by": "tier"}),
    ("public", "What does High risk mean?", ["search_knowledge"], [], {}),
    ("public", "What does the Watch tier mean?", ["search_knowledge"], [], {}),
    ("public", "What does Stalled mean?", ["search_knowledge"], [], {}),
    ("public", "How old is the data?", ["search_knowledge"], [], {}),
    ("public", "What is PAIMANA?", ["search_knowledge"], [], {}),
    ("public", "Projects near completion in Gujarat", ["search_projects"], [],
     {"state": "Gujarat", "near_complete": True}),
    ("public", "biggest railway projects in Bihar", ["search_projects"], [],
     {"sector": "Railways", "state": "Bihar", "sort": "cost"}),
    ("public", "top 5 riskiest projects in Odisha", ["search_projects"], [],
     {"state": "Odisha", "sort": "risk", "limit": 5}),
    ("public", "latest news on Pipalkoti", ["project_research"], [PIPALKOTI], {"key": PIPALKOTI}),
    ("public", "what changed for Bhadrak Baleshwar", ["project_history"], [BHADRAK], {"key": BHADRAK}),
    ("public", "why is Pipalkoti Medium?", ["get_project"], [PIPALKOTI], {"key": PIPALKOTI}),  # no drivers
    ("public", "compare Pipalkoti and Tapovan", ["compare_projects"], [PIPALKOTI, TAPOVAN],
     {"keys": [PIPALKOTI, TAPOVAN]}),
    ("public", "Show projects by sector", ["portfolio_stats"], [], {"group_by": "sector"}),
    ("public", "which state has the most critical projects", ["portfolio_stats"], [],
     {"group_by": "state", "tier": "Critical"}),
    ("public", "Is there a court case on the Darbhanga airport?", ["external_factors"], [DARBHANGA_AIRPORT],
     {"key": DARBHANGA_AIRPORT}),
    ("public", "how is NHAI doing", ["search_projects"], [], {"agency": "NHAI"}),  # no agency matrix
    ("public", "any land acquisition problems in Karnataka?", ["external_factors"], [],
     {"factor": "land", "state": "Karnataka"}),
    ("public", "Pipalkothi hydro project status", ["get_project"], [PIPALKOTI], {"key": PIPALKOTI}),  # a typo
    # a help word does not lose the project: its page first, then the help text
    ("public", "What is the tier of PRJ-000698?", ["get_project", "search_knowledge"], [PIPALKOTI],
     {"key": PIPALKOTI}),
    ("public", "What is the risk level of Pipalkoti?", ["get_project", "search_knowledge"], [PIPALKOTI],
     {"key": PIPALKOTI}),
    ("public", "What is the chance that PRJ-000698 will slip?", ["get_project", "search_knowledge"], [PIPALKOTI],
     {"key": PIPALKOTI}),
    ("ipmd", "How accurate is the prediction for Pipalkoti?", ["get_project", "search_knowledge"], [PIPALKOTI],
     {"key": PIPALKOTI}),
    ("ipmd", "why is Pipalkoti Medium?", ["explain_prediction", "get_project"], [PIPALKOTI], {"key": PIPALKOTI}),
    ("ipmd", "Why is PRJ-004941 Critical", ["explain_prediction", "get_project"], ["PRJ-004941"],
     {"key": "PRJ-004941"}),
    ("ipmd", "what is the second opinion on PRJ-000698", ["second_opinion"], [PIPALKOTI], {"key": PIPALKOTI}),
    ("ipmd", "top 5 land blockers in Karnataka", ["external_factors"], [],
     {"factor": "land", "state": "Karnataka", "limit": 5}),
    ("ipmd", "land bottlenecks in Maharashtra", ["bottlenecks"], [], {"category": "land", "state": "Maharashtra"}),
    ("ipmd", "which agencies have the worst track record", ["agency_scorecard"], [], {"sort": "schedule_overrun"}),
    ("ipmd", "which agencies have the biggest cost overrun", ["agency_scorecard"], [], {"sort": "cost_overrun"}),
    ("ipmd", "how is NHAI doing", ["agency_scorecard"], [], {"agency": "NHAI"}),
    ("ipmd", "Explain the drivers for Critical projects in Odisha", ["search_projects"], [],
     {"tier": "Critical", "state": "Odisha"}),
    ("ipmd", "any news on nagpur projects", ["search_projects"], [], {"q": "nagpur"}),
    ("ipmd", "What are the outside factors across the portfolio?", ["external_factors"], [], {}),
    ("ipmd", "forest clearance issues in Uttarakhand", ["external_factors"], [],
     {"factor": "forest_clearance", "state": "Uttarakhand"}),
    ("ipmd", "projects with utility shifting problems", ["external_factors"], [], {"factor": "utility_shifting"}),
    ("ipmd", "Coal ministry projects by state", ["portfolio_stats"], [],
     {"group_by": "state", "ministry": "Ministry of Coal"}),
    ("ipmd", "how many Watch projects are in the Ministry of Railways", ["search_projects"], [],
     {"tier": "Watch", "ministry": "Ministry of Railways"}),
    ("ipmd", "PRJ-002112 history", ["project_history"], ["PRJ-002112"], {"key": "PRJ-002112"}),
    ("ipmd", "tell me about prj 2711", ["get_project"], [BHADRAK], {"key": BHADRAK}),
    ("ipmd", "compare PRJ-000698 vs PRJ-002112 vs PRJ-004941", ["compare_projects"],
     [PIPALKOTI, "PRJ-002112", "PRJ-004941"], {}),
    ("ipmd", "Critical power projects", ["search_projects"], [], {"tier": "Critical", "sector": "Power"}),
    ("ipmd", "is there any forest clearance issue on Pipalkoti?", ["external_factors"], [PIPALKOTI],
     {"key": PIPALKOTI}),
    ("coal", "Critical projects in my ministry", ["search_projects"], [], {"tier": "Critical"}),
    ("coal", "how many projects are there", ["portfolio_stats"], [], {"group_by": "tier"}),
    ("coal", "projects by state", ["portfolio_stats"], [], {"group_by": "state"}),
    ("coal", "which coal projects are most delayed", ["search_projects"], [], {"sector": "Coal", "sort": "slip"}),
    ("pg", "how is my agency doing", ["agency_scorecard"], [], {}),
    ("pg", "top 3 riskiest projects", ["search_projects"], [], {"sort": "risk", "limit": 3}),
]


def ask(role, q, messages=None, project_key=None):
    return router.route(VIEWERS[role], (messages or []) + [{"role": "user", "content": q}], project_key)


def test_the_table_is_big_enough():
    assert len(TABLE) >= 40 and {r for r, *_ in TABLE} == set(VIEWERS)


@pytest.mark.parametrize("role, q, want_tools, want_keys, want_args", TABLE, ids=[t[1][:40] for t in TABLE])
def test_router_table(role, q, want_tools, want_keys, want_args):
    r = ask(role, q)
    assert [c["tool"] for c in r.calls] == want_tools, (r.intents, r.filters, r.calls)
    assert r.keys == want_keys
    assert r.confidence >= router.CONFIDENT
    assert {k: r.calls[0]["args"].get(k) for k in want_args} == want_args
    v = VIEWERS[role]
    for c in r.calls:  # every routed call is one this viewer may make, with arguments its tool accepts
        tools.validate_args(v, c["tool"], c["args"])


def test_a_list_before_per_project_detail_names_the_second_round():
    assert ask("ipmd", "Explain the drivers for Critical projects in Odisha").detail == "explain_prediction"
    assert ask("ipmd", "any news on nagpur projects").detail == "project_research"
    assert ask("public", "Explain the risk of Critical projects in Odisha").detail == "get_project"


def test_out_of_scope_names_match_nothing():
    r = ask("coal", "why is Pipalkoti Medium?")
    assert r.keys == [] and r.candidates == [] and r.confidence < router.CONFIDENT
    assert PIPALKOTI not in repr(r.calls) and PIPALKOTI not in repr(router.fallback(VIEWERS["coal"], r))
    assert ask("coal", "tell me about PRJ-000698").keys == []  # a key out of scope is no key


def test_ambiguous_names_list_the_candidates():
    r = ask("ipmd", "status of the Darbhanga project")
    assert r.keys == [] and len(r.candidates) > 1 and DARBHANGA_AIRPORT in r.candidates
    assert r.calls[0]["tool"] == "search_projects" and r.calls[0]["args"]["q"] == "darbhanga"


def test_follow_ups_take_the_previous_project_then_the_open_one():
    turns = [{"role": "user", "content": "why is Pipalkoti Medium?"}, {"role": "assistant", "content": "Because [1]."}]
    r = ask("ipmd", "and what changed lately?", turns)
    assert r.followup and r.keys == [PIPALKOTI] and [c["tool"] for c in r.calls] == ["project_history"]
    r = ask("ipmd", "what is its latest news?", [{"role": "user", "content": "hi"},
                                                  {"role": "assistant", "content": "PRJ-002112 is High [1]."}])
    assert r.keys == ["PRJ-002112"] and r.calls[0]["tool"] == "project_research"
    r = ask("public", "what are the risks of this project?", project_key="PRJ-002112")
    assert r.keys == ["PRJ-002112"] and r.calls[0] == {"tool": "get_project", "args": {"key": "PRJ-002112"}}
    r = ask("public", "why is it High?", project_key="PRJ-002112")
    assert r.keys == ["PRJ-002112"]
    # a filtered question is about the list, not the open project
    r = ask("public", "how many Critical projects are in Kerala?", project_key="PRJ-002112")
    assert r.keys == [] and r.calls[0]["tool"] == "search_projects"
    # the open project outside the viewer's scope is ignored
    assert ask("coal", "why is it High?", project_key=PIPALKOTI).keys == []


def test_filters_read_from_the_portfolio():
    f, _ = router._filter_words("high court stay on the Delhi metro, Orissa and J&K projects by sector")
    assert "tier" not in f and f["state"] == "Delhi" and f["group_by"] == "sector"
    assert router._filter_words("projects in Orissa")[0]["state"] == "Odisha"
    assert router._filter_words("Jammu and Kashmir roads")[0] == {"state": "Jammu & Kashmir",
                                                                  "sector": "Roads & Highways"}
    assert router._filter_words("oil projects of OIL")[0]["agency"] == "OIL"
    assert "agency" not in router._filter_words("oil projects")[0]
    assert router._filter_words("high risk projects")[0]["tier"] == "High"
    assert "tier" not in router._filter_words("projects with low progress")[0]


def test_routing_is_fast():
    ask("ipmd", "warm up Pipalkoti")
    t0 = time.perf_counter()
    for role, q, *_ in TABLE:
        ask(role, q)
    assert (time.perf_counter() - t0) / len(TABLE) < 0.05
