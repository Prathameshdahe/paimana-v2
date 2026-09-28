"""In-memory rate limits for the chat (POST /api/chat), per client IP and role: the public PUBLIC (6 questions a
minute and 40 an hour), a signed-in official OFFICIAL (20 a minute). Every answer can hold the one local LLM for a
minute, so the limits keep one browser from starving the others; they are not a security boundary (the role is a
trusted header, docs/ACCESS_CONTROL.md).

check(ip, role) records the request and returns None when it is allowed, else the seconds until the next one is
allowed (the rejected request is not recorded, so waiting out the window always works). Sliding windows: the
timestamps of the requests inside the longest window, per (ip, role). One process, one dict behind a lock; keys whose
window has emptied are dropped once there are more than MAX_KEYS. A real deployment behind a proxy would key on the
forwarded client address and keep the counters in a shared store.
"""
import math
import threading
import time
from collections import deque

PUBLIC = ((6, 60.0), (40, 3600.0))   # (requests, window in seconds)
OFFICIAL = ((20, 60.0),)
MAX_KEYS = 10_000

_hits: dict[tuple[str, str], deque] = {}
_lock = threading.Lock()


def limits(role: str) -> tuple[tuple[int, float], ...]:
    return PUBLIC if role == "public" else OFFICIAL


def check(ip: str, role: str, now: float | None = None) -> float | None:
    """None (allowed, recorded) or the seconds to wait (refused, not recorded)."""
    now = time.monotonic() if now is None else now
    rules = limits(role)
    horizon = max(w for _, w in rules)
    with _lock:
        q = _hits.setdefault((ip, role), deque())
        while q and now - q[0] >= horizon:
            q.popleft()
        wait = 0.0
        for n, window in rules:
            inside = [t for t in q if now - t < window]
            if len(inside) >= n:
                wait = max(wait, inside[len(inside) - n] + window - now)
        if wait > 0:
            return wait
        q.append(now)
        if len(_hits) > MAX_KEYS:
            for k in [k for k, d in _hits.items() if not d or now - d[-1] >= horizon]:
                del _hits[k]
    return None


def message(role: str, wait_s: float) -> str:
    rules = " and ".join(f"{n} {'a minute' if w == 60 else 'an hour'}" for n, w in limits(role))
    who = "from the public" if role == "public" else "per signed-in official"
    return (f"Too many questions: the assistant takes {rules} {who}. Please try again in "
            f"{math.ceil(wait_s)} seconds.")


def reset() -> None:
    """Forget every counter (tests)."""
    with _lock:
        _hits.clear()
