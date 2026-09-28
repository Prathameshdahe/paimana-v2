"""The sign-in and administration endpoints (SPEC9 section 2; shapes: frontend/src/contracts/auth.ts, models:
backend/schemas.py). /api/auth: signup, login, logout, me, password, reset. /api/admin (feature `admin`, the
audit log `audit`): sign-up requests, accounts, one-time reset tokens, the audit log.

Sign-in answers one generic 401 (GENERIC) for an unknown email, a wrong password and a disabled account alike, and
spends the same argon2 time and runs the same statements on each before answering (_fail); 423 and 429 carry
Retry-After (backend/auth/limits.py). The developer (backend/access.py) is invisible here to anyone else: not listed,
404 to fetch, change or reset, never a sign-up or approval role (the models allow the three official roles only).
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError

from backend import ratelimit
from backend.access import HIDDEN_ROLES, OFFICIAL_ROLES, Viewer, known_scope, need
from backend.db import accounts
from backend.db import app as appdb
from backend.db.engine import now
from backend.schemas import (
    ApproveSignup,
    AuditPage,
    LoginRequest,
    Me,
    PasswordChange,
    PasswordReset,
    RejectSignup,
    ResetToken,
    SignupAccepted,
    SignupIn,
    SignupRow,
    SignupStatus,
    User,
    UserPage,
    UserUpdate,
)

from . import limits, passwords, sessions

router = APIRouter(prefix="/api")
GENERIC = "email or password is wrong, or the account is locked or disabled"
RESET_TTL = timedelta(hours=24)
Admin = Depends(need("admin"))


def _email(raw: str) -> str:
    """The email as given, trimmed; 422 when it does not look like one or its domain is not allowed."""
    try:
        return passwords.normal_email(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _policy(password: str, email: str) -> None:
    try:
        passwords.check(password, email)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _wait(status: int, detail: str, seconds: float) -> HTTPException:
    s = max(1, int(round(seconds)))
    return HTTPException(status_code=status, detail=detail, headers={"Retry-After": str(s)})


def _me(s: dict) -> dict:
    return {"user_id": s["id"], "email": s["email"], "display_name": s["display_name"], "role": s["role"],
            "ministry": s["ministry"], "agency": s["agency"],
            "is_admin": s["role"] == "developer" or (s["role"] == "ipmd_analyst" and bool(s["is_admin"])),
            "csrf_token": s["csrf_token"], "session_expires_at": sessions.expires_at(s)}


def _locked(email: str) -> None:
    until = limits.email_lock(email)
    if until is not None:
        wait = limits.seconds(until)
        raise _wait(423, f"this account is locked after too many failed sign-ins; try again in "
                         f"{limits.minutes(wait)}", wait)


def _fail(email: str, ip: str | None, background: BackgroundTasks | None = None) -> None:
    """Record a failed password check on email: the attempt, and the account's counters with the lock this failure
    starts. The lock is computed and the counters' statement run whether or not the email has an account, the
    counters after the answer when background is given (a sign-in), so a failure takes as long for an unknown email
    as for a real one and its timing tells nothing."""
    lock = limits.lock_after_failure(email)
    accounts.record_attempt(email, ip, False)
    if background is not None:
        background.add_task(accounts.count_failure, email, lock)
    else:
        accounts.count_failure(email, lock)


# ---------------------------------------------------------------- /api/auth

@router.post("/auth/signup", status_code=202, response_model=SignupAccepted,
             responses={409: {"description": "a request for this email is pending, or it has an account"},
                        429: {"description": "3 requests an hour per address"}})
def post_signup(body: SignupIn, request: Request):
    """A request for an account; an administrator approves or rejects it (GET /api/admin/signups)."""
    ip = sessions.client_ip(request)
    wait = limits.signup_wait(ip)
    if wait is not None:
        raise _wait(429, f"too many access requests from this network; try again in {limits.minutes(wait)}", wait)
    email = _email(body.email)
    ministry, agency = known_scope(body.role, body.ministry, body.agency)
    _policy(body.password, email)
    if accounts.pending_signup(email) or accounts.user(email=email):
        raise HTTPException(status_code=409, detail="a request or an account for this email already exists")
    row = {"email": email, "display_name": body.display_name.strip(), "role": body.role, "ministry": ministry,
           "agency": agency, "justification": body.justification.strip() or None,
           "password_hash": passwords.hash_password(body.password)}
    try:
        return {"id": accounts.create_signup(row, ip)}
    except IntegrityError as e:   # a second request for the email in the same instant
        if isinstance(e.orig, UniqueViolation):
            raise HTTPException(status_code=409, detail="a request for this email is already pending") from e
        raise


@router.post("/auth/login", response_model=Me,
             responses={401: {"description": GENERIC}, 423: {"description": "locked; Retry-After"},
                        429: {"description": "too many failures from this address; Retry-After"}})
def post_login(body: LoginRequest, request: Request, response: Response, background: BackgroundTasks):
    """Sign in: sets the session cookie and answers Me (with the CSRF token)."""
    ip = sessions.client_ip(request)
    wait = limits.ip_wait(ip)
    if wait is not None:
        raise _wait(429, f"too many failed sign-ins from this network; try again in {limits.minutes(wait)}", wait)
    email = body.email.strip()
    if not email or len(email) > 254:
        raise HTTPException(status_code=401, detail=GENERIC)
    _locked(email)
    user = accounts.user(email=email, with_hash=True)
    ok = passwords.verify(user["password_hash"], body.password) if user else passwords.dummy_verify(body.password)
    if not ok or user["status"] != "active":
        _fail(email, ip, background)
        return JSONResponse(status_code=401, content={"detail": GENERIC})   # returned: a raise drops the background
    if passwords.needs_rehash(user["password_hash"]):
        accounts.rehash(user["id"], passwords.hash_password(body.password))
    accounts.record_attempt(email, ip, True, user["id"])
    return _me(sessions.start(user, request, response))


@router.post("/auth/logout", status_code=204)
def post_logout(request: Request):
    """End the session (when there is one) and clear the cookie; always 204."""
    s = sessions.session_of(request)
    if s is not None:
        accounts.revoke_session(s["session_id"], {"user_id": s["id"], "email": s["email"],
                                                  "ip": sessions.client_ip(request)}, s["role"])
    out = Response(status_code=204)
    sessions.clear_cookie(out)
    return out


@router.get("/auth/me", response_model=Me, responses={401: {"description": "not signed in"}})
def get_me(request: Request):
    s = sessions.current(request)
    if s is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return _me(s)


@router.post("/auth/password", status_code=204,
             responses={401: {"description": "not signed in, or the current password is wrong"},
                        422: {"description": "the new password fails the policy"}})
def post_password(body: PasswordChange, request: Request):
    """Change the signed-in account's password; every other session of the account ends."""
    s = sessions.current(request)
    if s is None:
        raise HTTPException(status_code=401, detail="not signed in")
    ip = sessions.client_ip(request)
    _locked(s["email"])
    user = accounts.user(s["id"], with_hash=True)
    if not passwords.verify(user["password_hash"], body.current):
        _fail(s["email"], ip)
        raise HTTPException(status_code=401, detail="the current password is wrong")
    _policy(body.new, s["email"])
    if body.new == body.current:
        raise HTTPException(status_code=422, detail="the new password must differ from the current one")
    accounts.set_password(s["id"], passwords.hash_password(body.new), keep_session=s["session_id"],
                          actor={"user_id": s["id"], "email": s["email"], "ip": ip}, actor_role=s["role"])
    return Response(status_code=204)


@router.post("/auth/reset", status_code=204,
             responses={400: {"description": "the token is unknown, used or expired"},
                        422: {"description": "the password fails the policy"}, 429: {"description": "too many"}})
def post_reset(body: PasswordReset, request: Request):
    """Set a new password with the one-time token an administrator issued; every session of the account ends."""
    ip = sessions.client_ip(request)
    wait = ratelimit.check(f"ip:{ip or 'unknown'}", "reset")
    if wait is not None:
        raise _wait(429, f"too many attempts; try again in {limits.minutes(wait)}", wait)
    digest = sessions.token_hash(body.token.strip())
    owner = accounts.reset_owner(digest)
    if owner is None:
        raise HTTPException(status_code=400, detail="this reset token is not valid: it may have been used or expired")
    _policy(body.password, owner["email"])
    if accounts.use_reset(digest, passwords.hash_password(body.password), ip) is None:
        raise HTTPException(status_code=400, detail="this reset token is not valid: it may have been used or expired")
    return Response(status_code=204)


# ---------------------------------------------------------------- /api/admin

def _hidden(v: Viewer) -> tuple[str, ...]:
    """The roles an administrator must not see (the developer's), none for the developer."""
    return () if v.role in HIDDEN_ROLES else HIDDEN_ROLES


def _account(v: Viewer, user_id: int) -> dict:
    u = accounts.user(user_id)
    if u is None or u["role"] in _hidden(v):
        raise HTTPException(status_code=404, detail=f"account {user_id} not found")
    return u


@router.get("/admin/signups", response_model=list[SignupRow])
def get_signups(status: SignupStatus | None = "pending", v: Viewer = Admin):
    """Sign-up requests, newest first; a request the hidden developer reviewed shows no reviewer to anyone else."""
    rows = accounts.signups(status)
    hidden = {u["id"] for role in _hidden(v) for u in accounts.with_role(role)}
    return [{**r, "reviewed_by": None} if r["reviewed_by"] in hidden else r for r in rows]


@router.post("/admin/signups/{signup_id}/approve", response_model=User,
             responses={404: {"description": "no such request"},
                        409: {"description": "not pending any more, or the email has an account"}})
def post_approve(signup_id: int, body: ApproveSignup | None = None, v: Viewer = Admin):
    """Create the account from the request (its role and scope unless corrected here) with the password chosen at
    sign-up."""
    body = body or ApproveSignup()
    req = accounts.signup(signup_id)
    if req is None:
        raise HTTPException(status_code=404, detail=f"sign-up request {signup_id} not found")
    given = body.model_fields_set
    role = body.role or req["role"]
    ministry = body.ministry if "ministry" in given else req["ministry"]
    agency = body.agency if "agency" in given else req["agency"]
    ministry, agency = known_scope(role, ministry, agency)
    try:
        row = accounts.approve_signup(signup_id, v.user_id, role, ministry, agency,
                                      (body.note or "").strip() or None, v.actor, v.role)
    except accounts.Conflict as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if row is None:
        raise HTTPException(status_code=404, detail=f"sign-up request {signup_id} not found")
    return row


@router.post("/admin/signups/{signup_id}/reject", response_model=SignupRow,
             responses={404: {"description": "no such request"}, 409: {"description": "not pending any more"}})
def post_reject(signup_id: int, body: RejectSignup, v: Viewer = Admin):
    try:
        row = accounts.reject_signup(signup_id, v.user_id, body.note.strip(), v.actor, v.role)
    except accounts.Conflict as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if row is None:
        raise HTTPException(status_code=404, detail=f"sign-up request {signup_id} not found")
    return row


@router.get("/admin/users", response_model=UserPage)
def get_users(q: str | None = Query(None, max_length=100), page: int = Query(1, ge=1),
              size: int = Query(50, ge=1, le=100), v: Viewer = Admin):
    """Accounts, newest first; q searches the email and the name."""
    return accounts.users(q.strip() if q else None, page, size, hide_roles=_hidden(v))


@router.post("/admin/users/{user_id}", response_model=User,
             responses={403: {"description": "an administrator's own disabling or demotion"},
                        404: {"description": "no such account"}})
def post_user(user_id: int, body: UserUpdate, v: Viewer = Admin):
    """Change an account's status, role, scope or admin flag (a field left out is left alone). Disabling ends its
    sessions; a role that is not IPMD drops the admin flag."""
    u = _account(v, user_id)
    given = body.model_fields_set
    role = body.role or u["role"]
    is_admin = body.is_admin if body.is_admin is not None else bool(u["is_admin"])
    if role != "ipmd_analyst" and role in OFFICIAL_ROLES:
        if body.is_admin:
            raise HTTPException(status_code=400, detail="only an IPMD analyst can be an administrator")
        is_admin = False
    if user_id == v.user_id and (body.status == "disabled" or role != u["role"] or (u["is_admin"] and not is_admin)):
        raise HTTPException(status_code=403, detail="you cannot disable or demote your own account")
    changes: dict = {"is_admin": is_admin}
    if body.status is not None:
        changes["status"] = body.status
    if "role" in given or "ministry" in given or "agency" in given:
        changes["ministry"], changes["agency"] = known_scope(
            role, body.ministry if "ministry" in given else u["ministry"],
            body.agency if "agency" in given else u["agency"])
        changes["role"] = role
    row = accounts.update_user(user_id, changes, v.actor, v.role)
    if row is None:
        raise HTTPException(status_code=404, detail=f"account {user_id} not found")
    return row


@router.post("/admin/users/{user_id}/reset-password", response_model=ResetToken)
def post_reset_token(user_id: int, request: Request, v: Viewer = Admin):
    """A one-time token (valid RESET_TTL) the administrator hands to the person, who sets a new password with it on
    /reset; shown once, only its sha256 is kept, and an earlier unused token stops working. Every session of the
    account ends now (the one this request comes from stays, when administrators reset their own)."""
    u = _account(v, user_id)
    token, expires = sessions.new_token(), now() + RESET_TTL
    mine = sessions.session_of(request)
    accounts.create_reset(u["id"], sessions.token_hash(token), expires, v.actor, v.role,
                          keep_session=mine["session_id"] if mine and mine["id"] == u["id"] else None)
    return {"token": token, "expires_at": expires.isoformat(timespec="seconds")}


@router.get("/admin/audit", response_model=AuditPage)
def get_audit(since: str | None = Query(None, max_length=40), user: str | None = Query(None, max_length=254),
              action: str | None = Query(None, max_length=60), page: int = Query(1, ge=1),
              size: int = Query(50, ge=1, le=100), v: Viewer = Depends(need("audit"))):
    """The audit log, newest first: who did what, to what, from where (the developer's own rows to developers
    only). since: an ISO date or time; user: an account id, an email or a role; action: exact."""
    try:
        return appdb.audit_rows(since or None, (user or "").strip() or None, (action or "").strip() or None, page,
                                size, hide_roles=_hidden(v))
    except ValueError as e:   # since is not a date
        raise HTTPException(status_code=422, detail="since must be an ISO date or time") from e
