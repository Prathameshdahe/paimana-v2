"""
External factors (docs/IMPLEMENTATION_GUIDE_v2.md A.4, B 2.2 External, B 5.2): delay events from the report
remarks and the Parivesh forest-clearance path, per project.

Run from repo root after the silver build:  python -m pipeline.run external

Inputs   silver/typed_rows.parquet (every clean remark with its PRJ key), silver/observations.parquet,
         silver/project_master.parquet, raw/external/parivesh_fc_scenarios.csv,
         raw/external/land_acquisition_*.csv (Bhoomi Rashi stretch tables: Maharashtra, and the other 28 states with
         data in land_acquisition_india.csv) and raw/external/bhoomi_rashi/ (raw Bhoomi Rashi state exports, parsed by
         pipeline/bhoomi_rashi.py), raw/external/parivesh_fc_proposals_linked.csv, parivesh_fc_timelines_remarks.csv
         and fc_project_links_reviewed.csv (PARIVESH proposals, pipeline/parivesh.py)
Outputs  gold/project_events.parquet, gold/project_mentions.parquet, gold/remark_status.parquet,
         gold/external_fc.parquet, gold/external_land.parquet, gold/external_land_links.parquet (its stretches),
         gold/external_land_pairs.parquet (the model's land input, see LA_MODEL_TABLE), gold/external_composite.parquet,
         gold/fc_proposal_status.parquet and gold/external_fc_portal.parquet (PARIVESH proposals)

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

Remark facts (quarter_facts): every sentence is also read for a forest-clearance stage (FC_STAGES: seven levels from
applied to Stage-II, plus FC awaited, rejected / in appeal and not applicable), the share of land acquired ('91.58 %
land acquisition', 'X ha out of Y ha', 'acquired X ha, balance Y ha'), the furthest land step it mentions
(notification to possession; a mention, not proof the step is done) and Parivesh proposal numbers
(FP/<state>/<category>/<n>/<year>). project_mentions carries the quarter's values on each of its rows, and
remark_status the latest value per project with the quarter it is as of: free text ends in 2023-Q2, so these are
evidence for the risk profile, not model features (they add no backtest lift).

Forest clearance: each project gets a profile (linear or not, mining, violation, forest hectares from its
events) and is matched to the Parivesh scenarios it can fall under. The form (A-H) is never known, so every
form counts; with no hectares every area band counts. Survey rows apply to survey projects and defence
exemptions to defence projects only; the public-utility-in-LWE exemption (<= 0.1 ha of amenities) never.
fc_prior_* repeat the match from sector and name alone (no remark hectares or violation): the same at every t,
so gold can use them as features without reading later remarks.

PARIVESH (pipeline/parivesh.py): proposal numbers named in the remarks are looked up in the saved PARIVESH 1.0 list
(or its timeline pages) and set the project's forest hectares and pending flag; hand-reviewed name matches add
proposals to external_fc_portal (stage at asof, months in it, open on the portal while the report is silent).

Land acquisition: road projects are linked to the Bhoomi Rashi NH stretches of their own state (a Multi-State
project: of each state whose district its name mentions) and of the NH number in their name (not one it names only as
a junction): stretches at the km range in the name first, then (NH, district), then NH alone. Only a km match rates a
project (flagged at complexity >= LA_FLAG, else clear); the district and NH-only links fell under 70% on a
hand-checked sample, so they are 'possible', shown and never flagged. A state with no land data is 'unknown', never
'clear'. The table is one snapshot: a stretch's parcels and complexity count every notification, so gold reads them
at t only for stretches whose last notification is by t (the pair tables keep the dates). The model's la_* features
read external_land_pairs, built as before from the Maharashtra table alone: the all-state table added no backtest lift.

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
from pipeline import parivesh  # noqa: E402
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
# SENTENCE splits 'Stage - I forest clearance' at ' - ' and the fragment loses its stage: rejoined to 'Stage-I' first
STAGE_DASH = r"\b([Ss]tage|STAGE|FC)\s+[-–]\s*(?=(?:II|I|1|2)(?![A-Za-z0-9]))"
# forest hectares: '12.5 ha of reserved forest', 'forest land of 30 ha', 'Forest land-71.72 hect', 'Forest - 3.101)',
# 'FC (323.49 Ha)'; not 'non-forest land of 648 ha', '3.2 hect and forest land ...' or '1426 Ha including forest and
# nonforest land'
_NOT_NON = r"(?<!non-)(?<!non )(?<!non)"
FOREST_HA = (r"(\d+(?:\.\d+)?)\s*(?:ha\b|hect\w*)\.?\s*(?:of\s+)?(?:(?!(?:and|or|including|non)\b)\w+\s+){0,2}"
             + _NOT_NON + r"forest(?!\s*(?:and|&|or|/)\s*non)"
             r"|" + _NOT_NON + r"forest\s*(?:land|area)?\s*(?:(?:of|\(|measuring|admeasuring)?\s*(\d+(?:\.\d+)?)\s*"
             r"(?:ha\b|hect)|[-:]\s*(\d+(?:\.\d+)?)(?:\s*(?:ha\b|hect)|(?=\s*[)\];,]|\s*$)))"
             r"|(?-i:\bFC\b)\s*\(\s*(\d+(?:\.\d+)?)\s*(?:ha\b|hect)"
             # the area of a Parivesh proposal or a diversion names no 'forest': 'proposal No FP/MP/RAIL/39172/2019 of
             # 66.69 ha', 'for diversion of 72.83 ha land' (only forest_env sentences are read)
             r"|(?-i:\bFP/[A-Z]{2}/[A-Z]+/\d+/\d{4})\)?\s*(?:of|for)\s+(\d+(?:\.\d+)?)\s*(?:ha\b|hect)"
             r"|diversion\s+of\s+(\d+(?:\.\d+)?)\s*(?:ha\b|hect\w*)\.?(?!\s*(?:of\s+)?non)")
VIOLATION = (r"violat\w*|post[\s-]*facto|without\s+(?:prior\s+|obtaining\s+|the\s+)?(?:forest\s+clearance|FC|EC"
             r"|environment\w*\s+clearance|clearance)")
# a mention that reports the matter done ('EC received on 31.07.23') and names no hold-up is resolved
DONE = (r"\b(?:obtained|received|got|granted|accorded|issued|completed\w*|achieved|approved|done|removed|resolved"
        r"|vacated|settled|cleared|finali[sz]ed|disbursed|handed\s+over|in\s+(?:physical\s+)?possession|available"
        r"|(?:is|are|was|were|has\s+been|have\s+been)\s+(?:made|paid|acquired|taken))\b")
LAND_DONE_PCT = 95        # a land mention with a share acquired is done at this share, whatever its verbs say
# not hold-ups, removed before BLOCKED is read: a reference number ('vide letter no. 12', 'proposal No FP/...') and
# work going on ('work is in progress')
NOT_HOLDUP = r"\bno\.|\b(?:letter|file|order|ref|proposal)\s+no\b|\bworks?\s+(?:is\s+|are\s+)?(?:in|under)\s+progress"
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


def sentences(text):
    """Free texts -> one row per sentence (index: the text's), original case, 'Stage - I' rejoined first."""
    sent = text.str.replace(STAGE_DASH, r"\1-", regex=True).str.split(SENTENCE, regex=True).explode().str.strip()
    return sent[sent.str.len() > 3]


def tag(text):
    """Free-text remarks (unique) -> one row per (text, category) with its shortest matching sentence, subtype,
    authority and forest hectares. Sentences keep their original case for the acronym patterns."""
    sent = sentences(text)
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
    # '91.58 % land acquisition completed' is 8% short: a land share decides, not the verb
    pct = m["sentence"].where(m["category"].eq("land")).map(lambda s: la_progress(s).get("la_pct"), na_action="ignore")
    pct = pct.astype("float64")
    done = m["sentence"].str.contains(DONE, case=False, regex=True).mask(pct.notna(), pct.ge(LAND_DONE_PCT))
    held = m["sentence"].str.replace(NOT_HOLDUP, " ", case=False, regex=True).str.contains(BLOCKED, case=False,
                                                                                           regex=True)
    m["resolved"] = done & ~held
    return m


def snippet(sentence, category):
    """The sentence cut to SNIPPET characters around its first keyword."""
    if len(sentence) <= SNIPPET:
        return sentence
    hit = re.search(category_regex(category), sentence, flags=re.IGNORECASE)
    start = max(0, (hit.start() if hit else 0) - 60)
    start = sentence.rfind(" ", 0, start) + 1 if start else 0
    return sentence[start:start + SNIPPET].strip()


# ---- remark facts: forest-clearance stage, land acquisition %, land step and Parivesh proposal numbers ----
# Ported from the 2026-09 remark research (hand-checked on fresh 40-sentence samples: forest stage 33/40, land %
# 38/40, land step 19/24). Remarks carry free text only up to 2023-Q2, so every value is as of its quarter.
# Forest stage, least to most advanced (the quarter keeps its most advanced sentence). The seven levels:
# 1 applied (application, enumeration, DGPS, CA land), 2 state level (DFO, CF, PCCF, nodal officer, state govt, FRA;
# 'stage1_pending' names no office), 3 regional office (IRO, RO, REC), 4 FAC / MoEFCC / NBWL, 5 Stage-I granted
# (awaiting Stage-II 'stage2_pending' or working permission 'wp_pending'), 6 working permission, 7 Stage-II or final
# ('approved_generic' names no stage). 'fc_awaited' is a clearance awaited with no stage, 'not_applicable' no forest
# land involved, and 'rejected' (rejected, returned, deferred, in appeal) outranks every stage of its quarter.
FC_STAGES = ["not_applicable", "fc_awaited", "applied", "stage1_pending", "state_level", "regional_iro",
             "central_fac_moef", "stage1_granted", "wp_pending", "stage2_pending", "working_permission",
             "approved_generic", "stage2_granted", "rejected"]
LA_STEPS = ["notification", "declaration", "award", "compensation_paid", "possession"]   # mentioned, not done
REMARK_FACTS = ["fc_stage", "la_pct", "la_step", "proposal_no"]
PROPOSAL_NO = r"(?-i:\bFP\s*/\s*([A-Z]{2})\s*/\s*([A-Z]+)\s*/\s*(\d+)\s*/\s*(\d{4})\b)"   # 'FP/MP/RAIL/39172/2019'

_I = re.IGNORECASE
_FC_CTX = re.compile(r"(?<!non-)(?<!non )(?<!non)forest|(?<![A-Z])FC\b|wild\s*life|\bNBWL\b|\bSBWL\b|\bFAC\b"
                     r"|\bNTCA\b|tiger\s+reserve|sanctuary|compensatory\s+afforest|\bCAMPA\b"
                     r"|stage\s*[-–?¿]*\s*(?:II|I|1|2)\s+(?:clear\w*|approval)|(?<![A-Z])FC[-\s]*(?:II|I|1|2)\b", _I)
_FC_DONE = r"(?:received|recd|obtained|granted|accorded|issued|approved|given|cleared|achieved|got|done|in\s+place)"
_FC_PEND = (r"(?:await\w*|pending|yet\s+to|under\s+(?:process|consideration|examination|scrutiny)|in\s+process"
            r"|to\s+be\s+(?:obtained|issued|granted|accorded|received|sought)|expected|not\s+(?:yet\s+)?(?:been\s+)?"
            r"(?:received|obtained|granted|issued)|delay\w*|applied|sought|required|procedure|being\s+processed"
            r"|for\s+(?:grant|issuance|issue|obtaining)|obtaining|subject\s+to|affect\w*|hamper\w*|held\s+up"
            r"|constraint)")
_FC_CUE = re.compile(r"\b(?:stage|stg|stag)\s*[-–—?¿.:]*\s*(II|I|1|2|one|two)(?![A-Za-z0-9])"
                     r"|\b(1st|first|2nd|second|final)\s+stage\b"
                     r"|\b(final)\s+(?:forest\w*\s+)?(?:clearance|approval|FC)"
                     r"|(?<![A-Z])FC\s*[-–]?\s*(II|I|1|2)(?![A-Za-z0-9])"
                     r"|\b(in[\s-]*princip\w*)\s+(?:\w+\s+){0,2}(?:approval|clearance|nod)", _I)
_FC_BOTH = re.compile(r"(?:stage|FC)\s*[-–?¿]*\s*(?:I|1)\s*(?:&|and|,)\s*(?:stage\s*[-–]?\s*)?(?:II|2)\b", _I)
_FC_NA = re.compile(r"no\s+forest\s+(?:land\s+)?(?:is\s+)?involv|(?:does\s+not|doesn.t)\s+involve\s+(?:any\s+)?forest"
                    r"|forest\s+clearance\s+(?:is\s+)?not\s+(?:required|applicable)|without\s+forest\s+land", _I)
_FC_MINISTRY = re.compile(r"ministry\s+of\s+environment[\s,]*(?:forests?)?(?:\s*(?:and|&)\s*climate\s+change)?"
                          r"|moe\s*f\s*(?:&|and)?\s*(?:cc)?", _I)
_FC_COMPLY2 = re.compile(r"compliance\s+(?:\w+\s+){0,2}(?:FC|stage)[\s-]*(?:II|2)\s+conditions|FC[\s-]*II\s+conditions",
                         _I)
_FC_OK_AFTER = re.compile(r"^.{0,45}?(?:clear\w*|clerance|clearacne|approv\w*|\bFC\b|forest\w*|permission|diversion"
                          r"|compliance|in\s+principle|\bnod\b)", _I)
_FC_OK_BEFORE = re.compile(r"(?:forest\w*|\bFC\b)\W+(?:\w+\W+){0,3}$", _I)
_FC_WP = re.compile(r"(?:working|work)\s+permission|permission\s+(?:to|for)\s+(?:start\s+)?work"
                    r"|tree\s+felling\s+permission|permission\s+for\s+(?:tree\s+)?felling", _I)
_FC_REGIONAL = re.compile(
    r"(?-i:\bIRO\b)|integrated\s+regional\s+office|regional\s+office|(?-i:\bREC\b)|regional\s+empowered"
    r"|(?-i:\bRO\b)\W+(?:of\s+)?MoE|MoE\w*\s*(?:&\s*CC)?[\s,-]+(?:regional|RO\b|Lucknow|Bhopal|Nagpur|Bhubaneswar|BBSR"
    r"|Ranchi|Shillong|Dehradun|Chandigarh|Bengaluru|Bangalore|Chennai|Raipur|Gandhinagar|Jaipur|Vijayawada)"
    r"|regional\s+(?:EAC|MoE)", _I)
_FC_CENTRAL = re.compile(
    r"(?-i:\bFAC\b)|forest\s+advisory|(?-i:\bNBWL\b)|national\s+board\s+(?:of|for)\s+wild\s*life|standing\s+committee"
    r"|(?-i:\bNTCA\b)|(?-i:\bCEC\b)|central\s+empowered|(?-i:\bAIG\b)"
    r"|(?:pending|awaited|lying|submitted|forwarded|sent|referred|placed|recommended)\s+(?:\w+\s+){0,4}"
    r"(?:to|with|at|before|by|from)\s+(?:the\s+)?(?:\bmoe\s*f\w*|ministry\s+of\s+environment)"
    r"|(?:\bmoe\s*f\w*|ministry\s+of\s+environment)[\w\s&,]{0,12}\s(?:has\s+)?(?:raised|sought|asked|is\s+to"
    r"|to\s+issue|returned|query|queries)", _I)
_FC_STATE = re.compile(
    r"(?-i:\bDFOs?\b)|divisional\s+forest|(?-i:\b(?:A?P?CCF|CF|APCCF|PCCF)\b)|conservator|nodal\s+off"
    r"|forest\s+(?:dept|deptt|department|division|officials?|authorit\w*)|state\s+(?:govt|government)"
    r"|(?-i:\bSBWL\b)|state\s+(?:board|wild\s*life\s+board)|(?-i:\bFRA\b)|forest\s+rights|(?-i:\bRoFR\b)"
    r"|gram\s+sabha|collector|(?-i:\bDC\b)", _I)
_FC_APPLIED = re.compile(
    r"application|proposal\s+(?:\w+\s+){0,3}(?:submitted|uploaded|sent|filed|prepared|forwarded)"
    r"|(?:submitted|uploaded|filed)\s+(?:\w+\s+){0,4}(?:proposal|application)|online|enumeration"
    r"|\bDGPS\b|joint\s+(?:inspection|verification|survey)|site\s+inspection|(?-i:FP/[A-Z]{2}/)"
    r"|\bCA\s+(?:land|scheme|area)|identified", _I)
# 'appeal' added to the research pattern: an appeal against an FAC decision was missed
_FC_REJECT = re.compile(r"reject\w*|returned|\bclosed\b|deferred|appeal\w*|not\s+(?:been\s+)?(?:recommended|agreed"
                        r"|approved)", _I)
_FC_WORD = (r"(?:forest\w*\s+(?:clear\w*|clerance|approval|permission|diversion|land\s+(?:clearance|diversion))"
            r"|\bFC\b|diversion\s+of\s+forest)")
_FC_GEN_DONE = re.compile(_FC_WORD + r"[^.;]{0,60}?\b" + _FC_DONE + r"\b|\b" + _FC_DONE + r"\b[^.;]{0,30}?" + _FC_WORD,
                          _I)
_FC_GEN_PEND = re.compile(_FC_WORD + r"[^;]{0,60}?\b" + _FC_PEND + r"|\b" + _FC_PEND + r"[^;]{0,40}?" + _FC_WORD
                          + r"|involvement\s+of\s+(?:\w+\s+){0,2}forest|forest\s+(?:issue|problem|hurdle)", _I)
_FC_LOCATION = {1: "applied", 2: "state_level", 3: "regional_iro", 4: "central_fac_moef"}


def _fc_cue_state(after, before):
    """'done', 'pending' or 'mention' for a stage cue: the first verb after it, else a done verb just before it."""
    p = re.search(r"\b" + _FC_PEND, after, _I)
    d = re.search(r"\b" + _FC_DONE + r"\b", after, _I)
    if d and (not p or d.start() < p.start()):
        return "done"
    if p:
        return "pending"
    return "done" if re.search(r"\b" + _FC_DONE + r"\b\W+(?:\w+\W+){0,2}$", before, _I) else "mention"


def fc_stage(text):
    """A sentence's forest-clearance stage (a FC_STAGES label), null when it is not about a clearance stage."""
    if not _FC_CTX.search(_FC_MINISTRY.sub(" ", text)):
        return None
    if _FC_NA.search(text):
        return "not_applicable"
    stage = _fc_stage(text)
    rejected = _FC_REJECT.search(text) and re.search(r"forest|FC|FAC|proposal", text, _I)
    return "rejected" if stage is not None and rejected else stage


def _fc_stage(text):
    """fc_stage of a forest sentence, before the rejected check."""
    text = re.sub(r"^(II|I)\s+(?=forest|FC|clear)", r"Stage-\1 ", text)
    found = []                                            # (level, label)
    if _FC_COMPLY2.search(text):
        found.append((7, "stage2_granted"))
    b = _FC_BOTH.search(text)
    if b and _fc_cue_state(text[b.end():b.end() + 90], "") == "done":
        found.append((7, "stage2_granted"))
    cues = list(_FC_CUE.finditer(text))
    for i, m in enumerate(cues):
        tok = next((g for g in m.groups() if g), "").lower()
        tok = "i" if tok.startswith("in") else tok
        fcx = m.group(4) is not None or m.group(5) is not None
        two = tok in ("ii", "2", "two", "2nd", "second", "final")
        after = text[m.end(): cues[i + 1].start() if i + 1 < len(cues) else m.end() + 90][:90]
        before = text[max(0, m.start() - 40): m.start()]
        if tok == "final" and m.group(3) is None and not _FC_OK_AFTER.search(after):
            continue
        if m.group(3) is None and not fcx and not (_FC_OK_AFTER.search(after) or _FC_OK_BEFORE.search(before)):
            continue
        # 'stage I & II approval given': the verb after the second cue is shared
        if not re.search(r"\w{3,}", re.sub(r"(?i)\b(?:and|&|stage|forest\w*|FC|clearance)\b|[-&,\s]", " ", after)):
            after = text[m.end(): m.end() + 90]
        state = _fc_cue_state(after, before)
        if two:
            found.append((7, "stage2_granted") if state == "done" else (5, "stage2_pending"))
        else:
            found.append((5, "stage1_granted") if state == "done" else (2, "stage1_pending"))
    w = _FC_WP.search(text)
    if w:
        after, before = text[w.end(): w.end() + 70], text[max(0, w.start() - 40): w.start()]
        p = re.search(r"\b" + _FC_PEND, after, _I)
        d = (re.search(r"\b" + _FC_DONE + r"\b", after, _I)
             or re.search(r"\b" + _FC_DONE + r"\b\W+(?:\w+\W+){0,2}$", before, _I))
        found.append((6, "working_permission") if d and not (p and p.start() < d.start()) else (5, "wp_pending"))
    loc = next((lv for lv, rx in [(3, _FC_REGIONAL), (4, _FC_CENTRAL), (2, _FC_STATE), (1, _FC_APPLIED)]
                if rx.search(text)), None)
    top = max(found)[0] if found else None
    generic_done = bool(_FC_GEN_DONE.search(text)) and not _FC_GEN_PEND.search(text)
    # an office named says where a proposal not yet granted sits
    if loc is not None and (top is None or (top == 2 and loc > 2)):
        if top is None and generic_done and loc >= 2 and not re.search(r"recommend|forward", text, _I):
            return "approved_generic"
        return _FC_LOCATION[loc]
    if found:
        return next(lab for lv, lab in found if lv == top)
    if generic_done:
        return "approved_generic"
    if _FC_GEN_PEND.search(text) or re.search(r"forest\s+clear\w*|\bFC\b|forest\s+land", text, _I):
        return "fc_awaited"
    return None


_NUM = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_NU = _NUM + r"\s*(ha\b|hac\w*|hect\w*|hec\b|acres?|ac\b)\.?"
_NO_NU = r"(?:(?!\d[\d.,]*\s*(?:ha\b|hac|hect|hec\b|acre|ac\b)).)"          # a character that does not start an area
_LA_ACQ = (r"acquired|possess\w*|handed\s+over|hand\s*over|received|registered|available|taken\s+over|transferred"
           r"|purchased|made\s+available")
_LA_REM = (r"yet\s+to\s+be|balance|remaining|to\s+be\s+acquired"
           r"|not\s+(?:yet\s+)?(?:been\s+)?(?:acquired|handed|possessed)")
_LA_CTX = re.compile(r"\bland|(?-i:\bLA\b)|(?-i:\bLAQ\b)|acqui|possession|PR\s+provision", _I)
# the % written just before 'land acquisition' wins over one after it: '91.58 % land acquisition completed. 95.9 %
# earthwork' is 91.58, and an after-% never crosses a sentence end
_LA_PCT_BEFORE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:of\s+)?(?:(?-i:LA\b)|land\s*(?:acqu?i\w*|has|have|is|was|handed"
                            r"|made|in\s+possession|possessed|available)|(?:acqu?i\w*|possession)\s+of\s+land)", _I)
_LA_PCT_AFTER = re.compile(r"land\s+acqu?i\w*(?:(?!\.\s)[^%]){0,80}?(\d+(?:\.\d+)?)\s*%", _I)
_LA_PCT_REMAIN = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:of\s+)?land\s+(?:\w+\s+){0,6}yet\s+to\s+be\s+acqu", _I)
_LA_PCT_BAD = re.compile(r"compensation|development|boundary|free\s+of\s+cost|cost\s+shar|only\s+(?:on|after)"
                         r"|after\s+acquiring|on\s+completion\s+of|\bRoR\b|return|release\s+of", _I)
_LA_OUT_WHICH = re.compile(_NU + _NO_NU + r"{0,80}?out\s+of\s+(?:which|this|these|it)\W+(?:\w+\W+){0,4}?" + _NU, _I)
_LA_OUT_PART = re.compile(_NU + r"(" + _NO_NU + r"{0,90}?)out\s+of\s+(?:the\s+)?(?:total\s+)?(?:\w+\s+){0,3}?" + _NU,
                          _I)
_LA_OUT_TOTAL = re.compile(r"out\s+of\s+(?:the\s+)?(?:total\s+)?(?:\w+\s+){0,4}?" + _NU + _NO_NU + r"{0,140}?" + _NU,
                           _I)
_LA_ACQ_BAL = re.compile(r"(?:acquired|possess\w*)\s+(?:is\s+)?" + _NU + _NO_NU + r"{0,40}?balance\s+(?:\w+\s+){0,5}?"
                         + _NU, _I)
_LA_STEP_RX = [
    r"\b3\s*[-(]?\s*A\b\)?|\b3\s*\(\s*1\s*\)|sec\w*\.?\s*(?:4|11)\s*(?:\(\s*1\s*\))?\b|\b20\s*A\b|\b4\s*\(\s*1\s*\)"
    r"|preliminary\s+notification|notification\s+u/?s|(?-i:\bCBA\b)",
    r"\b3\s*[-(]?\s*D\b|sec\w*\.?\s*(?:6|19)\b|\b20\s*E\b|\b9\s*\(\s*1\s*\)|declaration",
    r"\b3\s*[-(]?\s*G\b|\bawards?\s+(?:\w+\s+){0,3}(?:declared|passed|published|announced|made|pronounced|stage)"
    r"|\bfinal\s+award|\b20\s*F\b|sec\w*\.?\s*23\b",
    r"compensation\s+(?:\w+\s+){0,4}(?:disbursed|paid|deposited|distributed)"
    r"|(?:disburs\w*|payment|deposit\w*)\s+(?:of\s+)?(?:\w+\s+){0,3}compensation|\b3\s*[-(]?\s*H\b",
    r"possession|handed\s+over|hand\s*over|\b3\s*[-(]?\s*E\b",
]


def _ha(v, u):
    return float(v.replace(",", "")) * (0.4047 if u.lower().startswith("ac") else 1.0)


def _same_unit(a, b):
    return a.lower().startswith("ac") == b.lower().startswith("ac")


def _first_verb(s):
    """'acq' or 'rem' for whichever verb comes first in s, None when neither."""
    a, r = re.search(_LA_ACQ, s, _I), re.search(_LA_REM, s, _I)
    if a and (not r or a.start() < r.start()):
        return "acq"
    return "rem" if r else None


def _la_ratio(text):
    """Land share from hectares: 'X ha out of Y ha', 'Y ha ... out of which X ha', 'out of Y ha, X ha in
    possession', 'acquired X ha, balance Y ha' (acres in hectares). {} when none."""
    if re.search(r"\bFC\b|forest\s+clear|stage|application", text, _I) and not re.search(
            r"acqui|possess|handed|registered", text, _I):
        return {}
    for rx in (_LA_OUT_WHICH, _LA_OUT_PART, _LA_OUT_TOTAL):
        m = rx.search(text)
        if not m:
            continue
        if rx is _LA_OUT_WHICH:
            (tot, tu), (part, pu) = m.group(1, 2), m.group(3, 4)
            verb, pre_bal = _first_verb(text[m.end(): m.end() + 60]), False
        elif rx is _LA_OUT_PART:
            (part, pu), mid, (tot, tu) = m.group(1, 2), m.group(3), m.group(4, 5)
            verb = _first_verb(mid + " " + text[m.end(): m.end() + 60])
            pre_bal = bool(re.search(r"balance\s+(?:\w+\s+){0,3}$", text[max(0, m.start() - 30): m.start()], _I))
        else:
            (tot, tu), (part, pu) = m.group(1, 2), m.group(3, 4)
            verb = _first_verb(text[m.end(2): m.start(3)]) or _first_verb(text[m.end(): m.end() + 60])
            pre_bal = bool(re.search(r"balance\s+(?:\w+\s+){0,3}$", text[max(0, m.start(3) - 30): m.start(3)], _I))
        if not _same_unit(tu, pu) or re.search(r"compensation|sanctioned|application", text[m.start(): m.end() + 60],
                                               _I):
            continue
        t, p = _ha(tot, tu), _ha(part, pu)
        if t <= 0 or p > t:
            continue
        if pre_bal or verb == "rem":
            return {"la_pct": 100 * (1 - p / t), "la_total_ha": t}
        if verb == "acq":
            return {"la_pct": 100 * p / t, "la_total_ha": t}
    m = _LA_ACQ_BAL.search(text)
    if m and _same_unit(m.group(2), m.group(4)):
        a, b = _ha(*m.group(1, 2)), _ha(*m.group(3, 4))
        return {"la_pct": 100 * a / (a + b), "la_total_ha": a + b}
    return {}


def la_progress(text):
    """A sentence's land acquisition: la_pct (share acquired, 0-100), la_total_ha (the land the share is of, when
    given in hectares) and la_step (the furthest LA_STEPS step it mentions); keys absent when not stated."""
    out = {}
    if not _LA_CTX.search(text):
        return out
    m = _LA_PCT_REMAIN.search(text)
    if m:
        out["la_pct"] = 100 - float(m.group(1))
    else:
        for rx in (_LA_PCT_BEFORE, _LA_PCT_AFTER):
            m = rx.search(text)
            if m and not _LA_PCT_BAD.search(text[max(0, m.start() - 60): m.end() + 30]) and float(m.group(1)) <= 100:
                out["la_pct"] = float(m.group(1))
                break
    if "la_pct" not in out:
        out.update(_la_ratio(text))
    steps = [i for i, rx in enumerate(_LA_STEP_RX) if re.search(rx, text, _I)]
    if steps and re.search(r"land|acqui|notif|award|compensation|possession", text, _I):
        out["la_step"] = LA_STEPS[max(steps)]
    return out


def remark_facts(text):
    """Free texts (unique) -> one row per sentence that states a forest stage, land share or land step (index: the
    text's): fc_stage, la_pct, la_total_ha, la_step."""
    sent = sentences(text)
    u = pd.Series(sent.unique())
    f = pd.DataFrame([la_progress(s) for s in u], index=u.index, columns=["la_pct", "la_total_ha", "la_step"])
    f["fc_stage"] = u.map(fc_stage)
    f = f.set_index(u)
    x = f.reindex(sent.to_numpy()).set_index(sent.index)
    return x[x.notna().any(axis=1)]


def quarter_facts(rows):
    """Remark rows -> one row per (project_key, period) whose free text states something: fc_stage (its most
    advanced sentence), la_pct (of the sentence naming the largest land total, else the median of its percentages),
    la_step (the furthest mentioned) and proposal_no (the Parivesh numbers named, ;-joined)."""
    pk = ["project_key", "period"]
    rows = rows.assign(free=free_text(rows["remarks"].fillna("")))
    rows = rows.loc[rows["free"].notna(), pk + ["free"]].drop_duplicates()
    uniq = pd.Series(rows["free"].unique())
    f = remark_facts(uniq)
    f["free"] = uniq.to_numpy()[f.index]
    x = rows.merge(f, on="free")
    g = x.groupby(pk)
    rank = {s: i for i, s in enumerate(FC_STAGES)}
    out = pd.DataFrame({"fc_stage": g["fc_stage"].agg(lambda s: max(s.dropna(), key=rank.get, default=None)),
                        "la_step": g["la_step"].agg(lambda s: max(s.dropna(), key=LA_STEPS.index, default=None))})
    la = x[x["la_pct"].notna()]
    best = la.assign(_tot=la["la_total_ha"].fillna(-1)).sort_values(["_tot", "la_pct"]).drop_duplicates(pk, keep="last")
    best = best.set_index(pk)
    pct_only = la[la["la_total_ha"].isna()].groupby(pk)["la_pct"].median()
    out["la_pct"] = best["la_pct"].where(best["_tot"] > 0, pct_only.reindex(best.index)).round(2)
    no = uniq.str.extractall(PROPOSAL_NO)
    no = ("FP/" + no[0] + "/" + no[1] + "/" + no[2] + "/" + no[3]).groupby(level=0).agg(joined)
    p = rows.assign(proposal_no=rows["free"].map(pd.Series(no.to_numpy(), index=uniq.to_numpy()[no.index])))
    out = out.join(p[p["proposal_no"].notna()].groupby(pk)["proposal_no"].agg(split_joined), how="outer")
    out = out.reset_index()
    for c in ["fc_stage", "la_step", "proposal_no"]:
        out[c] = out[c].astype("str")
    out = out[out[REMARK_FACTS].notna().any(axis=1)]
    return out[pk + REMARK_FACTS].sort_values(pk, ignore_index=True)


def remark_status(qf):
    """Quarter facts -> per project the latest forest stage, land share and land step, each with the quarter it is
    as of (remarks end in 2023-Q2), and every proposal number named."""
    out = pd.DataFrame(index=pd.Index(sorted(qf["project_key"].unique()), name="project_key"))
    for c in ["fc_stage", "la_pct", "la_step"]:
        last = qf[qf[c].notna()].drop_duplicates("project_key", keep="last").set_index("project_key")
        out[c], out[f"{c}_as_of"] = last[c], last["period"]
    out["proposal_no"] = qf[qf["proposal_no"].notna()].groupby("project_key")["proposal_no"].agg(split_joined)
    out["proposal_no"] = out["proposal_no"].astype("str")
    return out.reset_index()


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


def forest_clearance(master, ev, scen, portal=None):
    """One row per project_key: its Parivesh profile and the complexity of the scenarios it matches. portal
    (project_key, area_ha, pending) overrides the remark hectares and the pending flag of the projects whose report
    remarks name a Parivesh proposal number found on the portal (pipeline/parivesh.py)."""
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
    if portal is not None:
        d["area_ha"] = d["project_key"].map(portal.set_index("project_key")["area_ha"]).fillna(d["area_ha"])
    prof = ["linear", "mining", "violation", "ofc", "defence", "survey", "area_ha"]
    # ponytail: one scenario scan per distinct profile, a few dozen; vectorise if hectares become common
    keys = d[prof].drop_duplicates()
    rows = [dict(p, **fc_summary(scenarios_for(scen, p), p)) for p in keys.to_dict("records")]
    out = d.merge(pd.DataFrame(rows), on=prof, how="left")
    out["fc_shape"] = np.where(out["linear"], "Linear", "Non-Linear")
    out["fc_area_known"] = out["area_ha"].notna()
    out["fc_mentioned"] = out["project_key"].isin(fe_ev["project_key"])
    out["fc_pending"] = out["project_key"].isin(fe_ev.loc[fe_ev["status"].eq("open"), "project_key"])
    if portal is not None:
        out["fc_pending"] = out["project_key"].map(portal.set_index("project_key")["pending"]).fillna(
            out["fc_pending"]).astype(bool)
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
# an NH named as an end point a few words after the cue is not the project's road: 'from Junction with
# Amritsar-Mehta-Tanda road NH-503A', 'to intersection with NH-44', 'connecting NH-119 and NH-58', 'starting at
# Ch. 237000 of NH 530'. Only the display link drops them (link_land strict); the model's link reads NH_TEXT alone.
NH_END = (r"\b(?:JUNCTION|JN\.?|INTERSECTION|CONNECTING|STARTING\s+(?:AT|FROM)|ENDING\s+AT|TERMINATING\s+AT)\s+"
          r"(?:(?:WITH|OF|AT|FROM)\s+)?(?:[^\s,;]+\s+){0,6}?(?:NH|N\.H\.|NATIONAL\s+HIGHWAY)\s*(?:NO\.?)?\s*[-:.]?\s*"
          + _NH_NO + r"(?:\s*(?:&|AND|/)\s*(?:NH\s*[-:.]?\s*)?" + _NH_NO + r")?")
# km range in a project name: 'Km 217.500 to Km 254.430', 'KM 267+500 TO KM 290+000', 'Ch. 0.000 to Ch. 49.2',
# 'km 193/0 to km 255/300', 'Km 55.00 Kuru to Km 95.400 Udaipura', 'Bakhtiyarpur Km 153.300 to Mokama Km 197.900';
# '+' and '/' are km + metres and a 5-6 digit number is metres ('Km 82000 to Km 94030')
_KM = r"(\d{1,6}(?:[.,+/]\s?\d{1,3})?)"
KM_RANGE = (r"(?:\bkm|\bch|chainage)\s*\.?\s*[:.]?\s*" + _KM
            + r"(?:\s*(?:to|-|–)\s*(?:(?:[a-z]+\.?\s+){0,2}(?:km|ch)(?![a-z])\.?\s*)?"
            + r"|\s+(?:[a-z]+\s+){1,3}to\s+(?:km|ch)(?![a-z])\.?\s*)"
            + _KM)
KM_TOL = 1.0              # a stretch links on km when it shares more than this (or half the shorter span) with the range
KM_MAX, KM_MAX_SPAN = 2000, 300   # a km range or stretch chainage past these is a misread, not used to link
LA_FLAG = 4               # a linked project is flagged at acquisition complexity >= 4 of 5, else clear
# link methods that rate a project flagged or clear; the others are only 'possible': shown, never flagged.
# Hand-checked on 100 current links (gold/land_link_check.csv, 2026-09-28): nh_chainage 21/25 correct (84%, Wilson CI
# 65-94%), nh_district 16/25 (64%, 45-80%: districts named as the road's end points, other packages of the same
# road), nh_only 16/50 (32%, 21-46%: the max over every stretch of a long NH). A method under 70% is 'possible'.
LA_CONFIDENT = ("nh_chainage",)
LA_POSSIBLE_WHY = {"nh_district": "NH and a district named in the name, no km range to place it",
                   "nh_only": "NH only, no district or km range in the name places the project on it"}
# the model's la_* features stay on this table and the NH/district link they were backtested on: the all-state
# table and the km-range link add no lift (2026-09 ablation), so they are evidence and display only
LA_MODEL_TABLE = "land_acquisition_maharashtra.csv"
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


def split_joined(v):
    """;-joined values -> their union, ;-joined."""
    return joined(n for s in v for n in s.split(";"))


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


def nh_endpoints(s):
    """NH ids each text names as an end point (NH_END), as sets (empty when none)."""
    m = s.fillna("").str.upper().str.extractall(NH_END)
    ids = pd.concat([m[0], m[1]]).dropna().str.replace(r"[\s-]", "", regex=True).str.lstrip("0")
    ends = ids.groupby(level=0).agg(set).reindex(s.index)
    return ends.map(lambda v: v if isinstance(v, set) else set())


def _km(v):
    """'217.500' -> 217.5, '217,5' -> 217.5, '267+500' / '267/500' -> 267.5 (km + metres); a plain integer is
    returned as an int (km or metres, km_range decides)."""
    whole, sep, frac = re.fullmatch(r"(\d+)(?:([.,+/])(\d+))?", v.replace(" ", "")).groups()
    if sep in ("+", "/"):
        return int(whole) + int(frac) / 1000
    return float(f"{whole}.{frac}") if sep else int(whole)


def _km_pair(a, b):
    """Both ends of a km range in km, or None: plain integers are metres when one has 5+ digits or both are
    plain with one >= 2000 ('Km 82000 to Km 94030', 'km 0000 to Km 4385'); a range over KM_MAX_SPAN km or past
    KM_MAX is a misread ('KM 377-700', 'KM.825-KM.30')."""
    x, y = _km(a), _km(b)
    ints = [v for v in (x, y) if isinstance(v, int)]
    if any(v >= 10000 for v in ints) or (len(ints) == 2 and max(ints) >= 2000):
        x, y = (v / 1000 if isinstance(v, int) else v for v in (x, y))
    lo, hi = sorted((float(x), float(y)))
    return (lo, hi) if hi - lo <= KM_MAX_SPAN and hi <= KM_MAX else None


def km_range(names):
    """The first km range each project name gives, as km_from <= km_to; null when it gives none (or a misread)."""
    m = names.fillna("").str.extract(KM_RANGE, flags=re.IGNORECASE)
    r = [_km_pair(a, b) if isinstance(a, str) else None for a, b in zip(m[0], m[1])]
    return pd.DataFrame([v or (np.nan, np.nan) for v in r], columns=["km_from", "km_to"], index=names.index)


def sane_chainage(st):
    """Stretches whose chainage reads as km: both ends in [0, KM_MAX] and at most KM_MAX_SPAN apart (the table has
    metre chainages such as '10163.000 - 152520.000' and whole-state spans such as '0.000 - 517.000')."""
    a, b = st["chainage_start_km"], st["chainage_end_km"]
    return a.between(0, KM_MAX) & b.between(0, KM_MAX) & (a - b).abs().le(KM_MAX_SPAN)


def state_key(s):
    """State names -> comparable keys: 'Jammu & Kashmir' and 'JAMMU AND KASHMIR' both -> 'JAMMU AND KASHMIR'."""
    return s.str.upper().str.replace("&", " AND ").str.replace(r"[^A-Z]+", " ", regex=True).str.strip()


def read_land(path):
    return pd.read_csv(path, dtype={"state": "str", "highway_name": "str", "chainage_raw": "str"})


def load_land(external=EXTERNAL):
    """Every land source as one stretch table (the land_acquisition_maharashtra.csv schema): the stretch CSVs
    raw/external/land_acquisition_*.csv, then the raw Bhoomi Rashi exports in raw/external/bhoomi_rashi/ (.xls,
    .html) parsed and aggregated. A (state, highway, chainage) stretch found in more than one keeps its first copy.
    A state in a scheduled pull (raw/external/bhoomi_rashi_pulls/<date>.csv, backend/live/portals.py) comes from the
    newest pull that has it instead, whole."""
    parts = [read_land(p) for p in sorted(external.glob("land_acquisition_*.csv"))]
    raw = sorted(p for p in (external / "bhoomi_rashi").glob("*") if p.suffix.lower() in (".xls", ".html", ".htm"))
    parts += [aggregate_stretches(parse_bhoomi_rashi(p)) for p in raw]
    la = pd.concat(parts, ignore_index=True)
    pulls = [read_land(p).assign(pull=p.stem) for p in sorted((external / "bhoomi_rashi_pulls").glob("*.csv"))]
    if pulls:
        pl = pd.concat(pulls, ignore_index=True).assign(k=lambda d: state_key(d["state"]))
        pl = pl[pl["pull"] == pl.groupby("k")["pull"].transform("max")].drop(columns=["pull", "k"])
        la = pd.concat([pl, la[~state_key(la["state"]).isin(set(state_key(pl["state"])))]], ignore_index=True)
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


def link_land(master, st, strict=True):
    """Road projects -> the LA stretches of their state and of the NH they name: stretches sharing more than KM_TOL
    km (or half the shorter span) with the km range in the name first ('nh_chainage'), then (NH, district) in the
    name ('nh_district'), then the NH alone ('nh_only'). An NH named only as an end point ('from Junction with ...
    NH-54') is not the project's road. A project's state is its own, or for a Multi-State project each land-table
    state whose district its name mentions; a state with no stretches leaves it unknown. A km range in the name rules
    out every stretch whose own chainage it contradicts ('no_stretch_at_its_km' when none is left). Only LA_CONFIDENT
    links rate a project: flagged at complexity >= LA_FLAG, else clear; the others are 'possible', shown but never
    flagged, and la_linked is False for them. strict=False is the model's link: no km rule and no end-point rule.
    Returns one row per project_key and the (project_key, nh, stretch_id, la_match_method) pairs. master has a
    RangeIndex."""
    road = master["sector"].eq("Roads & Highways")
    dist = districts_in(master["project_name"], st)
    # ponytail: a district name shared by two states (Aurangabad: Maharashtra and Bihar) makes a Multi-State road a
    # candidate in both; it links only where its NH is in that state's table too. Needs a location field to do better.
    own = pd.DataFrame({"idx": master.index, "state": state_key(master["state"].fillna(""))})
    multi = dist.loc[master["state"].eq("Multi-State").to_numpy()[dist["idx"]], ["idx", "state"]]
    at = pd.concat([own[own["state"].isin(set(st["state"]))], multi]).drop_duplicates()
    has_land = master.index.isin(at["idx"])
    nh = named_nh = nh_from_text(master["project_name"].fillna("") + " " + master["codes_seen"].fillna(""))
    if strict:
        ends = nh_endpoints(master["project_name"])
        nh = pd.Series([";".join(v for v in n.split(";") if v not in e) or None if isinstance(n, str) else None
                        for n, e in zip(nh, ends)], index=nh.index, dtype="str")
    at = at[road.to_numpy()[at["idx"]] & nh.notna().to_numpy()[at["idx"]]]
    cand = at.assign(project_key=master["project_key"].to_numpy()[at["idx"]], nh=nh.to_numpy()[at["idx"]])
    cand = cand.assign(nh=cand["nh"].str.split(";")).explode("nh")
    km = km_range(master["project_name"])
    use_km = strict and "chainage_start_km" in st
    chain = st.loc[sane_chainage(st), ["stretch_id", "chainage_start_km", "chainage_end_km"]] if use_km else None
    found = []

    def rest():
        done = pd.concat([f["project_key"] for f in found]) if found else pd.Series([], dtype="str")
        return cand[~cand["project_key"].isin(done)]

    def on_km(c):
        """Per candidate (idx, stretch_id) row: 'yes' where the stretch shares more than KM_TOL km (or half the
        shorter span) with the km range of the name ('30.05-49.15' only touching 'km 49.15 to 64.5' is a neighbour),
        'no' where both are known and it does not, 'unknown' otherwise."""
        if not use_km:
            return np.full(len(c), "unknown")
        x = c[["idx", "stretch_id"]].join(km, on="idx").merge(chain, on="stretch_id", how="left")
        lo, hi = np.fmin(x["chainage_start_km"], x["chainage_end_km"]), np.fmax(x["chainage_start_km"],
                                                                              x["chainage_end_km"])
        shared = np.fmin(hi, x["km_to"]) - np.fmax(lo, x["km_from"])
        need = np.fmin(KM_TOL, 0.5 * np.fmin(hi - lo, x["km_to"] - x["km_from"])).clip(lower=0.05)
        return np.select([x["km_from"].isna() | lo.isna(), shared >= need], ["unknown", "yes"], "no")

    by_nh = cand.merge(st[["state", "nh", "stretch_id"]], on=["state", "nh"])
    by_nh = by_nh.assign(km=on_km(by_nh))
    # a km range in the name that contradicts a stretch's own chainage rules the stretch out at every step
    found.append(by_nh[by_nh["km"].eq("yes")].assign(la_match_method="nh_chainage"))
    named = dist.assign(project_key=master["project_key"].to_numpy()[dist["idx"]])[["project_key", "state",
                                                                                    "district"]]
    ex = st.explode("districts").rename(columns={"districts": "district"})[["state", "district", "stretch_id"]]
    left = by_nh[by_nh["km"].eq("unknown")]
    by_d = left[left["project_key"].isin(rest()["project_key"])].merge(named, on=["project_key", "state"]).merge(
        ex, on=["state", "district", "stretch_id"]).assign(la_match_method="nh_district")
    found.append(by_d)
    found.append(left[left["project_key"].isin(rest()["project_key"])].assign(la_match_method="nh_only"))
    km_miss = master["project_key"].isin(by_nh["project_key"]) & ~master["project_key"].isin(
        pd.concat([f["project_key"] for f in found]))
    pairs = pd.concat(found, ignore_index=True)[["project_key", "nh", "stretch_id", "la_match_method"]]
    agg = aggregate(pairs.merge(st.drop(columns="nh"), on="stretch_id"), ["project_key"])
    pg = pairs.groupby("project_key")
    agg["la_nh"] = agg["project_key"].map(pg["nh"].agg(joined)).astype("str")
    agg["la_match_method"] = agg["project_key"].map(pg["la_match_method"].first())
    out = master[["project_key"]].merge(agg, on="project_key", how="left")
    linked_any = out["stretches"].notna()
    out["la_linked"] = linked_any & out["la_match_method"].isin(LA_CONFIDENT)
    reason = np.select([~road, ~has_land, named_nh.isna(), nh.isna(), km_miss.to_numpy()],
                       ["not_road", "no_land_data_for_state", "no_nh_in_name", "nh_only_as_end_point",
                        "no_stretch_at_its_km"], "nh_not_in_table")
    out["la_match_method"] = out["la_match_method"].fillna(pd.Series(reason, index=out.index))
    out["la_state"] = np.select([out["la_linked"] & (out["complexity_max"] >= LA_FLAG), out["la_linked"], linked_any],
                                ["flagged", "clear", "possible"], "unknown")
    out = out.rename(columns={c: f"la_{c}" for c in ["stretches", "parcels", "area_ha", "complexity_max",
                                                    "notif_span_days_max", "first_notif", "last_notif", "districts"]})
    for c in ["la_stretches", "la_parcels", "la_complexity_max", "la_notif_span_days_max"]:
        out[c] = out[c].astype("Int64")
    km_txt = ("km " + km["km_from"].map("{:g}".format, na_action="ignore").astype("str") + "-"
              + km["km_to"].map("{:g}".format, na_action="ignore").astype("str"))
    where = out["project_key"].map(by_d.groupby("project_key")["district"].agg(joined)).astype("str")
    where = where.str.title().str.replace(";", ", ").where(out["la_match_method"].eq("nh_district"))
    where = where.fillna(km_txt.where(out["la_match_method"].eq("nh_chainage")))
    where = (" (" + where + ")").fillna("")
    years = ((out["la_last_notif"] - out["la_first_notif"]).dt.days / 365.25).round(1).astype("str")
    parcels = out["la_parcels"].map(lambda v: f"{int(v):,}", na_action="ignore")
    why = out["la_match_method"].map(LA_POSSIBLE_WHY)
    possible = ("possible link, " + why + ": ").where(out["la_state"].eq("possible") & why.notna(), "")
    out["la_evidence"] = (possible + "NH-" + out["la_nh"].str.replace(";", ", NH-") + where + ": " + parcels
                          + " parcels over " + years + " years of notifications, complexity "
                          + out["la_complexity_max"].astype("str") + "/5").where(linked_any)
    return out[LA_COLS], pairs


def land_pairs(pairs, st):
    """link_land pairs -> one row per (project_key, stretch_id) with the stretch's LA_PAIR_COLS."""
    pairs = pairs.drop_duplicates(["project_key", "stretch_id"]).merge(st[LA_PAIR_COLS], on="stretch_id")
    return pairs.sort_values(["project_key", "stretch_id"], ignore_index=True)


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
    rows = load_rows("typed_rows", silver)
    seen, m = mentions(rows)
    ev = events(seen, m, master)
    qf = quarter_facts(rows)
    out.mkdir(parents=True, exist_ok=True)
    ev.to_parquet(out / "project_events.parquet", index=False)
    quarter_mentions(seen, m).merge(qf, on=["project_key", "period"], how="left").to_parquet(
        out / "project_mentions.parquet", index=False)
    rs = remark_status(qf)
    rs.to_parquet(out / "remark_status.parquet", index=False)
    print(f"project_events: {len(ev)} events from {len(m)} mentions over {ev['project_key'].nunique()} projects, "
          f"{time.time() - t0:.1f}s")
    rc = rs[rs["project_key"].isin(cur)]
    print(f"remark facts, as of {qf['period'].max():%Y-%m} at the latest (projects / key-quarters; current "
          f"portfolio of {len(cur)}):")
    print(pd.DataFrame({"projects": rs[REMARK_FACTS].notna().sum(), "key_quarters": qf[REMARK_FACTS].notna().sum(),
                        "current": rc[REMARK_FACTS].notna().sum()}).to_string())
    print(qf["fc_stage"].value_counts().to_string())
    ev_cur = ev[ev["project_key"].isin(cur)]
    print(pd.concat({"all": pd.crosstab(ev["category"], ev["status"], margins=True),
                     f"current ({len(cur)})": pd.crosstab(ev_cur["category"], ev_cur["status"], margins=True)},
                    axis=1).fillna(0).astype("int64").to_string())
    with pd.option_context("display.width", 250, "display.max_colwidth", 120):
        print(ev.sample(min(10, len(ev)), random_state=0)[
            ["project_key", "category", "subtype", "first_seen", "last_seen", "n_mentions", "status", "authority",
             "evidence"]].to_string(index=False))

    asof = obs["period"].max()
    links = pd.concat([parivesh.remark_links(rs), pd.read_csv(parivesh.LINKS, dtype="str").assign(
        link_source="reviewed name match")[["project_key", "proposal_no", "link_source"]]], ignore_index=True)
    links = links.drop_duplicates(["project_key", "proposal_no"])     # a remark number wins over a name match
    prop = parivesh.proposal_rows(links, parivesh.load_legacy(), parivesh.load_timelines(), asof)
    named = prop.merge(links.loc[links["link_source"].eq("report remarks"), ["project_key", "proposal_no"]])
    named.to_parquet(out / "fc_proposal_status.parquet", index=False)
    portal = parivesh.portal_projects(prop, links, ev, asof)
    portal.to_parquet(out / "external_fc_portal.parquet", index=False)
    # the remark-named proposals found on the portal set the forest area and whether the clearance is pending
    found = named[named["found_in"].ne("not_found")]
    over = found.groupby("project_key").agg(area_ha=("area_ha", "sum"),
                                            pending=("stage_at_asof", lambda s: s.ne(parivesh.STAGE_ORDER[3]).any()))
    pc = portal[portal["project_key"].isin(cur)]
    print(f"PARIVESH: {len(named)} proposal numbers named in remarks ({int(found.shape[0])} found), "
          f"{len(portal)} projects with a linked proposal ({len(pc)} current; open at {asof:%Y-%m}: "
          f"{int(pc['n_open'].gt(0).sum())}, open on the portal but not in the report: "
          f"{int(pc['open_not_in_report'].sum())})")
    with pd.option_context("display.width", 250, "display.max_colwidth", 250):
        print(named[["project_key", "evidence"]].to_string(index=False))

    scen = pd.read_csv(EXTERNAL / "parivesh_fc_scenarios.csv")
    fc = forest_clearance(master, ev, scen, over.reset_index())
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
    land_pairs(pairs, st).to_parquet(out / "external_land_links.parquet", index=False)
    # the model's input (gold la_*_by_t): the table and link its features were backtested on, see LA_MODEL_TABLE
    st_model = stretches(read_land(EXTERNAL / LA_MODEL_TABLE))
    land_pairs(link_land(master, st_model, strict=False)[1], st_model).to_parquet(
        out / "external_land_pairs.parquet", index=False)
    lc = land[land["project_key"].isin(cur)]
    print(f"external_land: {len(st)} stretches in {st['state'].nunique()} state(s) "
          f"({', '.join(sorted(st['state'].unique()))}) on {len(by_nh)} NH ids ({len(by_nh_district)} NH x district); "
          f"{int(land['la_linked'].sum())} projects linked ({int(land['la_state'].eq('possible').sum())} more "
          f"possible), {int(lc['la_linked'].sum())} of {len(lc)} current ones "
          f"({int(lc['la_state'].eq('possible').sum())} possible)")
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
