"""The HTTP hardening around every request (SPEC9 section 2; docs/SECURITY.md, API). install(app) puts them in this
order, outermost first:

1. ProxyHeaders: behind nginx the peer is the proxy. When the peer is in settings.trusted_proxies, the client address
   is the right-most X-Forwarded-For hop that is not itself a trusted proxy, and the scheme X-Forwarded-Proto; from
   any other peer both headers are ignored (a client cannot choose its own address). uvicorn runs with
   --no-proxy-headers so this is the one place that reads them (Dockerfile.api).
2. Front: a request id (the proxy's X-Request-ID when it looks like one, else a new one; echoed back), the security
   headers on every response (nosniff, frame DENY, referrer policy, permissions policy, HSTS when
   settings.secure_cookies, no-store on /api/auth and /api/admin) and one JSON access-log line per request (logger
   paimana.access: request id, client, method, path, the query string except on /api/auth and /api/admin, status,
   milliseconds, user id). Its last-resort handler turns an exception from the layers below into Errors' answer.
3. CORS from settings.allowed_origins, with credentials, the methods and headers the frontend uses.
4. HostCheck: the Host header must match settings.allowed_hosts ('*' any, '*.example.org' a suffix); /healthz and
   /readyz answer for any host (the container's own probe calls http://127.0.0.1:8000/healthz).
5. BodyLimit: a request body may be BODY_MAX (1 MiB); the report upload (UPLOAD_PATH) UPLOAD_MAX, 110 MiB, above the
   watcher's own 100 MB check, but only for a request that carries a session cookie (the route itself checks the
   session and the `jobs` feature before it reads a byte; the public never gets the allowance). A declared length
   over the limit is refused before reading, a streamed body as it passes.
6. Timeout: TIMEOUT_S (30 s) until a request is answered, else 504; the streams, the upload and the routes that wait on
   the local LLM or the web (EXEMPT) are exempt, and a background task after the answer (a job started from the API)
   is not timed. A synchronous route keeps running in its thread after the 504 (Python cannot stop a thread); the
   database's statement timeout (15 s) bounds its queries.
7. Errors: any exception a route raises becomes 500 {"detail": "internal error", "requestId"}; the traceback goes to
   the log with the request id, never to the client.

configure_logging() gives the app's own loggers (backend.*, llm.*, paimana.*) a stderr handler at INFO, so the access
log, the job runs and the errors reach `docker compose logs` (uvicorn configures only its own loggers).
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import sys
import time
import uuid
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend import settings as cfg

from .sessions import COOKIE

log = logging.getLogger("paimana.http")
access_log = logging.getLogger("paimana.access")

BODY_MAX, UPLOAD_MAX, UPLOAD_PATH = 1 << 20, 110 << 20, "/api/jobs/ingest"
TIMEOUT_S = 30.0
EXEMPT = re.compile(r"^/api/(chat|stream|jobs/ingest|jobs/scout|worker-runs/trigger)$"
                    r"|^/api/projects/[^/]+/(brief|second-opinion)$")
HEALTH_PATHS = frozenset({"/healthz", "/readyz"})
PRIVATE_PREFIXES = ("/api/auth", "/api/admin")   # no query string in the log; never cached
REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


class _Stderr(logging.StreamHandler):
    """Writes to sys.stderr as it is at each record (uvicorn's, or a test's capture), not as it was at start."""
    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def configure_logging() -> None:
    """INFO and up of the app's loggers to stderr, once: the access log as bare JSON lines, the rest with time,
    level and logger."""
    for name, fmt in (("paimana.access", "%(message)s"),
                      ("paimana.http", "%(asctime)s %(levelname)s %(name)s: %(message)s"),
                      ("backend", "%(asctime)s %(levelname)s %(name)s: %(message)s"),
                      ("llm", "%(asctime)s %(levelname)s %(name)s: %(message)s")):
        lg = logging.getLogger(name)
        if not any(isinstance(h, _Stderr) for h in lg.handlers):
            h = _Stderr()
            h.setFormatter(logging.Formatter(fmt))
            lg.addHandler(h)
            lg.setLevel(logging.INFO)
            lg.propagate = False


def _state(scope: Scope) -> dict:
    return scope.setdefault("state", {})


def _private(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in PRIVATE_PREFIXES)


def internal_error(scope: Scope) -> JSONResponse:
    return JSONResponse({"detail": "internal error", "requestId": _state(scope).get("request_id")}, status_code=500)


# ---------------------------------------------------------------- 1. the client address behind a proxy

@lru_cache(maxsize=8)
def _networks(cidrs: tuple[str, ...]) -> tuple:
    """The trusted networks; an entry that is not an address or network is logged and left out (settings.load refuses
    one at start; this keeps a later bad value from failing every request, the health probe's too)."""
    out = []
    for c in (c.strip() for c in cidrs):
        if not c:
            continue
        try:
            out.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            log.error("TRUSTED_PROXIES: %r is not an IP address or network; left out", c)
    return tuple(out)


def _ip(v: str):
    try:
        return ipaddress.ip_address(v.strip().strip("[]"))
    except ValueError:
        return None


def forwarded_client(peer: str | None, xff: str | None, cidrs: tuple[str, ...]) -> str | None:
    """The client address a request from peer with X-Forwarded-For xff stands for (None: keep the peer)."""
    nets = _networks(cidrs)
    addr = _ip(peer or "")
    if not xff or not nets or addr is None or not any(addr in n for n in nets):
        return None
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    for hop in reversed(hops):
        a = _ip(hop)
        if a is None:
            return None            # a malformed hop: believe nothing past it
        if not any(a in n for n in nets):
            return str(a)
    return str(_ip(hops[0])) if hops else None


class ProxyHeaders:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and cfg.settings.trusted_proxies:
            h = Headers(scope=scope)
            peer = scope.get("client")
            client = forwarded_client(peer[0] if peer else None, h.get("x-forwarded-for"),
                                      cfg.settings.trusted_proxies)
            if client is not None:
                scope = {**scope, "client": (client, 0)}
                proto = (h.get("x-forwarded-proto") or "").strip().lower()
                if proto in ("http", "https"):
                    scope["scheme"] = proto if scope["type"] == "http" else ("wss" if proto == "https" else "ws")
        await self.app(scope, receive, send)


# ---------------------------------------------------------------- 2. request id, headers, access log

class Front:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = Headers(scope=scope).get("x-request-id") or ""
        rid = given if REQUEST_ID.fullmatch(given) else uuid.uuid4().hex
        _state(scope)["request_id"] = rid
        path, t0, status, started = scope["path"], time.perf_counter(), [500], [False]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                started[0], status[0] = True, message["status"]
                h = MutableHeaders(scope=message)
                for k, v in SECURITY_HEADERS.items():
                    if k not in h:
                        h[k] = v
                h["x-request-id"] = rid
                if _private(path):
                    h["cache-control"] = "no-store"
                if cfg.settings.secure_cookies:
                    h["strict-transport-security"] = "max-age=31536000"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:   # noqa: BLE001 - the last resort: nothing below may send a traceback
            log.exception("unhandled error, request %s %s %s", rid, scope["method"], path)
            if not started[0]:
                await internal_error(scope)(scope, receive, send_with_headers)
        finally:
            peer = scope.get("client")
            line = {"rid": rid, "ip": peer[0] if peer else None, "method": scope["method"], "path": path,
                    "status": status[0], "ms": round((time.perf_counter() - t0) * 1000, 1),
                    "user": _state(scope).get("user_id")}
            query = scope.get("query_string", b"").decode("latin-1")
            if query and not _private(path):
                line["query"] = query[:500]
            access_log.info(json.dumps(line, separators=(",", ":")))


# ---------------------------------------------------------------- 4. Host

def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    name = host[:host.find("]") + 1] if host.startswith("[") else host.split(":")[0]
    name = name.lower()
    return any(p == "*" or name == p.lower() or (p.startswith("*.") and name.endswith(p[1:].lower()))
               for p in allowed)


class HostCheck:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] == "http" and scope["path"] not in HEALTH_PATHS
                and not host_allowed(Headers(scope=scope).get("host", ""), cfg.settings.allowed_hosts)):
            await JSONResponse({"detail": "invalid host header"}, status_code=400)(scope, receive, send)
            return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------- 5. body size

class TooLarge(HTTPException):
    """Raised from receive(); an HTTPException so FastAPI's body reader passes it on as the 413 it is."""
    def __init__(self, limit: int):
        super().__init__(status_code=413, detail=f"the request body is larger than {limit // (1 << 20)} MiB")


class BodyLimit:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        h = Headers(scope=scope)
        signed_in = COOKIE in cookie_parser(h.get("cookie") or "")
        limit = UPLOAD_MAX if scope["path"] == UPLOAD_PATH and signed_in else BODY_MAX
        declared = h.get("content-length") or ""
        if declared.isdigit() and int(declared) > limit:
            e = TooLarge(limit)
            await JSONResponse({"detail": e.detail}, status_code=413)(scope, receive, send)
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise TooLarge(limit)
            return message

        await self.app(scope, counted, send)


# ---------------------------------------------------------------- 6. time limit

class Timeout:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or EXEMPT.match(scope["path"]):
            await self.app(scope, receive, send)
            return
        started, late, answered = [False], [False], asyncio.Event()

        async def guarded(message: Message) -> None:
            if late[0]:
                return      # the route answered after its 504: nothing more goes out
            if message["type"] == "http.response.start":
                started[0] = True
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                answered.set()

        task = asyncio.ensure_future(self.app(scope, receive, guarded))
        waiter = asyncio.ensure_future(answered.wait())
        try:
            done, _ = await asyncio.wait({task, waiter}, timeout=TIMEOUT_S, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:   # the client went away: the route goes with it
            task.cancel()
            waiter.cancel()
            raise
        if done:
            waiter.cancel()
            await task      # answered in time: a background task after the answer (a job start) runs to its end
            return
        waiter.cancel()
        late[0] = True
        task.cancel()           # takes effect when a thread-bound route returns; its result is dropped
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        log.warning("request %s %s %s exceeded %.0f s", _state(scope).get("request_id"), scope["method"],
                    scope["path"], TIMEOUT_S)
        if not started[0]:
            await JSONResponse({"detail": "the request took too long; try again", "requestId":
                                _state(scope).get("request_id")}, status_code=504)(scope, receive, send)


# ---------------------------------------------------------------- 7. errors

class Errors:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = [False]

        async def watched(message: Message) -> None:
            if message["type"] == "http.response.start":
                started[0] = True
            await send(message)

        try:
            await self.app(scope, receive, watched)
        except TooLarge as e:
            if not started[0]:
                await JSONResponse({"detail": e.detail}, status_code=413)(scope, receive, send)
        except Exception:   # noqa: BLE001 - a route's failure is logged here and answered without its traceback
            log.exception("unhandled error, request %s %s %s", _state(scope).get("request_id"), scope["method"],
                          scope["path"])
            if not started[0]:
                await internal_error(scope)(scope, receive, send)


async def _validation_error(_request, exc: RequestValidationError) -> JSONResponse:
    """422 with where and what, never the input itself (a password that is too long is not echoed back)."""
    return JSONResponse({"detail": [{"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
                                    for e in exc.errors()]}, status_code=422)


def install(app: FastAPI) -> None:
    """The middlewares above in their order (Starlette runs the last added first), the 422 handler and the logging."""
    configure_logging()
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_middleware(Errors)
    app.add_middleware(Timeout)
    app.add_middleware(BodyLimit)
    app.add_middleware(HostCheck)
    app.add_middleware(CORSMiddleware, allow_origins=list(cfg.settings.allowed_origins), allow_credentials=True,
                       allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                       allow_headers=["Content-Type", "X-CSRF-Token", "Last-Event-ID", "X-Request-ID"],
                       expose_headers=["Retry-After", "X-Request-ID"])
    app.add_middleware(Front)
    app.add_middleware(ProxyHeaders)
