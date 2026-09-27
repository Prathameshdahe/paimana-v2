"""
PARIVESH forest-clearance proposals: the portal side of the forest row (evidence and display only; the 2026-09
research found no backtest lift from portal data, so nothing here is a model feature).

Built by the external step (pipeline/external.py main):
Inputs   raw/external/parivesh_fc_proposals_legacy.csv (proposals visible in the PARIVESH 1.0 online list,
         2014 to mid-2022, NOT a census: it lacks known proposals and diverges from official state totals),
         raw/external/parivesh_fc_timelines_remarks.csv (legacy timeline.aspx pages of proposal numbers the report
         remarks name but the list lacks), raw/external/fc_project_links_reviewed.csv (hand-reviewed project <->
         proposal links), the remark proposal numbers (gold/remark_status) and the forest events
Outputs  gold/fc_proposal_status.parquet (one row per project x proposal number named in its remarks),
         gold/external_fc_portal.parquet (one row per project with a linked proposal)

Point in time: a proposal's stage at asof reads only its dated events (received, Stage-I, Stage-II, queries) on or
before asof. Delisting, withdrawal and rejection carry no date in the list, so they are the status on the retrieval
date, shown as such. Only government bodies and PSUs keep a user agency name (public_agency); the portal's
'Pending Email' field and e-mail addresses are never stored.

Refresh the timeline cache (public page, one request per second at most, no captcha):
    python -m pipeline.parivesh timelines FP/MP/RAIL/41734/2019 [...]
"""
import re
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.silver import ROOT  # noqa: E402

EXTERNAL = ROOT / "dataset" / "raw" / "external"
LEGACY = EXTERNAL / "parivesh_fc_proposals_legacy.csv"
TIMELINES = EXTERNAL / "parivesh_fc_timelines_remarks.csv"
LINKS = EXTERNAL / "fc_project_links_reviewed.csv"
LEGACY_URL = "https://forestsclearance.nic.in/Online_Status.aspx"
TIMELINE_URL = "https://forestsclearance.nic.in/timeline.aspx"
USER_AGENT = "PAIMANA-early-warning/0.1 (public-data research prototype)"
MIN_GAP_S = 1.0           # polite rate: at most one request per second
LEGACY_NOTE = "visible in the PARIVESH 1.0 online list (2014 to mid-2022), not a census"
DROPPED = r"delist|withdrawn|reject|closed|returned|revoked"
# a user agency name is kept only when it is plainly a government body or PSU; a person's or a private firm's never
GOV_AGENCY = (
    r"NATIONAL\s+HIGH\s*WAY|\bNHAI\b|\bNHIDCL\b|\bMORTH\b|MINISTRY|\bP\.?\s*W\.?\s*D\b|PUBLIC\s+WORKS?|ROADS?\s+(?:AND|&)\s+"
    r"BUILDINGS?|\bR\s*&\s*B\b|RAILWAY|\bRLY\b|RAIL\s+VIKAS|\bRVNL\b|\bIRCON\b|BORDER\s+ROADS|\bBRO\b|DEPARTMENT|\bDEPTT?\b"
    r"|EXECUTIVE\s+ENGINEER|SUPERINTENDING\s+ENGINEER|CHIEF\s+ENGINEER|\bGOVT\b|GOVERNMENT|NAGAR\s+(?:PALIKA|NIGAM"
    r"|PANCHAYAT|PARISHAD)|MUNICIPAL|ZILLA|PANCHAYAT|COLLECTOR|IRRIGATION|JAL\s+(?:NIGAM|BOARD|SANSTHAN)|WATER\s+RESOURCES"
    r"|POWER\s*GRID|\bNTPC\b|\bNHPC\b|\bSJVN\b|\bTHDC\b|COAL\s+INDIA|COALFIELDS|\b(?:CCL|BCCL|MCL|SECL|WCL|NCL|ECL)\b"
    r"|SINGARENI|SINAGRENI|\bONGC\b|OIL\s+AND\s+NATURAL\s+GAS|OIL\s+INDIA|\bIOCL?\b|INDIAN\s+OIL|\bBPCL\b|\bHPCL\b|\bGAIL\b"
    r"|\bBSNL\b|\bNMDC\b|\bSAIL\b|\bNLC\b|UPPTCL|PSPCL|PSTCL|TRANSCO|\bUPCL\b|PTCUL|JBVNL|GETCO|GUJARAT\s+ENERGY|MSETCL"
    r"|KPTCL|TANTRANSCO|APTRANSCO|OPTCL|MPPTCL|RRVPNL|HVPNL|CSPTCL|WBSETCL|KSEB|POWER\s+TRANSMISSION\s+CORPORATION"
    r"|VIDYUT|ELECTRICITY\s+BOARD|DIVISION|CIRCLE|DEVELOPMENT\s+AUTHORITY|CPWD|\bAAI\b|AIRPORTS\s+AUTHORITY|DEFENCE"
    r"|\bARMY\b|\bITBP\b|\bBSF\b|\bCRPF\b|POLICE|GAS\s+AUTHORITY|BHARAT\s+(?:BROADBAND|PETROLEUM|SANCHAR)|\bBBNL\b"
    r"|STATE\s+(?:ELECTRICITY|TRANSMISSION|POWER|HIGHWAY|ROAD\s+DEVELOPMENT)|METRO\s+RAIL|DEDICATED\s+FREIGHT|\bDFCCIL\b"
    r"|\bKRCL\b|PORT\s+TRUST|HOUSING\s+BOARD|\bPMGSY\b|\bDRDA\b|RURAL\s+ENGINEERING|\bWRD\b|\bPHE\b")
PRIVATE_AGENCY = r"PRIVATE|\bPVT\b|\(P\)|\bLLP\b|\bM/S\b"
EMAIL = r"[\w.+-]+@[\w-]+\.[\w.]+"
LEGACY_COLS = ["state", "proposal_no", "file_no", "name", "category", "user_agency_govt", "area_ha", "status",
               "received", "stage1", "stage2", "milestones", "listing", "source", "retrieved"]
TIMELINE_COLS = ["proposal_no", "http", "name", "state", "category", "area_ha", "submitted", "division", "circle",
                 "nodal", "state_govt", "regional_office", "stage1", "stage2", "last_query_on", "last_query_by",
                 "last_query_replied", "note", "source", "retrieved"]
STATUS_COLS = ["project_key", "proposal_no", "found_in", "name", "category", "area_ha", "received", "stage1", "stage2",
               "stage_at_asof", "open_at_asof", "months_in_stage", "last_query_on", "last_query_by",
               "last_query_replied", "status_retrieved", "retrieved", "evidence"]
PORTAL_COLS = ["project_key", "link_source", "n_proposals", "proposals", "area_ha", "n_open", "n_stage1_only",
               "n_final", "n_dropped", "stage_at_asof", "months_in_stage", "oldest_open_received",
               "open_not_in_report", "evidence"]
# stage at asof, most to least outstanding: the project's reading is its most outstanding proposal
STAGE_ORDER = ["filed, no Stage-I", "Stage-I, awaiting Stage-II", "dropped without approval", "Stage-II (final)"]


def public_agency(s):
    """User agency names -> the name where it is plainly a government body or PSU, else null."""
    up = s.fillna("").str.upper()
    return s.where(up.str.contains(GOV_AGENCY) & ~up.str.contains(PRIVATE_AGENCY))


def legacy_table(pull, retrieved="2026-09-27"):
    """The research pull of the PARIVESH 1.0 list (one row per proposal) -> the committed CSV: user agency kept only
    for government bodies and PSUs, e-mail addresses removed from the milestone text."""
    d = pull.assign(user_agency_govt=public_agency(pull["user_agency"]),
                    milestones=pull["milestones"].str.replace(EMAIL, "", regex=True),
                    listing=LEGACY_NOTE, source=LEGACY_URL, retrieved=retrieved)
    for c in ["received", "stage1", "stage2"]:
        d[c] = pd.to_datetime(d[c]).dt.strftime("%Y-%m-%d")
    return d[LEGACY_COLS].sort_values("proposal_no", ignore_index=True)


def _dates(text):
    """dd/mm/YYYY dates in a text, as Timestamps."""
    return [pd.Timestamp(f"{y}-{m}-{d}") for d, m, y in re.findall(r"(\d{2})/(\d{2})/(\d{4})", text or "")]


def parse_timeline(html, pid):
    """A legacy timeline.aspx page -> one TIMELINE_COLS row: the date each level received the proposal, Stage-I
    and Stage-II, the last query with who raised it and whether it was answered, and the page's closing note
    ('Proposal Withdrawn', 'Stage-II Approval accorded by Regional Office'). E-mail addresses are dropped."""
    import lxml.html
    doc = lxml.html.fromstring(html)
    text = re.sub(r"\s+", " ", doc.text_content())
    out = {"proposal_no": pid, "http": 200}
    for key, rx in [("name", r"Name of Project for which Forest Land is required\s*:\s*(.*?)\s*\(iii\)"),
                    ("state", r"\(iv\)\. State\s*:\s*(.*?)\s*\(v\)"),
                    ("category", r"Category of the Project\s*:\s*(.*?)\s*\(vi\)"),
                    ("area_ha", r"proposed for diversion\(in ha\.\)\s*:\s*([\d.]+)")]:
        m = re.search(rx, text)
        out[key] = m.group(1).strip() if m else None
    tabs = [t for t in doc.iter("table") if "Stage-I Approval on" in t.text_content()]
    if tabs:
        rows = min(tabs, key=lambda t: len(t.text_content())).findall(".//tr")
        cell = lambda r: [re.sub(r"\s+", " ", c.text_content()).strip() for c in r if c.tag in ("td", "th")]  # noqa
        head, vals = cell(rows[0]), cell(rows[1]) if len(rows) > 1 else []
        cols = {"Submitted by User Agency": "submitted", "Division": "division", "Circle": "circle",
                "Nodal Office": "nodal", "State Government": "state_govt", "Regional Office": "regional_office",
                "Stage-I Approval on": "stage1", "Stage-II Approval on": "stage2"}
        for h, v in zip(head, vals):
            if h in cols:
                ds = _dates(v)
                out[cols[h]] = max(ds).strftime("%Y-%m-%d") if ds else None
    q = re.findall(r"(Query raised by|Replied by)\s*(.*?)\s*on\s*:\s*(\d{2}/\d{2}/\d{4})?", text)
    queries = [(pd.Timestamp("-".join(reversed(d.split("/")))), who, i) for i, (kind, who, d) in enumerate(q)
               if kind.startswith("Query") and d]
    if queries:
        on, who, i = max(queries)
        nxt = q[i + 1] if i + 1 < len(q) else None
        out.update(last_query_on=on.strftime("%Y-%m-%d"), last_query_by=re.sub(EMAIL, "", who).strip() or None,
                   last_query_replied=bool(nxt and nxt[0].startswith("Replied") and nxt[2]))
    note = re.search(r"NOTE:-\s*(.*?)\s*(?:\.\s|$)", text)
    if note:
        out["note"] = re.sub(r"\s+by\s*$", "", re.sub(EMAIL, "", note.group(1))).strip() or None
    return out


def fetch_timelines(pids, client=None, sleep=time.sleep, today=None):
    """Public legacy timeline pages, one request per MIN_GAP_S at most; a proposal whose page redirects to the
    portal's error page gets its http status and nothing else."""
    import httpx
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=False)
    rows = []
    try:
        for i, pid in enumerate(pids):
            if i:
                sleep(MIN_GAP_S)
            r = client.get(TIMELINE_URL, params={"pid": pid})
            row = parse_timeline(r.text, pid) if r.status_code == 200 else {"proposal_no": pid, "http": r.status_code}
            rows.append(row | {"source": f"{TIMELINE_URL}?pid={pid}",
                               "retrieved": str(today or date.today())})
    finally:
        if own:
            client.close()
    return pd.DataFrame(rows).reindex(columns=TIMELINE_COLS)


def last_eds(milestones, asof):
    """The latest EDS or site-inspection date on or before asof in a legacy milestone cell ('EDS(Addl. Info) :
    08 Oct 2025', 'EDS Sought(State Government): 13/07/2026', 'SIR RO Ranchi : 02 Feb 2026'), with its label."""
    if not isinstance(milestones, str):
        return None, None
    best = (None, None)
    for label, d in re.findall(r"((?:EDS|SIR)[^:]*?)\s*:\s*(\d{2}[ /](?:\d{2}|[A-Za-z]{3})[ /]\d{4})", milestones):
        t = pd.to_datetime(d, dayfirst=True, errors="coerce")
        if pd.notna(t) and t <= asof and (best[0] is None or t > best[0]):
            best = (t, label.strip())
    return best


def months(a, b):
    return (b - a).days / 30.4375


def stage_at(received, stage1, stage2, dropped, asof):
    """(stage label, date the stage began) at asof from a proposal's dated events; dropped is the list status on
    the retrieval date (undated)."""
    if pd.notna(stage2) and stage2 <= asof:
        return STAGE_ORDER[3], stage2
    if dropped:
        return STAGE_ORDER[2], pd.NaT
    if pd.notna(stage1) and stage1 <= asof:
        return STAGE_ORDER[1], stage1
    if pd.notna(received) and received <= asof:
        return STAGE_ORDER[0], received
    return None, pd.NaT


def load_legacy(path=LEGACY):
    d = pd.read_csv(path, dtype={"proposal_no": "str"})
    for c in ["received", "stage1", "stage2"]:
        d[c] = pd.to_datetime(d[c])
    return d


def load_timelines(path=TIMELINES):
    d = pd.read_csv(path, dtype={"proposal_no": "str"}) if Path(path).exists() else pd.DataFrame(columns=TIMELINE_COLS)
    for c in ["submitted", "stage1", "stage2", "last_query_on"]:
        d[c] = pd.to_datetime(d[c])
    return d


def proposal_rows(pairs, legacy, timelines, asof):
    """(project_key, proposal_no) pairs -> STATUS_COLS rows from the legacy list, else the timeline cache."""
    lg, tl = legacy.set_index("proposal_no"), timelines.set_index("proposal_no")
    out = []
    for k, pid in pairs[["project_key", "proposal_no"]].itertuples(index=False):
        r = {"project_key": k, "proposal_no": pid}
        if pid in lg.index:
            x = lg.loc[pid]
            q_on, q_by = last_eds(x["milestones"], asof)
            r.update(found_in="legacy_list", name=x["name"], category=x["category"], area_ha=x["area_ha"],
                     received=x["received"], stage1=x["stage1"], stage2=x["stage2"], last_query_on=q_on,
                     last_query_by=q_by, last_query_replied=None, status_retrieved=x["status"],
                     retrieved=x["retrieved"])
        elif pid in tl.index and tl.loc[pid, "http"] == 200:
            x = tl.loc[pid]
            q = x["last_query_on"] if pd.notna(x["last_query_on"]) and x["last_query_on"] <= asof else pd.NaT
            r.update(found_in="timeline_page", name=x["name"], category=x["category"], area_ha=float(x["area_ha"]),
                     received=x["submitted"], stage1=x["stage1"], stage2=x["stage2"], last_query_on=q,
                     last_query_by=x["last_query_by"] if pd.notna(q) else None,
                     last_query_replied=str(x["last_query_replied"]) == "True" if pd.notna(q) else None,
                     status_retrieved=x["note"] if isinstance(x["note"], str) else "no closing note on the page",
                     retrieved=x["retrieved"])
        else:
            r.update(found_in="not_found", status_retrieved="not in the saved list or timeline cache")
        out.append(r)
    d = pd.DataFrame(out).reindex(columns=STATUS_COLS)
    for c in ["received", "stage1", "stage2", "last_query_on"]:
        d[c] = pd.to_datetime(d[c])
    dropped = d["status_retrieved"].fillna("").str.contains(DROPPED, case=False)
    st = [stage_at(a, b, c, dr, asof) for a, b, c, dr in zip(d["received"], d["stage1"], d["stage2"], dropped)]
    d["stage_at_asof"] = [s for s, _ in st]
    d["months_in_stage"] = [round(months(t, asof), 1) if pd.notna(t) else np.nan for _, t in st]
    d["open_at_asof"] = d["stage_at_asof"].isin(STAGE_ORDER[:2])
    d["evidence"] = [evidence(r, asof) for r in d.itertuples(index=False)]
    return d


def evidence(r, asof):
    """'FP/JH/MIN/44804/2020 (Muraidih Colliery, 133.7 ha): filed Mar 2020, no Stage-I after 76 months at Jul 2026;
    last query 08 Oct 2025 (EDS(Addl. Info)); PARIVESH 1.0 status on 2026-09-27: Pending With UA'."""
    if r.found_in == "not_found":
        return f"{r.proposal_no}: not found in the saved PARIVESH list or timeline pages"
    name = str(r.name).strip().rstrip(".")
    name = name if len(name) <= 60 else name[:60].rsplit(" ", 1)[0] + "..."
    head = f"{r.proposal_no} ({name}, {r.area_ha:.1f} ha)"
    filed = f"filed {r.received:%b %Y}" if pd.notna(r.received) else "filing date not shown"
    at = f"{asof:%b %Y}"
    body = {STAGE_ORDER[0]: f"{filed}, no Stage-I after {r.months_in_stage:.0f} months at {at}",
            STAGE_ORDER[1]: f"{filed}, Stage-I {r.stage1:%b %Y}" if pd.notna(r.stage1) else filed,
            STAGE_ORDER[2]: f"{filed}, dropped without approval",
            STAGE_ORDER[3]: f"{filed}, Stage-II {r.stage2:%b %Y}" if pd.notna(r.stage2) else filed}.get(
        r.stage_at_asof, filed)
    if r.stage_at_asof == STAGE_ORDER[1]:
        body += f", awaiting Stage-II for {r.months_in_stage:.0f} months at {at}"
    q = ""
    if pd.notna(r.last_query_on) and r.stage_at_asof != STAGE_ORDER[3] and r.found_in == "timeline_page":
        who = f" by {r.last_query_by}" if isinstance(r.last_query_by, str) else ""
        replied = {True: ", answered", False: ", no reply on the page"}.get(r.last_query_replied, "")
        q = f"; last query {r.last_query_on:%d %b %Y}{who}{replied}"
    elif pd.notna(r.last_query_on) and r.stage_at_asof != STAGE_ORDER[3]:
        q = f"; last EDS or site-inspection entry {r.last_query_on:%d %b %Y} ({r.last_query_by})"
    return f"{head}: {body}{q}; portal status on {r.retrieved}: {r.status_retrieved}"


def portal_projects(rows, links, events, asof, open_q=4):
    """STATUS_COLS rows (every linked proposal) -> PORTAL_COLS per project. open_not_in_report: a proposal is open at
    asof while the report remarks carry no open forest event in the open_q quarters before asof."""
    r = rows[rows["found_in"].ne("not_found")].merge(links[["project_key", "proposal_no", "link_source"]],
                                                     on=["project_key", "proposal_no"])
    fe = events[events["category"].eq("forest_env") & events["status"].eq("open")
                & (events["last_seen"] > asof - pd.DateOffset(months=3 * open_q))]
    rank = {s: i for i, s in enumerate(STAGE_ORDER)}
    out = []
    for k, g in r.groupby("project_key"):
        g = g.assign(_r=g["stage_at_asof"].map(rank)).sort_values(["_r", "months_in_stage"], ascending=[True, False])
        top = g.iloc[0]
        op = g[g["open_at_asof"]]
        out.append({"project_key": k, "link_source": ";".join(sorted(set(g["link_source"]))),
                    "n_proposals": len(g), "proposals": ";".join(g["proposal_no"]),
                    "area_ha": round(float(g["area_ha"].sum()), 2), "n_open": len(op),
                    "n_stage1_only": int(g["stage_at_asof"].eq(STAGE_ORDER[1]).sum()),
                    "n_final": int(g["stage_at_asof"].eq(STAGE_ORDER[3]).sum()),
                    "n_dropped": int(g["stage_at_asof"].eq(STAGE_ORDER[2]).sum()),
                    "stage_at_asof": top["stage_at_asof"], "months_in_stage": top["months_in_stage"],
                    "oldest_open_received": op["received"].min() if len(op) else pd.NaT,
                    "open_not_in_report": bool(len(op)) and k not in set(fe["project_key"]),
                    "evidence": " | ".join(g["evidence"].head(3))
                                + (f" | and {len(g) - 3} more" if len(g) > 3 else "")})
    return pd.DataFrame(out, columns=PORTAL_COLS)


def remark_links(remark_status):
    """remark_status -> (project_key, proposal_no, link_source) for every proposal number the remarks name."""
    rs = remark_status[remark_status["proposal_no"].notna()]
    p = rs.assign(proposal_no=rs["proposal_no"].str.split(";")).explode("proposal_no")
    return p[["project_key", "proposal_no"]].assign(link_source="report remarks").reset_index(drop=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["timelines"] and argv[1:]:
        new = fetch_timelines(argv[1:])
        old = pd.read_csv(TIMELINES, dtype={"proposal_no": "str"}) if TIMELINES.exists() else new.iloc[:0]
        both = pd.concat([old[~old["proposal_no"].isin(new["proposal_no"])], new], ignore_index=True)
        both.sort_values("proposal_no").to_csv(TIMELINES, index=False)
        print(new.to_string(index=False))
        return both
    print(__doc__)


if __name__ == "__main__":
    main()
