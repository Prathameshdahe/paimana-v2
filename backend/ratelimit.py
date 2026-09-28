"""In-memory rate limits inside the api, behind nginx's per-address limits (deploy/nginx.conf.template). The chat
(POST /api/chat) keys on the account when signed in and on the client address for the public (backend/access.py
Viewer.who; the address is X-Forwarded-For's only from settings.trusted_proxies, backend/auth/middleware.py): the
public PUBLIC (6 questions a minute and 40 an hour), a signed-in account OFFICIAL (20 a minute). Every answer can hold
the one local LLM for a minute, so the limits keep one browser from starving the others. The password reset (POST
/api/auth/reset) takes RESET per address. The sign-in and sign-up limits live in the database instead
(backend/auth/limits.py), so a restart does not reset them.

check(who, kind) records the request and returns None when it is allowed, else the seconds until the next one is
allowed (the rejected request is not recorded, so waiting out the window always works). kind is a role ('public'
the public's limits, any other role OFFICIAL) or a bucket of RULES. Sliding windows: the timestamps of the requests
inside the longest window, per (who, kind). One process (uvicorn runs one worker), one dict behind a lock; keys whose
own longest window has emptied are dropped once there are more than MAX_KEYS.
"""
import math
import threading
import time
from collections import deque

PUBLIC = ((6, 60.0), (40, 3600.0))   # (requests, window in seconds)
OFFICIAL = ((20, 60.0),)
RESET = ((10, 60.0),)
RULES = {"public": PUBLIC, "reset": RESET}
MAX_KEYS = 10_000

_hits: dict[tuple[str, str], deque] = {}
_lock = threading.Lock()


def limits(kind: str) -> tuple[tuple[int, float], ...]:
    return RULES.get(kind, OFFICIAL)


def horizon(kind: str) -> float:
    """The longest window of kind's limits: how long a request of that kind counts."""
    return max(w for _, w in limits(kind))


def check(who: str, kind: str, now: float | None = None) -> float | None:
    """None (allowed, recorded) or the seconds to wait (refused, not recorded)."""
    now = time.monotonic() if now is None else now
    rules = limits(kind)
    with _lock:
        q = _hits.setdefault((who, kind), deque())
        while q and now - q[0] >= horizon(kind):
            q.popleft()
        wait = 0.0
        for n, window in rules:
            inside = [t for t in q if now - t < window]
            if len(inside) >= n:
                wait = max(wait, inside[len(inside) - n] + window - now)
        if wait > 0:
            return wait
        q.append(now)
        if len(_hits) > MAX_KEYS:  # each key by its own kind's horizon: a public hour outlives an official minute
            for k in [k for k, d in _hits.items() if not d or now - d[-1] >= horizon(k[1])]:
                del _hits[k]
    return None


def message(role: str, wait_s: float) -> str:
    rules = " and ".join(f"{n} {'a minute' if w == 60 else 'an hour'}" for n, w in limits(role))
    who = "from the public" if role == "public" else "per signed-in account"
    return (f"Too many questions: the assistant takes {rules} {who}. Please try again in "
            f"{math.ceil(wait_s)} seconds.")


def reset() -> None:
    """Forget every counter (tests)."""
    with _lock:
        _hits.clear()
