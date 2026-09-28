"""The one-click demo sign-in (DEMO_LOGIN, backend/auth/routes.py): off by default and 404; on, every role's demo
account signs in with a real session (scope, admin flag and the numbers policy as for a real account), a second click
switches roles with the CSRF token like any write, and each click leaves an audit row."""
import dataclasses
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend import settings as cfg  # noqa: E402
from backend.auth import passwords  # noqa: E402
from backend.auth import routes as auth_routes  # noqa: E402
from backend.db import accounts  # noqa: E402
from backend.main import app  # noqa: E402

DEV_EMAIL = "developer@tests.paimana.local"


@pytest.fixture()
def demo_on(monkeypatch, fresh_db):
    monkeypatch.setattr(cfg, "settings", dataclasses.replace(cfg.settings, demo_login=True))
    env = dict(cfg.environment())
    env.pop("PAIMANA_DEVELOPER_EMAIL", None)
    monkeypatch.setattr(cfg, "environment", lambda *a, **k: env)
    return env


def test_off_by_default_and_then_404(monkeypatch, fresh_db):
    assert cfg.Settings.__dataclass_fields__["demo_login"].default is False
    assert cfg.load({"DATABASE_URL": cfg.settings.database_url}).demo_login is False
    monkeypatch.setattr(cfg, "settings", dataclasses.replace(cfg.settings, demo_login=False))   # whatever .env says
    with TestClient(app) as c:
        assert c.get("/api/auth/demo").json() == {"enabled": False, "roles": []}
        assert c.post("/api/auth/demo", json={"role": "ipmd"}).status_code == 404
    assert accounts.user(email="ipmd.demo@paimana.local") is None


def test_lists_the_four_official_views_and_never_the_developer(demo_on):
    sc = serving.scopes()
    accounts.create_user(DEV_EMAIL, passwords.hash_password("correct horse battery staple 42"), "Dev", "developer",
                         is_admin=True)
    demo_on["PAIMANA_DEVELOPER_EMAIL"] = DEV_EMAIL          # even with the developer's account configured
    with TestClient(app) as c:
        info = c.get("/api/auth/demo").json()
        assert info["enabled"] is True
        assert [r["role"] for r in info["roles"]] == ["ipmd", "ministry", "agency", "admin"]
        scope = {r["role"]: r["scope"] for r in info["roles"]}
        assert scope["ministry"] == sc["ministries"][0]["name"] and scope["agency"] == sc["agencies"][0]["name"]
        assert c.post("/api/auth/demo", json={"role": "developer"}).status_code == 422
        assert c.get("/api/auth/me").status_code == 401


def test_any_ministry_or_agency_gets_its_own_demo_account(demo_on):
    sc = serving.scopes()
    other_m, other_a = sc["ministries"][1]["name"], sc["agencies"][1]["name"]
    with TestClient(app) as c:
        top = c.post("/api/auth/demo", json={"role": "ministry"}).json()
        h = {"X-CSRF-Token": top["csrfToken"]}
        m = c.post("/api/auth/demo", json={"role": "ministry", "ministry": other_m.upper()}, headers=h).json()
        assert m["ministry"] == other_m and m["userId"] != top["userId"]            # canonical spelling, own account
        assert c.get("/api/projects").json()["total"] == serving.projects(scope=("ministry", other_m), size=1)["total"]
        h = {"X-CSRF-Token": m["csrfToken"]}
        a = c.post("/api/auth/demo", json={"role": "agency", "agency": other_a}, headers=h).json()
        assert a["role"] == "agency_official" and a["agency"] == other_a
        h = {"X-CSRF-Token": a["csrfToken"]}
        bad = c.post("/api/auth/demo", json={"role": "agency", "agency": "No Such Agency"}, headers=h)
        assert bad.status_code == 400 and c.get("/api/auth/me").json()["agency"] == other_a   # the session holds
        again = c.post("/api/auth/demo", json={"role": "ministry", "ministry": other_m}, headers=h).json()
        assert again["userId"] == m["userId"]                                      # the same account next time
    assert accounts.user(user_id=top["userId"])["ministry"] == sc["ministries"][0]["name"]   # the default one kept its


@pytest.mark.parametrize("role, account_role, admin", [
    ("ipmd", "ipmd_analyst", False), ("ministry", "ministry_official", False),
    ("agency", "agency_official", False), ("admin", "ipmd_analyst", True)])
def test_each_role_signs_in_with_a_real_session(demo_on, role, account_role, admin):
    with TestClient(app) as c:
        r = c.post("/api/auth/demo", json={"role": role})
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["role"] == account_role and me["isAdmin"] is admin and me["csrfToken"]
        assert c.get("/api/auth/me").json()["userId"] == me["userId"]
        rows = c.get("/api/projects", params={"size": 50}).json()["items"]
        assert rows and all(x["pAny2q"] is None for x in rows)            # the numbers policy holds
        assert all(x["outlook"] is not None for x in rows if x["tier"] != "Watch")
        if role == "agency":
            assert me["agency"] and c.get("/api/projects").json()["total"] == serving.projects(
                scope=("agency", me["agency"]), size=1)["total"]
        assert (c.get("/api/admin/users").status_code == 200) is admin
        assert c.get("/api/models").status_code == 403


def test_a_second_click_switches_roles_with_the_csrf_token(demo_on):
    with TestClient(app) as c:
        first = c.post("/api/auth/demo", json={"role": "agency"}).json()
        old_cookie = c.cookies.get("paimana_session")
        assert c.post("/api/auth/demo", json={"role": "ministry"}).status_code == 403    # a write without the token
        r = c.post("/api/auth/demo", json={"role": "ministry"}, headers={"X-CSRF-Token": first["csrfToken"]})
        assert r.status_code == 200 and r.json()["role"] == "ministry_official"
        assert c.get("/api/auth/me").json()["role"] == "ministry_official"
    with TestClient(app) as stale:
        stale.cookies.set("paimana_session", old_cookie)
        assert stale.get("/api/auth/me").status_code == 401                             # the replaced session ended
    rows = db.audit_rows(action="auth.demo_login")["items"]
    assert [row["detail"].split(" (")[0] for row in rows] == ["one-click demo sign-in as ministry",
                                                          "one-click demo sign-in as agency"]


def test_a_demo_account_keeps_no_known_password_and_drift_is_corrected(demo_on):
    with TestClient(app) as c:
        me = c.post("/api/auth/demo", json={"role": "ipmd"}).json()
    email = me["email"]
    assert email == auth_routes.DEMO["ipmd"][0]
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"email": email, "password": ""}).status_code == 401
    accounts.update_user(me["userId"], {"status": "disabled", "role": "agency_official", "agency": "NHAI"})
    with TestClient(app) as c:
        again = c.post("/api/auth/demo", json={"role": "ipmd"}).json()
        assert again["userId"] == me["userId"] and again["role"] == "ipmd_analyst" and again["agency"] is None
