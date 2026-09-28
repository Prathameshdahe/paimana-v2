"""Accounts in PostgreSQL (schema app; the rules are backend/auth/, docs/ACCESS_CONTROL.md): users, sessions, sign-up
requests, login attempts and the one-time password reset tokens. `from backend.db import accounts`.

Rows go out as dicts like the other helpers (timestamps ISO-8601 in UTC, to the second); a user row never carries its
password_hash unless the caller asks for it (with_hash=True, the sign-in only). Emails are citext, so every lookup is
case-insensitive. The writes a person makes (a sign-up, a review, an account change, a reset) write their audit_log
row in the same transaction, with the actor {user_id, email, ip}. Sessions are stored by the sha256 of their cookie
token and reset tokens by the sha256 of the token: neither token is ever in the database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

import sqlalchemy as sa

from .app import _audit, _one, _rows, inet
from .engine import connect, now, read

USER_COLS = ("id, email, display_name, role, ministry, agency, is_admin, status, failed_logins, locked_until, "
             "password_changed_at, created_at, last_login_at")
SIGNUP_COLS = ("id, email, display_name, role, ministry, agency, justification, status, created_at, reviewed_by, "
               "reviewed_at, review_note, host(ip) AS ip")
EDITABLE = ("status", "role", "ministry", "agency", "is_admin", "display_name")


def exact_now() -> datetime:
    """Now to the microsecond: login attempts and password changes are compared with each other (a lock counts only
    the failures after the last success and after the last password change, which can fall in the same second)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- users

def user(user_id: int | None = None, email: str | None = None, with_hash: bool = False) -> dict | None:
    """One account by id or email (case-insensitive), None when there is none."""
    cols = USER_COLS + (", password_hash" if with_hash else "")
    cond, params = ("id = :v", {"v": user_id}) if user_id is not None else ("email = :v", {"v": email})
    with read() as con:
        return _one(con, f"SELECT {cols} FROM app.users WHERE {cond}", params)


def users(q: str | None = None, page: int = 1, size: int = 50, hide_roles: Iterable[str] = ()) -> dict:
    """One page of accounts, newest first; q matches the email or the name (substring, any case); rows of
    hide_roles are left out (the developer's, for an administrator)."""
    conds, params = [], {}
    if q:
        conds.append("(email ILIKE :q OR display_name ILIKE :q)")
        params["q"] = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if hide_roles:
        conds.append("NOT role = ANY(:hide)")
        params["hide"] = list(hide_roles)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with read() as con:
        total = con.execute(sa.text(f"SELECT count(*) FROM app.users{where}"), params).scalar()
        items = _rows(con, f"SELECT {USER_COLS} FROM app.users{where} ORDER BY id DESC LIMIT :limit OFFSET :offset",
                      {**params, "limit": size, "offset": (page - 1) * size})
    return {"total": total, "page": page, "size": size, "items": items}


def admins() -> list[dict]:
    """The active administrators (IPMD analysts with the admin flag); the developer is not one of them."""
    with read() as con:
        return _rows(con, f"SELECT {USER_COLS} FROM app.users WHERE role = 'ipmd_analyst' AND is_admin "
                          "AND status = 'active' ORDER BY id")


def with_role(role: str) -> list[dict]:
    """Every account of one role, oldest first."""
    with read() as con:
        return _rows(con, f"SELECT {USER_COLS} FROM app.users WHERE role = :role ORDER BY id", {"role": role})


def create_user(email: str, password_hash: str, display_name: str | None, role: str, ministry: str | None = None,
                agency: str | None = None, is_admin: bool = False, actor: Mapping | None = None,
                actor_role: str | None = None, action: str = "user.create") -> dict:
    """A new active account (the password as set now); its audit row when an actor is given."""
    with connect() as con:
        return _create(con, email, password_hash, display_name, role, ministry, agency, is_admin, actor, actor_role,
                       action)


def _create(con, email, password_hash, display_name, role, ministry, agency, is_admin, actor, actor_role,
            action) -> dict:
    row = _one(con, f"""INSERT INTO app.users (email, password_hash, display_name, role, ministry, agency, is_admin,
            password_changed_at) VALUES (:email, :hash, :name, :role, :ministry, :agency, :admin, :at)
        RETURNING {USER_COLS}""", {"email": email, "hash": password_hash, "name": display_name, "role": role,
                                   "ministry": ministry, "agency": agency, "admin": is_admin, "at": exact_now()})
    if actor is not None or actor_role is not None:
        _audit(con, actor_role, action, str(row["id"]), f"{row['email']} as {role}", actor)
    return row


def update_user(user_id: int, changes: Mapping, actor: Mapping | None = None, actor_role: str | None = None,
                action: str = "user.update") -> dict | None:
    """Apply changes (keys of EDITABLE) to one account; None when there is no such account. A change of status to
    disabled revokes the account's sessions in the same transaction."""
    sets = {k: v for k, v in changes.items() if k in EDITABLE}
    with connect() as con:
        if sets:
            row = _one(con, f"UPDATE app.users SET {', '.join(f'{k} = :{k}' for k in sets)} WHERE id = :id "
                            f"RETURNING {USER_COLS}", {**sets, "id": user_id})
        else:
            row = _one(con, f"SELECT {USER_COLS} FROM app.users WHERE id = :id", {"id": user_id})
        if row is None:
            return None
        if sets.get("status") == "disabled":
            _revoke_all(con, user_id)
        if actor is not None or actor_role is not None:
            detail = ", ".join(f"{k}={v}" for k, v in sets.items()) or "no change"
            _audit(con, actor_role, action, str(user_id), f"{row['email']}: {detail}", actor)
        return row


def set_password(user_id: int, password_hash: str, keep_session: str | None = None, actor: Mapping | None = None,
                 actor_role: str | None = None, action: str = "auth.password") -> None:
    """A new password: the lock and the failure count cleared, every session but keep_session (a session id)
    revoked, and the audit row."""
    with connect() as con:
        con.execute(sa.text("""UPDATE app.users SET password_hash = :hash, password_changed_at = :at,
            failed_logins = 0, locked_until = NULL WHERE id = :id"""),
                    {"hash": password_hash, "at": exact_now(), "id": user_id})
        _revoke_all(con, user_id, keep=keep_session)
        if actor is not None or actor_role is not None:
            _audit(con, actor_role, action, str(user_id), None, actor)


def rehash(user_id: int, password_hash: str) -> None:
    """The same password under newer argon2 parameters (at a sign-in); nothing else changes."""
    with connect() as con:
        con.execute(sa.text("UPDATE app.users SET password_hash = :hash WHERE id = :id"),
                    {"hash": password_hash, "id": user_id})


# ---------------------------------------------------------------- login attempts and the lock

def record_attempt(email: str, ip: str | None, ok: bool, user_id: int | None = None,
                   locked_until: datetime | None = None) -> None:
    """One login attempt; for an account also its counters: a success clears the failures and the lock, a failure
    counts one and sets locked_until when the caller computed a lock."""
    with connect() as con:
        con.execute(sa.text("INSERT INTO app.login_attempts (email, ip, \"at\", ok) VALUES "
                            "(:email, CAST(:ip AS inet), :at, :ok)"),
                    {"email": email, "ip": inet(ip), "at": exact_now(), "ok": ok})
        if user_id is None:
            return
        if ok:
            con.execute(sa.text("UPDATE app.users SET failed_logins = 0, locked_until = NULL, last_login_at = :at "
                                "WHERE id = :id"), {"at": now(), "id": user_id})
        else:
            con.execute(sa.text("UPDATE app.users SET failed_logins = failed_logins + 1, "
                                "locked_until = COALESCE(:until, locked_until) WHERE id = :id"),
                        {"until": locked_until, "id": user_id})


def failures(email: str, since: datetime) -> list[datetime]:
    """The failed attempts on email after since, after its last successful one and after the account's last password
    change (a reset lifts a lock), oldest first."""
    with read() as con:
        return list(con.execute(sa.text("""SELECT "at" FROM app.login_attempts WHERE email = :email AND NOT ok
            AND "at" > :since
            AND "at" > COALESCE((SELECT max("at") FROM app.login_attempts WHERE email = :email AND ok), '-infinity')
            AND "at" > COALESCE((SELECT password_changed_at FROM app.users WHERE email = :email), '-infinity')
            ORDER BY "at" """), {"email": email, "since": since}).scalars())


def ip_failures(ip: str | None, since: datetime) -> list[datetime]:
    """The failed attempts from ip after since, oldest first (none for a peer that is not an address)."""
    if inet(ip) is None:
        return []
    with read() as con:
        return list(con.execute(sa.text('SELECT "at" FROM app.login_attempts WHERE ip = CAST(:ip AS inet) '
                                        'AND NOT ok AND "at" > :since ORDER BY "at"'),
                                {"ip": inet(ip), "since": since}).scalars())


# ---------------------------------------------------------------- sessions

def create_session(session_id: str, user_id: int, csrf_token: str, expires_at: datetime, ip: str | None,
                   user_agent: str | None, actor: Mapping | None = None, actor_role: str | None = None) -> None:
    """A new session (and the sign-in's audit row)."""
    at = now()
    with connect() as con:
        con.execute(sa.text("""INSERT INTO app.sessions (id, user_id, csrf_token, created_at, expires_at, last_seen_at,
                ip, user_agent) VALUES (:id, :uid, :csrf, :at, :exp, :at, CAST(:ip AS inet), :ua)"""),
                    {"id": session_id, "uid": user_id, "csrf": csrf_token, "at": at, "exp": expires_at,
                     "ip": inet(ip), "ua": (user_agent or "")[:300] or None})
        if actor is not None:
            _audit(con, actor_role, "auth.login", str(user_id), None, actor)


def session(session_id: str, idle: timedelta) -> dict | None:
    """The live session with this id and its account: not revoked, before its absolute expiry, seen within idle,
    the account active; None otherwise. Keys: the session's (session_id, csrf_token, created_at, expires_at,
    last_seen_at) and the account's (USER_COLS)."""
    at = now()
    with read() as con:
        return _one(con, f"""SELECT s.id AS session_id, s.csrf_token, s.created_at AS session_created_at,
                s.expires_at, s.last_seen_at, {', '.join('u.' + c.strip() for c in USER_COLS.split(','))}
            FROM app.sessions s JOIN app.users u ON u.id = s.user_id
            WHERE s.id = :id AND s.revoked_at IS NULL AND s.expires_at > :at AND s.last_seen_at > :idle_since
              AND u.status = 'active'""", {"id": session_id, "at": at, "idle_since": at - idle})


def touch_session(session_id: str, every: timedelta = timedelta(minutes=1)) -> None:
    """Mark the session seen now (at most once per `every`: one write a minute per active session)."""
    at = now()
    with connect() as con:
        con.execute(sa.text("UPDATE app.sessions SET last_seen_at = :at WHERE id = :id AND last_seen_at < :before"),
                    {"at": at, "id": session_id, "before": at - every})


def revoke_session(session_id: str, actor: Mapping | None = None, actor_role: str | None = None) -> bool:
    """End one session (sign-out); False when it was already over."""
    with connect() as con:
        n = con.execute(sa.text("UPDATE app.sessions SET revoked_at = :at WHERE id = :id AND revoked_at IS NULL "
                                "RETURNING user_id"), {"at": now(), "id": session_id}).scalars().all()
        if n and actor is not None:
            _audit(con, actor_role, "auth.logout", str(n[0]), None, actor)
        return bool(n)


def _revoke_all(con, user_id: int, keep: str | None = None) -> int:
    return con.execute(sa.text("UPDATE app.sessions SET revoked_at = :at WHERE user_id = :uid AND revoked_at IS NULL "
                               "AND id IS DISTINCT FROM :keep"),
                       {"at": now(), "uid": user_id, "keep": keep}).rowcount


def revoke_sessions(user_id: int, keep: str | None = None) -> int:
    """End every session of an account except keep; returns how many ended."""
    with connect() as con:
        return _revoke_all(con, user_id, keep)


# ---------------------------------------------------------------- sign-up requests

def create_signup(row: Mapping, ip: str | None) -> int:
    """A pending request (email, display_name, role, ministry, agency, justification, password_hash); its audit row
    names the requested email and the address it came from."""
    with connect() as con:
        new_id = con.execute(sa.text("""INSERT INTO app.signup_requests (email, display_name, role, ministry, agency,
                justification, password_hash, created_at, ip)
            VALUES (:email, :display_name, :role, :ministry, :agency, :justification, :password_hash, :at,
                    CAST(:ip AS inet)) RETURNING id"""), {**row, "at": now(), "ip": inet(ip)}).scalar()
        _audit(con, "public", "signup.request", str(new_id), f"{row['email']} as {row['role']}",
               {"email": row["email"], "ip": ip})
        return new_id


def signups(status: str | None = None, limit: int = 500) -> list[dict]:
    """Sign-up requests (of one status), newest first."""
    cond = "WHERE status = :status" if status else ""
    with read() as con:
        return _rows(con, f"SELECT {SIGNUP_COLS} FROM app.signup_requests {cond} ORDER BY id DESC LIMIT :limit",
                     {"status": status, "limit": limit})


def signup(signup_id: int) -> dict | None:
    with read() as con:
        return _one(con, f"SELECT {SIGNUP_COLS} FROM app.signup_requests WHERE id = :id", {"id": signup_id})


def pending_signup(email: str) -> dict | None:
    with read() as con:
        return _one(con, f"SELECT {SIGNUP_COLS} FROM app.signup_requests WHERE email = :email AND status = 'pending'",
                    {"email": email})


def signups_from(ip: str | None, since: datetime) -> list[datetime]:
    """When the requests from ip after since were made, oldest first (none for a peer that is not an address)."""
    if inet(ip) is None:
        return []
    with read() as con:
        return list(con.execute(sa.text("SELECT created_at FROM app.signup_requests WHERE ip = CAST(:ip AS inet) "
                                        "AND created_at > :since ORDER BY created_at"),
                                {"ip": inet(ip), "since": since}).scalars())


class Conflict(Exception):
    """The request is no longer pending, or its email already has an account."""


def approve_signup(signup_id: int, reviewer_id: int, role: str, ministry: str | None, agency: str | None,
                   note: str | None, actor: Mapping, actor_role: str) -> dict | None:
    """Create the account from a pending request (its own password; role and scope as given) and mark the request
    approved, in one transaction; None when there is no such request, Conflict when it is not pending or the email
    has an account."""
    with connect() as con:
        req = _one(con, "SELECT * FROM app.signup_requests WHERE id = :id FOR UPDATE", {"id": signup_id})
        if req is None:
            return None
        if req["status"] != "pending":
            raise Conflict(f"this request was already {req['status']}")
        if _one(con, "SELECT id FROM app.users WHERE email = :email", {"email": req["email"]}):
            raise Conflict("an account with this email already exists")
        row = _create(con, req["email"], req["password_hash"], req["display_name"], role, ministry, agency, False,
                      actor, actor_role, "signup.approve")
        con.execute(sa.text("""UPDATE app.signup_requests SET status = 'approved', reviewed_by = :by, reviewed_at = :at,
            review_note = :note, role = :role, ministry = :ministry, agency = :agency WHERE id = :id"""),
                    {"by": reviewer_id, "at": now(), "note": note, "role": role, "ministry": ministry,
                     "agency": agency, "id": signup_id})
        return row


def reject_signup(signup_id: int, reviewer_id: int, note: str, actor: Mapping, actor_role: str) -> dict | None:
    """Mark a pending request rejected; None when there is none, Conflict when it is not pending."""
    with connect() as con:
        req = _one(con, "SELECT id, email, status FROM app.signup_requests WHERE id = :id FOR UPDATE",
                   {"id": signup_id})
        if req is None:
            return None
        if req["status"] != "pending":
            raise Conflict(f"this request was already {req['status']}")
        con.execute(sa.text("""UPDATE app.signup_requests SET status = 'rejected', reviewed_by = :by, reviewed_at = :at,
            review_note = :note WHERE id = :id"""), {"by": reviewer_id, "at": now(), "note": note, "id": signup_id})
        _audit(con, actor_role, "signup.reject", str(signup_id), req["email"], actor)
        return _one(con, f"SELECT {SIGNUP_COLS} FROM app.signup_requests WHERE id = :id", {"id": signup_id})


# ---------------------------------------------------------------- one-time password resets

def create_reset(user_id: int, token_hash: str, expires_at: datetime, actor: Mapping, actor_role: str,
                 keep_session: str | None = None) -> None:
    """A reset token for the account (earlier unused ones stop working), every session of the account but
    keep_session ended (an account reset to lock someone out is signed out at once), and the audit row."""
    with connect() as con:
        con.execute(sa.text("UPDATE app.password_resets SET used_at = :at WHERE user_id = :uid AND used_at IS NULL"),
                    {"at": now(), "uid": user_id})
        _revoke_all(con, user_id, keep=keep_session)
        con.execute(sa.text("""INSERT INTO app.password_resets (user_id, token_hash, created_by, created_at, expires_at)
            VALUES (:uid, :hash, :by, :at, :exp)"""),
                    {"uid": user_id, "hash": token_hash, "by": actor.get("user_id"), "at": now(), "exp": expires_at})
        _audit(con, actor_role, "user.reset_password", str(user_id), None, actor)


def reset_owner(token_hash: str) -> dict | None:
    """The active account a live (unused, unexpired) reset token belongs to, else None."""
    with read() as con:
        return _one(con, f"""SELECT {', '.join('u.' + c.strip() for c in USER_COLS.split(','))}
            FROM app.password_resets r JOIN app.users u ON u.id = r.user_id
            WHERE r.token_hash = :hash AND r.used_at IS NULL AND r.expires_at > :at AND u.status = 'active'""",
                    {"hash": token_hash, "at": now()})


def use_reset(token_hash: str, password_hash: str, ip: str | None) -> dict | None:
    """Spend a live reset token on a new password, in one transaction: the token marked used, the password set, the
    lock cleared, every session revoked, the audit row. None (nothing changed) when the token is unknown, used,
    expired, or its account is disabled."""
    with connect() as con:
        uid = con.execute(sa.text("""UPDATE app.password_resets r SET used_at = :at FROM app.users u
            WHERE r.token_hash = :hash AND r.used_at IS NULL AND r.expires_at > :at AND u.id = r.user_id
              AND u.status = 'active' RETURNING r.user_id"""), {"at": now(), "hash": token_hash}).scalar()
        if uid is None:
            return None
        row = _one(con, f"""UPDATE app.users SET password_hash = :hash, password_changed_at = :at, failed_logins = 0,
            locked_until = NULL WHERE id = :id RETURNING {USER_COLS}""",
                   {"hash": password_hash, "at": exact_now(), "id": uid})
        _revoke_all(con, uid)
        _audit(con, row["role"], "auth.reset", str(uid), None, {"user_id": uid, "email": row["email"], "ip": ip})
        return row


__all__ = ["Conflict", "user", "users", "admins", "with_role", "create_user", "update_user", "set_password", "rehash",
           "record_attempt", "failures", "ip_failures", "create_session", "session", "touch_session",
           "revoke_session", "revoke_sessions", "create_signup", "signups", "signup", "pending_signup", "signups_from",
           "approve_signup", "reject_signup", "create_reset", "reset_owner", "use_reset"]
