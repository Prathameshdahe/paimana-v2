"""The first administrator and the hidden developer account (SPEC9 sections 2 and 7; docs/DEPLOYMENT.md).

  python -m backend.auth.bootstrap --email <e> --name <n> [--force-reset]
  python -m backend.auth.bootstrap --developer-only

The first form creates the first administrator (an IPMD analyst with the admin flag). The password comes from
PAIMANA_ADMIN_PASSWORD (the process environment, .env or .env.db) or, without it, a hidden prompt asked twice; never
from the command line. It refuses when an active administrator exists or the email already has an account, unless
--force-reset: then the account with that email becomes an active administrator with the new password and every
session it had ends. --email may be left out when ADMIN_EMAIL is set.

Both forms then create or update the developer from PAIMANA_DEVELOPER_EMAIL and PAIMANA_DEVELOPER_PASSWORD when both
are set (they live in .env.db): active, every feature, no scope; its password is set again only when it changed
(which ends its sessions), and any other developer account is disabled, so the variables name the one developer.
An email that belongs to an official's account is refused, never promoted. ALLOWED_EMAIL_DOMAINS does not apply to
either account (it limits sign-up only); the address's shape is checked. The api container runs the second form at
every start (deploy/api-entrypoint.sh), so the account always exists. Every change writes an audit row (role
'bootstrap'). Nothing prints a password, nor the developer's email (the account is hidden, and the container logs
are read by operators). Exit status 0 when done or nothing to do, 1 when refused.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from backend import db
from backend import settings as cfg
from backend.db import accounts

from . import passwords

ROLE = "bootstrap"   # the audit rows' role
ACTOR = {"user_id": None, "email": None, "ip": None}


class Refused(Exception):
    pass


def _password(env: dict, email: str) -> str:
    pw = env.get("PAIMANA_ADMIN_PASSWORD")
    if not pw:
        if not sys.stdin.isatty():
            raise Refused("set PAIMANA_ADMIN_PASSWORD or run this in a terminal to type the password")
        pw = getpass.getpass("Administrator password: ")
        if getpass.getpass("Again: ") != pw:
            raise Refused("the two passwords differ")
    try:
        passwords.check(pw, email)
    except ValueError as e:
        raise Refused(str(e)) from None
    return pw


def admin(email: str, name: str, force_reset: bool, env: dict) -> str:
    """Create (or with force_reset, reset) the administrator; returns what was done."""
    try:
        email = passwords.normal_email(email, domains_apply=False)
    except ValueError as e:
        raise Refused(f"{email!r}: {e}") from None
    existing = accounts.user(email=email)
    if not force_reset:
        if accounts.admins():
            raise Refused("an administrator exists already; use --force-reset to reset one")
        if existing is not None:
            raise Refused(f"{email} already has an account; use --force-reset to make it the administrator")
    if existing is not None and existing["role"] == "developer":
        raise Refused("that email is the developer account's, not an administrator's")
    hashed = passwords.hash_password(_password(env, email))
    if existing is None:
        accounts.create_user(email, hashed, name, "ipmd_analyst", is_admin=True, actor=ACTOR, actor_role=ROLE,
                             action="bootstrap.admin")
        return f"administrator {email} created"
    accounts.update_user(existing["id"], {"role": "ipmd_analyst", "ministry": None, "agency": None, "is_admin": True,
                                          "status": "active", "display_name": name or existing["display_name"]},
                         ACTOR, ROLE, "bootstrap.admin")
    accounts.set_password(existing["id"], hashed, actor=ACTOR, actor_role=ROLE, action="bootstrap.password")
    return f"administrator {email} reset (its sessions ended)"


def developer(env: dict) -> str:
    """Create or update the developer from the environment; returns what was done."""
    email, pw = env.get("PAIMANA_DEVELOPER_EMAIL"), env.get("PAIMANA_DEVELOPER_PASSWORD")
    if not email or not pw:
        return "no developer configured (PAIMANA_DEVELOPER_EMAIL and PAIMANA_DEVELOPER_PASSWORD)"
    try:
        email = passwords.normal_email(email, domains_apply=False)
        passwords.check(pw, email)
    except ValueError as e:
        raise Refused(f"the developer account: {e}") from None
    u = accounts.user(email=email, with_hash=True)
    if u is not None and u["role"] != "developer":
        raise Refused("PAIMANA_DEVELOPER_EMAIL belongs to an official's account; the developer needs its own")
    done = []
    if u is None:
        u = accounts.create_user(email, passwords.hash_password(pw), "Developer", "developer", is_admin=True,
                                 actor=ACTOR, actor_role=ROLE, action="bootstrap.developer")
        done.append("created")
    else:
        want = {"status": "active", "is_admin": True, "ministry": None, "agency": None}
        if any(u[k] != v for k, v in want.items()):
            accounts.update_user(u["id"], want, ACTOR, ROLE, "bootstrap.developer")
            done.append("re-enabled")
        if not passwords.verify(u["password_hash"], pw):
            accounts.set_password(u["id"], passwords.hash_password(pw), actor=ACTOR, actor_role=ROLE,
                                  action="bootstrap.password")
            done.append("password changed (its sessions ended)")
    others = [o for o in accounts.with_role("developer") if o["id"] != u["id"] and o["status"] == "active"]
    for o in others:
        accounts.update_user(o["id"], {"status": "disabled"}, ACTOR, ROLE, "bootstrap.developer")
    if others:
        done.append(f"{len(others)} other developer account(s) disabled")
    return "developer account: " + (", ".join(done) or "up to date")   # its email stays out of the logs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.auth.bootstrap", description=__doc__.split("\n\n")[0])
    ap.add_argument("--email", help="the administrator's email (default: ADMIN_EMAIL)")
    ap.add_argument("--name", default="Administrator", help="the administrator's display name")
    ap.add_argument("--force-reset", action="store_true",
                    help="reset the password of (or promote) the account with --email even when an administrator "
                         "exists")
    ap.add_argument("--developer-only", action="store_true",
                    help="only create or update the developer from PAIMANA_DEVELOPER_EMAIL / _PASSWORD")
    args = ap.parse_args(argv)
    env = cfg.environment()
    try:
        db.upgrade()
        if not args.developer_only:
            email = args.email or cfg.settings.admin_email
            if not email:
                raise Refused("give --email (or set ADMIN_EMAIL)")
            print(admin(email, args.name.strip(), args.force_reset, env))
        print(developer(env))
    except Refused as e:
        print(f"bootstrap refused: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
