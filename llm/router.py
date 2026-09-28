"""The chat's deterministic router (docs/AI_ASSISTANT.md): the question -> intents, entities and tool calls, with no
LLM and in well under 50 ms, so most questions never wait for the planner.

Entities, each matched against the served portfolio (never a hand list that goes stale):
  project   a PRJ key ('PRJ-000698', 'prj 698'); 'this project' / 'this one' -> the open project (projectKey); a name
            by its distinctive words: the scout's place words (backend/live/scout.py: name words of 4+ letters in at
            most DF_MAX current project names, not the state's own words), matched exactly or, for a word of 5+
            letters, by rapidfuzz ratio >= FUZZ_MIN with the same first letter (a typo; not the word with a plural
            ending added or taken away, 'train' is no typo of 'trains'); question and filler words never match.
            Each matched word votes for its projects weighted 1 / (projects that share it); the project with the
            most words wins, ties are ambiguous (narrowed by a sector, state or tier the question names, else the
            candidates are listed, never guessed; below CONFIDENT when the word was only a near match). Only
            projects in the viewer's scope take part, so an out-of-scope name matches nothing. A
            place too common to be a place word ('nagpur') is searched as a name fragment when a project name in
            scope contains it. A question naming no project but reading as a follow-up ('it', 'its',
            'that project', 'what about ...', 'tell me more', or an intent that needs a project with no filter)
            takes the previous turn's project (its user message, else a PRJ key in the answer), else the open
            project.
  filters   tier words (Critical anywhere; High, Medium, Low, Watch next to risk/tier/projects), sector words (the
            sectors' own words and a few aliases: road, rail, airport ...), state names (with & / and), 'ministry of X'
            / 'X ministry', single-word agency names (upper case only when short or an English word: OIL, DOT),
            an outside factor (land, forest, court, contractor, utility shifting, inter-agency), 'top N', a sort
            word (riskiest, biggest, most delayed, least progress), near completion, 'by state / sector / ...'.
  intents   compare, explain, history, news, external, opinion, agency, bottleneck, count, stats, list, help, each a
            keyword pattern.
Intents map to calls (route()); a confident route (a project and an intent, or filters and a list/count/stats
intent, or a help question) runs as is, a weak one (confidence < CONFIDENT) goes to the planner when the LLM is up,
else its calls run with the fallback's: search_knowledge(q) + search_projects(q) on the longest word that a project
name in scope contains. A per-project intent over a filtered list ('why are the Critical projects in Odisha
Critical') runs the list first and names the per-project tool (detail) for the second round over its top keys.
Every call's arguments are validated by the tool's own model here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from backend import serving
from backend.live import scout
from llm import tools

CONFIDENT = 0.5
FUZZ_MIN = 88
MAX_CANDIDATES = 8
KEY_RX = re.compile(r"\bPRJ[-\s]?(\d{1,6})\b", re.I)
THIS_RX = re.compile(r"\b(?:this|the open|the current|same)\s+(?:project|one|scheme|work)\b|\bthis\b(?=\s*[?.!]?$)",
                     re.I)
PRONOUN_RX = re.compile(r"\b(?:it|its|it's|that project|that one|the project)\b|^\s*(?:and|what about|how about"
                        r"|also)\b", re.I)
MORE_RX = re.compile(r"^\s*(?:(?:please\s+)?(?:tell|show|give) me\s+)?more(?:\s+(?:details?|info(?:rmation)?))?"
                     r"(?:\s+please)?\s*[?.!]*\s*$", re.I)  # 'tell me more': a follow-up with no pronoun
INTENTS = {
    "compare": r"\bcompar\w*|\bvs\.?(?=\s)|\bversus\b|\bdifference between\b",
    "explain": r"\bwhy\b|\breasons?\b|\bdrivers?\b|\bexplain\w*|\bcaus\w*|\bwhat makes\b|\bbehind\b",
    "history": r"\bchang\w*|\btrend\w*|\bprogress over\b|\bhistory\b|\bover time\b|\btimeline\b|\bmoved\b"
               r"|\bslipp?ed\b|\blast (?:few |two |three |\d )?(?:reports?|quarters?)\b|\bsince when\b",
    "news": r"\bnews\b|\blatest (?:news|updates?|developments?|on|about)\b|\bupdates?\b|\bresearch\w*|\bhappening\b"
            r"|\bmedia\b|\bheadlines?\b|\bwhat'?s new\b|\bin the press\b",
    "external": r"\bland\b|\bforest\b|\bclearances?\b|\bcourts?\b|\bparivesh\b|\blitigation\b|\bcontractors?\b"
                r"|\benvironment\w*|\butility\b|\boutside factors?\b|\bexternal\b|\bblockers?\b|\bearly notice\b"
                r"|\binter-?agency\b",
    "opinion": r"\bsecond opinion\b|\bai (?:opinion|view)\b|\bopinion\b",
    "agency": r"\bagenc(?:y|ies)\b|\bscorecard\b|\btrack record\b|\bimplementing\b",
    "bottleneck": r"\bbottlenecks?\b|\bclusters?\b|\bblocking\b",
    "count": r"\bhow many\b|\bnumber of\b|\bcount\b|\bhow much\b|\btotal\b",
    "stats": r"\b(?:by|per|each|every)\s+(?:state|sector|ministry|tier)\b|\b(?:state|sector|ministry|tier)[- ]?wise\b"
             r"|\bbreak ?down\b|\bdistribution\b|\boverview\b|\bportfolio\b|\bsummary\b"
             r"|\bwhich (?:state|sector|ministry)\b",
    "list": r"\blist\b|\bshow\b|\btop\s+\d|\bwhich\b|\briskiest\b|\bbiggest\b|\blargest\b|\bcostliest\b"
            r"|\bnear(?:ing|est)?\s+(?:to\s+)?complet\w*|\bclosest to complet\w*|\balmost (?:done|complete)\b"
            r"|\bmost delayed\b|\bprojects\b|\bones\b",
    "help": r"\bwhat (?:is|are|does|do)\b|\bhow (?:does|do|is|are|old|often|reliable|accurate|should)\b"
            r"|\bmean(?:s|ing|t)?\b|\bdefin\w*|\bmethod\w*|\bwhere does\b|\bwhat can\b|\bcan you\b|\bhelp\b"
            r"|\bwho (?:makes|built|runs)\b",
}
INTENT_RX = {k: re.compile(v, re.I) for k, v in INTENTS.items()}
HELP_TOPIC = re.compile(r"\btiers?\b|\bwatch\b|\bstalled\b|\bprobabilit\w*|\bchances?\b|\bchecks?\b|\bchecklist\b"
                        r"|\bearly notice\b|\bdata\b|\bsources?\b|\bmodel\b|\bassistant\b|\bpaimana\b|\bscores?\b"
                        r"|\brisk (?:level|rating)\b|\bmean(?:s|ing|t)?\b|\bdefin\w*|\bmethod\w*|\bupdated?\b"
                        r"|\bcalculat\w*|\bpredict\w*|\baccura\w*|\breliab\w*", re.I)
PER_PROJECT = {"explain", "history", "news", "external", "opinion"}
TIER_RX = re.compile(r"\b(critical)\b|\b(high|medium|low|watch)(?=[\s-]*(?:risk|tier|projects?|ones|category|list)\b)"
                     r"|\b(?:tier|is|are|in)\s+(high|medium|low|watch)\b", re.I)
FACTOR_RX = [("land", re.compile(r"\bland\b", re.I)),
             ("forest_clearance", re.compile(r"\bforest\b|\benvironment\w*|\bparivesh\b|\bclearances?\b", re.I)),
             ("litigation", re.compile(r"\bcourts?\b|\blitigation\b|\blegal\b|\blawsuits?\b|\bcase in\b", re.I)),
             ("contractor", re.compile(r"\bcontractors?\b", re.I)),
             ("utility_shifting", re.compile(r"\butility\b|\butilities\b", re.I)),
             ("inter_agency", re.compile(r"\binter-?agency\b|\banother agency\b", re.I))]
FACTOR_TO_FLAG = {"land": "land", "forest_clearance": "forest", "litigation": "litigation", "contractor": "contractor"}
FACTOR_TO_CATEGORY = {"land": "land", "forest_clearance": "forest_env", "litigation": "litigation",
                      "contractor": "contractor", "utility_shifting": "utility_shifting",
                      "inter_agency": "inter_agency"}
MOST_RX = re.compile(r"\bmost\b|\bfewest\b|\bhighest number\b|\bhow many\b", re.I)  # rank groups by count
GROUP_RX = re.compile(r"\b(?:by|per|each|every|which)\s+(state|sector|ministry|tier)\b"
                      r"|\b(state|sector|ministry|tier)[- ]?wise\b", re.I)
LIMIT_RX = re.compile(r"\btop\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:riskiest|biggest|largest|most|worst|projects)\b", re.I)
SORTS = [("cost", re.compile(r"\bbiggest\b|\blargest\b|\bcostliest\b|\bmost expensive\b|\bby cost\b", re.I)),
         ("slip", re.compile(r"\bmost delayed\b|\bslipped (?:the )?most\b|\blongest delay\w*|\bby slip\b", re.I)),
         ("progress", re.compile(r"\bleast progress\b|\bslowest\b|\blowest progress\b", re.I)),
         ("risk", re.compile(r"\briskiest\b|\bmost at risk\b|\bby risk\b", re.I))]
AGENCY_SORTS = [("schedule_overrun", re.compile(r"\bworst\b|\bslowest\b|\blate\b|\bdelay\w*|\bpoor\w*|\boverrun\w*"
                                              r"|\bbehind\b", re.I)),
                ("cost_overrun", re.compile(r"\bcost overrun\w*|\bover budget\b|\bcost escalat\w*", re.I))]
AGENCY_SORTS.reverse()  # a cost overrun question is about cost first
NEAR_RX = re.compile(r"\bnear(?:ing|est)?\s+(?:to\s+)?complet\w*|\bclosest to complet\w*|\balmost (?:done|complete\w*)"
                     r"|\babout to (?:finish|complete)\b", re.I)
SECTOR_ALIASES = {"road": "Roads & Highways", "roads": "Roads & Highways", "highway": "Roads & Highways",
                  "highways": "Roads & Highways", "rail": "Railways", "railway": "Railways",
                  "electricity": "Power", "hospital": "Health", "hospitals": "Health", "irrigation": "Water Resources",
                  "university": "Education", "universities": "Education", "telecom": "Telecommunications",
                  "airport": "Civil Aviation", "airports": "Civil Aviation", "aviation": "Civil Aviation",
                  "mining": "Mines & Metals", "port": "Shipping & Ports", "ports": "Shipping & Ports",
                  "shipping": "Shipping & Ports", "oil": "Petroleum & Natural Gas",
                  "refinery": "Petroleum & Natural Gas",
                  "urban": "Urban Development & Housing", "housing": "Urban Development & Housing"}
STATE_ALIASES = {"orissa": "Odisha", "j&k": "Jammu & Kashmir", "tamilnadu": "Tamil Nadu", "new delhi": "Delhi",
                 "andaman": "Andaman & Nicobar Islands", "pondicherry": "Puducherry"}
NOT_STATES = {"Multi-State", "PAN India", "Offshore"}
ENGLISH = {"oil", "dot", "sail", "port", "hcl", "ppt", "dpt", "cr", "er", "nr", "sr", "wr", "ner", "ecr", "scr", "ncr",
           "ser", "nfr", "wcr", "nwr", "swr", "secr", "ecor", "scor"}  # agency names matched in upper case only
FILLER = {"tell", "know", "want", "need", "like", "look", "find", "give", "some", "more", "less", "than", "then",
          "your", "mine", "ours", "onto", "upon", "just", "very", "such", "here", "interesting", "something", "thing",
          "anything", "happened", "happen", "going", "doing", "okay", "thanks", "thank", "hello", "please", "kind",
          "sort", "type", "types", "okay", "nothing", "everyone", "people", "public", "citizen", "citizens"}
# words of a question that are never a project name, even when a name happens to contain them
QUESTION_WORDS = {
    "what", "which", "when", "where", "show", "list", "many", "much", "project", "projects", "about", "latest", "news",
    "update", "updates", "changed", "change", "changes", "progress", "history", "trend", "compare", "explain",
    "reason", "reasons", "driver", "drivers", "critical", "high", "medium", "watch", "tier", "tiers", "risk", "risky",
    "riskiest", "delay", "delayed", "delays", "cost", "costs", "status", "completion", "complete", "completed",
    "near", "closest", "land", "forest", "clearance", "court", "litigation", "contractor", "contractors",
    "environment", "research", "opinion", "second", "agency", "agencies", "bottleneck", "bottlenecks", "there",
    "their", "this", "that", "these", "those", "with", "from", "have", "does", "mean", "means", "stalled", "data",
    "state", "states", "sector", "sectors", "ministry", "give", "tell", "please", "over", "time", "last", "since",
    "between", "versus", "happening", "blockers", "blocker", "biggest", "largest", "slipped", "slip", "chance",
    "early", "notice", "quarter", "quarters", "report", "reports", "show", "same", "open", "current", "same", "they",
    "them", "compare", "comparison", "difference", "summary", "overview", "portfolio", "total", "number", "count",
    "within", "under", "into", "most", "least", "wise", "each", "every", "done", "almost", "going", "work", "works",
    "doing", "much", "also", "only", "same", "other", "another", "some", "still", "being", "been", "were", "will",
    "would", "could", "should", "whose", "whom", "outside", "factors", "factor", "external", "utility", "shifting",
    "track", "record", "scorecard", "implementing", "worst", "best", "good", "well", "badly", "lately", "recently",
    "recent", "things", "anything", "everything", "headline", "headlines", "media", "press", "second", "view",
    "exactly", "really", "right", "wrong", "risks", "issue", "issues", "problem", "problems", "stuck", "cleared",
    "pending", "rise", "rising", "fall", "falling", "increase", "increased", "revised", "revision", "expected",
    "finish", "finished", "money", "spent", "spend", "budget", "crore", "lakh", "percent", "month", "months",
    "year", "years", "today", "help", "assistant", "paimana", "model", "score", "scores", "check", "checks",
    "method", "calculated", "predict", "prediction", "predicted", "accurate", "reliable", "define", "meaning",
    "cluster", "clusters", "blocking", "legal", "case", "cases", "interagency", "parivesh", "flagged", "flag",
    "flags", "government", "central", "india", "indian", "national", "scheme", "schemes", "construction",
    "acquisition", "acquired", "acquire", "across", "whole", "entire", "country", "nationwide", "overall",
    "happens",
}


@dataclass
class Route:
    question: str
    intents: list[str]
    calls: list[dict]
    confidence: float
    keys: list[str] = field(default_factory=list)        # projects the question is about, in order of mention
    candidates: list[str] = field(default_factory=list)  # an ambiguous name: the projects it could be
    filters: dict = field(default_factory=dict)
    followup: bool = False
    detail: str | None = None                            # the per-project tool of a second round over a list
    reason: str = ""
    name_word: str | None = None                         # the best name word, for search_projects(q=...)
    used: set[str] = field(default_factory=set)          # the question's words that named a filter


# ------------------------------------------------------------------ vocabulary

@serving.cached
def _chat_router_vocab(s) -> dict:
    """The portfolio's filter words (sector, state and agency patterns) and the scout's place-word index."""
    sectors = tools.values("sector")
    words: dict[str, set[str]] = {}
    for low, sector in sectors.items():
        for w in re.findall(r"[a-z]{4,}", low):
            words.setdefault(w, set()).add(sector)
    sector_words = {w: next(iter(s_)) for w, s_ in words.items()
                    if len(s_) == 1 and w not in {"natural", "development"}}
    sector_words.update({w: s_ for w, s_ in SECTOR_ALIASES.items() if s_ in sectors.values()})
    states = [st for st in tools.values("state").values() if st not in NOT_STATES]
    state_rx = [(re.compile(r"\b" + re.escape(st).replace(r"\&", r"(?:&|and)").replace(r"\ ", r"\s+") + r"\b", re.I),
                 st) for st in sorted(states, key=len, reverse=True)]
    state_rx += [(re.compile(r"\b" + re.escape(a) + r"(?=\W|$)", re.I), st) for a, st in STATE_ALIASES.items()
                 if st in states]
    agency_rx = []
    for name in tools.values("agency").values():
        if " " in name or not re.fullmatch(r"[A-Z0-9]{2,}", name):
            continue
        flags = 0 if len(name) <= 3 or name.lower() in ENGLISH else re.I
        agency_rx.append((re.compile(rf"\b{re.escape(name)}\b", flags), name))
    idx = scout.index()
    return {"sector_words": sector_words, "state_rx": state_rx, "agency_rx": agency_rx, "index": idx,
            "vocab": sorted(idx["by_token"])}


def vocab() -> dict:
    return _chat_router_vocab()


# ------------------------------------------------------------------ entities

def _keys_in(viewer, text: str) -> list[str]:
    out = []
    for m in KEY_RX.finditer(text):
        k = serving.canonical(f"PRJ-{int(m[1]):06d}")
        if k and viewer.sees(k) and k not in out:
            out.append(k)
    return out


def _filter_words(text: str) -> tuple[dict, set[str]]:
    """The filters a question names and the words they used (kept out of the name match)."""
    v, low, used, f = vocab(), text.lower(), set(), {}
    m = TIER_RX.search(text)
    if m and not re.search(r"\bhigh\s+court\b", low[max(0, m.start() - 1): m.end() + 7]):
        f["tier"] = next(g for g in m.groups() if g).capitalize()
        used.add(f["tier"].lower())
    ministry = (re.search(r"\bministry of ([a-z&, ]+?)(?:\s+(?:projects?|in|with|and|that|which)\b|[?.!,]|$)", low)
                or re.search(r"\b(?!(?:the|my|our|this|that|which|a|your|of)\b)([a-z]+) ministry\b", low))
    if ministry:
        try:
            f["ministry"] = tools.validate_args(_ANY, "search_projects",
                                                {"ministry": ministry[1].strip()})["ministry"]
            used |= set(re.findall(r"[a-z]{4,}", ministry[0]))
        except ValueError:
            pass
    for rx, st in v["state_rx"]:
        m = rx.search(text)
        if m:
            f["state"] = st
            used |= set(re.findall(r"[a-z]{4,}", m[0].lower()))
            break
    if "ministry" not in f:
        for w in re.findall(r"[a-z]{3,}", low):
            if w in v["sector_words"] and w not in used:
                f["sector"] = v["sector_words"][w]
                used.add(w)
                break
    for rx, name in v["agency_rx"]:
        if rx.search(text):
            f["agency"] = name
            used.add(name.lower())
            break
    for factor, rx in FACTOR_RX:
        if rx.search(text):
            f["factor"] = factor
            break
    if re.search(r"\bearly notice\b", low):
        f["flag"] = "early_notice"
    m = LIMIT_RX.search(text)
    if m:
        f["limit"] = max(1, min(20, int(m[1] or m[2])))
    for sort, rx in SORTS:
        if rx.search(text):
            f["sort"] = sort
            break
    if NEAR_RX.search(text):
        f["near_complete"] = True
    m = GROUP_RX.search(text)
    if m:
        f["group_by"] = (m[1] or m[2]).lower()
    return f, used


@dataclass(frozen=True)
class _AnyViewer:  # validates filter spellings only; never runs a tool
    role: str = "ipmd_analyst"

    def can(self, feature: str) -> bool:
        return True


_ANY = _AnyViewer()


def _inflection(w: str, hit: str) -> bool:
    """hit is w with a plural ending added or taken away ('train' / 'trains', 'bridge' / 'bridges'): an ordinary
    English word, not a typo of a place word."""
    return any(a == b + end for a, b in ((w, hit), (hit, w)) for end in ("s", "es"))


def _names(viewer, text: str, skip: set[str]) -> tuple[list[str], list[str], str | None]:
    """(projects named, in order; the candidates of an ambiguous name; the best name word) by place words."""
    v = vocab()
    by_token, keys = v["index"]["by_token"], viewer.keys
    words = [w for w in dict.fromkeys(scout.WORD_RX.findall(text.lower()))
             if w not in QUESTION_WORDS and w not in FILLER and w not in skip]
    owners: dict[str, list[str]] = {}  # matched place word -> its projects in the viewer's scope
    for w in words:
        hit = w if w in by_token else None
        if hit is None and len(w) >= 5:
            best = process.extractOne(w, v["vocab"], scorer=fuzz.ratio, score_cutoff=FUZZ_MIN)
            hit = best[0] if best and best[0][0] == w[0] and not _inflection(w, best[0]) else None
        ks = [k for k in by_token.get(hit, ()) if keys is None or k in keys] if hit else []
        if ks and hit not in owners:
            owners[hit] = ks
    if not owners:
        return [], [], None
    votes: dict[str, tuple[int, float, int]] = {}
    for ks in owners.values():
        for k in ks:
            n, score, first = votes.get(k, (0, 0.0, len(votes)))
            votes[k] = (n + 1, score + 1.0 / len(ks), first)
    ranked = sorted(votes, key=lambda k: (-votes[k][0], -votes[k][1], votes[k][2]))
    top = ranked[0]
    ties = [k for k in ranked if votes[k][:2] == votes[top][:2]]
    unique = list(dict.fromkeys(ks[0] for ks in owners.values() if len(ks) == 1))
    word = next(w for w, ks in owners.items() if top in ks)
    if len(ties) > 1:
        # tied projects that each have a word of their own are several projects named (compare A and B); tied
        # projects that share the only words are one ambiguous name
        named = [k for k in ties if k in unique]
        return (named[:4], [], word) if len(named) > 1 else ([], ties[:MAX_CANDIDATES], word)
    return ([top] + [k for k in unique if k != top])[:4], [], word


def _previous_project(viewer, messages: list[dict]) -> str | None:
    """The project of the previous turn: named in an earlier user message (latest first), else a PRJ key in an
    earlier answer."""
    for m in reversed(messages[:-1]):
        if m["role"] == "user":
            keys = _keys_in(viewer, m["content"]) or _names(viewer, m["content"], _filter_words(m["content"])[1])[0]
            if keys:
                return keys[0]
    for m in reversed(messages[:-1]):
        if m["role"] == "assistant":
            keys = _keys_in(viewer, m["content"])
            if keys:
                return keys[0]
    return None


# ------------------------------------------------------------------ route

def intents_of(text: str) -> list[str]:
    return [name for name, rx in INTENT_RX.items() if rx.search(text)]


def _call(viewer, tool: str, **args) -> dict | None:
    """A call with its arguments validated (None when the tool is not the viewer's or an argument is wrong)."""
    args = {k: v for k, v in args.items() if v is not None}
    try:
        checked = tools.validate_args(viewer, tool, args)
    except ValueError:
        return None
    return {"tool": tool, "args": {k: checked[k] for k in args}}


def _search_filters(f: dict) -> dict:
    return {k: f.get(k) for k in ("tier", "sector", "state", "ministry", "agency", "sort", "limit")} | {
        "flag": f.get("flag") or FACTOR_TO_FLAG.get(f.get("factor")), "near_complete": f.get("near_complete")}


def route(viewer, messages: list[dict], project_key: str | None = None) -> Route:
    """Intents, entities and the tool calls for the last user message (module docstring)."""
    q = messages[-1]["content"].strip()
    intents = intents_of(q)
    filters, used = _filter_words(q)
    keys = _keys_in(viewer, q)
    candidates, word = [], None
    if not keys:
        keys, candidates, word = _names(viewer, q, used)
    if candidates and {"sector", "state", "tier"} & set(filters):  # 'the Darbhanga airport': the sector decides
        rows = serving.rows_for_keys(tuple(candidates))
        fit = [x["key"] for x in rows if all(x[c] == filters[c] for c in ("sector", "state", "tier") if c in filters)]
        keys, candidates = (fit, []) if len(fit) == 1 else ([], fit or candidates)
    open_key = project_key if project_key and viewer.sees(project_key) else None
    followup = False
    if not keys and not candidates:
        unfiltered = not ({"tier", "sector", "state", "ministry", "agency", "near_complete"} & set(filters))
        wants_project = bool(set(intents) & PER_PROJECT) and unfiltered and not set(intents) & {"count", "stats"}
        if THIS_RX.search(q) and open_key:
            keys, followup = [open_key], True
        elif ((PRONOUN_RX.search(q) or MORE_RX.match(q)) and unfiltered) or wants_project:
            prev = _previous_project(viewer, messages)
            if prev or open_key:
                keys, followup = [prev or open_key], True
    r = Route(q, intents, [], 0.0, keys, candidates, filters, followup, name_word=word, used=used)
    official = viewer.can("insights")
    calls: list[dict | None] = []
    if keys:
        _project_calls(viewer, r, calls, official)
    else:
        _portfolio_calls(viewer, r, calls, official)
    seen, out = set(), []
    for c in calls:
        if c and (c["tool"], repr(sorted(c["args"].items()))) not in seen:
            seen.add((c["tool"], repr(sorted(c["args"].items()))))
            out.append(c)
    r.calls = out[:4]
    if not r.calls:
        r.confidence, r.reason = 0.0, r.reason or "no call"
    return r


def _project_calls(viewer, r: Route, calls: list, official: bool) -> None:
    p, it = r.keys[0], set(r.intents)
    r.confidence, r.reason = 0.9, "project" + (" (follow-up)" if r.followup else "")
    if "compare" in it and len(r.keys) >= 2:
        calls.append(_call(viewer, "compare_projects", keys=r.keys[:4]))
        return
    if "explain" in it:
        calls.append(_call(viewer, "explain_prediction", key=p) if official else None)
        calls.append(_call(viewer, "get_project", key=p))
    if "history" in it:
        calls.append(_call(viewer, "project_history", key=p))
    if "news" in it:
        calls.append(_call(viewer, "project_research", key=p))
    if "external" in it:
        calls.append(_call(viewer, "external_factors", key=p))
    if "opinion" in it and official:
        calls.append(_call(viewer, "second_opinion", key=p))
    if not any(calls):  # also under a help word: 'what is the tier of X' needs the project before the help text
        calls.append(_call(viewer, "get_project", key=p))
    if "help" in it and HELP_TOPIC.search(r.question):
        calls.append(_call(viewer, "search_knowledge", q=r.question[:300]))
    if "compare" in it:  # compare with only one project named: the planner may find the other
        r.confidence, r.reason = 0.4, "compare needs two projects"


def _leftover(viewer, q: str, used: set[str]) -> str | None:
    """The longest word of the question that is no question word, filter or filler and that a project name in the
    viewer's scope contains (a place too common to be a place word, 'nagpur'): a name fragment to search."""
    words = [w for w in scout.WORD_RX.findall(q.lower()) if w not in QUESTION_WORDS | FILLER and w not in used]
    for w in sorted(dict.fromkeys(words), key=len, reverse=True):
        if serving.projects(q=w, size=1, scope=viewer.scope)["total"]:
            return w
    return None


def _portfolio_calls(viewer, r: Route, calls: list, official: bool) -> None:
    it, f, q = set(r.intents), r.filters, r.question
    scoped = {"tier", "sector", "state", "ministry", "agency", "near_complete", "flag"} & set(f)
    listy = bool(it & {"list", "count", "stats"}) or bool(scoped) or "limit" in f
    word = None if scoped else _leftover(viewer, q, r.used)
    per_project = it & {"explain", "history", "opinion", "news"}
    narrowed = bool(scoped or word)
    if r.candidates:  # a name that fits several projects: list them, the writer asks which
        calls.append(_call(viewer, "search_projects", q=r.name_word, limit=MAX_CANDIDATES))
        if r.name_word in scout.WORD_RX.findall(q.lower()):
            r.confidence, r.reason = 0.7, "ambiguous name"
        else:  # only a near match of a word of the question (a typo, or not a name at all): the planner decides
            r.confidence, r.reason = 0.4, "ambiguous near match"
        return
    if "help" in it and HELP_TOPIC.search(q) and not (it & {"count", "stats", "bottleneck", "agency"}) \
            and not (scoped - {"tier"}):
        calls.append(_call(viewer, "search_knowledge", q=q[:300]))
        r.confidence, r.reason = 0.85, "help"
        return
    if "bottleneck" in it and viewer.can("bottlenecks"):
        calls.append(_call(viewer, "bottlenecks", category=FACTOR_TO_CATEGORY.get(f.get("factor")),
                           state=f.get("state"), limit=min(f.get("limit") or 5, 10)))
    if ("agency" in it or (f.get("agency") and not it & {"list", "count", "stats"})) and viewer.can("agencies") \
            and not (it & {"list", "count"} and scoped - {"agency"}):
        sort = next((s_ for s_, rx in AGENCY_SORTS if rx.search(q)), None)
        calls.append(_call(viewer, "agency_scorecard", agency=f.get("agency"), sort=sort))
    topical = it & {"external", "news", "agency", "bottleneck"}  # 'portfolio' / 'overview' alone is no breakdown
    if ("stats" in it and (f.get("group_by") or not topical)) or ("count" in it and not narrowed and not topical):
        calls.append(_call(viewer, "portfolio_stats", group_by=f.get("group_by") or "tier",
                           rank_by="projects" if MOST_RX.search(q) else None,
                           **{k: f.get(k) for k in ("tier", "sector", "state", "ministry")}))
    if "external" in it and "bottleneck" not in it and f.get("factor"):
        calls.append(_call(viewer, "external_factors", factor=f["factor"], state=f.get("state"),
                           limit=f.get("limit") or 5))
    elif "external" in it and not f.get("factor") and not narrowed and "news" not in it:
        calls.append(_call(viewer, "external_factors"))  # 'research blockers' is the news side
    if "news" in it and not narrowed:
        calls.append(_call(viewer, "project_research"))
    covered = any(c and c["tool"] in ("external_factors", "portfolio_stats", "bottlenecks", "agency_scorecard")
                  for c in calls)
    if (listy and not covered) or (per_project and narrowed):
        calls.append(_call(viewer, "search_projects", q=word, **_search_filters(f)))
        if per_project and narrowed:
            r.detail = ("explain_prediction" if "explain" in per_project and official else
                        "project_history" if "history" in per_project else
                        "project_research" if "news" in per_project else "get_project")
    if any(calls):
        r.confidence, r.reason = 0.85, "portfolio"
        return
    if "help" in it or not it:
        calls.append(_call(viewer, "search_knowledge", q=q[:300]))
        r.confidence, r.reason = 0.3, "nothing matched: knowledge search"
    else:
        r.confidence, r.reason = 0.2, "an intent without its project"


def fallback(viewer, r: Route) -> list[dict]:
    """The calls when neither the router nor the planner has a plan: search the knowledge index and, when the
    question has a name-like word, the project names."""
    word = r.name_word or _leftover(viewer, r.question, r.used)
    calls = [_call(viewer, "search_knowledge", q=r.question[:300]),
             _call(viewer, "search_projects", q=word, limit=5) if word else None]
    return [c for c in calls if c]
