"""Sessions, the cookie, and what every write must carry (SPEC9 section 2; docs/ACCESS_CONTROL.md, docs/SECURITY.md).

A session is a 256-bit random token in the `paimana_session` cookie (HttpOnly, SameSite=Lax, Path=/, Secure when
settings.secure_cookies); the database keeps only its sha256 (app.sessions.id) with the session's CSRF token. It
ends after settings.session_idle_h idle hours or settings.session_max_d days, at sign-out, when its account is
disabled, and when its account's password changes (every session but the one that changed it).

current() resolves the request's cookie once per request (cached on request.state): None without a cookie, the
session joined with its account when it is live, 401 with the cookie cleared when it is not. guard() is an
app-wide dependency (backend/main.py): on every request that is not GET/HEAD/OPTIONS the Origin header, when sent,
must be one of settings.allowed_origins (a browser always sends it on a cross-site write; curl and the tests may
leave it out), and a request that carries a live session must send its CSRF token as X-CSRF-Token (GET
/api/auth/me hands it to the page). A cookie-less write (the public's chat, sign-in, sign-up, reset) needs no token.

client_ip() is the client address as backend/auth/middleware.py set it (X-Forwarded-For believed only from
settings.trusted_proxies).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, Response

from backend import settings as cfg
from backend.db import accounts
from backend.db.engine import now

COOKIE = "paimana_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_MISSING = object()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    """256 random bits, URL-safe (43 characters)."""
    return secrets.token_urlsafe(32)


def idle() -> timedelta:
    return timedelta(hours=cfg.settings.session_idle_h)


def lifetime() -> timedelta:
    return timedelta(days=cfg.settings.session_max_d)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _cookie_attrs() -> str:
    return "Path=/; HttpOnly; SameSite=Lax" + ("; Secure" if cfg.settings.secure_cookies else "")


def set_cookie(response: Response, token: str) -> None:
    response.headers.append("Set-Cookie", f"{COOKIE}={token}; Max-Age={int(lifetime().total_seconds())}; "
                                          f"{_cookie_attrs()}")


def cleared_cookie() -> str:
    """The Set-Cookie value that removes the session cookie (a response object or a raised 401 carries it)."""
    return f"{COOKIE}=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; {_cookie_attrs()}"


def clear_cookie(response: Response) -> None:
    response.headers.append("Set-Cookie", cleared_cookie())


def session_of(request: Request) -> dict | None:
    """The live session the request's cookie names, with its account (accounts.session), or None: no cookie, or a
    cookie that names no live session. Looked up once per request; a live one is marked seen."""
    cached = getattr(request.state, "session", _MISSING)
    if cached is not _MISSING:
        return cached
    token = request.cookies.get(COOKIE)
    s = None
    if token and len(token) <= 128:
        s = accounts.session(token_hash(token), idle())
        if s is not None:
            accounts.touch_session(s["session_id"])
    request.state.session = s
    return s


def current(request: Request) -> dict | None:
    """The request's live session, None for the public (no cookie); 401 with the cookie cleared when the cookie names
    no live session."""
    s = session_of(request)
    if s is None and COOKIE in request.cookies:
        raise HTTPException(status_code=401, detail="your session has ended; sign in again",
                            headers={"Set-Cookie": cleared_cookie()})
    return s


def origin_allowed(origin: str) -> bool:
    return origin.rstrip("/") in {o.rstrip("/") for o in cfg.settings.allowed_origins}


def guard(request: Request) -> None:
    """App-wide dependency: the Origin and CSRF checks of every write (module docstring)."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and not origin_allowed(origin):
        raise HTTPException(status_code=403, detail="this request came from a page the server does not trust")
    s = session_of(request)
    if s is not None and not hmac.compare_digest(request.headers.get(CSRF_HEADER, "").encode(),
                                                 s["csrf_token"].encode()):
        raise HTTPException(status_code=403, detail="the request is missing its security token; reload the page")


def start(user: dict, request: Request, response: Response, actor_role: str | None = None) -> dict:
    """A new session for user (after a successful sign-in): the row, the cookie on response; the request's earlier
    session, if any, is ended (a sign-in never keeps an old cookie alive). Returns the session as current() would."""
    old = session_of(request)
    if old is not None:
        accounts.revoke_session(old["session_id"])
    token, csrf = new_token(), new_token()
    expires = now() + lifetime()
    ip = client_ip(request)
    accounts.create_session(token_hash(token), user["id"], csrf, expires, ip, request.headers.get("user-agent"),
                            actor={"user_id": user["id"], "email": user["email"], "ip": ip},
                            actor_role=actor_role or user["role"])
    set_cookie(response, token)
    s = accounts.session(token_hash(token), idle())
    request.state.session = s
    return s


def expires_at(s: dict) -> str:
    """When the session ends if unused from now: the earlier of its absolute expiry and now plus the idle time."""
    absolute = datetime.fromisoformat(s["expires_at"])
    return min(absolute, now() + idle()).isoformat(timespec="seconds")
