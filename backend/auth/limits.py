"""The sign-in limits, kept in app.login_attempts so they hold across restarts and never tell whether an email has
an account (an unknown email is counted and locked exactly like a known one):

- lock: LOCK_FAILURES failed attempts on one email within LOCK_WINDOW lock that email for LOCK_FOR from the last of
  them (423 with Retry-After); only failures after the email's last successful sign-in and after its account's
  last password change count, and an attempt refused by the lock is not recorded, so waiting it out always works;
- per address: IP_FAILURES failed attempts from one client address within IP_WINDOW refuse that address's
  sign-ins until the oldest leaves the window (429 with Retry-After);
- sign-up: SIGNUPS_PER_HOUR requests from one address an hour (429), from app.signup_requests.
A successful sign-in is never refused by the address limit (an office behind one address keeps working).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from backend.db import accounts
from backend.db.accounts import exact_now as now

LOCK_FAILURES, LOCK_WINDOW, LOCK_FOR = 5, timedelta(minutes=15), timedelta(minutes=15)
IP_FAILURES, IP_WINDOW = 20, timedelta(minutes=1)
SIGNUPS_PER_HOUR = 3


def locked_until(fails: list[datetime], at: datetime) -> datetime | None:
    """When the lock these failures (oldest first) put on their email ends, None when there is none at `at`."""
    if not fails:
        return None
    last = fails[-1]
    burst = [t for t in fails if t > last - LOCK_WINDOW]
    until = last + LOCK_FOR
    return until if len(burst) >= LOCK_FAILURES and until > at else None


def email_lock(email: str) -> datetime | None:
    """The end of the email's current lock, or None."""
    at = now()
    return locked_until(accounts.failures(email, at - LOCK_WINDOW - LOCK_FOR), at)


def lock_after_failure(email: str) -> datetime | None:
    """The lock one more failure now would start (the caller records the failure with it)."""
    at = now()
    return locked_until(accounts.failures(email, at - LOCK_WINDOW - LOCK_FOR) + [at], at)


def ip_wait(ip: str | None) -> float | None:
    """Seconds until the address may try again, None when it may now."""
    at = now()
    fails = accounts.ip_failures(ip, at - IP_WINDOW)
    if len(fails) < IP_FAILURES:
        return None
    return max(1.0, (fails[-IP_FAILURES] + IP_WINDOW - at).total_seconds())


def signup_wait(ip: str | None) -> float | None:
    at = now()
    made = accounts.signups_from(ip, at - timedelta(hours=1))
    if len(made) < SIGNUPS_PER_HOUR:
        return None
    return max(1.0, (made[-SIGNUPS_PER_HOUR] + timedelta(hours=1) - at).total_seconds())


def seconds(until: datetime) -> int:
    return max(1, math.ceil((until - now()).total_seconds()))


def minutes(s: float) -> str:
    m = max(1, math.ceil(s / 60))
    return f"{m} minute{'s' if m != 1 else ''}"
