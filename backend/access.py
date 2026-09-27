"""Who is asking and what they may see (docs/ACCESS_CONTROL.md).

PROTOTYPE, no authentication: the frontend (frontend/src/lib/api.ts) sends the signed-in role and scope as
X-Paimana-Role, X-Paimana-Ministry and X-Paimana-Agency (URI-encoded) and the backend trusts them. A real deployment
would build the same Viewer from a verified session instead; nothing else here changes. No headers is public.

POLICY is the one table: per role the features it may use and the scope its project rows are cut to: 'ministry' the
current projects of one ministry, 'agency' those of one canonical agency (gold/agency_map.csv), None every project.
Endpoints that every role may read (meta, portfolio, projects, project page, timeline, external summary, scopes) need
no feature; they still apply the scope.
"""
from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import Depends, Header, HTTPException, Query

from . import serving

ROLES = ("public", "agency_official", "ministry_official", "ipmd_analyst")
_INTERNAL = {"insights", "alerts", "watchlist", "bottlenecks", "agencies", "radar", "approvals", "live"}
POLICY = {
    # redacted project page (no drivers, analogues, intervals or provenance), no alerts, no internal pages
    "public": {"scope": None, "features": set()},
    "agency_official": {"scope": "agency", "features": _INTERNAL},
    "ministry_official": {"scope": "ministry", "features": _INTERNAL | {"ack", "models", "chat"}},
    "ipmd_analyst": {"scope": None, "features": _INTERNAL | {"ack", "models", "chat", "jobs", "workers",
                                                             "unlinked_signals"}},
}
# feature -> what it covers (the frontend keeps the same names in src/lib/auth/access.ts)
FEATURES = {
    "insights": "drivers (SHAP), analogues, quantile intervals, provenance, forecast, brief, project news",
    "alerts": "alert feed, bell and live stream", "ack": "acknowledge an alert",
    "watchlist": "per-role watchlist", "bottlenecks": "Bottleneck Intelligence", "agencies": "Agency matrix",
    "radar": "External Evidence Radar", "approvals": "approval inbox (memos addressed to the role)",
    "live": "live job status", "models": "Models page", "chat": "project assistant (frontend only)",
    "jobs": "run the inbox watcher, news scout and uploads", "workers": "worker console and trigger",
    "unlinked_signals": "news items not linked to any project",
}


@dataclass(frozen=True)
class Viewer:
    role: str = "public"
    ministry: str | None = None
    agency: str | None = None

    @property
    def scope(self) -> tuple[str, str] | None:
        """('ministry', name), ('agency', canonical name) or None (every project); serving.* take it as scope=."""
        kind = POLICY[self.role]["scope"]
        return (kind, self.ministry if kind == "ministry" else self.agency) if kind else None

    @property
    def keys(self) -> frozenset | None:
        """The project keys in scope (current and past projects), None for every project."""
        return serving.scope_keys(self.scope) if self.scope else None

    def can(self, feature: str) -> bool:
        return feature in POLICY[self.role]["features"]

    def sees(self, key: str) -> bool:
        return self.scope is None or key in self.keys

    def acting_as(self, role: str | None) -> str:
        """The role an action is recorded under. A role sent in the body or query must be the signed-in one."""
        if role is not None and role != self.role:
            raise HTTPException(status_code=403, detail=f"signed in as {self.role}, not {role}")
        return self.role


def _clean(v: str | None) -> str | None:
    return unquote(v).strip() or None if v else None


def make_viewer(role: str | None, ministry: str | None, agency: str | None) -> Viewer:
    role = _clean(role) or "public"
    if role not in POLICY:
        raise HTTPException(status_code=400, detail=f"unknown role {role}; one of {', '.join(ROLES)}")
    kind = POLICY[role]["scope"]
    if kind is None:
        return Viewer(role)
    name = _clean(ministry if kind == "ministry" else agency)
    known = {r["name"] for r in serving.scopes()["ministries" if kind == "ministry" else "agencies"]}
    if name not in known:
        raise HTTPException(status_code=400, detail=f"{role} needs a known {kind} (X-Paimana-{kind.capitalize()}); "
                                                    "see /api/scopes")
    return Viewer(role, **{kind: name})


def viewer(x_paimana_role: str | None = Header(None), x_paimana_ministry: str | None = Header(None),
           x_paimana_agency: str | None = Header(None)) -> Viewer:
    return make_viewer(x_paimana_role, x_paimana_ministry, x_paimana_agency)


def stream_viewer(role: str | None = Query(None, max_length=40), ministry: str | None = Query(None, max_length=200),
                  agency: str | None = Query(None, max_length=200)) -> Viewer:
    """EventSource cannot send headers, so the alert stream takes the same three as query parameters."""
    return make_viewer(role, ministry, agency)


def need(feature: str):
    """Dependency: the viewer, or 403 when POLICY does not give their role this feature."""
    def dep(v: Viewer = Depends(viewer)) -> Viewer:
        if not v.can(feature):
            raise HTTPException(status_code=403, detail=f"{FEATURES[feature]} is not available to {v.role}")
        return v
    return dep


def in_scope(v: Viewer, key: str) -> str:
    """key (canonical) when the viewer's scope has it, else 404 (an out-of-scope project does not exist for them)."""
    if not v.sees(key):
        raise HTTPException(status_code=404, detail=f"project {key} not found")
    return key
