"""
External factors (docs/IMPLEMENTATION_GUIDE_v2.md A.4, B 2.2 External, B 5.2): delay events from the report
remarks and the Parivesh forest-clearance path, per project.

Run from repo root after the silver build:  python -m pipeline.run external

Inputs   silver/typed_rows.parquet (every clean remark with its PRJ key), silver/observations.parquet,
         silver/project_master.parquet, raw/external/parivesh_fc_scenarios.csv,
         raw/external/land_acquisition_*.csv (stretch tables, Maharashtra so far) and raw/external/bhoomi_rashi/
         (raw Bhoomi Rashi state exports, parsed by pipeline/bhoomi_rashi.py)
Outputs  gold/project_events.parquet, gold/project_mentions.parquet, gold/external_fc.parquet,
         gold/external_land.parquet, gold/external_land_pairs.parquet, gold/external_composite.parquet

Remarks are free text only in 2014-2023 reports; later reports print templates ('start: 2025-04',
'Milestones achieved/total: 0/7'). Templates are stripped first, the rest is split into sentences and tagged
with TAXONOMY. A quarter counts as remark-observed for a project when one of its reports has free text left,
and an event is a run of consecutive remark-observed quarters that mention the category. It is open when its
last mention is in one of the project's last OPEN_LAST_Q remark-observed quarters, that quarter's mentions do not
all report it done ('EC received on ...'), and the project is not completed. Its quote is a mention from its last
quarter that agrees with that state.

Remarks come from typed_rows (every accepted clean report row), not observations (the quarter's last remark):
it finds every observations mention plus 6% more key-quarter-category mentions and 16% more events, and the
first mention keeps its own document and page. project_mentions keeps the per-quarter timeline (every
remark-observed quarter and the categories it mentions) so gold can tell what was open at any earlier t.

Forest clearance: each project gets a profile (linear or not, mining, violation, forest hectares from its
events) and is matched to the Parivesh scenarios it can fall under. The form (A-H) is never known, so every
form counts; with no hectares every area band counts. Survey rows apply to survey projects and defence
exemptions to defence projects only; the public-utility-in-LWE exemption (<= 0.1 ha of amenities) never.
fc_prior_* repeat the match from sector and name alone (no remark hectares or violation): the same at every t,
so gold can use them as features without reading later remarks.

Land acquisition: road projects are linked to the Bhoomi Rashi NH stretches of their own state (a Multi-State
project: of each state whose district its name mentions) and of the NH number in their name, on (NH, district)
first, then NH alone. A state with no land data (every state but Maharashtra so far) is 'unknown', never 'clear'.
The table is one snapshot: a stretch's parcels and complexity count every notification, so gold reads them at t
only for stretches whose last notification is by t (external_land_pairs keeps the dates).

Composite (external_composite): the teammate's score 0.5 x forest complexity/7 + 0.5 x land complexity/5 where land
is linked, forest/7 alone ('fc_only') where it is not. Informational, not a model feature.
"""
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.bhoomi_rashi import aggregate_stretches, parse_bhoomi_rashi  # noqa: E402
from pipeline.silver import ROOT, SILVER, quarter  # noqa: E402

GOLD = ROOT / "dataset" / "gold"          # not imported from pipeline.gold, which imports this module
EXTERNAL = ROOT / "dataset" / "raw" / "external"

# category -> subtype -> regex (case-insensitive; (?-i:...) marks the case-sensitive acronyms).
# The first subtype that matches names the mention.
TAXONOMY = {
    "land": {
        "acquisition": r"\bland\s*(?:acq|aq|acu)\w*|\b(?:acq|aq)\w*sition\s+of\s+(?:\w+\s+){0,2}land|(?-i:\bLA\b)",
        "notification": (r"\b3\s*\(?[ADG]\)?\s*(?:notification|notified|gazette)"
                         r"|notifi\w*\s+(?:u/s|under\s+sec\w*)\s*3\s*\(?[ADG]\b|(?-i:\bCBA\b)"),
        "compensation": r"\bcompensation\b|\bawards?\s+(?:for|of)\s+land",
        "possession": (r"\bpossession\b|(?:handing|hand|handed)\s+over\s+of\s+(?:\w+\s+){0,2}land"
                       r"|(?:non[\s-]*availability|allot\w*|transfer)\s+of\s+(?:\w+\s+){0,2}land"
                       r"|land\s+(?:issue|problem|dispute|hurdle|record"
                       r"|not\s+(?:yet\s+)?(?:available|acquired|handed))"),
        "encroachment": r"encroach\w*",
        "rr": r"(?-i:\bR\s*&\s*R\b)|rehabilit\w*\s+(?:&|and)\s+resettle\w*|\bresettle\w*|(?-i:\bPA[FP]s?\b)",
        "row": r"(?-i:\bRO[Ww]\b)|\bright\s+of\s+way\b",
    },
    "forest_env": {
        "forest_clearance": (r"(?<!non-)(?<!non )\bforest\w*|afforest\w*|(?-i:\bFC\b)"
                             r"|stage[\s-]*(?:I{1,2}|1|2)\b\s*(?:forest\s+)?(?:clearance|FC)"),
        "wildlife": r"wild\s*life|sanctuary|national\s+park|tiger\s+reserve|eco[\s-]*sensitive|elephant\s+corridor",
        "environment_clearance": (r"environment\w*\s+(?:clearance|approval|permission)|(?-i:\bEC\b)"
                                  r"|consent\s+to\s+(?:establish|operate)|pollution\s+control"),
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
        "case": (r"(?:court|legal)\s+case|case\s+(?:filed|pending|in\s+(?:the\s+)?(?:hon\w*\s+)?(?:court|high))"
                 r"|filed\s+(?:a\s+)?case"),
        "dispute": r"legal\s+(?:dispute|issue|hurdle|matter)|litigat\w*|disput\w*",
    },
    "contractor": {
        "termination": r"terminat\w*|foreclos\w*|rescind\w*",
        "retender": r"\bre[\s-]*tender\w*|\bre[\s-]*award\w*|\bre[\s-]*bid\w*",
        "insolvency": r"insolven\w*|(?-i:\bNCLT\b)|(?-i:\bCIRP\b)|liquidat\w*|bankrupt\w*",
        "performance": (r"contractor.{0,40}\b(?:slow|poor|delay|fail|not|non|default|abandon|stopp|left|lack|inadequate"
                        r"|financial)|\b(?:slow|poor|delay|fail|non|default|inadequate|lack)\w*.{0,40}\bcontractors?\b"
                        r"|(?:poor|inadequate|lack\s+of|non)[\s-]*(?:mobili[sz]ation|deployment)\s+of\s+(?:resources"
                        r"|manpower)"),
    },
    "funding": {
        "fund_constraint": (r"\bfunds?\s+(?:constraint|crunch|shortage|problem|issue"
                            r"|not\s+(?:yet\s+)?(?:released|available))"
                            r"|(?:paucity|shortage|non[\s-]*availability|availability|lack|want|inadequa\w*"
                            r"|constraints?|non[\s-]*release|release)\s+of\s+(?:\w+\s+)?funds?\b"
                            r"|financial\s+(?:constraint|crunch|problem|difficult)\w*"),
        "budget": r"budget\w*\s+(?:constraint|allocation|cut|shortage)\w*|(?:inadequate|insufficient|low)\s+budget",
        "financial_closure": r"financial\s+closure",
        "payment": (r"payments?\s+(?:pending|due|delay\w*|not\s+released)"
                    r"|(?:pending|delay\w*\s+in|non[\s-]*)\s*payments?"),
    },
    "utility_shifting": {
        "utility": (r"utilit\w*\s+shift\w*|shift\w*\s+(?:of\s+)?(?:\w+\s+){0,2}utilit\w*"
                    r"|utilit\w*\s+(?:relocation|diversion)"),
        "lines": (r"(?:shifting|diversion|relocation|crossing)\s+of\s+(?:\w+\s+){0,3}(?:lines?|pipe\s*lines?|cables?"
                  r"|poles?|towers?|mains)\b|(?:electric\w*|power|HT|LT|overhead|transmission|EHV)\s+lines?\s+(?:shift"
                  r"|cross|divers)\w*|pipe\s*lines?\s+crossing"),
    },
    "inter_agency": {
        "railway_approval": (r"\b(?:railways?|rly\.?)\s+(?:board\s+)?(?:approval|clearance|permission|nod|NOC)"
                             r"|(?:approval|clearance|permission|NOC)\s+(?:\w+\s+){0,3}(?:from|by|of)\s+(?:the\s+)?"
                             r"(?:railways?|rly)\b"
                             r"|(?-i:\bR[OU]Bs?\b).{0,40}(?:approv|GAD|railway|rly|clearance|permission)"),
        "gad": r"(?-i:\bGADs?\b)|general\s+arrangement\s+drawing",
        "noc": r"(?-i:\bNOCs?\b)|no[\s-]+objection",
        "state_approval": (r"(?:state|central)\s+gov\w*\.?\s+(?:approval|clearance|permission|sanction|nod|consent)"
                           r"|(?:approval|clearance|permission|nod|consent)\s+(?:\w+\s+){0,3}(?:from|of|by)\s+"
                           r"(?:the\s+)?(?:state|concerned)\s+gov"),
        "other_approval": (r"statutory\s+(?:clearance|approval)s?|local\s+(?:body|authority)\s+(?:approval|permission"
                           r"|clearance)s?|defence\s+(?:clearance|approval|NOC|permission)"
                           r"|(?:clearance|approval|permission)s?\s+(?:\w+\s+){0,3}awaited"),
    },
    "law_order": {
        "law_order": r"law\s*(?:&|and)\s*order|security\s+(?:problem|issue|concern|situation)|\bunrest\b|curfew",
        "lwe": r"naxal\w*|maoist\w*|(?-i:\bLWE\b)|left\s+wing\s+extrem\w*|insurgen\w*|militan\w*|terror\w*",
        "agitation": (r"agitation\w*|agitat(?:ed|ing)\b|protest\w*|\bbandh\w*|blockade|dharna|gherao\w*"
                      r"|(?:labou?r|workers?|truckers?|transport\w*|general)\s+strikes?"),
        "local_resistance": (r"(?:local|public|villagers?)\s+(?:\w+\s+)?(?:resistance|opposition|objection|obstruct\w*"
                             r"|hindrance|resist\w*)|obstruct\w*\s+(?:by|from)\s+(?:the\s+)?(?:local|villager)"
                             r"|villagers?\s+(?:obstruct|object|resist|oppos|stop)\w*"),
    },
    "weather": {
        "monsoon": r"monsoon\w*|\brain(?!\s*water)\w*|cloud\s*burst",
        "flood": (r"flood(?!\s+protection)\w*|landslide\w*|land\s+slide\w*|cyclon\w*|earthquake|snow\w*|inclement"
                  r"|extreme\s+weather|heat\s*wave"),
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
               r"|implementation mode:[^;]*|ppp_mode:[^;]*"
               r"|anticipated doc (?:reported )?in the previous quarter:\s*[\d-]+"
               r"|list dated as on[^.;]*|status:\s*completed|also in this report's list of completed projects"
               r"|no project card printed in this report[^;]*"
               r"|listed under 'projects completed/dropped during the month'[^;]*"
               r"|status not printed per project|physical progress for the month of \w+ is [\d.]+\s*%"
               r"|this project was approved on \w+ \d+ with capital investment of rs\.? [\d.,]+ crores?"
               r"(?: with schedule completion date \w+ \d+)?|under progress(?: \(p\))?|work in progress")
SENTENCE = r"\s*(?:[;•\n\r]|\.\s+(?=[A-Z(])|\s-\s*(?=[A-Z])|(?:^|(?<=\s))\(?(?:[ivx]{1,4}|\d{1,2})\)\s)\s*"
# forest hectares: '12.5 ha of reserved forest', 'forest land of 30 ha', 'Forest land-71.72 hect', 'Forest - 3.101)',
# 'FC (323.49 Ha)'; not 'non-forest land of 648 ha', '3.2 hect and forest land ...' or '1426 Ha including forest and
# nonforest land'
_NOT_NON = r"(?<!non-)(?<!non )(?<!non)"
FOREST_HA = (r"(\d+(?:\.\d+)?)\s*(?:ha\b|hect\w*)\.?\s*(?:of\s+)?(?:(?!(?:and|or|including|non)\b)\w+\s+){0,2}"
             + _NOT_NON + r"forest(?!\s*(?:and|&|or|/)\s*non)"
             r"|" + _NOT_NON + r"forest\s*(?:land|area)?\s*(?:(?:of|\(|measuring|admeasuring)?\s*(\d+(?:\.\d+)?)\s*"
             r"(?:ha\b|hect)|[-:]\s*(\d+(?:\.\d+)?)(?:\s*(?:ha\b|hect)|(?=\s*[)\];,]|\s*$)))"
             r"|(?-i:\bFC\b)\s*\(\s*(\d+(?:\.\d+)?)\s*(?:ha\b|hect)")
VIOLATION = (r"violat\w*|post[\s-]*facto|without\s+(?:prior\s+|obtaining\s+|the\s+)?(?:forest\s+clearance|FC|EC"
             r"|environment\w*\s+clearance|clearance)")
# a mention that reports the matter done ('EC received on 31.07.23') and names no hold-up is resolved
DONE = (r"\b(?:obtained|received|granted|accorded|issued|completed|achieved|approved|done|removed|resolved|vacated"
        r"|settled|cleared|finali[sz]ed|disbursed|handed\s+over|in\s+(?:physical\s+)?possession|available)\b")
BLOCKED = (r"\b(?:await\w*|pending|delay\w*|yet\s+to|not|non|no|hold|held\s+up|stopp\w*|stalled|hamper\w*|affect\w*"
           r"|problems?|issues?|constraints?|balance|slow|obstruct\w*|disput\w*|ban|banned|under\s+process"
           r"|in\s+progress|expected|anticipated|likely|shortly)\b"
           # a step, not the clearance: a recommendation, proposal or ToR issued, or something sent 'for ... approval'
           r"|\bissued\s+(?:\S+\s+){0,2}(?:recommendation|proposal|ToR|terms\s+of\s+reference)\b"
           r"|\b(?:recommendation|proposal|ToR|terms\s+of\s+reference)s?\s+(?:\S+\s+){0,3}issued"
           r"|\bfor\s+(?:(?!and\b)[a-z&-]+\s+){0,3}approval(?!\s+(?:has|have|was|were)\s+been)")
MIN_FREE_WORDS = 3        # a report has free text when this many 3+ letter words survive the template strip
OPEN_LAST_Q = 2           # an event is open when seen in one of the project's last 2 remark-observed quarters
SNIPPET = 200
EVENT_COLS = ["project_key", "category", "event_no", "first_seen", "last_seen", "n_quarters", "n_mentions", "status",
              "resolved", "subtype", "authority", "forest_area_ha", "violation", "evidence", "source_doc_id",
              "source_page", "state", "sector", "remarks_last_seen"]


def category_regex(cat):
    return "|".join(f"(?:{r})" for r in TAXONOMY[cat].values())


def first_match(s, patterns):
    """Name of the first pattern (dict order) each string matches; null where none does."""
    out = pd.Series(pd.NA, index=s.index, dtype="str")
    for name, rx in reversed(list(patterns.items())):
        out = out.mask(s.str.contains(rx, case=False, regex=True), name)
    return out


def forest_area(s):
    """Hectares of forest a sentence names ('12.5 ha forest', 'forest land of 30 ha'), largest if several: a total
    and its parts ('out of total 336.58 Ha of Forest Land ... balance of 59.53 Ha of Forest land')."""
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


def quarter_mentions(seen, m):
    """One row per (key, remark-observed quarter, category mentioned); category is null for a quarter whose free
    text mentions none. resolved: every mention of the category in that quarter reports it done."""
    qm = m.groupby(["project_key", "period", "category"], as_index=False)["resolved"].all()
    out = seen.merge(qm, on=["project_key", "period"], how="left")
    out["resolved"] = out["resolved"].astype("boolean")
    return out.sort_values(["project_key", "period", "category"], kind="mergesort", ignore_index=True)


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
    # quote a mention of the event's last quarter that agrees with its state (unresolved for an open event, resolved
    # for one reported done): the shortest that still says something, very short ones only when nothing longer
    end = q[at_end]
    best = end[end["resolved"].eq(ev["resolved"].reindex(pd.MultiIndex.from_frame(end[key])).to_numpy())]
    best = best.assign(_short=best["_len"].lt(12)).sort_values(key + ["_short", "_len"], kind="mergesort")
    best = best.drop_duplicates(key).set_index(key)
    cats = best.index.get_level_values("category")
    ev["evidence"] = pd.Series([snippet(s, c) for s, c in zip(best["sentence"], cats)], index=best.index)
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
               r"|\bsys(?:tem)?\.?\s+associated|(?:system|grid|regional)\s+streng\w*|\bgrid\b|evacuation|\d\s*kv\b"
               r"|\bckm\b"
               r"|(?-i:\bLILO\b)|\bhvdc\b|canal|optical\s+fib|(?-i:\bOFC\b)|bharat\s*net|highway|expressway|flyover"
               r"|rural\s+roads?|roads?\s+(?:and|&)\s+bridges?|road\s+connectivity"
               r"|(?:new|broad\s+gauge|3rd|4\s*th|third|fourth|tie)\s+(?:\w+\s+){0,2}lines?\b"
               r"|doubling|tripling|quadrupling"
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
GATES = {"psc_required": "PSC", "rec_required": "REC", "fac_required": "FAC",
         "site_inspection_required": "site inspection"}
FC_COLS = ["project_key", "fc_shape", "fc_mining", "fc_violation", "fc_area_ha", "fc_area_known",
           "fc_expected_complexity", "fc_worst_complexity", "fc_min_authority_level", "fc_max_authority_level",
           "fc_likely_authority", "fc_gates", "fc_candidate_scenarios", "fc_mentioned", "fc_pending", "fc_evidence"]
FC_PRIOR = ["fc_expected_complexity", "fc_worst_complexity", "fc_max_authority_level"]


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
            "fc_evidence": f"{head}, {area}: up to {w['approving_authority']} with {gates} "
                           f"(scenario {w['scenario_id']})"}


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


# NH number in a project name: 'NH-161A', 'NH 161', 'NH161', 'National Highway 161', 'NH No. 161', 'NH-17 & 48';
# 'OLD NH-6' is dropped and a 'NEW NH-148' replaces the rest. A number followed by '.5' or 'km' is a chainage.
# An end point is not the road: 'Junction of NH-66', 'Jn. with NH 30' and 'from NH-565 Junction' are dropped.
_NH_NO = r"(\d{1,3}(?:-?[A-Z]{1,2}|\s[A-Z])?)\b(?![.,]\d)"   # '161A', '548-DD', '548 D'; not 'NH-66 CH-227'
NH_TEXT = (r"(?:\b(OLD|NEW|ERSTWHILE|JUNCTION\s+(?:OF|WITH)|JN\.?\s*(?:OF|WITH)?)\s*)?"
           r"(?:\bNH|\bN\.H\.|\bNATIONAL\s+HIGHWAY)\s*(?:NO\.?|NUMBER)?\s*[-:.]?\s*"
           + _NH_NO + r"(?:\s*(?:&|AND|/)\s*" + _NH_NO + r"(?!\s*K\.?M))?(\s*(?:JUNCTION|JN)\b)?")
NE_TEXT = r"\b(NE)[-\s]?(\d{1,2})\b"   # national expressways, 'NE-4'
LA_FLAG = 3               # a linked project is flagged at acquisition complexity >= 3 of 5, else clear
DISTRICT_ALIAS = {"AURANGABAD": ["CHHATRAPATI SAMBHAJINAGAR", "SAMBHAJINAGAR"], "AHMEDNAGAR": ["AHILYANAGAR"],
                  "RAIGAD": ["RAIGARH"], "GONDIA": ["GONDIYA"], "BULDHANA": ["BULDANA"], "NASHIK": ["NASIK"]}
LA_COLS = ["project_key", "la_linked", "la_match_method", "la_state", "la_nh", "la_districts", "la_stretches",
           "la_parcels", "la_area_ha", "la_complexity_max", "la_notif_span_days_max", "la_first_notif", "la_last_notif",
           "la_evidence"]
LA_PAIR_COLS = ["stretch_id", "num_parcels", "acquisition_complexity_score", "first_notif_date", "last_notif_date"]


def nh_id(s):
    """LA highway names -> NH id: '161 (New)' -> '161', '160 Ext.' -> '160', 'NH53' -> '53', '353 C' -> '353C';
    null when there is no number ('Greenfield Expressway', 'No Yet to be Assigned')."""
    s = s.str.upper().str.replace(r"\(NEW\)|\bNEW\b|\bEXT\b\.?|^NH", "", regex=True)
    s = s.str.replace(r"[\s.\-]", "", regex=True)
    return s.where(s.str.fullmatch(r"(?:NE)?\d{1,3}[A-Z]{0,3}|NE[IVX]+")).astype("str")


def joined(v):
    return ";".join(sorted(set(v)))


def nh_from_text(s):
    """NH ids named in each text (Series index -> sorted ;-joined ids, null when none)."""
    up = s.fillna("").str.upper()
    m, ne = up.str.extractall(NH_TEXT), up.str.extractall(NE_TEXT)
    m[0] = m[0].mask(m[0].str.startswith("J", na=False) | m[3].notna(), "JUNCTION")
    cols = ["tag", "nh"]
    ids = pd.concat([m[[0, 1]].set_axis(cols, axis=1), m[[0, 2]].set_axis(cols, axis=1),
                     pd.DataFrame({"tag": pd.NA, "nh": ne[0] + ne[1]}, index=ne.index)])
    ids = ids[ids["nh"].notna()].reset_index(level=1, drop=True)
    new = ids["tag"].eq("NEW").groupby(level=0).transform("any")
    ids = ids[(ids["tag"].eq("NEW") | ~new) & ~ids["tag"].isin(["OLD", "ERSTWHILE", "JUNCTION"])]
    ids = ids["nh"].str.replace(r"[\s-]", "", regex=True).str.lstrip("0")
    return ids.groupby(level=0).agg(joined).reindex(s.index)


def state_key(s):
    """State names -> comparable keys: 'Jammu & Kashmir' and 'JAMMU AND KASHMIR' both -> 'JAMMU AND KASHMIR'."""
    return s.str.upper().str.replace("&", " AND ").str.replace(r"[^A-Z]+", " ", regex=True).str.strip()


def load_land(external=EXTERNAL):
    """Every land source as one stretch table (the land_acquisition_maharashtra.csv schema): the stretch CSVs
    raw/external/land_acquisition_*.csv, then the raw Bhoomi Rashi exports in raw/external/bhoomi_rashi/ (.xls,
    .html) parsed and aggregated. A (state, highway, chainage) stretch found in more than one keeps its first copy."""
    text = {"state": "str", "highway_name": "str", "chainage_raw": "str"}
    parts = [pd.read_csv(p, dtype=text) for p in sorted(external.glob("land_acquisition_*.csv"))]
    raw = sorted(p for p in (external / "bhoomi_rashi").glob("*") if p.suffix.lower() in (".xls", ".html", ".htm"))
    parts += [aggregate_stretches(parse_bhoomi_rashi(p)) for p in raw]
    la = pd.concat(parts, ignore_index=True)
    return la[~la.assign(k=state_key(la["state"])).duplicated(["k", "highway_name", "chainage_raw"])].reset_index(
        drop=True)


def stretches(la):
    """LA rows -> one row per stretch with its state key, NH id, parsed dates and upper-case district list."""
    d = la.assign(stretch_id=np.arange(len(la)), state=state_key(la["state"]), nh=nh_id(la["highway_name"]),
                  districts=la["districts_touched"].str.upper().str.split("|"),
                  first_notif_date=pd.to_datetime(la["first_notif_date"]),
                  last_notif_date=pd.to_datetime(la["last_notif_date"]))
    return d[d["nh"].notna()].reset_index(drop=True)


def aggregate(rows, by):
    """Stretch rows (a stretch may repeat, e.g. once per district) -> per group: stretches, parcels, area,
    max complexity, max notification span, first and last notification, districts."""
    rows = rows.drop_duplicates(by + ["stretch_id"])
    g = rows.groupby(by)
    return g.agg(stretches=("stretch_id", "nunique"), parcels=("num_parcels", "sum"), area_ha=("total_area_ha", "sum"),
                 complexity_max=("acquisition_complexity_score", "max"), notif_span_days_max=("notif_span_days", "max"),
                 first_notif=("first_notif_date", "min"), last_notif=("last_notif_date", "max"),
                 districts=("districts", lambda v: ";".join(sorted({x for ds in v for x in ds})))).reset_index()


def land_tables(st):
    """Per NH id and per (NH id, district)."""
    return aggregate(st, ["nh"]), aggregate(st.assign(district=st["districts"]).explode("district"), ["nh", "district"])


def districts_in(names, st):
    """Land-table districts (and their alias names) each project name mentions, as (index, state, district) rows."""
    names = names.fillna("").str.upper()
    out = []
    for state, dist in sorted({(s, x) for s, ds in zip(st["state"], st["districts"]) for x in ds}):
        words = [w.strip() for w in re.split(r"[()]", dist) if w.strip()] + DISTRICT_ALIAS.get(dist, [])
        hit = names.str.contains(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b", regex=True)
        out.append(pd.DataFrame({"idx": names.index[hit], "state": state, "district": dist}))
    return pd.concat(out, ignore_index=True)


def link_land(master, st):
    """Road projects -> the LA stretches of their state and of the NH they name: (NH, district) in the name first,
    then the NH alone. A project's state is its own, or for a Multi-State project each land-table state whose
    district its name mentions; a state with no stretches leaves it unknown. Returns one row per project_key and the
    (project_key, nh, stretch_id, la_match_method) pairs. master has a RangeIndex."""
    road = master["sector"].eq("Roads & Highways")
    dist = districts_in(master["project_name"], st)
    # ponytail: a district name shared by two states (Aurangabad: Maharashtra and Bihar) makes a Multi-State road a
    # candidate in both; it links only where its NH is in that state's table too. Needs a location field to do better.
    own = pd.DataFrame({"idx": master.index, "state": state_key(master["state"].fillna(""))})
    multi = dist.loc[master["state"].eq("Multi-State").to_numpy()[dist["idx"]], ["idx", "state"]]
    at = pd.concat([own[own["state"].isin(set(st["state"]))], multi]).drop_duplicates()
    has_land = master.index.isin(at["idx"])
    nh = nh_from_text(master["project_name"].fillna("") + " " + master["codes_seen"].fillna(""))
    at = at[road.to_numpy()[at["idx"]] & nh.notna().to_numpy()[at["idx"]]]
    cand = at.assign(project_key=master["project_key"].to_numpy()[at["idx"]],
                     nh=nh.to_numpy()[at["idx"]]).drop(columns="idx")
    cand = cand.assign(nh=cand["nh"].str.split(";")).explode("nh")
    named = dist.assign(project_key=master["project_key"].to_numpy()[dist["idx"]])[["project_key", "state",
                                                                                    "district"]]
    ex = st.explode("districts").rename(columns={"districts": "district"})[["state", "nh", "district", "stretch_id"]]
    by_d = cand.merge(named, on=["project_key", "state"]).merge(ex, on=["state", "nh", "district"]).assign(
        la_match_method="nh_district")
    rest = cand[~cand["project_key"].isin(by_d["project_key"])]
    by_n = rest.merge(st[["state", "nh", "stretch_id"]], on=["state", "nh"]).assign(la_match_method="nh_only")
    pairs = pd.concat([by_d, by_n], ignore_index=True)[["project_key", "nh", "stretch_id", "la_match_method"]]
    agg = aggregate(pairs.merge(st.drop(columns="nh"), on="stretch_id"), ["project_key"])
    pg = pairs.groupby("project_key")
    agg["la_nh"] = agg["project_key"].map(pg["nh"].agg(joined)).astype("str")
    agg["la_match_method"] = agg["project_key"].map(pg["la_match_method"].first())
    out = master[["project_key"]].merge(agg, on="project_key", how="left")
    out["la_linked"] = out["stretches"].notna()
    reason = np.select([~road, ~has_land, nh.isna()], ["not_road", "no_land_data_for_state", "no_nh_in_name"],
                       "nh_not_in_table")
    out["la_match_method"] = out["la_match_method"].fillna(pd.Series(reason, index=out.index))
    flag = np.where(out["complexity_max"] >= LA_FLAG, "flagged", "clear")
    out["la_state"] = np.where(out["la_linked"], flag, "unknown")
    out = out.rename(columns={c: f"la_{c}" for c in ["stretches", "parcels", "area_ha", "complexity_max",
                                                    "notif_span_days_max", "first_notif", "last_notif", "districts"]})
    for c in ["la_stretches", "la_parcels", "la_complexity_max", "la_notif_span_days_max"]:
        out[c] = out[c].astype("Int64")
    where = out["project_key"].map(by_d.groupby("project_key")["district"].agg(joined)).astype("str")
    where = (" (" + where.str.title().str.replace(";", ", ") + ")").fillna("")
    years = ((out["la_last_notif"] - out["la_first_notif"]).dt.days / 365.25).round(1).astype("str")
    parcels = out["la_parcels"].map(lambda v: f"{int(v):,}", na_action="ignore")
    out["la_evidence"] = ("NH-" + out["la_nh"].str.replace(";", ", NH-") + where + ": " + parcels + " parcels over "
                          + years + " years of notifications, complexity " + out["la_complexity_max"].astype("str")
                          + "/5").where(out["la_linked"])
    return out[LA_COLS], pairs


COMPOSITE_COLS = ["project_key", "fc_component", "la_component", "external_factor_score", "coverage",
                  "ext_score_evidence"]


def external_composite(fc, land):
    """Per project: the guide's composite external-factor score (docs/EXTERNAL_FACTORS_GUIDE.md section 4, the
    mock v0 formula). fc_component = expected Parivesh complexity / 7 (the rulebook applies nationwide);
    la_component = linked land complexity / 5, null when no land data is linked. The score is 0.5 fc + 0.5 la when
    both are known (coverage 'fc+la'), else fc_component alone ('fc_only'): unknown land never counts as 0.
    Informational only (risk profile and summary), NOT a model feature: its inputs already are features
    (fc_prior_*, la_*_by_t), so adding it would count them twice."""
    d = fc[["project_key", "fc_expected_complexity", "fc_area_ha", "fc_violation"]].merge(
        land[["project_key", "la_linked", "la_complexity_max", "la_nh"]], on="project_key", how="left")
    both = d["la_linked"].fillna(False).astype(bool)
    d["fc_component"] = d["fc_expected_complexity"] / 7
    d["la_component"] = (d["la_complexity_max"].astype("float64") / 5).where(both)
    d["external_factor_score"] = (0.5 * d["fc_component"] + 0.5 * d["la_component"]).where(both, d["fc_component"])
    d["coverage"] = np.where(both, "fc+la", "fc_only")
    area = d["fc_area_ha"].map(lambda v: f"{v:g} ha", na_action="ignore").fillna("area unknown")
    forest = ("forest " + d["fc_expected_complexity"].map(lambda v: f"{v:g}", na_action="ignore").fillna("?")
              + "/7 (rulebook, " + area + np.where(d["fc_violation"].fillna(False), ", violation", "") + ")")
    land_part = (" + land " + d["la_complexity_max"].astype("str") + "/5 (NH-" + d["la_nh"].str.replace(";", ", NH-")
                 + ", Bhoomi Rashi)")
    d["ext_score_evidence"] = forest + land_part.where(both, "; land unknown")
    return d[COMPOSITE_COLS]


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
    quarter_mentions(seen, m).to_parquet(out / "project_mentions.parquet", index=False)
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

    scen = pd.read_csv(EXTERNAL / "parivesh_fc_scenarios.csv")
    fc = forest_clearance(master, ev, scen)
    # the prior uses sector and name only (no remark hectares or violations), so it is the same at every t
    prior = forest_clearance(master, ev.iloc[:0], scen)[["project_key", *FC_PRIOR]]
    fc = fc.merge(prior.rename(columns={c: c.replace("fc_", "fc_prior_") for c in FC_PRIOR}), on="project_key")
    fc.to_parquet(out / "external_fc.parquet", index=False)
    fc_cur = fc[fc["project_key"].isin(cur)]
    print(f"external_fc: {len(fc)} projects, {int(fc['fc_area_known'].sum())} with forest hectares, "
          f"{int(fc['fc_violation'].sum())} with a violation mention; current portfolio "
          f"(mentioned {int(fc_cur['fc_mentioned'].sum())}, pending {int(fc_cur['fc_pending'].sum())}):")
    print(fc_cur.groupby(["fc_shape", "fc_mining", "fc_area_known", "fc_expected_complexity", "fc_worst_complexity",
                          "fc_likely_authority"]).size().rename("projects").to_string())

    st = stretches(load_land())
    by_nh, by_nh_district = land_tables(st)
    land, pairs = link_land(master, st)
    land.to_parquet(out / "external_land.parquet", index=False)
    pairs = pairs.drop_duplicates(["project_key", "stretch_id"]).merge(st[LA_PAIR_COLS], on="stretch_id")
    pairs.sort_values(["project_key", "stretch_id"], ignore_index=True).to_parquet(
        out / "external_land_pairs.parquet", index=False)
    lc = land[land["project_key"].isin(cur)]
    print(f"external_land: {len(st)} stretches in {st['state'].nunique()} state(s) "
          f"({', '.join(sorted(st['state'].unique()))}) on {len(by_nh)} NH ids ({len(by_nh_district)} NH x district); "
          f"{int(land['la_linked'].sum())} projects linked, {int(lc['la_linked'].sum())} of {len(lc)} current ones")
    print(pd.crosstab(lc["la_match_method"], lc["la_state"], margins=True).to_string())
    with pd.option_context("display.width", 250, "display.max_colwidth", 120):
        show = lc[lc["la_linked"]].merge(master[["project_key", "project_name"]], on="project_key")
        show["project_name"] = show["project_name"].str[:70]
        print(show.sample(min(10, len(show)), random_state=0)[
            ["project_key", "la_match_method", "la_state", "project_name", "la_evidence"]].to_string(index=False))

    comp = external_composite(fc, land)
    comp.to_parquet(out / "external_composite.parquet", index=False)
    cc = comp[comp["project_key"].isin(cur)]
    print("external_composite: current portfolio by coverage (score = 0.5 fc/7 + 0.5 la/5, fc/7 alone without land):")
    print(cc.groupby("coverage")["external_factor_score"].describe().round(3).to_string())
    return ev, fc, land


if __name__ == "__main__":
    main()
