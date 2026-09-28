"""python -m backend.auth.bootstrap: the first administrator (password from the environment or a prompt, never the
command line; refused once one exists unless --force-reset) and the hidden developer from PAIMANA_DEVELOPER_EMAIL /
PAIMANA_DEVELOPER_PASSWORD (idempotent, one developer, never an official's email). No password is ever printed."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db  # noqa: E402
from backend import settings as cfg  # noqa: E402
from backend.auth import bootstrap, passwords  # noqa: E402
from backend.db import accounts  # noqa: E402
from backend.main import app  # noqa: E402
from viewers import account  # noqa: E402 - tests/viewers.py

ADMIN = "chief@tests.paimana.local"
ADMIN_PW = "first administrator passphrase 1"
DEV = "maker@tests.paimana.local"
DEV_PW = "developer passphrase number 2"


@pytest.fixture()
def env(fresh_db, monkeypatch):
    values = {"PAIMANA_ADMIN_PASSWORD": ADMIN_PW}
    monkeypatch.setattr(cfg, "environment", lambda: values)
    return values


def run(*args) -> int:
    return bootstrap.main(list(args))


def test_first_administrator_then_refused_then_force_reset(env, capsys):
    assert run("--email", ADMIN, "--name", "PAIMANA Administrator") == 0
    u = accounts.user(email=ADMIN, with_hash=True)
    assert (u["role"], u["is_admin"], u["status"], u["display_name"]) == ("ipmd_analyst", True, "active",
                                                                           "PAIMANA Administrator")
    assert passwords.verify(u["password_hash"], ADMIN_PW)
    assert run("--email", "second@tests.paimana.local") == 1           # an administrator exists
    assert "exists already" in capsys.readouterr().err
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"email": ADMIN, "password": ADMIN_PW}).status_code == 200
        env["PAIMANA_ADMIN_PASSWORD"] = "a reset administrator passphrase"
        assert run("--email", ADMIN, "--force-reset") == 0
        assert c.get("/api/auth/me").status_code == 401                # the reset ended its sessions
    assert passwords.verify(accounts.user(email=ADMIN, with_hash=True)["password_hash"],
                            "a reset administrator passphrase")
    out = capsys.readouterr()
    assert ADMIN_PW not in out.out + out.err and "reset administrator passphrase" not in out.out + out.err
    actions = {r["action"] for r in db.audit_rows(user="bootstrap")["items"]}
    assert {"bootstrap.admin", "bootstrap.password"} <= actions


def test_the_administrator_refuses_weak_passwords_and_official_emails(env, capsys):
    env["PAIMANA_ADMIN_PASSWORD"] = "password1234"
    assert run("--email", ADMIN) == 1 and "common password" in capsys.readouterr().err
    env["PAIMANA_ADMIN_PASSWORD"] = ADMIN_PW
    taken = account("ministry", ministry="Ministry of Coal")["email"]
    assert run("--email", taken) == 1                                  # an existing account needs --force-reset
    assert run("--email", "not an email") == 1
    env.pop("PAIMANA_ADMIN_PASSWORD")                                  # no variable, no terminal: refused
    assert run("--email", ADMIN) == 1 and "PAIMANA_ADMIN_PASSWORD" in capsys.readouterr().err


def test_the_developer_is_created_kept_and_alone(env, capsys):
    assert run("--developer-only") == 0 and "no developer configured" in capsys.readouterr().out
    env.update(PAIMANA_DEVELOPER_EMAIL=DEV, PAIMANA_DEVELOPER_PASSWORD=DEV_PW)
    assert run("--developer-only") == 0
    dev = accounts.user(email=DEV, with_hash=True)
    assert (dev["role"], dev["is_admin"], dev["ministry"], dev["agency"]) == ("developer", True, None, None)
    assert run("--developer-only") == 0 and "up to date" in capsys.readouterr().out
    assert accounts.user(dev["id"], with_hash=True)["password_hash"] == dev["password_hash"]   # not rehashed
    env["PAIMANA_DEVELOPER_PASSWORD"] = "another developer passphrase 3"
    assert run("--developer-only") == 0
    hashed = accounts.user(dev["id"], with_hash=True)["password_hash"]
    assert passwords.verify(hashed, env["PAIMANA_DEVELOPER_PASSWORD"])
    env["PAIMANA_DEVELOPER_EMAIL"] = "maker2@tests.paimana.local"
    assert run("--developer-only") == 0
    assert accounts.user(dev["id"])["status"] == "disabled"            # the variables name the one developer
    out = capsys.readouterr()
    assert DEV_PW not in out.out and "another developer passphrase" not in out.out + out.err
    env["PAIMANA_DEVELOPER_EMAIL"] = account("ipmd")["email"]
    assert run("--developer-only") == 1 and "official" in capsys.readouterr().err
    assert accounts.user(email=env["PAIMANA_DEVELOPER_EMAIL"])["role"] == "ipmd_analyst"   # never promoted


def test_the_admin_run_also_brings_the_developer(env):
    env.update(PAIMANA_DEVELOPER_EMAIL=DEV, PAIMANA_DEVELOPER_PASSWORD=DEV_PW)
    assert run("--email", ADMIN) == 0
    assert accounts.user(email=DEV)["role"] == "developer" and len(accounts.admins()) == 1   # it is not an admin
