"""Sign-in, sessions, CSRF, lockout, sign-up, administration and the audit trail (backend/auth, SPEC9 section 2),
against the test database. Accounts other than the ones a test creates on purpose come from tests/viewers.py."""
import hashlib
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend import settings as cfg  # noqa: E402
from backend.auth import limits, passwords, sessions  # noqa: E402
from backend.auth.routes import GENERIC  # noqa: E402
from backend.db import accounts  # noqa: E402
from backend.db.engine import now  # noqa: E402
from backend.main import app  # noqa: E402
from viewers import PASSWORD, as_role, email_for  # noqa: E402 - tests/viewers.py

NEW_PASSWORD = "a brand new passphrase 77"
ADDRESS = "203.0.113.30"


@pytest.fixture()
def client(fresh_db):
    with TestClient(app, client=(ADDRESS, 40000)) as c:
        yield c


@pytest.fixture(scope="module")
def coal():
    return next(m["name"] for m in serving.scopes()["ministries"] if m["name"] == "Ministry of Coal")


def login(c, email, password=PASSWORD):
    c.cookies.clear()
    return c.post("/api/auth/login", json={"email": email, "password": password})


def sql(q, **params):
    with db.connect() as con:
        return con.execute(sa.text(q), params)


def official(role="ministry", **kw):
    """A test account (tests/viewers.py) and its email."""
    from viewers import account
    u = account(role, **kw)
    return u, u["email"]


# ------------------------------------------------------------------ the session round trip

def test_login_me_write_logout_flow(client, coal):
    u, email = official(ministry=coal)
    r = login(client, email)
    assert r.status_code == 200
    me = r.json()
    assert me == {"userId": u["id"], "email": email, "displayName": u["display_name"], "role": "ministry_official",
                  "ministry": coal, "agency": None, "isAdmin": False, "csrfToken": me["csrfToken"],
                  "sessionExpiresAt": me["sessionExpiresAt"]}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{sessions.COOKIE}=") and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Path=/" in cookie and "Secure" not in cookie   # SECURE_COOKIES=0 in dev
    token = client.cookies.get(sessions.COOKIE)
    # only the token's sha256 is stored, with its own CSRF token
    row = sql("SELECT id, csrf_token FROM app.sessions").mappings().one()
    assert row["id"] == hashlib.sha256(token.encode()).hexdigest() != token and row["csrf_token"] == me["csrfToken"]
    assert client.get("/api/auth/me").json()["userId"] == u["id"]
    key = client.get("/api/projects", params={"size": 1}).json()["items"][0]["key"]
    assert client.post("/api/watchlist", json={"projectKey": key}).status_code == 403        # no CSRF token
    assert client.post("/api/watchlist", json={"projectKey": key},
                       headers={sessions.CSRF_HEADER: "wrong"}).status_code == 403
    ok = client.post("/api/watchlist", json={"projectKey": key}, headers={sessions.CSRF_HEADER: me["csrfToken"]})
    assert ok.status_code == 200 and ok.json()["total"] == 1
    assert client.post("/api/auth/logout", headers={sessions.CSRF_HEADER: me["csrfToken"]}).status_code == 204
    assert sessions.COOKIE not in client.cookies
    assert client.get("/api/auth/me").status_code == 401
    # the old cookie is dead even when replayed
    client.cookies.set(sessions.COOKIE, token)
    r = client.get("/api/portfolio")
    assert r.status_code == 401 and f"{sessions.COOKIE}=;" in r.headers["set-cookie"]
    client.cookies.clear()
    assert client.get("/api/portfolio").status_code == 200   # no cookie: the public
    rows = [r for r in db.audit_rows(size=50)["items"] if r["action"] in ("auth.login", "auth.logout")]
    assert {r["action"] for r in rows} == {"auth.login", "auth.logout"}
    assert all(r["user_id"] == u["id"] and r["email"] == email and r["ip"] == ADDRESS for r in rows)


def test_public_needs_no_token_and_a_forged_cookie_is_401(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/logout").status_code == 204          # nothing to end, still 204
    client.cookies.set(sessions.COOKIE, "made-up")
    r = client.get("/api/alerts")
    assert r.status_code == 401 and f"{sessions.COOKIE}=;" in r.headers["set-cookie"]
    client.cookies.set(sessions.COOKIE, "x" * 500)
    assert client.get("/api/auth/me").status_code == 401


def test_origin_is_checked_on_every_write(client, coal):
    _, email = official(ministry=coal)
    evil = {"Origin": "https://evil.example"}
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}, headers=evil)
    assert r.status_code == 403
    ok = client.post("/api/auth/login", json={"email": email, "password": PASSWORD},
                     headers={"Origin": "http://localhost:5173"})
    assert ok.status_code == 200
    csrf = {sessions.CSRF_HEADER: ok.json()["csrfToken"]}
    assert client.post("/api/auth/logout", headers={**csrf, **evil}).status_code == 403
    assert client.get("/api/auth/me", headers=evil).status_code == 200    # a read is not a write


def test_idle_and_absolute_expiry(client, coal):
    _, email = official(ministry=coal)
    assert login(client, email).status_code == 200
    sql("UPDATE app.sessions SET last_seen_at = now() - interval '13 hours'")
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and f"{sessions.COOKIE}=;" in r.headers["set-cookie"]
    assert login(client, email).status_code == 200
    sql("UPDATE app.sessions SET expires_at = now() - interval '1 second' WHERE revoked_at IS NULL")
    assert client.get("/api/auth/me").status_code == 401
    me = login(client, email).json()
    assert me["sessionExpiresAt"] and me["sessionExpiresAt"] > now().isoformat()


def test_a_new_sign_in_ends_the_old_session(client, coal):
    """A sign-in that arrives with a live session cookie (and its token) ends that session."""
    h = as_role(client, "ipmd")
    old = client.cookies.get(sessions.COOKIE)
    _, email = official(ministry=coal)
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}, headers=h)
    assert r.status_code == 200 and client.cookies.get(sessions.COOKIE) != old
    assert accounts.session(sessions.token_hash(old), sessions.idle()) is None
    assert client.get("/api/auth/me").json()["role"] == "ministry_official"


# ------------------------------------------------------------------ failed sign-ins

def test_generic_error_for_unknown_wrong_and_disabled(client, coal):
    u, email = official(ministry=coal)
    unknown = login(client, "nobody@tests.paimana.local")
    wrong = login(client, email, "not the password at all")
    accounts.update_user(u["id"], {"status": "disabled"})
    disabled = login(client, email)
    for r in (unknown, wrong, disabled):
        assert r.status_code == 401 and r.json() == {"detail": GENERIC}
    assert GENERIC == "email or password is wrong, or the account is locked or disabled"


def test_lockout_after_five_failures_for_known_and_unknown_emails(client, coal):
    u, email = official(ministry=coal)
    for who in (email, "ghost@tests.paimana.local"):
        for _ in range(limits.LOCK_FAILURES):
            assert login(client, who, "wrong password here").status_code == 401
        r = login(client, who, PASSWORD)                       # even the right password waits
        assert r.status_code == 423 and 0 < int(r.headers["Retry-After"]) <= 15 * 60
        assert "locked" in r.json()["detail"]
    assert accounts.user(u["id"])["locked_until"] is not None and accounts.user(u["id"])["failed_logins"] == 5
    # a refused attempt is not recorded, so the lock ends 15 minutes after the fifth failure
    sql("UPDATE app.login_attempts SET \"at\" = \"at\" - interval '16 minutes'")
    assert login(client, email).status_code == 200
    assert accounts.user(u["id"])["failed_logins"] == 0 and accounts.user(u["id"])["locked_until"] is None


def test_slow_failures_do_not_lock_and_a_success_resets_the_count(client, coal):
    _, email = official(ministry=coal)
    for _ in range(4):
        login(client, email, "wrong password here")
    assert login(client, email).status_code == 200           # the success clears the streak
    for _ in range(4):
        login(client, email, "wrong password here")
    assert login(client, email).status_code == 200
    at = now()
    spread = [at - limits.LOCK_WINDOW * 2 + limits.LOCK_WINDOW / 4 * i for i in range(5)]
    assert limits.locked_until(spread, at) is None           # five failures over 30 minutes: no lock


def test_a_failed_sign_in_runs_the_same_queries_for_known_and_unknown_emails(client, coal):
    """Review finding (unit B, round 1): up to its answer, a failed sign-in on an unknown email runs the very same
    statements as one on a real account (the lock is computed for both); the account's counters are written after the
    answer. So the time a failure takes does not tell which emails have accounts."""
    from backend.db.engine import engine
    _, email = official(ministry=coal)
    log, answered = [], []

    def seen(conn, cursor, statement, params, context, executemany):
        log.append((bool(answered), " ".join(statement.split())))

    async def marked(scope, receive, send):     # the app, noting when the answer has gone out
        async def mark(message):
            if message["type"] == "http.response.body" and not message.get("more_body"):
                answered.append(1)
            await send(message)
        await app(scope, receive, mark)

    def failed(who):
        log.clear()
        answered.clear()
        r = TestClient(marked, client=(ADDRESS, 1)).post("/api/auth/login",
                                                         json={"email": who, "password": "wrong password here"})
        assert r.status_code == 401
        return list(log)
    sa.event.listen(engine(), "before_cursor_execute", seen)
    try:
        known, unknown = failed(email), failed("nobody.at.all@tests.paimana.local")
    finally:
        sa.event.remove(engine(), "before_cursor_execute", seen)
    before = lambda rows: [q for after, q in rows if not after]  # noqa: E731
    assert before(known) == before(unknown), (before(known), before(unknown))
    assert any("INSERT INTO app.login_attempts" in q for q in before(known))
    assert not any("UPDATE app.users" in q for q in before(known))
    assert any(after and "UPDATE app.users" in q for after, q in known)
    assert accounts.user(email=email)["failed_logins"] == 1                 # the counter is still kept


def test_per_address_limit(fresh_db, coal):
    _, email = official(ministry=coal)
    with TestClient(app, client=("198.51.100.20", 1)) as c, TestClient(app, client=("198.51.100.21", 1)) as other:
        for i in range(limits.IP_FAILURES):
            assert login(c, f"spray{i}@tests.paimana.local", "wrong password here").status_code == 401
        r = login(c, email)
        assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
        assert login(other, email).status_code == 200           # another address is not held back


def test_admin_reset_lifts_a_lock(client, coal):
    u, email = official(ministry=coal)
    for _ in range(limits.LOCK_FAILURES):
        login(client, email, "wrong password here")
    assert login(client, email).status_code == 423
    h = as_role(client, "ipmd", admin=True)
    token = client.post(f"/api/admin/users/{u['id']}/reset-password", headers=h).json()["token"]
    client.cookies.clear()
    assert client.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 204
    assert login(client, email, NEW_PASSWORD).status_code == 200


# ------------------------------------------------------------------ passwords

def test_password_policy():
    assert passwords.problems("short") == ["at least 12 characters"]
    assert passwords.problems("Password1234") == ["not a common password"]
    assert passwords.problems("Password@123") == ["not a common password"]
    assert passwords.problems("pass-word-1234") == ["not a common password"]   # punctuation does not hide it
    assert passwords.problems("rajesh.kumar is here", "Rajesh.Kumar@gov.in") == [
        "not containing the name part of the email"]
    assert passwords.problems(PASSWORD, "ipmd-1@tests.paimana.local") == []
    h = passwords.hash_password(PASSWORD)
    assert h.startswith("$argon2id$") and passwords.verify(h, PASSWORD) and not passwords.verify(h, "x")
    assert not passwords.verify("not a hash", PASSWORD) and not passwords.verify(None, PASSWORD)
    assert passwords.dummy_verify(PASSWORD) is False


def test_password_policy_refuses_blank_and_repeated_passwords(client, coal):
    """Review finding (unit B, round 1): the length counts no whitespace at either end, and a password needs at least
    MIN_DISTINCT different characters, so twelve spaces, spaces and tabs, or one repeated letter do not pass."""
    for pw in (" " * 12, " 	" * 8, "a" * 12, "abab" * 4, "   eleven chars 1   "[:3] + "x" * 11):
        assert passwords.problems(pw), repr(pw)
    assert passwords.problems(" " * 12) == ["at least 12 characters", f"at least {passwords.MIN_DISTINCT} different "
                                                                        "characters"]
    assert passwords.problems("  " + "abcdefghij" + "  ") == ["at least 12 characters"]   # ten, not fourteen
    assert passwords.problems("aaaa bbbb cccc dd") == [] and passwords.problems(PASSWORD) == []
    r = client.post("/api/auth/signup", json=signup_body(coal, password=" " * 12))
    assert r.status_code == 422 and "different characters" in r.json()["detail"]


def test_change_password(client, coal):
    u, email = official(ministry=coal)
    with TestClient(app) as elsewhere:
        login(elsewhere, email)
        h = {sessions.CSRF_HEADER: login(client, email).json()["csrfToken"]}
        body = {"current": "not my password", "new": NEW_PASSWORD}
        assert client.post("/api/auth/password", json=body, headers=h).status_code == 401
        assert client.post("/api/auth/password", json={"current": PASSWORD, "new": "short"},
                           headers=h).status_code == 422
        assert client.post("/api/auth/password", json={"current": PASSWORD, "new": NEW_PASSWORD},
                           headers=h).status_code == 204
        assert client.get("/api/auth/me").status_code == 200        # this session stays
        assert elsewhere.get("/api/auth/me").status_code == 401     # every other one ends
    assert login(client, email).status_code == 401 and login(client, email, NEW_PASSWORD).status_code == 200
    assert accounts.user(u["id"])["password_changed_at"]
    assert client.post("/api/auth/password", json={"current": "x", "new": "y" * 20}).status_code == 403  # no CSRF


# ------------------------------------------------------------------ sign-up and approval

def signup_body(coal, **kw):
    return {"email": "new.officer@coal.gov.in", "displayName": "New Officer", "role": "ministry_official",
            "ministry": coal, "justification": "Monitoring coal projects", "password": NEW_PASSWORD, **kw}


def test_signup_approve_then_sign_in(client, coal):
    r = client.post("/api/auth/signup", json=signup_body(coal, ministry=coal.upper()))
    assert r.status_code == 202 and set(r.json()) == {"id"}
    sid = r.json()["id"]
    assert client.post("/api/auth/signup", json=signup_body(coal)).status_code == 409   # one pending per email
    assert login(client, "new.officer@coal.gov.in", NEW_PASSWORD).status_code == 401    # not approved yet
    h = as_role(client, "ipmd", admin=True)
    rows = client.get("/api/admin/signups", params={"status": "pending"}).json()
    assert [(x["id"], x["email"], x["ministry"], x["ip"]) for x in rows] == [
        (sid, "new.officer@coal.gov.in", coal, ADDRESS)]            # the scope in /api/scopes' spelling
    assert "passwordHash" not in rows[0] and "password_hash" not in str(rows[0])
    user = client.post(f"/api/admin/signups/{sid}/approve", json={"note": "checked by phone"}, headers=h).json()
    assert user["role"] == "ministry_official" and user["ministry"] == coal and not user["isAdmin"]
    assert client.post(f"/api/admin/signups/{sid}/approve", json={}, headers=h).status_code == 409
    assert client.post(f"/api/admin/signups/{sid}/reject", json={"note": "x"}, headers=h).status_code == 409
    done = client.get("/api/admin/signups", params={"status": "approved"}).json()[0]
    assert done["reviewNote"] == "checked by phone" and done["reviewedBy"] and done["reviewedAt"]
    me = login(client, "new.officer@coal.gov.in", NEW_PASSWORD)
    assert me.status_code == 200 and me.json()["ministry"] == coal
    assert client.post("/api/auth/signup", json=signup_body(coal)).status_code == 403   # signed in: no token
    client.cookies.clear()
    assert client.post("/api/auth/signup", json=signup_body(coal)).status_code == 409   # it has an account now


def test_approve_can_correct_the_role_and_scope_and_reject_needs_a_note(client, coal):
    agency = serving.scopes()["agencies"][0]["name"]
    a = client.post("/api/auth/signup", json=signup_body(coal)).json()["id"]
    b = client.post("/api/auth/signup", json=signup_body(coal, email="other@coal.gov.in")).json()["id"]
    h = as_role(client, "ipmd", admin=True)
    assert client.post(f"/api/admin/signups/{a}/approve", json={"role": "agency_official"},
                       headers=h).status_code == 400                     # an agency official needs an agency
    user = client.post(f"/api/admin/signups/{a}/approve", json={"role": "agency_official", "agency": agency},
                       headers=h).json()
    assert (user["role"], user["ministry"], user["agency"]) == ("agency_official", None, agency)
    assert client.post(f"/api/admin/signups/{b}/reject", json={}, headers=h).status_code == 422
    assert client.post(f"/api/admin/signups/{b}/reject", json={"note": ""}, headers=h).status_code == 422
    row = client.post(f"/api/admin/signups/{b}/reject", json={"note": "not an official email"}, headers=h).json()
    assert row["status"] == "rejected" and row["reviewNote"] == "not an official email"
    assert client.post("/api/admin/signups/999/approve", json={}, headers=h).status_code == 404
    assert client.post(f"/api/admin/signups/{a}/approve", json={"role": "developer"}, headers=h).status_code == 422


def test_a_review_by_the_developer_names_no_reviewer_to_administrators(client, coal):
    """Review finding (unit B, round 1): reviewedBy of a request the hidden developer reviewed is empty for anyone
    else (an id that no account list shows would give the account away); the developer sees its own id."""
    a = client.post("/api/auth/signup", json=signup_body(coal)).json()["id"]
    b = client.post("/api/auth/signup", json=signup_body(coal, email="other@coal.gov.in")).json()["id"]
    h = as_role(client, "developer")
    dev_id = client.get("/api/auth/me").json()["userId"]
    assert client.post(f"/api/admin/signups/{a}/approve", json={}, headers=h).status_code == 200
    assert client.post(f"/api/admin/signups/{b}/reject", json={"note": "no"}, headers=h).json()["reviewedBy"] == dev_id
    assert [r["reviewedBy"] for r in client.get("/api/admin/signups", params={"status": "approved"}).json()] == [dev_id]
    as_role(client, "ipmd", admin=True)
    for status in ("approved", "rejected"):
        rows = client.get("/api/admin/signups", params={"status": status}).json()
        assert [r["reviewedBy"] for r in rows] == [None] and rows[0]["reviewedAt"], status


@pytest.mark.parametrize("change, status", [
    ({"ministry": "Ministry of Nothing"}, 400), ({"role": "developer"}, 422), ({"password": "password1234"}, 422),
    ({"password": "new.officer rules ok"}, 422), ({"justification": "x" * 501}, 422), ({"email": "not-an-email"}, 422),
    ({"isAdmin": True}, 422), ({"displayName": ""}, 422)])
def test_signup_validation(client, coal, change, status):
    assert client.post("/api/auth/signup", json=signup_body(coal, **change)).status_code == status


def test_signup_limits_and_domains(client, coal, monkeypatch):
    for i in range(limits.SIGNUPS_PER_HOUR):
        assert client.post("/api/auth/signup", json=signup_body(coal, email=f"o{i}@coal.gov.in")).status_code == 202
    r = client.post("/api/auth/signup", json=signup_body(coal, email="o9@coal.gov.in"))
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    import dataclasses
    monkeypatch.setattr(cfg, "settings", dataclasses.replace(cfg.settings, allowed_email_domains=("gov.in",)))
    with TestClient(app, client=("198.51.100.40", 1)) as c:
        assert c.post("/api/auth/signup", json=signup_body(coal, email="a@gmail.com")).status_code == 422
        assert c.post("/api/auth/signup", json=signup_body(coal, email="a@gov.in")).status_code == 202


# ------------------------------------------------------------------ administration

def test_admin_needs_the_flag_and_audit_needs_the_developer(client, coal):
    for sign_in in (lambda: as_role(client, "public"), lambda: as_role(client, "ministry", ministry=coal),
                    lambda: as_role(client, "ipmd")):
        h = sign_in()
        assert client.get("/api/admin/users").status_code == 403
        assert client.get("/api/admin/signups").status_code == 403
        assert client.post("/api/admin/users/1", json={"status": "disabled"}, headers=h).status_code == 403
    as_role(client, "ipmd", admin=True)
    assert client.get("/api/admin/users").status_code == 200
    assert client.get("/api/admin/audit").status_code == 403
    as_role(client, "developer")
    assert client.get("/api/admin/audit").status_code == 200


def test_users_list_hides_the_developer_from_administrators(client, coal):
    dev = as_role(client, "developer")
    me = client.get("/api/auth/me", headers=dev).json()
    assert me["role"] == "developer" and me["isAdmin"] is True and me["ministry"] is None
    official(ministry=coal)
    h = as_role(client, "ipmd", admin=True)
    page = client.get("/api/admin/users").json()
    assert "developer" not in {u["role"] for u in page["items"]} and page["total"] == len(page["items"]) == 2
    assert client.get("/api/admin/users", params={"q": "ministry-"}).json()["total"] == 1
    assert client.get("/api/admin/users", params={"size": 101}).status_code == 422
    dev_id = me["userId"]
    assert client.post(f"/api/admin/users/{dev_id}", json={"status": "disabled"}, headers=h).status_code == 404
    assert client.post(f"/api/admin/users/{dev_id}/reset-password", headers=h).status_code == 404
    as_role(client, "developer")
    assert "developer" in {u["role"] for u in client.get("/api/admin/users").json()["items"]}


def test_update_account_rules(client, coal):
    u, email = official(ministry=coal)
    admin_h = as_role(client, "ipmd", admin=True)
    admin_id = client.get("/api/auth/me").json()["userId"]
    post = lambda uid, body: client.post(f"/api/admin/users/{uid}", json=body, headers=admin_h)  # noqa: E731
    for body in ({"status": "disabled"}, {"isAdmin": False}, {"role": "ministry_official", "ministry": coal}):
        r = post(admin_id, body)
        assert r.status_code == 403 and "your own account" in r.json()["detail"]
    assert post(admin_id, {"status": "active"}).status_code == 200            # a no-op on oneself is fine
    assert post(u["id"], {"isAdmin": True}).status_code == 400               # only an IPMD analyst
    assert post(u["id"], {"role": "agency_official"}).status_code == 400     # an agency official needs an agency
    assert post(u["id"], {"ministry": "Ministry of Nothing"}).status_code == 400
    assert post(u["id"], {"role": "developer"}).status_code == 422
    assert post(999999, {"status": "active"}).status_code == 404
    moved = post(u["id"], {"role": "ipmd_analyst", "isAdmin": True}).json()
    assert (moved["role"], moved["ministry"], moved["agency"], moved["isAdmin"]) == ("ipmd_analyst", None, None, True)
    back = post(u["id"], {"role": "ministry_official", "ministry": coal}).json()
    assert back["isAdmin"] is False and back["ministry"] == coal             # the flag goes with the role
    # disabling ends the account's sessions at once
    with TestClient(app) as theirs:
        login(theirs, email)
        assert theirs.get("/api/auth/me").status_code == 200
        assert post(u["id"], {"status": "disabled"}).json()["status"] == "disabled"
        assert theirs.get("/api/auth/me").status_code == 401
    assert login(client, email).status_code == 401


def test_a_role_change_applies_to_the_next_request(client, coal):
    u, email = official(ministry=coal)
    with TestClient(app) as theirs:
        login(theirs, email)
        n_coal = theirs.get("/api/portfolio").json()["kpis"]["nProjects"]
        accounts.update_user(u["id"], {"role": "ipmd_analyst", "ministry": None})
        assert theirs.get("/api/portfolio").json()["kpis"]["nProjects"] > n_coal


def test_reset_token_is_one_time_and_expires(client, coal):
    u, email = official(ministry=coal)
    h = as_role(client, "ipmd", admin=True)
    first = client.post(f"/api/admin/users/{u['id']}/reset-password", headers=h).json()
    second = client.post(f"/api/admin/users/{u['id']}/reset-password", headers=h)
    assert second.headers["cache-control"] == "no-store"
    second = second.json()
    assert len(second["token"]) >= 43 and second["expiresAt"]
    stored = sql("SELECT token_hash FROM app.password_resets").scalars().all()
    assert second["token"] not in stored and hashlib.sha256(second["token"].encode()).hexdigest() in stored
    client.cookies.clear()
    def reset(token, pw=NEW_PASSWORD):
        return client.post("/api/auth/reset", json={"token": token, "password": pw})
    assert reset(first["token"]).status_code == 400                    # a newer token replaced it
    assert reset(second["token"], "short").status_code == 422          # the policy; the token is not spent
    with TestClient(app) as theirs:
        login(theirs, email)
        assert reset(second["token"]).status_code == 204
        assert theirs.get("/api/auth/me").status_code == 401           # every session ended
    assert reset(second["token"]).status_code == 400                   # used
    assert login(client, email).status_code == 401 and login(client, email, NEW_PASSWORD).status_code == 200
    h = as_role(client, "ipmd", admin=True)
    third = client.post(f"/api/admin/users/{u['id']}/reset-password", headers=h).json()
    sql("UPDATE app.password_resets SET expires_at = now() - interval '1 minute'")
    client.cookies.clear()
    assert reset(third["token"], "yet another passphrase 9").status_code == 400    # expired
    assert reset("nonsense").status_code == 400


def test_issuing_a_reset_token_signs_the_account_out(client, coal):
    """Review finding (unit B, round 1): issuing a reset token (a forgotten password, or an account to lock out)
    ends every session of the account at once, not only when the token is used; an administrator resetting their own
    account keeps the session they did it from."""
    u, email = official(ministry=coal)
    with TestClient(app) as theirs:
        login(theirs, email)
        assert theirs.get("/api/auth/me").status_code == 200
        h = as_role(client, "ipmd", admin=True)
        assert client.post(f"/api/admin/users/{u['id']}/reset-password", headers=h).status_code == 200
        assert theirs.get("/api/auth/me").status_code == 401
    me = client.get("/api/auth/me").json()["userId"]
    with TestClient(app) as mine_elsewhere:
        login(mine_elsewhere, email_for("ipmd_analyst", admin=True))
        assert client.post(f"/api/admin/users/{me}/reset-password", headers=h).status_code == 200
        assert client.get("/api/auth/me").status_code == 200 and mine_elsewhere.get("/api/auth/me").status_code == 401


def test_every_admin_write_is_audited_with_who_and_where(client, coal):
    u, _ = official(ministry=coal)
    h = as_role(client, "ipmd", admin=True)
    admin_email = email_for("ipmd_analyst", admin=True)
    client.post(f"/api/admin/users/{u['id']}", json={"status": "disabled"}, headers=h)
    client.post(f"/api/admin/users/{u['id']}/reset-password", headers=h)
    as_role(client, "developer")
    page = client.get("/api/admin/audit", params={"user": admin_email}).json()
    acts = {r["action"]: r for r in page["items"]}
    assert {"auth.login", "user.update", "user.reset_password"} <= set(acts)
    assert all(r["email"] == admin_email and r["ip"] == ADDRESS and r["userId"] for r in page["items"])
    assert acts["user.update"]["target"] == str(u["id"]) and "status=disabled" in acts["user.update"]["detail"]
    assert client.get("/api/admin/audit", params={"action": "user.update"}).json()["total"] == 1
    assert client.get("/api/admin/audit", params={"since": "2999-01-01"}).json()["total"] == 0
    assert client.get("/api/admin/audit", params={"since": "yesterday"}).status_code == 422
    newest = client.get("/api/admin/audit").json()["items"]
    assert [r["id"] for r in newest] == sorted((r["id"] for r in newest), reverse=True)
    # the developer's own rows are for developers only
    assert db.audit_rows(hide_roles=("developer",))["total"] < db.audit_rows()["total"]


def test_audit_detail_never_holds_a_password_or_a_token(client, coal):
    u, email = official(ministry=coal)
    client.post("/api/auth/signup", json=signup_body(coal))
    login(client, email, "wrong password here")
    h = as_role(client, "ipmd", admin=True)
    token = client.post(f"/api/admin/users/{u['id']}/reset-password", headers=h).json()["token"]
    text = str(db.audit_rows(size=100)) + str(sql("SELECT * FROM app.signup_requests").mappings().all())
    assert NEW_PASSWORD not in text and token not in text and "wrong password here" not in text
