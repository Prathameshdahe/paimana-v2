"""The HTTP hardening (backend/auth/middleware.py) and the probes (backend/main.py): security headers, request ids,
no-store on the account routes, errors without tracebacks, 422 without the input, the body limit, the time limit,
the Host check, client addresses behind a trusted proxy, /healthz and /readyz. The middlewares are also tried on a
small app of their own, so a slow or failing route can be staged."""
import asyncio
import dataclasses
import sys
import time
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db  # noqa: E402
from backend import main  # noqa: E402
from backend import settings as cfg  # noqa: E402
from backend.auth import middleware  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def with_settings(monkeypatch, **kw):
    monkeypatch.setattr(cfg, "settings", dataclasses.replace(cfg.settings, **kw))


@pytest.fixture()
def small(monkeypatch):
    """A tiny app behind the same middlewares, with routes that fail, stall or echo the client address."""
    mini = FastAPI()
    middleware.install(mini)

    @mini.get("/boom")
    def boom():
        raise RuntimeError("secret connection string postgresql://paimana:hunter2@db")

    @mini.get("/slow-async")
    async def slow_async():
        await asyncio.sleep(3)
        return {"ok": True}

    @mini.get("/slow-sync")
    def slow_sync():
        time.sleep(1.5)
        return {"ok": True}

    @mini.get("/api/chat")
    async def exempt():
        await asyncio.sleep(0.6)
        return {"ok": True}

    @mini.post("/start-job")
    def start_job(background: BackgroundTasks):
        background.add_task(time.sleep, 0.8)
        background.add_task(ran.append, "job")
        return {"started": True}

    @mini.get("/who")
    def who(request: Request):
        return {"ip": request.client.host, "scheme": request.url.scheme}

    @mini.post("/echo")
    async def echo(request: Request):
        return {"n": len(await request.body())}

    ran = []
    mini.state.ran = ran
    monkeypatch.setattr(middleware, "TIMEOUT_S", 0.4)
    return mini


def test_security_headers_request_id_and_no_store(client, monkeypatch):
    r = client.get("/api/meta")
    for k, v in middleware.SECURITY_HEADERS.items():
        assert r.headers[k] == v
    assert "strict-transport-security" not in r.headers and len(r.headers["x-request-id"]) == 32
    assert "no-store" not in r.headers.get("cache-control", "")
    assert client.get("/api/meta", headers={"X-Request-ID": "nginx-abc-12345"}).headers["x-request-id"] == \
        "nginx-abc-12345"
    assert client.get("/api/meta", headers={"X-Request-ID": "<script>"}).headers["x-request-id"] != "<script>"
    for path in ("/api/auth/me", "/api/admin/users"):
        assert client.get(path).headers["cache-control"] == "no-store"
    missing = client.get("/api/no-such-route")
    assert missing.status_code == 404 and missing.headers["x-frame-options"] == "DENY"
    with_settings(monkeypatch, secure_cookies=True)
    assert client.get("/api/meta").headers["strict-transport-security"] == "max-age=31536000"


def test_an_error_never_sends_its_traceback(small):
    with TestClient(small) as c:
        r = c.get("/boom")
    body = r.json()
    assert r.status_code == 500 and body == {"detail": "internal error", "requestId": r.headers["x-request-id"]}
    assert "hunter2" not in r.text and "Traceback" not in r.text and r.headers["x-content-type-options"] == "nosniff"


def test_validation_errors_do_not_echo_the_input(client):
    secret = "p" * 300
    r = client.post("/api/auth/login", json={"email": "a@b.gov.in", "password": secret})
    assert r.status_code == 422 and secret not in r.text
    assert r.json()["detail"][0]["loc"] == ["body", "password"] and r.json()["detail"][0]["msg"]


def test_body_limit(client, small):
    big = b'{"messages": [' + b" " * (middleware.BODY_MAX + 10) + b"]}"
    r = client.post("/api/chat", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and "1 MiB" in r.json()["detail"]

    def chunks():   # no Content-Length: counted as it streams in
        for _ in range(3):
            yield b"x" * (middleware.BODY_MAX // 2)
    with TestClient(small) as c:
        assert c.post("/echo", content=chunks()).status_code == 413
        assert c.post("/echo", content=b"x" * 1000).json() == {"n": 1000}


def test_time_limit(small):
    with TestClient(small) as c:
        for path in ("/slow-async", "/slow-sync"):
            t0 = time.monotonic()
            r = c.get(path)
            assert r.status_code == 504 and r.json()["requestId"], path
            assert time.monotonic() - t0 < 1.2, path     # answered at the limit, not when the route ends
        assert c.get("/api/chat").status_code == 200     # the streams and the LLM routes are exempt
        r = c.post("/start-job")                         # answered at once; its background job outlives the limit
        assert r.status_code == 200 and small.state.ran == ["job"]
    assert middleware.EXEMPT.match("/api/projects/PRJ-000001/brief")
    assert middleware.EXEMPT.match("/api/projects/PRJ-000001/second-opinion")
    assert not middleware.EXEMPT.match("/api/projects/PRJ-000001")


def test_host_check(client, monkeypatch):
    with_settings(monkeypatch, allowed_hosts=("radar.example.gov.in", "localhost", "127.0.0.1"))
    assert client.get("/api/meta", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/meta", headers={"Host": "radar.example.gov.in"}).status_code == 200
    assert client.get("/api/meta", headers={"Host": "localhost:8000"}).status_code == 200
    for path in ("/healthz", "/readyz"):   # the container's own probe answers for any host
        assert client.get(path, headers={"Host": "evil.example"}).status_code in (200, 503)
    assert middleware.host_allowed("a.example.org", ("*.example.org",))
    assert not middleware.host_allowed("example.org.evil", ("*.example.org",))
    assert middleware.host_allowed("[::1]:8000", ("[::1]",))


def test_forwarded_client_only_from_trusted_proxies():
    nets = ("10.201.0.0/24",)
    f = middleware.forwarded_client
    assert f("10.201.0.3", "1.2.3.4, 198.51.100.9", nets) == "198.51.100.9"     # the hop nginx appended
    assert f("10.201.0.3", "198.51.100.9, 10.201.0.8", nets) == "198.51.100.9"  # a second proxy is skipped
    assert f("203.0.113.5", "1.2.3.4", nets) is None                              # not a trusted peer: ignored
    assert f("10.201.0.3", "1.2.3.4", ()) is None                                 # no proxies configured
    assert f("10.201.0.3", "garbage, 198.51.100.9", nets) == "198.51.100.9"
    assert f("10.201.0.3", "198.51.100.9, garbage", nets) is None                 # malformed: believe nothing
    assert f("10.201.0.3", "10.201.0.7", nets) == "10.201.0.7"


def test_client_address_behind_the_proxy(small, monkeypatch):
    with_settings(monkeypatch, trusted_proxies=("10.201.0.0/24",))
    headers = {"X-Forwarded-For": "6.6.6.6, 198.51.100.9", "X-Forwarded-Proto": "https"}
    with TestClient(small, client=("10.201.0.3", 5000)) as c:
        assert c.get("/who", headers=headers).json() == {"ip": "198.51.100.9", "scheme": "https"}
    with TestClient(small, client=("203.0.113.5", 5000)) as c:   # a client that sends the header itself
        assert c.get("/who", headers=headers).json() == {"ip": "203.0.113.5", "scheme": "http"}


def test_health_and_readiness(client, monkeypatch):
    assert client.get("/healthz").json() == {"status": "ok"}
    monkeypatch.setattr(main.llm_client, "LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(main, "_llm_probe", {"at": -1e9, "ok": False})
    r = client.get("/readyz")
    body = r.json()
    assert r.status_code == 200 and body["ready"] and body["database"] and body["data"]
    assert body["llm"] == "unreachable"      # reported, not required
    monkeypatch.setattr(db, "healthy", lambda: False)
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json()["ready"] is False and r.json()["database"] is False


def test_api_docs_setting():
    assert cfg.load({"API_DOCS": "0"}).api_docs is False and cfg.load({}).api_docs is True
