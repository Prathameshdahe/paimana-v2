"""
External factors (docs/IMPLEMENTATION_GUIDE_v2.md A.4, B 2.2 External, B 5.2): delay events from the report
remarks and the Parivesh forest-clearance path, per project.

Run from repo root after the silver build:  python -m pipeline.run external

Inputs   silver/typed_rows.parquet (every clean remark with its PRJ key), silver/observations.parquet,
         silver/project_master.parquet, raw/external/parivesh_fc_scenarios.csv
Outputs  gold/project_events.parquet, gold/external_fc.parquet

Remarks are free text only in 2014-2023 reports; later reports print templates ('start: 2025-04',
'Milestones achieved/total: 0/7'). Templates are stripped first, the rest is split into sentences and tagged
with TAXONOMY. A quarter counts as remark-observed for a project when one of its reports has free text left,
and an event is a run of consecutive remark-observed quarters that mention the category. It is open when its
last mention is in one of the project's last OPEN_LAST_Q remark-observed quarters, that quarter's mentions do not
all report it done ('EC received on ...'), and the project is not completed.

Remarks come from typed_rows (every accepted clean report row), not observations (the quarter's last remark):
it finds every observations mention plus 6% more key-quarter-category mentions and 16% more events, and the
first mention keeps its own document and page.

Forest clearance: each project gets a profile (linear or not, mining, violation, forest hectares from its
events) and is matched to the Parivesh scenarios it can fall under. The form (A-H) is never known, so every
form counts; with no hectares every area band counts. Survey rows apply to survey projects and defence
exemptions to defence projects only; the public-utility-in-LWE exemption (<= 0.1 ha of amenities) never.
"""
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.gold import GOLD  # noqa: E402
from pipeline.silver import ROOT, SILVER, quarter  # noqa: E402

EXTERNAL = ROOT / "dataset" / "raw" / "external"

# category -> subtype -> regex (case-insensitive; (?-i:...) marks the case-sensitive acronyms).
# The first subtype that matches names the mention.
TAXONOMY = {
    "land": {
        "acquisition": r"\bland\s*(?:acq|aq|acu)\w*|\b(?:acq|aq)\w*sition\s+of\s+(?:\w+\s+){0,2}land|(?-i:\bLA\b)",
        "notification": r"\b3\s*\(?[ADG]\)?\s*(?:notification|notified|gazette)|notifi\w*\s+(?:u/s|under\s+sec\w*)\s*3\s*\(?[ADG]\b"
                        r"|(?-i:\bCBA\b)",
        "compensation": r"\bcompensation\b|\bawards?\s+(?:for|of)\s+land",
        "possession": r"\bpossession\b|(?:handing|hand|handed)\s+over\s+of\s+(?:\w+\s+){0,2}land"
                      r"|(?:non[\s-]*availability|allot\w*|transfer)\s+of\s+(?:\w+\s+){0,2}land"
                      r"|land\s+(?:issue|problem|dispute|hurdle|record|not\s+(?:yet\s+)?(?:available|acquired|handed))",
        "encroachment": r"encroach\w*",
        "rr": r"(?-i:\bR\s*&\s*R\b)|rehabilit\w*\s+(?:&|and)\s+resettle\w*|\bresettle\w*|(?-i:\bPA[FP]s?\b)",
        "row": r"(?-i:\bRO[Ww]\b)|\bright\s+of\s+way\b",
    },
    "forest_env": {
        "forest_clearance": r"(?<!non-)(?<!non )\bforest\w*|afforest\w*|(?-i:\bFC\b)|stage[\s-]*(?:I{1,2}|1|2)\b\s*(?:forest\s+)?(?:clearance|FC)",
        "wildlife": r"wild\s*life|sanctuary|national\s+park|tiger\s+reserve|eco[\s-]*sensitive|elephant\s+corridor",
        "environment_clearance": r"environment\w*\s+(?:clearance|approval|permission)|(?-i:\bEC\b)|consent\s+to\s+(?:establish|operate)"
                                 r"|pollution\s+control",
        "ngt": r"(?-i:\bNGT\b)|green\s+tribunal",
        "moefcc": r"\bmoe\s*f\w*|ministry\s+of\s+environment",
        "crz": r"(?-i:\bCRZ\b)|coastal\s+regulation|mangrove\w*",
        "tree_felling": r"(?:felling|cutting)\s+of\s+(?:\w+\s+){0,3}trees|\btrees?\s+(?:felling|cutting)",
    },
    "litigation": {
        "court": r"\bhigh\s*court|supreme\s+court|apex\s+court|\bcourt\w*",
        "arbitration": r"arbitra\w*|(?-i:\bDRB\b)|\bconciliation",
        "stay": r"\bstay\s+(?:order|on|by|granted|vacated)|\bstayed\b",
        "writ": r"\bwrit\b|(?-i:\bPIL\b)|sub[\s-]*judice",
        "case": r"(?:court|legal)\s+case|case\s+(?:filed|pending|in\s+(?:the\s+)?(?:hon\w*\s+)?(?:court|high))|filed\s+(?:a\s+)?case",
        "dispute": r"legal\s+(?:dispute|issue|hurdle|matter)|litigat\w*|disput\w*",
    },
    "contractor": {
        "termination": r"terminat\w*|foreclos\w*|rescind\w*",
        "retender": r"\bre[\s-]*tender\w*|\bre[\s-]*award\w*|\bre[\s-]*bid\w*",
        "insolvency": r"insolven\w*|(?-i:\bNCLT\b)|(?-i:\bCIRP\b)|liquidat\w*|bankrupt\w*",
        "performance": r"contractor.{0,40}\b(?:slow|poor|delay|fail|not|non|default|abandon|stopp|left|lack|inadequate|financial)"
                       r"|\b(?:slow|poor|delay|fail|non|default|inadequate|lack)\w*.{0,40}\bcontractors?\b"
                       r"|(?:poor|inadequate|lack\s+of|non)[\s-]*(?:mobili[sz]ation|deployment)\s+of\s+(?:resources|manpower)",
    },
    "funding": {
        "fund_constraint": r"\bfunds?\s+(?:constraint|crunch|shortage|problem|issue|not\s+(?:yet\s+)?(?:released|available))"
                           r"|(?:paucity|shortage|non[\s-]*availability|availability|lack|want|inadequa\w*|constraints?|"
                           r"non[\s-]*release|release)\s+of\s+(?:\w+\s+)?funds?\b|financial\s+(?:constraint|crunch|problem|difficult)\w*",
        "budget": r"budget\w*\s+(?:constraint|allocation|cut|shortage)\w*|(?:inadequate|insufficient|low)\s+budget",
        "financial_closure": r"financial\s+closure",
        "payment": r"payments?\s+(?:pending|due|delay\w*|not\s+released)|(?:pending|delay\w*\s+in|non[\s-]*)\s*payments?",
    },
    "utility_shifting": {
        "utility": r"utilit\w*\s+shift\w*|shift\w*\s+(?:of\s+)?(?:\w+\s+){0,2}utilit\w*|utilit\w*\s+(?:relocation|diversion)",
        "lines": r"(?:shifting|diversion|relocation|crossing)\s+of\s+(?:\w+\s+){0,3}(?:lines?|pipe\s*lines?|cables?|poles?|towers?|mains)\b"
                 r"|(?:electric\w*|power|HT|LT|overhead|transmission|EHV)\s+lines?\s+(?:shift|cross|divers)\w*"
                 r"|pipe\s*lines?\s+crossing",
    },
    "inter_agency": {
        "railway_approval": r"\b(?:railways?|rly\.?)\s+(?:board\s+)?(?:approval|clearance|permission|nod|NOC)"
                            r"|(?:approval|clearance|permission|NOC)\s+(?:\w+\s+){0,3}(?:from|by|of)\s+(?:the\s+)?(?:railways?|rly)\b"
                            r"|(?-i:\bR[OU]Bs?\b).{0,40}(?:approv|GAD|railway|rly|clearance|permission)",
        "gad": r"(?-i:\bGADs?\b)|general\s+arrangement\s+drawing",
        "noc": r"(?-i:\bNOCs?\b)|no[\s-]+objection",
        "state_approval": r"(?:state|central)\s+gov\w*\.?\s+(?:approval|clearance|permission|sanction|nod|consent)"
                          r"|(?:approval|clearance|permission|nod|consent)\s+(?:\w+\s+){0,3}(?:from|of|by)\s+(?:the\s+)?(?:state|concerned)\s+gov",
        "other_approval": r"statutory\s+(?:clearance|approval)s?|local\s+(?:body|authority)\s+(?:approval|permission|clearance)s?"
                          r"|defence\s+(?:clearance|approval|NOC|permission)|(?:clearance|approval|permission)s?\s+(?:\w+\s+){0,3}awaited",
    },
    "law_order": {
        "law_order": r"law\s*(?:&|and)\s*order|security\s+(?:problem|issue|concern|situation)|\bunrest\b|curfew",
        "lwe": r"naxal\w*|maoist\w*|(?-i:\bLWE\b)|left\s+wing\s+extrem\w*|insurgen\w*|militan\w*|terror\w*",
        "agitation": r"agitation\w*|agitat(?:ed|ing)\b|protest\w*|\bbandh\w*|blockade|dharna|gherao\w*|(?:labou?r|workers?|truckers?|transport\w*|general)\s+strikes?",
        "local_resistance": r"(?:local|public|villagers?)\s+(?:\w+\s+)?(?:resistance|opposition|objection|obstruct\w*|hindrance|resist\w*)"
                            r"|obstruct\w*\s+(?:by|from)\s+(?:the\s+)?(?:local|villager)|villagers?\s+(?:obstruct|object|resist|oppos|stop)\w*",
    },
    "weather": {
        "monsoon": r"monsoon\w*|\brain(?!\s*water)\w*|cloud\s*burst",
        "flood": r"flood(?!\s+protection)\w*|landslide\w*|land\s+slide\w*|cyclon\w*|earthquake|snow\w*|inclement|extreme\s+weather|heat\s*wave",
        "covid": r"covid\w*|corona\w*|pandemic|lock\s*down",
        "force_majeure": r"force\s+majeure",
    },
}
# authority named in the sentence, first match in this order
AUTHORITY = {
    "NGT": r"(?-i:\bNGT\b)|green\s+tribunal",
    "Supreme Court": r"supreme\s+court|apex\s+court",
    "High Court": r"high\s*court",
    "MoEFCC": r"\bmoe\s*f\w*|ministry\s+of\s+environment",
    "State Forest Dept": r"forest\s+(?:dept|department|deptt|division|officials?|authorit\w*)|(?-i:\b(?:P?CCF|DFO)\b)"
                         r"|conservator\s+of\s+forest",
    "NHAI": r"(?-i:\bNHAI\b)|national\s+highways?\s+authority",
    "Railways": r"railway\s+board|\brly\.?\s*board|\brailways?\b|\brly\b",
    "State Govt": r"state\s+gov\w*|\bgovt?\.?\s+of\s+(?!india\b)[a-z]+|revenue\s+(?:dept|department|authorit\w*)"
                  r"|district\s+(?:administration|collector|authorit\w*)|\bcollector\b",
}
# report templates, stripped before tagging; what is left decides whether a report has free-text remarks
BOILERPLATE = (r"milestones achieved/total:\s*\d+/\d+|start:\s*\d{4}-\d{2}|doc reported (?:last|this) month:\s*[\d-]+"
               r"|delay w\.r\.t\. revised schedule(?:\s*\(r\d*\))?:\s*-?\d+\s*months|completed during(?: qtr\.)?[^;.]*"
               r"|cost_overrun_wrt_revised_cr:\s*-?[\d.]+|delay_wrt_revised_months:\s*-?\d+(?:\s*\(schedule r\d+\))?"
               r"|implementation mode:[^;]*|ppp_mode:[^;]*|anticipated doc (?:reported )?in the previous quarter:\s*[\d-]+"
               r"|list dated as on[^.;]*|status:\s*completed|also in this report's list of completed projects"
               r"|no project card printed in this report[^;]*|listed under 'projects completed/dropped during the month'[^;]*"
               r"|status not printed per project|physical progress for the month of \w+ is [\d.]+\s*%"
               r"|this project was approved on \w+ \d+ with capital investment of rs\.? [\d.,]+ crores?"
               r"(?: with schedule completion date \w+ \d+)?|under progress(?: \(p\))?|work in progress")
SENTENCE = r"\s*(?:[;•\n\r]|\.\s+(?=[A-Z(])|\s-\s*(?=[A-Z])|(?:^|(?<=\s))\(?(?:[ivx]{1,4}|\d{1,2})\)\s)\s*"
FOREST_HA = (r"(\d+(?:\.\d+)?)\s*(?:ha|hect\w*)\.?\s*(?:of\s+)?(?:\w+\s+){0,2}(?<!non )forest"
             r"|forest\s+land\s*(?:of|:|\(|measuring|admeasuring)?\s*(\d+(?:\.\d+)?)\s*(?:ha|hect)"
             r"|(?-i:\bFC\b)\s*\(\s*(\d+(?:\.\d+)?)\s*(?:ha|hect)")
VIOLATION = (r"violat\w*|without\s+(?:prior\s+|obtaining\s+|the\s+)?(?:forest\s+clearance|FC|EC|environment\w*\s+clearance"
             r"|clearance)|post[\s-]*facto")
# a mention that reports the matter done ('EC received on 31.07.23') and names no hold-up is resolved
DONE = (r"\b(?:obtained|received|granted|accorded|issued|completed|achieved|approved|done|removed|resolved|vacated"
        r"|settled|cleared|finali[sz]ed|disbursed|handed\s+over|in\s+(?:physical\s+)?possession|available)\b")
BLOCKED = (r"\b(?:await\w*|pending|delay\w*|yet\s+to|not|non|no|hold|held\s+up|stopp\w*|stalled|hamper\w*|affect\w*"
           r"|problems?|issues?|constraints?|balance|slow|obstruct\w*|disput\w*|ban|banned|under\s+process|in\s+progress"
           r"|expected|anticipated|likely|shortly)\b")
MIN_FREE_WORDS = 3        # a report has free text when this many 3+ letter words survive the template strip
OPEN_LAST_Q = 2           # an event is open when seen in one of the project's last 2 remark-observed quarters
SNIPPET = 200
EVENT_COLS = ["project_key", "category", "event_no", "first_seen", "last_seen", "n_quarters", "n_mentions", "status",
              "resolved", "subtype", "authority", "forest_area_ha", "violation", "evidence", "source_doc_id", "source_page", "state", "sector",
              "remarks_last_seen"]


def category_regex(cat):
    return "|".join(f"(?:{r})" for r in TAXONOMY[cat].values())


def first_match(s, patterns):
    """Name of the first pattern (dict order) each string matches; null where none does."""
    out = pd.Series(pd.NA, index=s.index, dtype="str")
    for name, rx in reversed(list(patterns.items())):
        out = out.mask(s.str.contains(rx, case=False, regex=True), name)
    return out


def forest_area(s):
    """Hectares of forest a sentence names ('12.5 ha forest', 'forest land of 30 ha'), largest if several."""
    m = s.str.extractall(FOREST_HA, flags=2).astype("float64")
    return m.max(axis=1).groupby(level=0).max().reindex(s.index)


def free_text(remarks):
    """Remarks with the report templates stripped; null when fewer than MIN_FREE_WORDS words are left."""
    rest = remarks.str.replace(BOILERPLATE, " ", case=False, regex=True)
    return rest.where(rest.str.count(r"[A-Za-z]{3,}") >= MIN_FREE_WORDS)


def tag(text):
    """Free-text remarks (unique) -> one row per (text, category) with its shortest matching sentence, subtype,
    authority and forest hectares. Sentences keep their original case for the acronym patterns."""
    sent = text.str.split(SENTENCE, regex=True).explode().str.strip()
    sent = sent[sent.str.len() > 3]
    parts = []
    for cat in TAXONOMY:
        hit = sent[sent.str.contains(category_regex(cat), case=False, regex=True)]
        if hit.empty:
            continue
        parts.append(pd.DataFrame({"text_id": hit.index, "sentence": hit.to_numpy(), "category": cat}))
    m = pd.concat(parts, ignore_index=True)
    m["subtype"] = pd.concat([first_match(g["sentence"], TAXONOMY[c]) for c, g in m.groupby("category")]).sort_index()
    m["authority"] = first_match(m["sentence"], AUTHORITY)
    fe = m["category"].eq("forest_env")
    m["forest_area_ha"] = forest_area(m["sentence"]).where(fe)
    m["violation"] = fe & m["sentence"].str.contains(VIOLATION, case=False, regex=True)
    m["resolved"] = (m["sentence"].str.contains(DONE, case=False, regex=True)
                     & ~m["sentence"].str.contains(BLOCKED, case=False, regex=True))
    return m


def snippet(sentence, category):
    """The sentence cut to SNIPPET characters around its first keyword."""
    if len(sentence) <= SNIPPET:
        return sentence
    hit = re.search(category_regex(category), sentence, flags=re.IGNORECASE)
    start = max(0, (hit.start() if hit else 0) - 60)
    start = sentence.rfind(" ", 0, start) + 1 if start else 0
    return sentence[start:start + SNIPPET].strip()


def load_rows(source="typed_rows", silver=SILVER):
    """Accepted remark rows: project_key, period (quarter), remarks, source_doc_id, source_page, report."""
    if source == "typed_rows":
        t = pd.read_parquet(silver / "typed_rows.parquet",
                            columns=["project_key", "review_status", "report_period", "source_report_type",
                                     "remarks", "source_file", "page"])
        t = t[t["review_status"].eq("accepted")]
        return pd.DataFrame({"project_key": t["project_key"], "period": quarter(t["report_period"]),
                             "remarks": t["remarks"], "source_doc_id": t["source_file"], "source_page": t["page"],
                             "report": t["source_report_type"] + "|" + t["report_period"].astype("str")})
    o = pd.read_parquet(silver / "observations.parquet",
                        columns=["project_key", "period", "remarks", "source_doc_id", "source_page"])
    return o.assign(report=o["period"].astype("str"))


def mentions(rows):
    """Remark rows -> (quarters with free text per key, mention rows: key x report x category)."""
    rows = rows.assign(free=free_text(rows["remarks"].fillna("")))
    rows = rows[rows["free"].notna()]
    seen = rows[["project_key", "period"]].drop_duplicates()
    uniq = pd.Series(rows["free"].unique())
    tags = tag(uniq)
    tags["free"] = uniq.to_numpy()[tags["text_id"]]
    m = rows.merge(tags.drop(columns="text_id"), on="free")
    m = m.drop_duplicates(["project_key", "report", "category", "sentence"])
    return seen, m.drop(columns=["free", "remarks"])


def events(seen, m, master):
    """Mentions -> one row per (project_key, category, run of consecutive remark-observed quarters)."""
    seen = seen.sort_values(["project_key", "period"], ignore_index=True)
    seen["qn"] = seen.groupby("project_key").cumcount()
    last = seen.groupby("project_key")["qn"].max().rename("qn_last")
    q = m.merge(seen, on=["project_key", "period"]).sort_values(["project_key", "category", "period", "report"],
                                                               kind="mergesort", ignore_index=True)
    qq = q.drop_duplicates(["project_key", "category", "period"])
    step = qq.groupby(["project_key", "category"])["qn"].diff()
    qq = qq.assign(event_no=step.ne(1).groupby([qq["project_key"], qq["category"]]).cumsum().astype("int64"))
    q = q.merge(qq[["project_key", "category", "period", "event_no"]], on=["project_key", "category", "period"])
    q["_len"] = q["sentence"].str.len()
    key = ["project_key", "category", "event_no"]
    g = q.groupby(key)
    ev = g.agg(first_seen=("period", "min"), last_seen=("period", "max"), n_quarters=("period", "nunique"),
               n_mentions=("report", "nunique"), qn_end=("qn", "max"), forest_area_ha=("forest_area_ha", "max"),
               violation=("violation", "any"))
    at_end = q["period"].eq(g["period"].transform("max"))
    ev["resolved"] = q[at_end].groupby(key)["resolved"].all()
    ev["subtype"] = g["subtype"].agg(lambda s: s.mode().iloc[0])
    ev["authority"] = g["authority"].agg(lambda s: s.mode().iloc[0] if s.notna().any() else pd.NA)
    first = q.drop_duplicates(key).set_index(key)
    ev[["source_doc_id", "source_page"]] = first[["source_doc_id", "source_page"]]
    # shortest sentence of the event's subtype that still says something; very short ones only when nothing longer
    best = q[q["subtype"].eq(ev["subtype"].reindex(pd.MultiIndex.from_frame(q[key])).to_numpy())]
    best = best.assign(_short=best["_len"].lt(12)).sort_values(key + ["_short", "_len"], kind="mergesort")
    best = best.drop_duplicates(key).set_index(key)
    ev["evidence"] = pd.Series([snippet(s, c) for s, c in zip(best["sentence"], best.index.get_level_values("category"))],
                               index=best.index)
    ev = ev.reset_index().merge(last, on="project_key")
    ev = ev.merge(master[["project_key", "state", "sector", "completed_period"]], on="project_key", how="left")
    ev["remarks_last_seen"] = ev["project_key"].map(seen.groupby("project_key")["period"].max())
    recent = ev["qn_end"].ge(ev["qn_last"] - (OPEN_LAST_Q - 1))
    ev["status"] = np.where(recent & ~ev["resolved"] & ev["completed_period"].isna(), "open", "closed")
    ev["source_page"] = ev["source_page"].astype("Int64")
    return ev[EVENT_COLS].sort_values(["project_key", "category", "event_no"], ignore_index=True)


LINEAR_SECTORS = {"Roads & Highways", "Railways"}
# name keywords; a linear keyword wins over a non-linear one, the sector decides when neither is there
LINEAR_NAME = (r"pipe\s*lines?|superlines?|city\s+gas|gas\s+distribution|(?-i:\bCGD\b)|transmission|\btr\.?\s+system"
               r"|\bsys(?:tem)?\.?\s+associated|(?:system|grid|regional)\s+streng\w*|\bgrid\b|evacuation|\d\s*kv\b|\bckm\b"
               r"|(?-i:\bLILO\b)|\bhvdc\b|canal|optical\s+fib|(?-i:\bOFC\b)|bharat\s*net|highway|expressway|flyover"
               r"|rural\s+roads?|roads?\s+(?:and|&)\s+bridges?|road\s+connectivity"
               r"|(?:new|broad\s+gauge|3rd|4\s*th|third|fourth|tie)\s+(?:\w+\s+){0,2}lines?\b|doubling|tripling|quadrupling"
               r"|gauge\s+conversion|\(GC\)|rail(?:way)?\s+(?:line|link|connectivity)|metro|(?-i:\bRRTS\b)|corridor")
NON_LINEAR_NAME = (r"workshop|factory|coach|wagon|\bshed\b|depot|station\s+(?:re)?develop|building|hospital|campus"
                   r"|refinery|plant|terminal|airport|jetty|berth|\bport\b|\bdam\b|hydro|(?-i:\bHEP\b)")
OFC_NAME = r"optical\s+fib|(?-i:\bOFC\b)|bharat\s*net"
DEFENCE_NAME = r"defence|border\s+road|(?-i:\bBRO\b)|strategic|\barmy\b|military|naval"
SURVEY_NAME = r"\bsurvey|exploration|seismic|prospecting"
# project_category text of a scenario -> the ordinary projects it covers (encroachment, dereservation and the
# entity type are never known, so they do not narrow anything)
CATEGORY = {
    "": lambda p: True,
    "Any": lambda p: True,
    "All except Mining/Encroachment/Violation/Dereservation": lambda p: not p["mining"] and not p["violation"],
    "Except Encroachment/Violation/Mining": lambda p: not p["mining"] and not p["violation"],
    "All linear": lambda p: p["linear"],
    "All except linear project": lambda p: not p["linear"],
    "Non-Mining": lambda p: not p["mining"],
    "Mining": lambda p: p["mining"],
    "Encroachment/Dereservation/Mining": lambda p: p["mining"],
    "Mining/Encroachment/Dereservation/Violation": lambda p: p["mining"] or p["violation"],
    "Non-Govt entity except Encroachment/Dereservation/Mining": lambda p: not p["mining"],
    "Govt entity under OFC and GA categories": lambda p: p["ofc"],
    "Govt entity except Encroachment/Dereservation/Violation/Mining/OFC/GA":
        lambda p: not p["mining"] and not p["violation"] and not p["ofc"],
}
GATES = {"psc_required": "PSC", "rec_required": "REC", "fac_required": "FAC", "site_inspection_required": "site inspection"}
FC_COLS = ["project_key", "fc_shape", "fc_mining", "fc_violation", "fc_area_ha", "fc_area_known",
           "fc_expected_complexity", "fc_worst_complexity", "fc_min_authority_level", "fc_max_authority_level",
           "fc_likely_authority", "fc_gates", "fc_candidate_scenarios", "fc_mentioned", "fc_pending", "fc_evidence"]


def shape(sector, name):
    """'Linear' for roads, railway lines, pipelines, transmission lines, optical fibre, canals and metro corridors,
    else 'Non-Linear'. Roads are always linear ('... Port Road' names its end point); otherwise a linear name keyword
    wins, then a non-linear one, then the sector."""
    name = name.fillna("")
    lin = name.str.contains(LINEAR_NAME, case=False, regex=True) | sector.eq("Roads & Highways")
    non = name.str.contains(NON_LINEAR_NAME, case=False, regex=True)
    return pd.Series(np.where(lin | (~non & sector.isin(LINEAR_SECTORS)), "Linear", "Non-Linear"), index=name.index)


def mining(sector, name, linear):
    """Coal or mines in the sector, or a mine in the name of a project that is not a line (a railway to a mine
    is not a mining lease)."""
    named = name.fillna("").str.contains(r"\bmines?\b|\bmining\b", case=False, regex=True)
    return sector.fillna("").str.contains(r"coal|mine|mining", case=False, regex=True) | (named & ~linear)


def band(cond):
    """Area condition -> (low, high], hectares; None when it is not a plain band ('NA (<=100 trees...)',
    'Within 100 km')."""
    c = str(cond).strip()
    if c.lower() == "any":
        return (-np.inf, np.inf)
    m = re.fullmatch(r"(>|<=)\s*(\d+(?:\.\d+)?)(?:\s*&\s*(>|<=)\s*(\d+(?:\.\d+)?))?", c)
    if not m:
        return None
    lo, hi = -np.inf, np.inf
    for op, v in [(m[1], m[2]), (m[3], m[4])]:
        if op == ">":
            lo = float(v)
        elif op == "<=":
            hi = float(v)
    return lo, hi


def scenarios_for(scen, p):
    """Scenario rows a project profile can fall under (p: linear, mining, violation, ofc, defence, survey, area_ha)."""
    ok = []
    for r in scen.itertuples(index=False):
        sid, cat = r.scenario_id, "" if pd.isna(r.project_category) else r.project_category
        if "survey" in sid or cat == "Survey":
            fits = p["survey"]
        elif sid.startswith("exempt_def"):
            fits = p["defence"]
        elif sid.startswith("exempt_"):
            fits = False
        else:
            fits = CATEGORY[cat](p)
        shp = "Any" if pd.isna(r.shape) else r.shape
        fits = fits and shp in ("Any", "Linear" if p["linear"] else "Non-Linear")
        fits = fits and ("Yes" if p["violation"] else "No") in str(r.violation).split("/")
        b = band(r.area_ha_condition)
        if fits and b is not None and not np.isnan(p["area_ha"]):
            fits = b[0] < p["area_ha"] <= b[1]
        ok.append(fits)
    return scen[ok]


def fc_summary(match, p):
    """Expected (median) and worst complexity, authority levels, and the worst case's authority and gates."""
    if match.empty:
        return {}
    w = match.sort_values(["complexity_score", "authority_level"], ascending=False, kind="mergesort").iloc[0]
    gates = " + ".join(g for c, g in GATES.items() if w[c]) or "no PSC/REC/FAC/site inspection"
    area = f"{p['area_ha']:g} ha forest" if not np.isnan(p["area_ha"]) else "area unknown"
    head = ("linear" if p["linear"] else "non-linear") + (" mining" if p["mining"] else "")
    head += ", violation" if p["violation"] else ""
    return {"fc_expected_complexity": float(match["complexity_score"].median()),
            "fc_worst_complexity": int(w["complexity_score"]),
            "fc_min_authority_level": int(match["authority_level"].min()),
            "fc_max_authority_level": int(match["authority_level"].max()),
            "fc_likely_authority": w["approving_authority"], "fc_gates": gates,
            "fc_candidate_scenarios": ";".join(match["scenario_id"]),
            "fc_evidence": f"{head}, {area}: up to {w['approving_authority']} with {gates} (scenario {w['scenario_id']})"}


def forest_clearance(master, ev, scen):
    """One row per project_key: its Parivesh profile and the complexity of the scenarios it matches."""
    name, sector = master["project_name"], master["sector"]
    lin = shape(sector, name).eq("Linear")
    fe_ev = ev[ev["category"].eq("forest_env")]
    fe = fe_ev.groupby("project_key")
    d = pd.DataFrame({
        "project_key": master["project_key"], "linear": lin, "mining": mining(sector, name, lin),
        "violation": master["project_key"].map(fe["violation"].any()).fillna(False).astype(bool),
        "ofc": name.fillna("").str.contains(OFC_NAME, case=False, regex=True),
        "defence": sector.eq("Defence") | name.fillna("").str.contains(DEFENCE_NAME, case=False, regex=True),
        "survey": name.fillna("").str.contains(SURVEY_NAME, case=False, regex=True),
        "area_ha": master["project_key"].map(fe["forest_area_ha"].max()).astype("float64")})
    prof = ["linear", "mining", "violation", "ofc", "defence", "survey", "area_ha"]
    # ponytail: one scenario scan per distinct profile, a few dozen; vectorise if hectares become common
    keys = d[prof].drop_duplicates()
    rows = [dict(p, **fc_summary(scenarios_for(scen, p), p)) for p in keys.to_dict("records")]
    out = d.merge(pd.DataFrame(rows), on=prof, how="left")
    out["fc_shape"] = np.where(out["linear"], "Linear", "Non-Linear")
    out["fc_area_known"] = out["area_ha"].notna()
    out["fc_mentioned"] = out["project_key"].isin(fe_ev["project_key"])
    out["fc_pending"] = out["project_key"].isin(fe_ev.loc[fe_ev["status"].eq("open"), "project_key"])
    out = out.rename(columns={"mining": "fc_mining", "violation": "fc_violation", "area_ha": "fc_area_ha"})
    return out[FC_COLS]


def current_keys(obs, master):
    """The scored portfolio: keys in the latest report that are not completed at the latest period."""
    last = obs[obs["period"].eq(obs["period"].max())]
    return set(master.loc[master["in_latest_report"] & master["project_key"].isin(
        last.loc[~last["is_completed"], "project_key"]), "project_key"])


def main(out=GOLD, silver=SILVER):
    t0 = time.time()
    master = pd.read_parquet(silver / "project_master.parquet")
    obs = pd.read_parquet(silver / "observations.parquet", columns=["project_key", "period", "is_completed"])
    cur = current_keys(obs, master)
    seen, m = mentions(load_rows("typed_rows", silver))
    ev = events(seen, m, master)
    out.mkdir(parents=True, exist_ok=True)
    ev.to_parquet(out / "project_events.parquet", index=False)
    print(f"project_events: {len(ev)} events from {len(m)} mentions over {ev['project_key'].nunique()} projects, "
          f"{time.time() - t0:.1f}s")
    ev_cur = ev[ev["project_key"].isin(cur)]
    print(pd.concat({"all": pd.crosstab(ev["category"], ev["status"], margins=True),
                     f"current ({len(cur)})": pd.crosstab(ev_cur["category"], ev_cur["status"], margins=True)},
                    axis=1).fillna(0).astype("int64").to_string())
    with pd.option_context("display.width", 250, "display.max_colwidth", 120):
        print(ev.sample(min(10, len(ev)), random_state=0)[
            ["project_key", "category", "subtype", "first_seen", "last_seen", "n_mentions", "status", "authority",
             "evidence"]].to_string(index=False))

    fc = forest_clearance(master, ev, pd.read_csv(EXTERNAL / "parivesh_fc_scenarios.csv"))
    fc.to_parquet(out / "external_fc.parquet", index=False)
    fc_cur = fc[fc["project_key"].isin(cur)]
    print(f"external_fc: {len(fc)} projects, {int(fc['fc_area_known'].sum())} with forest hectares, "
          f"{int(fc['fc_violation'].sum())} with a violation mention; current portfolio "
          f"(mentioned {int(fc_cur['fc_mentioned'].sum())}, pending {int(fc_cur['fc_pending'].sum())}):")
    print(fc_cur.groupby(["fc_shape", "fc_mining", "fc_area_known", "fc_expected_complexity", "fc_worst_complexity",
                          "fc_likely_authority"]).size().rename("projects").to_string())
    return ev, fc


if __name__ == "__main__":
    main()
