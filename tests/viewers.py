"""The one way a test becomes a viewer other than the anonymous public: as_role(client, role, ...) makes the client
(a TestClient, or any httpx.Client aimed at the app) act as that viewer and returns the headers every write of the
test must carry. No test sends a session cookie or a CSRF token by hand.

  h = as_role(client, "ministry", ministry="Ministry of Coal")
  client.get("/api/portfolio")                       # as that ministry official (the cookie rides along)
  client.post("/api/watchlist", json=..., headers=h)  # a write carries the CSRF token

role: 'public' (or None) | 'agency' | 'ministry' | 'ipmd' | 'developer' (the full role names work too); ministry /
agency: the scope of those roles, as /api/scopes spells it; admin: the administrator flag (IPMD analysts). The account
(one per role, scope and flag, email under tests.paimana.local) is created in app.users when missing and set back to
active with that role, scope and flag when it drifted; the client then signs in through POST /api/auth/login, so it
holds a real session cookie, and gets the session's CSRF token back. 'public' clears the client's cookies and returns
{}. A client that already holds a live session of the same account is not signed in again (the argon2 check is the
slow part of a test that switches viewers often).
"""
from __future__ import annotations

import hashlib
import weakref
from functools import lru_cache

from backend.access import known_scope
from backend.auth import passwords, sessions
from backend.db import accounts

PASSWORD = "correct horse battery staple 42"
DOMAIN = "tests.paimana.local"
ROLES = {None: "public", "public": "public", "agency": "agency_official", "ministry": "ministry_official",
         "ipmd": "ipmd_analyst", "developer": "developer"}
_signed_in: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


@lru_cache(maxsize=1)
def _hash() -> str:
    return passwords.hash_password(PASSWORD)


def email_for(role: str, ministry: str | None = None, agency: str | None = None, admin: bool = False) -> str:
    """The test account's email for this viewer (the same one every time)."""
    tag = hashlib.sha1(f"{ministry}|{agency}".encode()).hexdigest()[:10]
    return f"{role.split('_')[0]}-{tag}{'-admin' if admin else ''}@{DOMAIN}"


def account(role: str, ministry: str | None = None, agency: str | None = None, admin: bool = False) -> dict:
    """The active test account for this viewer (created or corrected), as app.users has it."""
    full = ROLES.get(role, role)
    if full != "developer":
        ministry, agency = known_scope(full, ministry, agency)
    want = {"role": full, "ministry": ministry, "agency": agency, "is_admin": admin or full == "developer",
            "status": "active"}
    email = email_for(full, ministry, agency, admin)
    u = accounts.user(email=email)
    if u is None:
        u = accounts.create_user(email, _hash(), f"Test {full}", full, ministry, agency, want["is_admin"])
    elif any(u[k] != v for k, v in want.items()):
        u = accounts.update_user(u["id"], want)
    return u


def as_role(client, role, *, ministry=None, agency=None, admin=False) -> dict[str, str]:
    """Make client act as that viewer; returns the headers (the CSRF token) its writes must send."""
    if ROLES.get(role, role) == "public":
        client.cookies.clear()
        _signed_in.pop(client, None)
        return {}
    u = account(role, ministry, agency, admin)
    held = _signed_in.get(client)
    token = client.cookies.get(sessions.COOKIE)
    if held and held[0] == u["id"] and token:
        s = accounts.session(sessions.token_hash(token), sessions.idle())
        if s is not None and s["id"] == u["id"]:
            return {sessions.CSRF_HEADER: s["csrf_token"]}
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": u["email"], "password": PASSWORD})
    assert r.status_code == 200, (r.status_code, r.text)
    csrf = r.json()["csrfToken"]
    _signed_in[client] = (u["id"], csrf)
    return {sessions.CSRF_HEADER: csrf}
