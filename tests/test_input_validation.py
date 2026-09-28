"""Input bounds on the API (Segment 9 hardening): a project key must look like PRJ-000123 (400 before any lookup),
every free-text query and path parameter has a length limit and paging its range (422), and an upload name never
reaches the file system as given."""
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import routes  # noqa: E402
from backend.live import watcher  # noqa: E402
from backend.main import app  # noqa: E402
from viewers import as_role  # noqa: E402 - tests/viewers.py

BAD_KEYS = ["PRJ-1", "prj-000698", "PRJ-0000001", "PRJ-00069a", "nonsense", "PRJ-000698%00",
            "PRJ-000698 OR 1=1", "PRJ-000698;", " PRJ-000698"]
# in a body or a query string a path can arrive as given (in a URL path the router drops it before any route)
BAD_BODY_KEYS = [k.replace("%", "") for k in BAD_KEYS] + ["../../etc", "PRJ-000698/../PRJ-000001", "PRJ-000698\n"]
KEY_ROUTES = ["/api/projects/{}", "/api/projects/{}/timeline", "/api/projects/{}/research",
              "/api/projects/{}/forecast", "/api/projects/{}/brief", "/api/projects/{}/second-opinion",
              "/api/projects/{}/signals"]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PAIMANA_DB", str(tmp_path_factory.mktemp("db") / "paimana.db"))
        with TestClient(app) as c:
            c.headers.update(as_role(c, "developer"))   # the job routes are the developer's
            yield c


def test_a_malformed_project_key_is_400_everywhere_and_a_well_formed_unknown_one_404(client):
    assert routes.KEY_RX.fullmatch("PRJ-000698") and not routes.KEY_RX.fullmatch("PRJ-000698\n")
    for key in BAD_KEYS:
        for route in KEY_ROUTES:
            r = client.get(route.format(key))
            assert r.status_code == 400 and "PRJ-000123" in r.json()["detail"], (route, key, r.status_code)
    for key in BAD_BODY_KEYS:
        assert client.post("/api/watchlist", json={"projectKey": key}).status_code == 400, key
        assert client.delete("/api/watchlist", params={"project_key": key}).status_code == 400, key
        for job in ("scout", "research", "second-opinion"):
            assert client.post(f"/api/jobs/{job}", params={"project_key": key}).status_code == 400, (job, key)
        chat = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "projectKey": key})
        assert chat.status_code == 400, key
    for route in KEY_ROUTES:
        assert client.get(route.format("PRJ-999999")).status_code == 404, route
    assert client.post("/api/watchlist", json={"projectKey": "PRJ-999999"}).status_code == 404
    assert client.post("/api/jobs/scout", params={"project_key": "PRJ-999999"}).status_code == 404


def test_every_free_text_parameter_has_a_length_bound_and_paging_its_range(client):
    long = "x" * 101
    for path, params in (("/api/projects", {"q": long}), ("/api/projects", {"ministry": long}),
                         ("/api/projects", {"sector": "s" * 61}), ("/api/projects", {"state": "s" * 61}),
                         ("/api/portfolio", {"ministry": long}), ("/api/portfolio", {"sector": "s" * 61}),
                         ("/api/portfolio", {"state": "s" * 61}), ("/api/agencies/matrix", {"sector": "s" * 61}),
                         ("/api/agencies/matrix", {"ministry": long}), ("/api/bottlenecks", {"category": "c" * 41}),
                         ("/api/bottlenecks", {"state": "s" * 61}), ("/api/signals/feed", {"category": "c" * 41}),
                         ("/api/signals/feed", {"state": "s" * 61}), ("/api/signals/feed", {"severity": 4}),
                         ("/api/projects", {"page": 0}), ("/api/projects", {"size": 101}),
                         ("/api/projects", {"size": 0}), ("/api/alerts", {"size": 101}),
                         ("/api/bottlenecks", {"min_projects": 0}), ("/api/projects", {"tier": "Extreme"}),
                         ("/api/projects", {"sort": "secret"}), ("/api/stream", {"after": -1})):
        assert client.get(path, params=params).status_code == 422, (path, params)
    assert client.get(f"/api/agencies/{'a' * 101}/projects").status_code == 422
    assert client.get(f"/api/agencies/{'a' * 100}/projects").status_code == 404      # bounded, then unknown
    assert client.get(f"/api/bottlenecks/{'b' * 65}").status_code == 422
    assert client.get(f"/api/bottlenecks/{'b' * 64}").status_code == 404
    assert client.post("/api/jobs/bhoomi-pull", params={"state": "s" * 61}).status_code == 422
    assert client.post("/api/jobs/scout", params={"project_key": "P" * 33}).status_code == 422
    assert client.delete("/api/watchlist", params={"project_key": "P" * 33}).status_code == 422
    assert client.get("/api/projects", params={"q": "x" * 100, "ministry": "m" * 100, "sector": "s" * 60,
                                              "state": "s" * 60, "size": 100}).status_code == 200


def test_an_upload_name_never_reaches_the_file_system_as_given(tmp_path, monkeypatch):
    """save_upload keeps only the base name, replaces every character outside a small set and refuses anything but
    .csv and .pdf, so a path in the name cannot leave the inbox (the endpoint test covers the route)."""
    monkeypatch.setattr(watcher, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(watcher, "ROOT", tmp_path)
    monkeypatch.setattr(watcher.db, "source_seen", lambda sha, pv: False)
    monkeypatch.setattr(watcher, "pipeline_version", lambda: "pv")
    out = watcher.save_upload("..\\..\\..\\etc\\passwd; rm -rf ~ .csv", io.BytesIO(b"a,b\n1,2\n"))
    saved = tmp_path / out["saved_as"]
    assert saved.parent == tmp_path / "inbox" and saved.name == "passwd_ rm -rf _ .csv"
    out = watcher.save_upload("../../evil.csv", io.BytesIO(b"a,b\n1,2\n"))
    assert (tmp_path / out["saved_as"]).parent == tmp_path / "inbox" and out["saved_as"].endswith("inbox/evil.csv")
    for name in ("report.exe", "report.csv.exe", "report", ".csv", "report.PDF.txt", None):
        with pytest.raises(ValueError):
            watcher.save_upload(name, io.BytesIO(b"x"))
    monkeypatch.setattr(watcher, "MAX_UPLOAD", 8)
    with pytest.raises(ValueError, match="larger than"):
        watcher.save_upload("big.csv", io.BytesIO(b"x" * 9))
    assert not list((tmp_path / "inbox").glob(".upload-*"))     # the partial file is removed
