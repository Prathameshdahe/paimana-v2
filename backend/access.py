"""Who is asking and what they may see (docs/ACCESS_CONTROL.md).

The viewer comes from the session cookie (backend/auth/sessions.py): no cookie is the public; a cookie that names a
live session is its account's role, scope and admin flag, read from app.users on every request (a disabled account,
a changed role or scope takes effect at once); a cookie that names no live session (expired, revoked, signed out
elsewhere) is 401 with the cookie cleared, so the browser falls back to the public instead of showing stale pages.

POLICY is the one table: per role the features it may use and the scope its project rows are cut to: 'ministry' the
current projects of one ministry, 'agency' those of one canonical agency (gold/agency_map.csv), None every project.
Endpoints that every role may read (meta, portfolio, projects, project page, timeline, external summary, scopes) need
no feature; they still apply the scope. FLAGGED features need the account's is_admin flag on top of the role (an IPMD
analyst with the flag is the administrator, secure.txt section 17); the developer has every feature, the flag or not.
The developer is hidden: bootstrap-only (backend/auth/bootstrap.py), never listed to administrators, never a sign-up
choice, its audit rows shown to developers only. Model numbers (`numbers`), the models page, the worker console, job
runs, the unlinked news pool and the audit log are the developer's alone (SPEC9_ui sections 6 and 7).
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from . import serving
from .auth import sessions

ROLES = ("public", "agency_official", "ministry_official", "ipmd_analyst", "developer")
OFFICIAL_ROLES = ("agency_official", "ministry_official", "ipmd_analyst")   # the roles a person can ask for
HIDDEN_ROLES = ("developer",)
_INTERNAL = {"insights", "alerts", "watchlist", "bottlenecks", "agencies", "radar", "approvals", "live"}
FLAGGED = {"admin"}
POLICY = {
    # redacted project page (no drivers, analogues, intervals or provenance), no alerts, no internal pages; the
    # assistant answers from the same public outputs (llm/tools.py decides per tool what each viewer reads)
    "public": {"scope": None, "features": {"chat"}},
    "agency_official": {"scope": "agency", "features": _INTERNAL | {"chat"}},
    "ministry_official": {"scope": "ministry", "features": _INTERNAL | {"ack", "chat"}},
    "ipmd_analyst": {"scope": None, "features": _INTERNAL | {"ack", "chat", "admin"}},
    "developer": {"scope": None, "features": _INTERNAL | {"ack", "chat", "admin", "numbers", "models", "workers",
                                                          "jobs", "unlinked_signals", "audit"}},
}
# feature -> what it covers (the frontend keeps the same names in src/lib/auth/access.ts)
FEATURES = {
    "insights": "drivers, analogues, intervals, provenance, forecast, brief, project news, second opinion",
    "alerts": "alert feed, bell and live stream", "ack": "acknowledge an alert",
    "watchlist": "per-role watchlist", "bottlenecks": "Bottleneck Intelligence", "agencies": "Agency matrix",
    "radar": "External Evidence Radar", "approvals": "approval inbox (memos addressed to the role)",
    "live": "live job status", "models": "Models page",
    "chat": "AI assistant (POST /api/chat; each tool reads only what the role may see, docs/AI_ASSISTANT.md)",
    "jobs": "run the inbox watcher, news scout, research agent, portal refreshes and uploads",
    "workers": "worker console and trigger",
    "unlinked_signals": "news items not linked to any project",
    "admin": "administration: sign-up requests and accounts",
    "audit": "the audit log",
    "numbers": "raw model numbers (probabilities, contributions, intervals, calibration)",
}


@dataclass(frozen=True)
class Viewer:
    role: str = "public"
    ministry: str | None = None
    agency: str | None = None
    user_id: int | None = None
    is_admin: bool = False
    email: str | None = None
    ip: str | None = None

    @property
    def scope(self) -> tuple[str, str] | None:
        """('ministry', name), ('agency', canonical name) or None (every project); serving.* take it as scope=."""
        kind = POLICY[self.role]["scope"]
        return (kind, self.ministry if kind == "ministry" else self.agency) if kind else None

    @property
    def keys(self) -> frozenset | None:
        """The project keys in scope (current and past projects), None for every project."""
        return serving.scope_keys(self.scope) if self.scope else None

    @property
    def actor(self) -> dict:
        """Who does a write, for its audit row: {user_id, email, ip} (the public: the address only)."""
        return {"user_id": self.user_id, "email": self.email, "ip": self.ip}

    @property
    def who(self) -> str:
        """The rate limiters' key: the account when signed in, else the client address."""
        return f"user:{self.user_id}" if self.user_id is not None else f"ip:{self.ip or 'unknown'}"

    def can(self, feature: str) -> bool:
        if feature not in POLICY[self.role]["features"]:
            return False
        return feature not in FLAGGED or self.is_admin or self.role == "developer"

    def sees(self, key: str) -> bool:
        return self.scope is None or key in self.keys

    def acting_as(self, role: str | None) -> str:
        """The role an action is recorded under. A role sent in the body or query must be the signed-in one."""
        if role is not None and role != self.role:
            raise HTTPException(status_code=403, detail="that role is not the signed-in one")
        return self.role


def make_viewer(role: str | None, ministry: str | None = None, agency: str | None = None) -> Viewer:
    """A viewer of role and scope without a session, for the command-line tools and the tests of code below the API
    (llm/eval.py, llm/rag.py, the router tests); 400 for an unknown role or scope. The API never builds one from
    request data: viewer() reads the session."""
    role = (role or "").strip() or "public"
    if role not in POLICY:
        raise HTTPException(status_code=400, detail=f"unknown role {role}; one of {', '.join(ROLES)}")
    kind = POLICY[role]["scope"]
    if kind is None:
        return Viewer(role)
    name = ((ministry if kind == "ministry" else agency) or "").strip()
    known = {r["name"] for r in serving.scopes()["ministries" if kind == "ministry" else "agencies"]}
    if name not in known:
        raise HTTPException(status_code=400, detail=f"{role} needs a known {kind}; see /api/scopes")
    return Viewer(role, **{kind: name})


def known_scope(role: str, ministry: str | None, agency: str | None) -> tuple[str | None, str | None]:
    """(ministry, agency) an account of role is cut to, spelled as /api/scopes spells it (a case-insensitive match):
    a ministry official has a known ministry and no agency, an agency official a known canonical agency and no
    ministry, anyone else neither. 400 when the role needs a scope it was not given."""
    kind = POLICY[role]["scope"]
    if kind is None:
        return None, None
    given = ((ministry if kind == "ministry" else agency) or "").strip().casefold()
    names = {r["name"].casefold(): r["name"] for r in serving.scopes()["ministries" if kind == "ministry"
                                                                        else "agencies"]}
    if given not in names:
        raise HTTPException(status_code=400, detail=f"a {role.replace('_', ' ')} needs a known {kind}; "
                                                    "pick one from /api/scopes")
    return (names[given], None) if kind == "ministry" else (None, names[given])


def viewer(request: Request) -> Viewer:
    """Dependency: the public without a session cookie, the signed-in account with one; 401 for a cookie that names
    no live session (sessions.current)."""
    s = sessions.current(request)
    ip = sessions.client_ip(request)
    if s is None:
        return Viewer(ip=ip)
    request.state.user_id = s["id"]   # the access log's user column (backend/auth/middleware.py)
    return Viewer(s["role"], s["ministry"], s["agency"], s["id"], bool(s["is_admin"]), s["email"], ip)


def need(feature: str):
    """Dependency: the viewer, or 403 when POLICY does not give their role this feature."""
    def dep(v: Viewer = Depends(viewer)) -> Viewer:
        if not v.can(feature):
            raise HTTPException(status_code=403, detail=f"{FEATURES[feature]}: not available to this account")
        return v
    return dep


def in_scope(v: Viewer, key: str) -> str:
    """key (canonical) when the viewer's scope has it, else 404 (an out-of-scope project does not exist for them)."""
    if not v.sees(key):
        raise HTTPException(status_code=404, detail=f"project {key} not found")
    return key
