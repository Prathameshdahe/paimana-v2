"""The numbers policy (SPEC9_ui section 6, docs/ACCESS_CONTROL.md): the model's own numbers reach only the developer
(the `numbers` feature); the public, agency, ministry and IPMD viewers get words (backend/serving.py plain_*).

The words themselves (bands, drivers, agency and hidden-delay words, the evidence rewrite over the whole checklist),
then every endpoint scanned recursively for a fixed list of hidden keys (and for the telltale phrases of a model
number in text) as each viewer, the developer still getting them; then the forecast, agency, map, alert, brief,
second-opinion, chat and worker variants. Every viewer but the public goes through tests/viewers.py."""
import asyncio
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import brief, db, labels, serving, store  # noqa: E402
from backend.access import Viewer  # noqa: E402
from backend.live import scheduler  # noqa: E402
from backend.main import app  # noqa: E402
from backend.schemas import ScoutOutput, _to_camel  # noqa: E402
from llm import agent, client as llm_client, rag, second_opinion as so, tools, worker  # noqa: E402
from pipeline import gold  # noqa: E402
from viewers import as_role  # noqa: E402

HIDDEN = {_to_camel(k) for k in (
    "p_any_2q", "p_date_push_2q", "p_cost_rev_2q", "p_any_4q", "p_cost_revision_2q", "months_p05", "months_p50",
    "months_p95", "cost_pct_p05", "cost_pct_p50", "cost_pct_p95", "slip_months_p05", "slip_months_p50",
    "slip_months_p95", "cost_change_pct_p05", "cost_change_pct_p50", "cost_change_pct_p95", "tier_rank_pct",
    "tier_by_rank", "shap_top5", "top_drivers", "contribution", "mean_p_any_2q", "mean_months_p50", "schedule_bias",
    "schedule_bias_raw", "schedule_bias_q25", "schedule_bias_q75", "schedule_bias_ci_lo", "schedule_bias_ci_hi",
    "cost_bias", "cost_bias_raw", "cost_bias_q25", "cost_bias_q75", "cost_bias_ci_lo", "cost_bias_ci_hi",
    "sector_schedule_bias", "sector_cost_bias", "shrink_weight", "trend", "distance", "y_months", "y_cost_pct",
    "y_any", "y_date_push", "y_cost_rev", "p05", "p50", "p95", "lift", "lift_within_sector_year", "extra_months",
    "extra_months_lo", "extra_months_hi", "extra_push", "extra_push_lo", "extra_push_hi", "holm_months", "holm_push",
    "garvit_band", "external_factor_score", "fc_component", "la_component", "mean", "min", "25%", "50%", "75%",
    "max", "link_score", "slip_rate_with", "slip_rate_without", "ci_lo", "ci_hi")}
# the chat's fact keys that carry a model number (llm/tools.py)
HIDDEN_FACTS = {"slip_chance_within_2_quarters_pct", "date_push_chance_within_2_quarters_pct",
                "cost_revision_chance_within_2_quarters_pct", "slip_chance_within_4_quarters_pct",
                "likely_slip_months_within_2_quarters", "slip_months_90pct_range", "horizon_quarters",
                "schedule_overrun_pct", "sector_schedule_overrun_pct", "recent_trend_pct", "score", "value"}
# (the agencies' cost_overrun_pct is checked on agency_scorecard alone: the portfolio's cost_overrun_pct is a report
# fact, the anticipated against the original cost)
# a model number written into text: the checklist's model rows, alerts, agency statistics, intervals, scores
TEXT_LEAK = re.compile(r"\bP = \d|High-tier cut|P\(date push|\bCI [+-]?\d|pts date-push risk|agency timelines run"
                       r"|slip rate \d|\bscore \d\.\d|median slip|nearest analogues"
                       r"|(?:probability|chance) of (?:approximately )?\d|\bSHAP\b|risk exposure of")
CHANCES = {"very likely", "likely", "possible", "unlikely", None}
SLIPS = {"under 6 months", "6 to 12 months", "1 to 2 years", "over 2 years", None}
OFFICIALS = ("agency", "ministry", "ipmd")


def leaks(v, path="") -> list[str]:
    """Every hidden key (camelCased) holding a value other than null or empty, anywhere in v (but /api/meta's models,
    the served model's name per target: a name, not a number)."""
    out = []
    if isinstance(v, dict):
        for k, x in v.items():
            if path == "" and k == "models" and isinstance(x, dict) and all(isinstance(y, str) for y in x.values()):
                continue
            if _to_camel(str(k)) in HIDDEN and x not in (None, [], {}):
                out.append(f"{path}.{k}")
            out += leaks(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out += leaks(x, f"{path}[{i}]")
    return out


def text_leaks(v) -> list[str]:
    if isinstance(v, str):
        return [v[:160]] if TEXT_LEAK.search(v) else []
    if isinstance(v, dict):
        return [t for x in v.values() for t in text_leaks(x)]
    if isinstance(v, list):
        return [t for x in v for t in text_leaks(x)]
    return []


def fact_leaks(v, path="") -> list[str]:
    out = []
    if isinstance(v, dict):
        for k, x in v.items():
            if (k in HIDDEN_FACTS or _to_camel(k) in HIDDEN) and x not in (None, [], {}):
                out.append(f"{path}.{k}")
            out += fact_leaks(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out += fact_leaks(x, f"{path}[{i}]")
    return out


# ------------------------------------------------------------------ the words

def test_chance_and_slip_bands():
    assert [serving.chance_word(p) for p in (0.95, 0.75, 0.7499, 0.5, 0.4999, 0.25, 0.2499, 0.0)] == [
        "very likely", "very likely", "likely", "likely", "possible", "possible", "unlikely", "unlikely"]
    assert serving.chance_word(None) is None and serving.chance_word(float("nan")) is None
    assert [serving.slip_word(m) for m in (-0.3, 5.99, 6, 11.99, 12, 24, 24.1)] == [
        "under 6 months", "under 6 months", "6 to 12 months", "6 to 12 months", "1 to 2 years", "1 to 2 years",
        "over 2 years"]
    assert serving.slip_word(None) is None
    assert serving.outlook(None, 0.3, None) == {"delay": None, "cost": "possible", "slip": None,
                                                "horizon": "next two quarters"}


def test_drivers_in_words_by_tercile():
    shap = [{"feature": "log_cost", "value": 7.1, "contribution": -0.2},
            {"feature": "months_to_anticipated_completion", "value": 5.0, "contribution": 2.1},
            {"feature": "stagnation_quarters", "value": 2.0, "contribution": 0.9},
            {"feature": "burn_gap", "value": -23.0, "contribution": 0.0},
            {"feature": "ext_open_land", "value": 1, "contribution": 0.05},
            {"feature": "sector_slip_4q", "value": 0.66, "contribution": -0.4}]
    got = serving.drivers_plain(shap)
    assert [d["label"] for d in got] == ["Time left to the expected completion", "Quarters with no progress",
                                         "Recent delays in the sector", "Project size",
                                         "Open land issue in the report remarks"]   # largest first, no zero
    assert [d["direction"] for d in got] == ["raises", "raises", "lowers", "lowers", "raises"]
    assert [d["strength"] for d in got] == ["strong", "strong", "moderate", "moderate", "slight"]
    assert serving.drivers_plain([]) == [] and serving.drivers_plain(None) == []
    assert [d["strength"] for d in serving.drivers_plain(shap[:2])] == ["strong", "moderate"]


def test_driver_labels_carry_no_number_or_unit():
    names = list(gold.FEATURES) + list(labels.FEATURE_LABELS) + ["ext_open_new_kind", "sector_x_2q_pct"]
    for f in names:
        label = labels.driver_label(f)
        assert label and not re.search(r"\d|%|\(|\bpp\b|log|_", label), (f, label)
    # every model feature (the champions' feature lists are drawn from gold.FEATURES) has words of its own
    assert set(gold.FEATURES) <= set(labels.DRIVER_LABELS), set(gold.FEATURES) - set(labels.DRIVER_LABELS)
    assert set(labels.FEATURE_LABELS) <= set(labels.DRIVER_LABELS)
    assert labels.driver_label("ext_ever_inter_agency") == "A wait for another agency's approval reported before"
    assert labels.driver_label("ext_open_forest_env") == "Open forest or environment issue in the report remarks"


def test_agency_and_hidden_delay_words():
    w = serving.schedule_word
    assert [w({"schedule_bias": b, "hidden": False}) for b in (0.56, 0.1, -0.1, -0.3)] == [
        "usually later", "about on time", "about on time", "usually earlier"]
    assert w({"schedule_bias": 0.9, "hidden": True}) == "too few projects" == w({"schedule_bias": None})
    c = serving.cost_word
    assert [c({"cost_bias": b, "n_cost": 8}) for b in (0.2, 0.05, -0.2)] == [
        "usually costs more", "about as planned", "usually costs less"]
    assert c({"cost_bias": 0.2, "n_cost": 4}) == "too few projects"
    e = serving.extra_months_word
    assert e({"measurable": False, "extra_months": None}) is None
    assert e({"measurable": True, "extra_months": 1.4, "extra_months_lo": -1.0, "extra_months_hi": 3.0}) == \
        serving.NO_EXTRA
    assert [e({"measurable": True, "extra_months": m, "extra_months_lo": 0.5, "extra_months_hi": m + 3})
            for m in (3, 6, 12, 20)] == ["a few months", "about half a year", "about a year", "over a year"]


def test_evidence_in_words_over_the_whole_checklist():
    rows = serving._rows(serving.state(), "SELECT dimension, evidence FROM rp")
    changed = 0
    for r in rows:
        t = serving.plain_text(r["evidence"], r["dimension"])
        assert not TEXT_LEAK.search(t or ""), (r["dimension"], t)
        changed += t != r["evidence"]
    assert changed > 1000   # the model rows, the agency statistics, the composite scores, the measured delays
    p = serving.plain_text
    assert p("P = 0.87 (High-tier cut 0.85); velocity 0.8%/q vs sector 0.0%/q", "schedule_slip") == (
        "a completion-date push is very likely within the next two quarters; velocity 0.8%/q vs sector 0.0%/q")
    assert p("P = 0.31 (High-tier cut 0.04); cost variation so far +66%", "cost_escalation") == (
        "a cost revision is possible within the next two quarters; cost variation so far +66%")
    assert p("agency timelines run +75% vs schedule (median of 6 projects); 2q slip rate 36%") == (
        "this agency's projects usually finish later than planned (6 projects)")
    assert p("score 0.61 (fc+la): forest 3/7 (rulebook) + land 4/5 (NH-37)") == (
        "forest 3/7 (rulebook) + land 4/5 (NH-37)")
    assert p("x: no measurable extra delay (-1 month over the next year, CI -3 to 0; +3 pts date-push risk, CI -6 to "
             "+11; 69 projects)") == "x: no measurable extra delay (69 projects)"
    assert p("stage: +7 months over the next year (CI 2 to 12) and +12 pts date-push risk (CI 1 to 20), measured on "
             "16 projects") == ("stage: about half a year of extra delay and a higher chance of a date push, "
                                "measured on 16 projects")
    assert p("then: +12 pts date-push risk (CI 1 to 20), measured on 38 projects") == (
        "then: a higher chance of a date push, measured on 38 projects")
    assert p("entered Critical at asof 2026-07-01; P(date push or cost revision, 2q) = 0.95") == (
        "entered Critical at asof 2026-07-01; a date push or cost revision is very likely within the next two "
        "quarters")
    assert p("flagged High at asof 2026-07-01 (P = 0.62); by the 2027-01 report") == (
        "flagged High at asof 2026-07-01 (rated likely); by the 2027-01 report")
    assert p(None) is None and p("") == ""


# ------------------------------------------------------------------ every endpoint, every viewer

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:   # the lifespan seeds the alert feed (tier alerts print the chance of a slip)
        yield c


@pytest.fixture(scope="module")
def world(client):
    """Per viewer: its scope, a rich project in it (drivers, analogues; for the unscoped a measured hidden delay),
    an agency and a bottleneck in it; a news signal and a watcher alert with a probability on each project."""
    s, sc = serving.state(), serving.scopes()
    ministry, agency = sc["ministries"][0]["name"], sc["agencies"][0]["name"]
    ranked = serving._rows(s, """SELECT c.project_key AS k FROM cur c JOIN rstat r USING (project_key)
        ORDER BY c.p_any_2q DESC NULLS LAST""")
    rich = next(r["k"] for r in ranked if serving.project(r["k"])["external"]["hidden_delay"])
    scope = {"public": None, "agency": ("agency", agency), "ministry": ("ministry", ministry), "ipmd": None,
             "developer": None}
    key = {r: rich if sc_ is None else serving.projects(scope=sc_, size=1)["items"][0]["key"]
           for r, sc_ in scope.items()}
    bid = {r: next((b["bottleneck_id"] for b in serving.bottlenecks(scope=sc_)["items"]), None)
           for r, sc_ in scope.items()}
    for k in set(key.values()):
        db.save_signals([{"url": f"https://n/{k}", "url_hash": k, "title": f"Work stopped on {k}", "source": "PTI",
                          "published_at": "2026-08-02T06:00:00+00:00", "fetched_at": "2026-08-02T06:00:00+00:00",
                          "summary": "", "category": "law_order", "severity": 2, "text_hash": k,
                          "links": [(k, 0.75, "places+context")]}])
        db.add_alerts([{"project_key": k, "kind": "slip_realised", "severity": 2, "title": f"Slip realised: {k}",
                        "detail": "flagged High at asof 2026-07-01 (P = 0.87); by the 2027-01 report: completion date "
                                  "pushed", "asof": "2026-07-01", "source": "test"}])
    return {"ministry": ministry, "agency": agency, "scope": scope, "key": key, "bottleneck": bid}


def headers(client, world, role):
    return as_role(client, role, ministry=world["ministry"] if role == "ministry" else None,
                   agency=world["agency"] if role == "agency" else None)


def paths(world, role) -> list[str]:
    k, bid = world["key"][role], world["bottleneck"][role]
    agency = world["agency"] if role == "agency" else "NHAI"
    out = ["/api/meta", "/api/scopes", "/api/portfolio", "/api/projects?size=100", "/api/projects/map",
           "/api/projects?tier=Critical&size=100", f"/api/projects/{k}", f"/api/projects/{k}/timeline",
           f"/api/projects/{k}/research", "/api/research/summary", f"/api/projects/{k}/forecast",
           f"/api/projects/{k}/second-opinion?cached=1", f"/api/projects/{k}/signals",
           "/api/agencies/matrix?include_hidden=true", f"/api/agencies/{agency}/projects", "/api/bottlenecks?size=100",
           "/api/external/summary", "/api/alerts?size=100", "/api/alerts?kind=slip_realised&size=100",
           "/api/watchlist", "/api/jobs", "/api/live/status",
           "/api/signals/feed", "/api/radar/summary", "/api/dispatch", "/api/models", "/api/worker-runs"]
    return out + ([f"/api/bottlenecks/{bid}"] if bid else [])


def scan(client, world, role) -> dict[str, dict]:
    """GET every path as the viewer (after watching its project): path -> JSON, for the 200s; asserts the rest are
    403 (a feature the role does not have)."""
    h = headers(client, world, role)
    if role != "public":
        assert client.post("/api/watchlist", headers=h, json={"projectKey": world["key"][role]}).status_code == 200
    out = {}
    for path in paths(world, role):
        r = client.get(path, headers=h)
        assert r.status_code in (200, 403), (role, path, r.status_code, r.text[:300])
        if r.status_code == 200:
            out[path] = r.json()
    return out


@pytest.mark.parametrize("role", ["public", "agency", "ministry", "ipmd"])
def test_no_hidden_number_reaches_a_viewer_without_numbers(client, world, role):
    got = scan(client, world, role)
    k = world["key"][role]
    must = {"/api/portfolio", "/api/projects?size=100", f"/api/projects/{k}", "/api/external/summary"}
    if role != "public":
        must |= {f"/api/projects/{k}/forecast", "/api/agencies/matrix?include_hidden=true", "/api/bottlenecks?size=100",
                 "/api/alerts?size=100", "/api/watchlist", f"/api/projects/{k}/signals"}
    assert must <= set(got), must - set(got)
    assert not {"/api/models", "/api/worker-runs"} & set(got)   # the models page and the worker console: developer's
    for path, body in got.items():
        assert not leaks(body), (role, path, leaks(body)[:5])
        assert not text_leaks(body), (role, path, text_leaks(body)[:3])
    detail = got[f"/api/projects/{k}"]
    o = detail["scores"]["outlook"]
    assert o["horizon"] == "next two quarters" and o["delay"] in CHANCES and o["slip"] in SLIPS
    assert all(r["outlook"] for r in got["/api/projects?size=100"]["items"])
    assert all(r["outlook"] for r in got["/api/portfolio"]["top"])
    if role == "public":
        assert detail["scores"]["driversPlain"] == []
        assert all(r["driversPlain"] == [] for r in got["/api/projects?size=100"]["items"])
    else:
        assert detail["scores"]["driversPlain"] and all(
            set(d) == {"label", "direction", "strength"} for d in detail["scores"]["driversPlain"])
        assert any(i["project"] and i["project"]["outlook"] for i in got["/api/watchlist"]["items"])
        alerts = got["/api/alerts?kind=slip_realised&size=100"]["items"]
        assert alerts and all("(rated " in a["detail"] for a in alerts)   # the watcher's '(P = 0.87)' in words


def test_the_developer_gets_every_number(client, world):
    got = scan(client, world, "developer")
    found = {p.rsplit(".", 1)[-1].split("[")[0] for body in got.values() for p in leaks(body)}
    found = {_to_camel(f) for f in found}
    want = {"pAny2q", "pDatePush2q", "monthsP95", "tierRankPct", "shapTop5", "contribution", "scheduleBias",
            "scheduleBiasCiLo", "trend", "distance", "yMonths", "p95", "lift", "extraMonths", "meanPAny2q",
            "externalFactorScore", "mean", "linkScore", "garvitBand", "slipRateWith", "ciLo"}
    assert want <= found, want - found
    detail = got[f"/api/projects/{world['key']['developer']}"]
    assert detail["scores"]["outlook"] and detail["scores"]["driversPlain"]   # the words go to the developer too
    assert any("P(date push" in (a["detail"] or "") for a in got["/api/alerts?size=100"]["items"])
    ev = {r["dimension"]: r["evidence"] for r in detail["riskProfile"]}
    assert ev["schedule_slip"].startswith("P = ")


# ------------------------------------------------------------------ shapes

def test_forecast_in_words(client, world):
    k = world["key"]["ipmd"]
    plain = client.get(f"/api/projects/{k}/forecast", headers=headers(client, world, "ipmd")).json()
    full = client.get(f"/api/projects/{k}/forecast", headers=headers(client, world, "developer")).json()
    c = plain["completion"]
    assert c["anticipated"] == full["completion"]["anticipated"] and c["band"] == full["completion"]["band"]
    assert c["band"] in SLIPS - {None} and all(c[f] is None for f in ("monthsP05", "monthsP50", "monthsP95", "p50"))
    assert full["completion"]["monthsP50"] is not None and full["completion"]["p95"]
    assert len(plain["analogues"]) == len(full["analogues"]) == 10
    for a, b in zip(plain["analogues"], full["analogues"]):
        assert a["name"] == b["name"] == b["analogueName"] and a["outcome"] == b["outcome"]
        assert a["outcome"] == {1: "slipped", 0: "held"}.get(b["yAny"], "unknown")
        assert isinstance(a["yearsAgo"], int) and a["yearsAgo"] >= 0 and a["yearsAgo"] == b["yearsAgo"]
        assert a["distance"] is None and a["yMonths"] is None and a["yAny"] is None and b["distance"] is not None
    n = sum(a["outcome"] == "slipped" for a in plain["analogues"])
    assert plain["analogueSummary"].startswith(f"{n} of the 10 most similar") and "median" not in plain[
        "analogueSummary"]
    # the scenario curves and their band stay: the chart draws them (it prints no value)
    assert plain["scenarios"] == full["scenarios"] and plain["band"] == full["band"] and plain["scurve"]
    assert "percentile" not in plain["bandMethod"] and "percentile" in full["bandMethod"]


def test_agency_matrix_in_words(client, world):
    q = "/api/agencies/matrix?include_hidden=true"
    plain = client.get(q, headers=headers(client, world, "ipmd")).json()
    full = client.get(q, headers=headers(client, world, "developer")).json()
    assert [p["agency"] for p in plain["points"]] == [p["agency"] for p in full["points"]]   # the same order
    for a, b in zip(plain["points"], full["points"]):
        assert a["scheduleWord"] == b["scheduleWord"] and a["costWord"] == b["costWord"]
        assert a["nProjects"] == b["nProjects"] and a["nOpen"] == b["nOpen"] and a["capitalCr"] == b["capitalCr"]
        assert a["scheduleBias"] is None and a["trend"] is None
        want = serving.schedule_word({"schedule_bias": b["scheduleBias"], "hidden": b["hidden"]})
        assert b["scheduleWord"] == want
        assert b["hidden"] is False or b["scheduleWord"] == "too few projects"
    words = {p["scheduleWord"] for p in full["points"]}
    assert {"usually later", "too few projects"} <= words
    assert "bootstrap" not in plain["method"] and "bootstrap" in full["method"]


def test_external_summary_bands(client, world):
    plain = client.get("/api/external/summary", headers=headers(client, world, "ipmd")).json()
    full = client.get("/api/external/summary", headers=headers(client, world, "developer")).json()
    rows, frows = plain["hiddenDelayPriors"]["rows"], full["hiddenDelayPriors"]["rows"]
    assert [r["extra_months_word"] for r in rows] == [r["extra_months_word"] for r in frows]
    assert all(r["extra_months"] is None and r["n_projects"] is not None for r in rows)
    assert {r["extra_months_word"] for r in rows} <= {None, serving.NO_EXTRA, "a few months", "about half a year",
                                                       "about a year", "over a year"}
    assert any(r["extra_months_word"] for r in rows)
    nb, fb = plain["noticeBacktest"]["land_or_forest"], full["noticeBacktest"]["land_or_forest"]
    # the lift is with / without: both rates go too (overall and per sector), the counts stay
    assert nb["lift"] is None and nb["slip_rate_with"] is None and nb["slip_rate_without"] is None
    assert fb["slip_rate_with"] is not None and (nb["n_with"], nb["n_without"]) == (fb["n_with"], fb["n_without"])
    assert nb["by_sector"] and all(r["slip_rate_with"] is None and r["lift"] is None for r in nb["by_sector"].values())
    links = plain["landCoverage"]["link_check"]   # the hand-checked land links: counts, not their bootstrap interval
    assert links and all(c["ci_lo"] is None and c["ci_hi"] is None and c["n"] >= c["correct"] for c in links.values())
    assert all(c["ci_lo"] is not None for c in full["landCoverage"]["link_check"].values())
    comp = plain["externalComposite"]["by_coverage"]["fc+la"]
    assert comp["mean"] is None and comp["n_score_ge_high"] == full["externalComposite"]["by_coverage"]["fc+la"][
        "n_score_ge_high"]
    card = plain["earlyNotice"]["top"][0]
    assert card["p_any_2q"] is None and card["outlook"]["horizon"] == "next two quarters"


def test_map_rows_and_top_reason(client, world):
    ipmd, pub = headers(client, world, "ipmd"), as_role(client, "public")
    m = client.get("/api/projects/map", headers=ipmd).json()
    assert m["total"] == len(m["items"]) == serving.meta()["n_current"]
    rank = {t: i for i, t in enumerate(serving.TIERS + [serving.WATCH])}
    order = [(rank.get(r["tier"], len(rank)), r["key"]) for r in m["items"]]
    assert order == sorted(order)   # by tier, then key: a row's place says nothing of its hidden chance of a slip
    crit = client.get("/api/projects/map", headers=ipmd, params={"tier": "Critical"}).json()
    assert crit["total"] == client.get("/api/projects", headers=ipmd, params={"tier": "Critical", "size": 1}).json()[
        "total"] and all(r["tier"] == "Critical" for r in crit["items"])
    scoped = client.get("/api/projects/map", headers=headers(client, world, "ministry")).json()
    assert scoped["total"] == serving.projects(scope=world["scope"]["ministry"], size=1)["total"]
    row = m["items"][0]
    assert set(row) == {"key", "name", "sector", "state", "tier", "override", "anticipatedCompletion",
                        "anticipatedCostCr", "physicalProgressPct", "noCompletionDate", "flags", "outlook", "topReason"}
    words = serving._words()
    checks = {labels.dimension_label(d) for d in serving.PLAIN_RISK}
    for r in m["items"][:200]:
        w = words[r["key"]]
        assert r["topReason"] == w["top_reason"]
        assert r["topReason"] is None or r["topReason"] in checks or r["topReason"] in {
            d["label"] for d in w["drivers_plain"] if d["direction"] == "raises"}
    public = client.get("/api/projects/map", headers=pub).json()["items"]
    assert all(r["topReason"] == words[r["key"]]["top_check"] for r in public[:200])
    assert all(r["topReason"] is None or r["topReason"] in checks for r in public)
    rows = client.get("/api/projects", headers=ipmd, params={"size": 50}).json()["items"]
    assert all(r["topReason"] == words[r["key"]]["top_reason"] for r in rows)
    top = client.get("/api/portfolio", headers=pub).json()["top"]   # the public's top list: a check, never a driver
    assert top and all(r["topReason"] == words[r["key"]]["top_check"] for r in top)
    top = client.get("/api/portfolio", headers=ipmd).json()["top"]
    assert all(r["topReason"] == words[r["key"]]["top_reason"] for r in top)
    assert client.get("/api/projects/map", params={"tier": "Severe"}).status_code == 422


MEMO = ("Project: VISHNUGAD PIPALKOTI HYDRO ELECTRIC PROJECT (PRJ-000698)\nSummary: The project has a high slip "
        "probability of 0.7636 and significant risk exposure of Cr1454.89. The top SHAP drivers indicate that the "
        "agency and physical progress are contributing to the risk.\nBottlenecks: ['agency', 'physical_progress']\n"
        "Recommended action: Address the land acquisition delay (66 MW, KM 206.00 to KM 242.00).")


def test_memo_in_words():
    """The worker's stored memos (database/dispatch_drafts.json, written before llm/worker.py gave the analyst words)
    quote the model's probability, a risk exposure (probability times cost) and 'SHAP': serving.plain_memo."""
    p = serving.plain_memo
    assert p(MEMO) == (
        "Project: VISHNUGAD PIPALKOTI HYDRO ELECTRIC PROJECT (PRJ-000698)\nSummary: The project has a high slip "
        "probability (rated very likely) and significant risk exposure. The top drivers indicate that the agency and "
        "physical progress are contributing to the risk.\nBottlenecks: ['agency', 'physical_progress']\n"
        "Recommended action: Address the land acquisition delay (66 MW, KM 206.00 to KM 242.00).")
    assert p("a high slip probability of 69.47% and significant risk exposure of approximately 74.87 Cr. Next") == (
        "a high slip probability (rated likely) and significant risk exposure. Next")
    assert p("a high slip probability of 0.6816608236574031 with no risk exposure in currency terms") == (
        "a high slip probability (rated likely) with no risk exposure in currency terms")
    assert p("risk exposure of approximately 517 million Cr. The SHAP analysis identifies drivers") == (
        "risk exposure. The analysis identifies drivers")
    assert p("risk exposure of Cr 97.0987. To minimize slip probability, act.") == (
        "risk exposure. To minimize slip probability, act.")
    assert p(None) is None and p("") == ""


def test_dispatch_memos_in_words(client, world, tmp_path, monkeypatch):
    ipmd = client.get("/api/dispatch", headers=headers(client, world, "ipmd")).json()
    dev = client.get("/api/dispatch", headers=headers(client, world, "developer")).json()
    assert len(ipmd) == len(dev) and any("probability of 0." in d["draftMemo"] for d in dev)   # the developer: stored
    assert not text_leaks(ipmd)
    k = world["key"]["ministry"]
    drafts = [{"id": "m", "project_id": k, "project_name": "X", "draft_memo": MEMO,
               "recommended_recipient_role": "ministry_official", "status": "pending",
               "created_at": "2026-09-21T21:29:01+00:00",
               "evidence": [{"tag": "news", "source_url": None, "note": "a slip probability of 0.91 (SHAP)"}]}]
    path = tmp_path / "drafts.json"
    path.write_text(json.dumps(drafts), encoding="utf-8")
    monkeypatch.setattr(store, "DISPATCH_DRAFTS_PATH", str(path))
    h = headers(client, world, "ministry")
    got = client.get("/api/dispatch", headers=h).json()
    assert len(got) == 1 and "(rated very likely)" in got[0]["draftMemo"] and not text_leaks(got)
    decided = client.post("/api/approvals", headers=h, json={"draftId": "m", "decision": "approved"})
    assert decided.status_code == 200 and decided.json()["status"] == "approved" and not text_leaks(decided.json())
    assert json.loads(path.read_text(encoding="utf-8"))[0]["draft_memo"] == MEMO   # stored as written


def test_job_summaries_carry_no_live_accuracy(client, world):
    """The ingest job's summary counts the live accuracy (realised, slipped, flagged, flagged_and_slipped: the
    precision of High / Critical follows): the models page's, the developer's only."""
    live = {"realised": 120, "slipped": 50, "flagged": 30, "flagged_and_slipped": 21}
    db.record_job("ingest", "2026-09-28T00:00:00+00:00", "ok", {"rows": 10, "realised": live})
    for role in OFFICIALS:
        h = headers(client, world, role)
        run = {j["job"]: j for j in client.get("/api/jobs", headers=h).json()}["ingest"]
        assert run["summary"]["realised"] is None and run["summary"]["rows"] == 10
        last = client.get("/api/live/status", headers=h).json()["watch"]["lastRun"]
        assert last["id"] == run["id"] and last["summary"]["realised"] is None
    dev = {j["job"]: j for j in client.get("/api/jobs", headers=headers(client, world, "developer")).json()}
    assert dev["ingest"]["summary"]["realised"] == live


def test_alert_stream_sends_words(fresh_db, monkeypatch):
    monkeypatch.setattr(scheduler, "POLL_S", 0.05)
    db.init()
    start = db.max_alert_id()
    db.add_alerts([{"project_key": "PRJ-IN", "kind": "tier_up", "severity": 3, "title": "Critical: x",
                    "detail": "entered Critical at asof 2026-07-01; P(date push or cost revision, 2q) = 0.95"}])

    async def first(redact):
        async for line in scheduler.alert_stream(start, None, redact):
            if line.startswith("id:"):
                return line
    plain = asyncio.run(asyncio.wait_for(first(serving.plain_alert), 10))
    assert "very likely within the next two quarters" in plain and "0.95" not in plain
    assert "P(date push or cost revision, 2q) = 0.95" in asyncio.run(asyncio.wait_for(first(None), 10))


# ------------------------------------------------------------------ brief and second opinion

def test_brief_views_are_worded_and_cached_apart(client, world, monkeypatch):
    k = world["key"]["ipmd"]
    plain, full = brief.payload(k), brief.payload(k, numbers=True)
    assert plain["view"] == "plain" and full["view"] == "numbers"
    assert not leaks(plain) and not text_leaks(plain) and leaks(full)
    pr = plain["prediction"]
    assert pr["delay"] in CHANCES and pr["likely_slip"] in SLIPS | {"unknown"} and pr["horizon"] == "next two quarters"
    assert plain["drivers_plain"] == serving.project(k)["scores"]["drivers_plain"]
    words = (f"The model rates this project {pr['tier']}; a delay is {pr['delay']} over the next two quarters.\n\n"
             f"Progress is {plain['status']['physical_progress_pct']}%.")
    assert brief.validate(words, plain)[0]
    probs = {full["prediction"][c] for c in ("p_date_push_2q", "p_cost_revision_2q", "p_any_2q", "p_any_4q")}
    leaves = brief._numbers_in({k: v for k, v in plain.items() if k != "model_version"}, [], set())
    assert not probs & set(leaves)   # no probability among the numbers a plain brief may write
    systems = []
    monkeypatch.setattr(llm_client, "complete", lambda system, user: systems.append(system) or (
        words if "outlook is given in words" in system else f"It is {full['prediction']['tier']}, "
        f"{full['prediction']['p_any_2q']}.\n\nSo."))
    monkeypatch.setattr(llm_client, "_down_at", -1e9)
    ipmd, dev = headers(client, world, "ipmd"), headers(client, world, "developer")
    a = client.get(f"/api/projects/{k}/brief", headers=ipmd).json()
    b = client.get(f"/api/projects/{k}/brief", headers=dev).json()
    assert a["status"] == b["status"] == "ok" and a["view"] == "plain" and b["view"] == "numbers"
    assert a["text"] == words and a["text"] != b["text"] and systems == [brief.SYSTEM_PLAIN, brief.SYSTEM]
    assert not leaks(a["payload"]) and leaks(b["payload"])
    again = client.get(f"/api/projects/{k}/brief", headers=ipmd).json()
    assert again["cached"] and again["text"] == words and len(systems) == 2
    assert client.get(f"/api/projects/{k}/brief", headers=dev).json()["text"] == b["text"]


def _opinion_reply(p) -> str:
    strong = next(it["id"] for it in p["items"] if it["direction"] == "negative" and not it["stale"]
                  and (it["severity"] or 0) >= 2)
    return json.dumps({"concern": "concern", "headline": "Work on site is held up by a protest",
                       "narrative": f"Work on site was reported stopped after a protest [{strong}]. The report shows "
                                    "most of the work done [E1].", "key_evidence": [strong],
                       "gaps": ["No source says when work restarts"]})


def test_second_opinion_views_are_worded_and_stored_apart(client, world, fresh_db, monkeypatch):
    db.init()
    k = "PRJ-000698"
    db.save_signals([{"url": "https://n/stopped", "url_hash": "stopped", "title": "Work stopped at Vishnugad site "
                      "after protest", "source": "PTI", "published_at": "2026-08-02T06:00:00+00:00",
                      "fetched_at": "2026-08-02T06:00:00+00:00", "summary": "", "category": "law_order",
                      "severity": 2, "text_hash": "stopped", "links": [(k, 0.75, "places+context")]}])
    plain, full = so.pack(k), so.pack(k, numbers=True)
    assert plain["view"] == "plain" and full["view"] == "numbers"
    model = {p["view"]: next(it["text"] for it in p["items"] if it["kind"] == "model") for p in (plain, full)}
    assert "P(" in model["numbers"] and not re.search(r"\d\.\d\d", model["plain"])
    status = [next(it for it in p["items"] if it["kind"] == "status") for p in (plain, full)]
    assert "next two quarters" in model["plain"] and status[0] == status[1]   # the report line is a fact
    assert not text_leaks([it["text"] for it in plain["items"]])
    assert so.evidence_hash(plain) != so.evidence_hash(full)
    legacy = {kk: v for kk, v in full.items() if kk != "view"}   # the numbers view hashes as before the views
    assert so.evidence_hash(full) == so.evidence_hash(legacy)
    monkeypatch.setattr(llm_client, "chat", lambda messages, **kw: _opinion_reply(full))
    monkeypatch.setattr(llm_client, "_down_at", -1e9)
    out = so.generate(k, numbers=True)
    assert out["status"] == "ok" and out["view"] == "numbers"
    ipmd, dev = headers(client, world, "ipmd"), headers(client, world, "developer")
    assert client.get(f"/api/projects/{k}/second-opinion?cached=1", headers=ipmd).json()["status"] == "none"
    got = client.get(f"/api/projects/{k}/second-opinion?cached=1", headers=dev).json()
    assert got["status"] == "ok" and got["view"] == "numbers" and got["cached"]
    monkeypatch.setattr(llm_client, "chat", lambda messages, **kw: _opinion_reply(plain))
    o = client.get(f"/api/projects/{k}/second-opinion", headers=ipmd).json()
    assert o["status"] == "ok" and o["view"] == "plain" and not o["cached"]
    assert not leaks(o) and not text_leaks(o) and o["evidenceHash"] == so.evidence_hash(plain)
    assert {r["view"] for r in db.second_opinions(k)} == {"numbers", "plain"}


# ------------------------------------------------------------------ chat and worker

CHAT_VIEWERS = {"public": Viewer("public"), "agency": Viewer("agency_official", agency="NHAI"),
                "ministry": Viewer("ministry_official", ministry="Ministry of Road Transport & Highways"),
                "ipmd": Viewer("ipmd_analyst")}


def _chat_calls(k):
    return [("search_projects", {"tier": "Critical", "limit": 5}), ("portfolio_stats", {"group_by": "tier"}),
            ("get_project", {"key": k}), ("project_history", {"key": k}), ("compare_projects", {"keys": [k, k]}),
            ("external_factors", {"key": k}), ("external_factors", {"factor": "land"}),
            ("explain_prediction", {"key": k}), ("agency_scorecard", {"sort": "schedule_overrun"}),
            ("agency_scorecard", {}), ("bottlenecks", {}), ("second_opinion", {"key": k})]


@pytest.mark.parametrize("role", list(CHAT_VIEWERS))
def test_chat_tools_say_words_to_a_viewer_without_numbers(role):
    db.init()
    v = CHAT_VIEWERS[role]
    k = serving.projects(scope=v.scope, size=1)["items"][0]["key"]
    for name, args in _chat_calls(k):
        if not tools.TOOLS[name].allowed(v):
            continue
        r = tools.run(v, name, args)
        body = {"facts": r.facts, "cards": r.cards, "summary": r.summary}
        assert not fact_leaks(r.facts), (role, name, fact_leaks(r.facts)[:4])
        assert not leaks(r.cards), (role, name, leaks(r.cards)[:4])
        assert not text_leaks(body), (role, name, text_leaks(body)[:2])
        assert "%" not in re.sub(r"\d+(?:\.\d+)?% (?:progress|done)|progress \d+(?:\.\d+)?%|\d+(?:\.\d+)?%/q", "",
                                 r.summary) or name == "project_history", (role, name, r.summary)
    p = tools.run(v, "get_project", {"key": k})
    assert p.facts["outlook"]["over"] == "the next two quarters" and p.cards[0]["outlook"]["horizon"]
    assert p.cards[0]["pAny2q"] is None
    if v.can("insights"):
        e = tools.run(v, "explain_prediction", {"key": k})
        assert e.cards[0]["drivers"] == [] and e.cards[0]["driversPlain"]
        assert all(set(d) == {"input", "effect", "strength"} for d in e.facts["drivers"])
        assert e.sources[0]["source"] == "PAIMANA risk model"
    if v.can("agencies"):
        a = tools.run(v, "agency_scorecard", {"sort": "schedule_overrun"})
        assert all("cost_overrun_pct" not in x and x["schedule"] and x["cost"] for x in a.facts["agencies"])


def test_chat_tools_keep_numbers_for_the_developer():
    db.init()
    dev = Viewer("developer")
    k = serving.projects(size=1)["items"][0]["key"]
    p = tools.run(dev, "get_project", {"key": k})
    assert p.facts["slip_chance_within_2_quarters_pct"] and p.facts["horizon_quarters"] == [2, 4]
    assert p.facts["outlook"] and p.cards[0]["pAny2q"] is not None
    e = tools.run(dev, "explain_prediction", {"key": k})
    assert e.cards[0]["drivers"] and all("contribution" in d for d in e.cards[0]["drivers"])
    a = tools.run(dev, "agency_scorecard", {"sort": "schedule_overrun"})
    assert all("schedule_overrun_pct" in x and x["schedule"] for x in a.facts["agencies"])


def test_the_answer_check_refuses_model_internals_without_numbers():
    blocks = [{"tool": "get_project", "cite": 1, "tier": "High", "outlook": {"delay": "likely"}}]
    src = [{"n": 1, "title": "p", "source": "PAIMANA", "date": None}]
    assert agent.check("It is High; a delay is likely [1].", blocks, src, "why?", False, numbers=False)[0]
    assert not agent.check("SHAP says High [1].", blocks, src, "why?", False, numbers=False)[0]
    assert agent.check("SHAP says High [1].", blocks, src, "why?", False, numbers=True)[0]
    assert not agent.check("It is High, with a 71% chance [1].", blocks, src, "why?", False, numbers=False)[0]
    route = agent.router.Route("why?", [], [], 1.0)
    msgs = agent._writer_messages("why?", route, [{"role": "user", "content": "why?"}], src, blocks, False,
                                  numbers=False)
    assert msgs[0]["content"].endswith(agent.NO_NUMBERS)


def test_worker_memo_input_has_no_model_numbers(monkeypatch):
    prompts = []
    monkeypatch.setattr(worker, "_generate", lambda system, user, model: prompts.append(user) or model(
        summary="s", bottlenecks=[], recommended_action="a"))
    k = serving.projects(size=1)["items"][0]["key"]
    fc = worker.forecaster(k)
    worker.analyst(fc, ScoutOutput(tags=[]))
    assert fc["p_any_2q"] is not None   # the forecaster (worker console) keeps them
    assert "P(" not in prompts[0] and not re.search(r"(?<![\d.])0\.\d", prompts[0]) and "SHAP" not in prompts[0]
    assert f"a completion-date push is {fc['outlook']['delay']}" in prompts[0]
    assert fc["drivers_plain"][0]["label"] in prompts[0]


def test_an_index_saved_before_the_policy_is_never_served(tmp_path):
    """The search index saved before the numbers policy (chunk VERSION 2) has the public project cards with the chance
    of a slip in percent and the model-statistics docs open to officials: load() refuses it, so _refresh() does not
    serve it while the new one is built; _rebuild() still reuses its vectors (load(any_version=True))."""
    rag.save(rag.build_index([rag._chunk("help:1", "help", "public", "Help", "what the tiers mean", "PAIMANA help")],
                             "before"), tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    (tmp_path / "meta.json").write_text(json.dumps({**meta, "version": 2}), encoding="utf-8")
    assert rag.load(tmp_path) is None and rag.load(tmp_path, any_version=True) is not None


def test_model_statistics_docs_only_for_the_developer():
    rows = [rag._chunk("doc:a", "doc", "official", "Method", "how the tiers are cut", "docs/A.md"),
            rag._chunk("doc:b", "doc", "numbers", "Backtest", "validation results", "docs/MODEL_UPGRADES_2026-09.md"),
            rag._chunk("help:1", "help", "public", "Help", "what the tiers mean", "PAIMANA help")]
    idx = rag.build_index(rows, "test")

    def seen(v):
        return {idx.rows[i]["id"] for i in idx.candidates(v)}
    assert seen(Viewer("public")) == {"help:1"}
    assert seen(Viewer("ipmd_analyst")) == seen(Viewer("ministry_official", ministry="Ministry of Coal")) == {
        "doc:a", "help:1"}
    assert seen(Viewer("developer")) == {"doc:a", "doc:b", "help:1"}
    vis = {c["source"]: c["visibility"] for c in rag.doc_chunks()}
    assert vis["docs/MODEL_UPGRADES_2026-09.md"] == "numbers" and vis["docs/SECOND_OPINION.md"] == "official"
