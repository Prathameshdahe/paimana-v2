"""
External factors (docs/IMPLEMENTATION_GUIDE_v2.md A.4, B 2.2 External, B 5.2): delay events from the report
remarks, per project.

Run from repo root after the silver build:  python -m pipeline.run external

Inputs   silver/typed_rows.parquet (every clean remark with its PRJ key), silver/observations.parquet,
         silver/project_master.parquet
Outputs  gold/project_events.parquet

Remarks are free text only in 2014-2023 reports; later reports print templates ('start: 2025-04',
'Milestones achieved/total: 0/7'). Templates are stripped first, the rest is split into sentences and tagged
with TAXONOMY. A quarter counts as remark-observed for a project when one of its reports has free text left,
and an event is a run of consecutive remark-observed quarters that mention the category. It is open when its
last mention is in one of the project's last OPEN_LAST_Q remark-observed quarters, that quarter's mentions do not
all report it done ('EC received on ...'), and the project is not completed.

Remarks come from typed_rows (every accepted clean report row), not observations (the quarter's last remark):
it finds every observations mention plus 6% more key-quarter-category mentions and 16% more events, and the
first mention keeps its own document and page.
"""
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.gold import GOLD  # noqa: E402
from pipeline.silver import SILVER, quarter  # noqa: E402

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
FOREST_HA = (r"(\d+(?:\.\d+)?)\s*(?:ha|hect\w*)\.?\s*(?:of\s+)?(?:\w+\s+){0,2}forest"
             r"|forest\s+land\s*(?:of|:|\(|measuring|admeasuring)?\s*(\d+(?:\.\d+)?)\s*(?:ha|hect)")
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
              "resolved", "subtype", "authority", "forest_area_ha", "evidence", "source_doc_id", "source_page", "state", "sector",
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
    m["forest_area_ha"] = forest_area(m["sentence"]).where(m["category"].eq("forest_env"))
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
               n_mentions=("report", "nunique"), qn_end=("qn", "max"), forest_area_ha=("forest_area_ha", "max"))
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
    return ev


if __name__ == "__main__":
    main()
