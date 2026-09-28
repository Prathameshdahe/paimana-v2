"""pipeline/research.py: sweep validation, the privacy floor over the committed file, live facts and the gold tables."""
import json

import pandas as pd
import pytest

from pipeline import research as R

ASOF = pd.Timestamp("2026-07-01")
FACT = {"category": "land", "direction": "negative", "severity": 2, "event_date": "2026-05", "published_date":
        "2026-05-20", "status": "ongoing", "summary": "About 4 km held up over land at 19 locations.",
        "headline": "Highway widening stuck at 19 spots", "source": "The Hindu", "url": "https://www.thehindu.com/a/b",
        "match": "high", "match_reason": "Names the NH-66 package and the agency", "verified": "keep"}


def line(key="PRJ-A", facts=(FACT,), **kw):
    return {"project_key": key, "researched_on": "2026-09-28", "searched": True, "queries": ["q1", "q2"],
            "latest_status": "Work continues on the open stretches.", "external": {
                "land_acquired_pct": {"value": 91.5, "as_of": "2026-06"}, "forest_clearance": None,
                "court_case": None,
                "contractor": {"company": "IRB Infrastructure", "status": "slow", "as_of": "2026-09"},
                "new_target": {"date": "2027-03", "as_of": "2026-04"}, "cost_revision": None},
            "facts": list(facts), **kw}


def committed():
    paths = sorted(R.RESEARCH.glob("research_sweep_*.jsonl"))
    assert paths, "no committed sweep file"
    return paths, [json.loads(ln) for p in paths for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def strings(x):
    """Every string value in a parsed JSON value, however deep."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def test_committed_sweep_names_no_private_person():
    """The privacy floor over every string of every committed line (the queries and URLs are committed too, though
    they never reach gold): no honorific + name outside an organisation or place."""
    _, lines = committed()
    hits = [(r.get("project_key"), n) for r in lines for t in strings(r) for n in R.private_names(t)]
    assert hits == []
    assert list(strings({"q": ["a", {"b": "Mr Rao"}], "n": 1})) == ["a", "Mr Rao"]


def test_committed_sweep_validates_without_drops():
    paths, lines = committed()
    known = {r["project_key"] for r in lines}
    got, counts = R.load(paths, known)
    assert counts["lines_dropped"] == counts["facts_dropped"] == counts["privacy_rejected"] == 0, counts["reasons"]
    assert sum(len(f) for _, f in got) == sum(len(r["facts"]) for r in lines)
    assert all(r["searched"] for r in lines) and all(f["verified"] in R.VERDICTS for r in lines for f in r["facts"])


@pytest.mark.parametrize("text, private", [
    ("Shri Ramesh Kumar and other villagers blocked the road", True),
    ("Mr. Singh said work would resume", True),
    ("Smt. Devi filed a petition", True),
    ("SHRI Nitin Gadkari reviewed the project", True),   # officials by office only
    ("Dr. Ram Manohar Lohia Hospital block handed over", False),
    ("Shri Mata Vaishno Devi Shrine Board approved the ropeway", False),
    ("Dr B R Ambedkar Institute of Technology", False),
    ("Sri Lanka ferry terminal", False),
    ("The Union Minister reviewed the Bhatkal stretch", False),
    ("DR. NTR Marg flyover", False),
    # an organisation after of / the / and does not make the person before it one
    ("Shri Ramesh Kumar of the Municipal Corporation said", True),
    ("Mr Ramesh Kumar and the Irrigation Department", True),
    # surnames that are also place words, and no space after the dot
    ("Dr. Anil Sagar, the contractor", True),
    ("Mr. Ramesh Nagar protested", True),
    ("Mr.Singh said", True),
    ("Shri Ram Kumar District Collector inspected the site", True),   # ends in an office, not an organisation
    ("Sri City Industrial Park allotted land", False),
    ("Dr. Ambedkar Nagar Road widening", False),
    ("Sri Avantika Contractors won the package", False),
    ("Sri Lanka and India signed the port deal", False),
    # a length after a number is not Kumari; a festival is not a person
    ("162-Km Khammam-Devarapalle Greenfield Highway Nears Completion", False),
    ("DMRC floats tender for the 4.94-Km Underground Stretch", False),
    ("A 41 Km Corridor From Prahladpura To Todi", False),
    ("Km Sunita Devi filed a petition", True),
    ("Traffic curbs for Sri Rama Navami near the site", False),
])
def test_privacy_floor(text, private):
    assert bool(R.private_names(text)) is private


def test_bad_facts_are_dropped_with_their_reason():
    bad = [{**FACT, "category": "weather"}, {**FACT, "direction": "bad"}, {**FACT, "severity": 4},
           {**FACT, "url": "ftp://x/y"}, {**FACT, "url": "javascript:alert(1)"}, {**FACT, "event_date": "May 2026"},
           {**FACT, "summary": "word " * 41}, {**FACT, "summary": "Mr. Rao, a landowner, sued."},
           {**FACT, "verified": "drop"}, {**FACT, "match": "certain"}]
    proj, facts, issues = R.validate_line(line(facts=[FACT, *bad]), {"PRJ-A"})
    assert len(facts) == 1 and len(issues) == len(bad) and all(w == "fact" for w, _ in issues)
    reasons = " | ".join(why for _, why in issues)
    for want in ("category 'weather'", "direction", "severity 4", "url is not http(s)", "not YYYY-MM-DD",
                 "over 40 words", "privacy: names a person", "verified 'drop'", "match"):
        assert want in reasons
    assert "Rao" not in reasons   # a rejected name never reaches the summary file
    f = facts[0]
    assert (f["taxonomy"], f["event_date"], f["date_precision"], f["domain"]) == (
        "land", pd.Timestamp("2026-05-01"), "month", "thehindu.com")
    assert f["fact_id"] == R.fact_id("PRJ-A", FACT["url"], "land", "2026-05") and len(f["fact_id"]) == 12
    assert proj["land_acquired_pct"] == 91.5 and proj["contractor"] == "IRB Infrastructure"
    assert proj["new_target"] == "2027-03" and proj["court"] is None and proj["n_queries"] == 2


def test_basis_defaults_to_article_and_is_checked():
    head = {**FACT, "basis": "headline", "url": "https://news.google.com/rss/articles/x"}
    _, facts, issues = R.validate_line(line(facts=[FACT, head, {**FACT, "basis": "rumour"}]), {"PRJ-A"})
    assert [f["basis"] for f in facts] == ["article", "headline"]
    assert [why for _, why in issues] == ["basis 'rumour'"]


def test_unknown_keys_bad_external_and_private_status():
    assert R.validate_line(line(key="PRJ-ZZZ"), {"PRJ-A"})[0] is None
    assert R.validate_line({**line(), "researched_on": "yesterday"}, {"PRJ-A"})[0] is None
    ext = {**line()["external"], "land_acquired_pct": {"value": 140, "as_of": "2026-06"},
           "court_case": {"court": "High Court", "status": "stay", "as_of": "2026-13"}}
    proj, _, issues = R.validate_line({**line(), "external": ext, "latest_status": "Shri Ram Lal protested."},
                                      {"PRJ-A"})
    assert proj["land_acquired_pct"] is None and proj["court"] is None and proj["latest_status"] is None
    assert {w for w, _ in issues} == {"external.land_acquired_pct", "external.court_case", "latest_status"}
    assert R.validate_fact("PRJ-A", {**FACT, "status": "Stalled"})[0]["status"] == "unknown"


def test_wrong_types_are_reasons_not_crashes(tmp_path):
    """A field of the wrong type drops its fact, entry or line with a reason: the step (and the report watcher's
    ingest after it) never stops on one bad line."""
    bad = [{**FACT, "source": 123}, {**FACT, "match_reason": ["x"]}, {**FACT, "headline": 5},
           {**FACT, "category": ["land"]}, {**FACT, "event_date": 2026.5}, {**FACT, "summary": {"a": 1}}]
    for f in bad:
        row, why = R.validate_fact("PRJ-A", f)
        assert row is None and why, f
    assert R.validate_fact("PRJ-A", {**FACT, "status": ["ongoing"]})[0]["status"] == "unknown"
    ext = {**line()["external"], "contractor": {"company": ["IRB"], "status": "slow", "as_of": "2026-09"}}
    proj, facts, issues = R.validate_line(line(facts=[FACT, *bad], external=ext), {"PRJ-A"})
    assert len(facts) == 1 and proj["contractor"] is None and ("external.contractor", "company is not text") in issues
    assert R.validate_line(line(key=["PRJ-A"]), {"PRJ-A"})[0] is None
    assert R.validate_line(line(searched="false"), {"PRJ-A"})[2] == [("line", "searched is not true or false")]
    assert R.validate_line(line(searched=False), {"PRJ-A"})[0]["searched"] is False
    path = tmp_path / "research_sweep_2026-09.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in [line(facts=[FACT, *bad]), line(key=["PRJ-A"]), [1, 2],
                                                        line(key="PRJ-B", researched_on=20260901)]) + "\n",
                    encoding="utf-8")
    got, counts = R.load([path], {"PRJ-A", "PRJ-B"})
    assert [p["project_key"] for p, _ in got] == ["PRJ-A"] and counts["lines_dropped"] == 3
    assert counts["facts_dropped"] == len(bad)


def test_categories_map_to_the_remark_taxonomy():
    from pipeline.external import TAXONOMY
    assert {R.TAXONOMY_OF[c] for c in ("funds", "natural_event")} == {"funding", "weather"}
    rest = set(R.TAXONOMY_OF.values()) - set(TAXONOMY)
    assert rest == {"approvals_other", "design_scope", "progress", "other"}


def test_live_is_negative_unresolved_and_recent():
    def fact(**kw):
        return {"direction": "negative", "status": "ongoing", "event_date": pd.Timestamp("2026-03-01"),
                "published_date": None, **kw}
    rows = pd.DataFrame([fact(), fact(direction="positive"), fact(status="resolved"),
                         fact(event_date=pd.Timestamp("2025-07-01")),                 # exactly LIVE_Q back: not live
                         fact(event_date=pd.Timestamp("2025-07-02")),
                         fact(event_date=None, published_date=pd.Timestamp("2026-08-01")),
                         fact(event_date=None), fact(event_date=pd.Timestamp("2026-09-01"))])
    assert R.live(rows, ASOF).tolist() == [True, False, False, False, True, True, False, True]
    assert [R.is_live(r.direction, r.status, r.event_date, r.published_date, ASOF) for r in rows.itertuples()] == \
        R.live(rows, ASOF).tolist()


def test_tables_latest_line_wins_and_counts(tmp_path):
    old = line(facts=[{**FACT, "url": "https://a.in/old"}], researched_on="2026-01-10")
    new = line(facts=[FACT, FACT, {**FACT, "direction": "positive", "status": "resolved", "url": "https://a.in/p"}])
    empty = line(key="PRJ-B", facts=[])
    a, b = tmp_path / "research_sweep_2026-01.jsonl", tmp_path / "research_sweep_2026-09.jsonl"
    a.write_text(json.dumps(old) + "\n", encoding="utf-8")
    b.write_text("\n".join([json.dumps(new), json.dumps(empty), "{not json", json.dumps(line(key="PRJ-X"))]) + "\n",
                 encoding="utf-8")
    lines, counts = R.load([a, b], {"PRJ-A", "PRJ-B"})
    assert counts["lines_read"] == 5 and counts["lines_dropped"] == 2
    facts, projects = R.tables(lines, ASOF)
    assert facts.columns.tolist() == R.FACT_COLS and projects.columns.tolist() == R.PROJECT_COLS
    # the old line is replaced, the duplicate fact dropped
    assert facts.set_index("url")["live"].to_dict() == {FACT["url"]: True, "https://a.in/p": False}
    assert facts["origin"].eq("sweep").all()
    assert projects.set_index("project_key")[["n_facts", "n_negative_live"]].to_dict("index") == {
        "PRJ-A": {"n_facts": 2, "n_negative_live": 1}, "PRJ-B": {"n_facts": 0, "n_negative_live": 0}}
    s = R.summary(facts, projects, ASOF, pd.Series({"PRJ-A": "Karnataka", "PRJ-B": "Goa"}), counts)
    assert s["coverage"] == {"n_projects_searched": 2, "n_projects_with_facts": 1, "n_facts": 2,
                             "n_negative_live": 1, "n_projects_negative_live": 1}
    assert s["facts_by_category"] == {"land": {"negative": 1, "positive": 1}}
    assert s["top_recent_blockers"] == facts.loc[facts["live"], "fact_id"].tolist()
    assert s["by_state"][0]["state"] == "Karnataka" and s["by_state"][0]["n_negative_live"] == 1
    json.dumps(s)   # JSON-safe


def test_gold_outputs_match_the_committed_sweep():
    facts = pd.read_parquet(R.FACTS)
    projects = pd.read_parquet(R.PROJECTS)
    s = json.loads(R.SUMMARY.read_text(encoding="utf-8"))
    _, lines = committed()
    assert set(projects["project_key"]) == {r["project_key"] for r in lines}
    assert len(facts) == s["coverage"]["n_facts"] and facts["fact_id"].is_unique
    assert facts["project_key"].str.startswith("PRJ-").all() and set(facts.columns) == set(R.FACT_COLS)
    assert set(s["top_recent_blockers"]) <= set(facts.loc[facts["live"], "fact_id"])
