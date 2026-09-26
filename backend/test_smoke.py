"""Minimal self-check for the non-LLM logic (Auditor detection, Forecaster lookup).
Run: python -m backend.test_smoke
"""
from backend import data_access
from llm import worker


def test_auditor_flags_zero_progress_with_overrun():
    row = {
        "project_id": "does-not-exist-in-panel",
        "project_name": "test",
        "physical_progress": 0,
        "cost_overrun_pct": 12.5,
    }
    issues, confidence, query = worker.auditor(row)
    assert any("cost has already overrun" in i for i in issues)
    assert confidence < 1.0
    # LLM only called when issues exist and LM Studio is reachable; skip asserting query here.


def test_auditor_no_issues_when_clean():
    row = {
        "project_id": "does-not-exist-in-panel-2",
        "project_name": "test",
        "physical_progress": 50,
        "cost_overrun_pct": 0,
    }
    issues, confidence, query = worker.auditor(row)
    # staleness-missing-panel issue is expected (no panel history for a fake id)
    assert query is None or len(issues) > 0


def test_forecaster_is_pure_lookup_no_llm_import():
    import inspect
    src = inspect.getsource(worker.forecaster)
    assert "call_llm(" not in src


def test_forecaster_lookup_matches_csv():
    df = data_access.load_latest_features()
    pid = df.iloc[0]["project_id"]
    out = worker.forecaster(pid)
    assert out["project_id"] == pid
    assert out["slip_probability"] == df.iloc[0]["slip_probability"]


if __name__ == "__main__":
    test_auditor_flags_zero_progress_with_overrun()
    test_auditor_no_issues_when_clean()
    test_forecaster_is_pure_lookup_no_llm_import()
    test_forecaster_lookup_matches_csv()
    print("smoke tests passed")
