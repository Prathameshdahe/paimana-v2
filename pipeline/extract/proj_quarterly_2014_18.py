"""
QPISR quarterly reports 2014-15 .. 2017-18 (16 PDFs) -> projects / summary / manifest parts.

Run from repo root:
    python pipeline/extract/proj_quarterly_2014_18.py            # all files (parallel) + write parts
    python pipeline/extract/proj_quarterly_2014_18.py --one NAME  # one file -> scratch cache only
    python pipeline/extract/proj_quarterly_2014_18.py --merge     # rebuild parts from cache

Parsing is span-based (fitz get_text("dict")): Part II per-project detail blocks
("<n> NAME[CODE]", Location, Capacity, 7-column cost/schedule table, Background
narrative) give the ongoing master list; appendix lists give completed and
additionally-delayed projects; Part I / sector pages give the summary tables (incl. the five
sector-wise cost/time overrun tables with their delay ranges).
"""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, PROJECT_COLS, SUMMARY_COLS, fiscal_year,  # noqa: E402
                    rel, to_num, to_ym, write_part)

FAMILY = "proj_quarterly_2014_18"
SRC_DIR = DATASET / "Project Monitoring" / "Quaterly Reports"
FYS = ["2014-15", "2015-16", "2016-17", "2017-18"]
CACHE = Path(os.environ.get("QPISR_CACHE", Path(os.environ.get("TEMP", "/tmp")) / f"{FAMILY}_cache"))
REPORT_TYPE = "quarterly_qpisr"

QMAP = {"apr": ("Q1", 6), "jul": ("Q2", 9), "oct": ("Q3", 12), "jan": ("Q4", 3)}


def files():
    out = []
    for fy in FYS:
        out += sorted((SRC_DIR / fy).glob("*.pdf"))
    return out


def period_from_name(name):
    """'april-june-2014.pdf' -> ('2014-06', 'Q1'); 'Jan-March_2018.pdf' -> ('2018-03', 'Q4')."""
    n = name.lower()
    m = re.match(r"([a-z]{3})[a-z]*[-_ ]+[a-z]+[-_ ]*(\d{4})", n)
    q, mo = QMAP[m[1]]
    return f"{m[2]}-{mo:02d}", q


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\u00ad", "-").replace("\u2010", "-")).strip()


# ---------------------------------------------------------------- page model
FURNITURE = re.compile(r"^(MoSPI|OCMS|`)$|Hkkjr ljdkj|vkbZ- ih-|ea=ky")


def content_lines(page):
    """page_lines minus running headers/footers (MoSPI/OCMS banner, Hindi footer, page numbers)."""
    h = page.rect.height
    return [ln for ln in page_lines(page)
            if not FURNITURE.search(ln["text"])
            and not (re.fullmatch(r"\d{1,3}", ln["text"]) and (ln["y"] > 0.93 * h or ln["y"] < 0.06 * h))]


def page_lines(page):
    """Visual lines: list of dicts {y, x0, text, spans[(x0,y0,x1,y1,text,flags,size)]}."""
    spans = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                t = s["text"]
                if t.strip():
                    x0, y0, x1, y1 = s["bbox"]
                    spans.append((x0, y0, x1, y1, t, s["flags"], s["size"]))
    spans.sort(key=lambda s: ((s[1] + s[3]) / 2, s[0]))
    lines = []
    for s in spans:
        yc = (s[1] + s[3]) / 2
        if lines and abs(lines[-1]["y"] - yc) <= 2.0:
            lines[-1]["spans"].append(s)
        else:
            lines.append({"y": yc, "spans": [s]})
    for ln in lines:
        ln["spans"].sort(key=lambda s: s[0])
        ln["x0"] = ln["spans"][0][0]
        ln["text"] = clean(" ".join(s[4] for s in ln["spans"]))
    return lines


def is_bold_italic(ln):
    return all((s[5] & 2) and (s[5] & 16) for s in ln["spans"])


def is_bold(ln):
    return all(s[5] & 16 for s in ln["spans"])


HDR_RE = re.compile(r"^(\d{1,4})\s+(.*?)\s*\[\s*([A-Za-z0-9]*)\s*\]\s*$")


# ------------------------------------------------------------ detail blocks
def br(t):
    """bracket kind of a table token: '' plain, '(' revised, '[' anticipated."""
    t = t.strip()
    if t.startswith("["):
        return "["
    if t.startswith("("):
        return "("
    return ""


def unwrap(t):
    return t.strip().strip("[]()").strip()


def parse_table(centers, vals, row_step):
    """centers: x-centres of '(1)'..'(7)'. vals: spans (x0,gy0,x1,gy1,text) with global y.
    Returns dict of project fields."""
    cols = {i: [] for i in range(1, 8)}
    for v in vals:
        xc = (v[0] + v[2]) / 2
        k = min(centers, key=lambda i: abs(centers[i] - xc))
        if abs(centers[k] - xc) < 45:
            cols[k].append(((v[1] + v[3]) / 2, v[4].strip()))
    for k in cols:
        cols[k].sort()
    # row references from the cost column (plain / ( ) / [ ])
    ref = {}
    for c in (2, 4, 6):
        for y, t in cols[c]:
            ref.setdefault(br(t), y)
    if "" not in ref and "(" in ref:
        ref[""] = ref["("] - row_step
    if "(" not in ref and "" in ref:
        ref["("] = ref[""] + row_step
    if "[" not in ref and "(" in ref:
        ref["["] = ref["("] + row_step
    rows = {"": "top", "(": "mid", "[": "bot"}

    def row_of(y):
        if not ref:
            return None
        return rows[min(ref, key=lambda r: abs(ref[r] - y))]

    f = {}

    def triple(c, conv):
        out = {}
        for y, t in cols[c]:
            out.setdefault(br(t), conv(unwrap(t)))
        return out.get(""), out.get("("), out.get("[")

    doa = [t for y, t in cols[1] if br(t) == ""]
    f["doa_original"] = to_ym(doa[0]) if doa else None
    doar = [t for y, t in cols[1] if br(t) == "("]
    f["doa_revised"] = to_ym(unwrap(doar[0])) if doar else None
    f["cost_original_cr"], f["cost_revised_cr"], f["cost_anticipated_cr"] = triple(2, to_num)
    f["cost_overrun_pct"] = triple(3, lambda s: to_num(s.replace("%", "")))[0]
    f["doc_original"], f["doc_revised"], f["doc_anticipated"] = triple(4, to_ym)
    top = [t for y, t in cols[5] if br(t) == "" and row_of(y) == "top"]
    mid = [t for y, t in cols[5] if br(t) == "" and row_of(y) == "mid"]
    paren = [t for y, t in cols[5] if br(t) == "("]
    f["outlay_current_fy_cr"] = to_num(top[0]) if top else None
    f["_exp_prev_march"] = to_num(mid[0]) if mid else None     # cumulative up to the previous March
    f["expenditure_cum_cr"] = to_num(unwrap(paren[-1])) if paren else None
    dl = [t for y, t in cols[6] if br(t) == "" and row_of(y) == "top"]
    f["delay_months"] = to_num(dl[0]) if dl else None
    pp = [to_num(t) for y, t in cols[7] if br(t) == "" and to_num(t) is not None]
    f["_pp_col"] = pp[0] if pp else None
    st = clean(" ".join(t for y, t in cols[7] if to_num(t) is None and t.strip("-() "))).strip("() ")
    if re.sub(r"\s", "", st).lower() == "completed":   # printed split as '(Complet' / 'ed)'
        st = "Completed"
    f["_status"] = st or None
    return f


PP_RE = re.compile(r"physical\s+progress[^%\d]{0,45}?(\d{1,3}(?:\.\d+)?)\s*%", re.I)


def narrative_pp(text):
    vals = {float(v) for v in PP_RE.findall(text or "")}
    vals = {v for v in vals if 0 <= v <= 100}
    return vals.pop() if len(vals) == 1 else None


STATUS_RE = re.compile(r"^Status of projects (as on|during)", re.I)
END_RE = re.compile(r"^(annexure|annexures|list of|part\W*ii\W*annex|central sector pr|details of central)", re.I)
# a bare section heading line ('PART-II' / 'Annexure' on a divider page, or 'PART-II Annexure')
SECTION_RE = re.compile(r"^(part\W*ii|(part\W*ii\W*)?annexures?(\W*[ivx\d]+)?)\W*$", re.I)


def parse_part2(doc):
    """Walk pages from the first 'Sector:' page to the annexures; yield project dicts."""
    projects = []
    sector = agency = None
    started = False
    cur = None          # current project dict
    mode = None         # 'overview' | 'hdr' | 'table' | 'vals' | 'narr'
    pending_agency = []
    hdr_buf, hdr_agency, hdr_prev_mode = [], [], None
    centers = last_centers = None
    upto = None
    goff = 0.0
    row_step = 10.5

    info = {"start": None, "end": None, "status_pages": []}

    def finish():
        nonlocal cur
        if cur:
            projects.append(cur)
        cur = None

    for pno in range(doc.page_count):
        page = doc[pno]
        lines = content_lines(page)
        h = page.rect.height
        if not lines:
            goff += h
            continue
        top_text = lines[0]["text"]
        if not started:
            if re.match(r"^Sector\s*:", top_text):
                started = True
                info["start"] = pno
            else:
                goff += h
                continue
        elif END_RE.match(top_text) and "Location:" not in " ".join(l["text"] for l in lines[:8]):
            break
        info["end"] = pno
        if any(STATUS_RE.match(l["text"]) for l in lines[:6]):
            info["status_pages"].append(pno)
        for li, ln in enumerate(lines):
            t = ln["text"]
            m_sec = re.match(r"^Sector\s*:\s*(.+)$", t)
            if m_sec and li < 2:
                finish()
                sector = clean(m_sec[1])
                agency = None
                mode = "overview"
                pending_agency = []
                continue
            # project header (bold, starts with serial number, name has letters)
            if re.match(r"^\d{1,4}\s+\S", t) and re.search(r"[A-Za-z]{2}", t) and is_bold(ln) and ln["x0"] < page.rect.width * 0.25 \
                    and mode not in ("table", "vals"):
                if mode == "hdr" and not hdr_buf[-1].endswith("]") and len(hdr_buf) < 3:
                    hdr_buf.append(t)       # wrapped name whose 2nd line starts with a number
                    continue
                if mode != "hdr":
                    hdr_prev_mode = mode
                    hdr_agency = pending_agency
                    pending_agency = []
                hdr_buf = [t]
                mode = "hdr"
                continue
            if mode == "hdr" and not t.startswith("Location") and len(hdr_buf) >= 3:
                # not a project header after all: give the lines back
                if cur is not None and hdr_prev_mode == "narr":
                    cur["_narr"] += hdr_agency + hdr_buf
                mode = hdr_prev_mode
                hdr_buf = []
            if mode == "hdr":
                if t.startswith("Location"):
                    finish()
                    if hdr_agency:
                        agency = clean(" ".join(hdr_agency))
                    full = clean(" ".join(hdr_buf))
                    m = HDR_RE.match(full)
                    cur = {"page": pno + 1, "sector_raw": sector, "agency": agency, "_hdr": full,
                           "_narr": [], "_vals": []}
                    if m:
                        cur["project_name"] = clean(m[2])
                        cur["project_code"] = m[3] or None
                    else:
                        mm = re.match(r"^(\d{1,4})\s+(.*)$", full)
                        cur["project_name"] = clean(mm[2]) if mm else full
                        cur["project_code"] = None
                    cur["location"] = clean(t.split(":", 1)[1]) or None
                    mode = "table"
                else:
                    hdr_buf.append(t)
                continue
            if cur is None:
                if t == "Background" and sector and mode == "overview":
                    # a project narrative with no header / value table printed before it (Oct-Dec_2017 p597:
                    # the page before is the sector's chart image); finalize_project names it from the narrative
                    cur = {"page": pno + 1, "sector_raw": sector, "agency": None, "_hdr": "", "_narr": [],
                           "_vals": [], "_orphan": True, "project_code": None}
                    pending_agency = []
                    mode = "narr"
                    continue
                # overview area: only watch for agency headings
                if is_bold_italic(ln) and not re.search(r"[a-z]", t) and t != "Background":
                    pending_agency.append(t)
                elif mode == "overview":
                    pending_agency = []
                continue
            if mode == "table":
                if t.startswith("Capacity"):
                    c = clean(t.split(":", 1)[1]).strip("[] ").strip()
                    cur["capacity"] = c or None
                    continue
                m_up = re.search(r"upto\s*(\d{1,2})[./](\d{1,2})[./](\d{4})", t.replace(" ", ""), re.I)
                if m_up:
                    upto = f"{m_up[3]}-{int(m_up[2]):02d}"
                m_mar = re.search(r"\bMarch\s*,\s*(20\d\d)", t)     # 'Cummulative expenditure upto March,2014'
                if m_mar:
                    cur["_march"] = m_mar[1]
                marks = {}
                for s in ln["spans"]:
                    mk = re.fullmatch(r"\((\d)\)", s[4].strip())
                    if mk:
                        marks[int(mk[1])] = (s[0] + s[2]) / 2
                if len(marks) >= 6:
                    centers = marks if len(marks) == 7 else {**(last_centers or {}), **marks}
                    last_centers = centers
                    mode = "vals"
                continue
            if mode == "vals":
                if t.startswith("Background"):
                    cur.update(parse_table(centers, cur.pop("_vals"), row_step))
                    cur["expenditure_upto"] = upto
                    cur["_vals"] = []
                    mode = "narr"
                else:
                    for s in ln["spans"]:
                        mk = re.fullmatch(r"\((\d)\)", s[4].strip())
                        if mk:          # a column marker printed on its own line
                            centers[int(mk[1])] = (s[0] + s[2]) / 2
                            continue
                        cur["_vals"].append((s[0], goff + s[1], s[2], goff + s[3], s[4]))
                continue
            if mode == "narr":
                if SECTION_RE.match(t):      # 'PART-II Annexure' heading printed below the last project
                    continue
                if is_bold_italic(ln) and not re.search(r"[a-z]", t) and t != "Background":
                    pending_agency.append(t)
                    continue
                if pending_agency:          # it was narrative after all
                    cur["_narr"] += pending_agency
                    pending_agency = []
                cur["_narr"].append(t)
        goff += h
    finish()
    return projects, info


def strip_heading(text, name, location, capacity):
    """Drop the 'NAME, LOCATION, CAPACITY' heading the narrative starts with (printed once or twice,
    possibly wrapped). Matching ignores punctuation/spacing; needs the whole name to match."""
    norm = lambda t: re.sub(r"[^A-Z0-9]", "", (t or "").upper())
    target, need = norm(name) + norm(location) + norm(capacity), len(norm(name))
    for _ in range(2):
        j = cut = 0
        for i, ch in enumerate(text):
            c = ch.upper()
            if not ("A" <= c <= "Z" or "0" <= c <= "9"):
                continue
            if j < len(target) and c == target[j]:
                j += 1
                cut = i + 1
            else:
                break
        if not need or j < need:
            break
        text = text[cut:].lstrip(" ,.;:-")
    return text


NOT_REPORTED = re.compile(r"progress[^.]{0,45}\bnot\s+(?:been\s+|being\s+)?reported", re.I)
PP_PLACEHOLDER_EXP_SHARE = 0.10   # spend above a typical 10% mobilisation advance with 0.00% progress = not reported


def finalize_project(p):
    dq = p.setdefault("_dq", [])
    narr = list(p.pop("_narr", []))
    if p.pop("_orphan", False) and narr:
        # narrative block printed without its header / value table: 'NAME, CITY, STATE' is its first line
        parts = [clean(x) for x in narr.pop(0).split(",")]
        p["project_name"], p["location"] = parts[0], ",".join(parts[1:]) or None
        dq.append("header_and_table_not_printed")
    name = p.get("project_name") or ""
    remarks = strip_heading(clean(" ".join(narr)), name, p.get("location"), p.get("capacity"))
    if not re.search(r"[A-Za-z0-9]", remarks):
        remarks = ""
    status = p.pop("_status", None)
    if status:
        remarks = clean(f"Status: {status}. {remarks}")
    # '0.00' is the OCMS default for 'not reported' in the quarter-end cumulative expenditure: a value below the
    # cumulative up to the previous March (printed just above it) cannot be real
    prev_march = p.pop("_exp_prev_march", None)
    march = p.pop("_march", None)
    if p.get("expenditure_cum_cr") == 0 and prev_march and prev_march > 0:
        p["expenditure_cum_cr"] = None
        dq.append("placeholder_zero:expenditure_cum_cr")
        remarks = clean(f"{remarks} Cumulative expenditure up to March{' ' + march if march else ''}: "
                        f"{prev_march:.2f} crore.")
    p["remarks"] = remarks or None
    pp_col = p.pop("_pp_col", None)
    pp_nar = narrative_pp(remarks)
    if pp_col is not None and not 0 <= pp_col <= 100:    # misprint (e.g. 952.00 for 92%)
        pp_col = None
    if pp_col is not None and pp_col > 0:
        p["physical_progress_pct"] = pp_col
    elif pp_nar is not None:
        p["physical_progress_pct"] = pp_nar
    else:
        p["physical_progress_pct"] = pp_col
    if p["physical_progress_pct"] == 0:
        spent = max(p.get("expenditure_cum_cr") or 0, prev_march or 0)
        cost = max(p.get("cost_original_cr") or 0, p.get("cost_anticipated_cr") or 0)
        if status == "Completed" or NOT_REPORTED.search(remarks) or (cost > 0 and spent >= PP_PLACEHOLDER_EXP_SHARE * cost):
            p["physical_progress_pct"] = None
            dq.append("placeholder_zero:physical_progress_pct")
    # OCMS placeholder: original DOC printed as 01/1999 for projects approved later (the 2017-18 Q3/Q4 reports
    # print no DOA; no 01/1999 DOC in the 14 reports that do is genuine). The printed time overrun counts from it.
    if p.get("doc_original") == "1999-01" and (p.get("doa_original") or "9999") > "1999-01":
        p["doc_original"] = None
        p["_placeholder_doc"] = True
        dq.append("placeholder_doc_1999")
        if p.get("delay_months") is not None:
            p["delay_months"] = None
    for k in ("_hdr", "_vals"):
        p.pop(k, None)
    return p


# ------------------------------------------------------------ summary tables
NUMTOK = re.compile(r"^\(?-?(?:\d[\d,]*)?\.?\d+\)?%?$|^\d[\d,]*\.$")    # '1043175.' = number wrapped after the point
BLANKTOK = {"-", "--", "N.A.", "NA", "N.A"}
FOOTNOTE = re.compile(r"^([\d.,()%-]*\d[\d.,()%]*)[*$^#]+$")     # '301*' -> '301'
RANGE_RE = re.compile(r"^\d{1,3}-(\d{1,3})?$")   # '17-71'; '61-' when the max wrapped to the next line


def tokens(ln):
    """Split a visual line into word tokens with estimated x-centres."""
    out = []
    for s in ln["spans"]:
        txt = s[4]
        n = max(len(txt), 1)
        w = (s[2] - s[0]) / n
        for m in re.finditer(r"\S+", txt):
            t = m.group()
            f = FOOTNOTE.match(t)
            out.append(((s[0] + w * (m.start() + m.end()) / 2), f[1] if f else t))
    return out


def merge_range(toks):
    """Glue a trailing delay range printed as '17 - 71', '54- 71' or '6 -132' into one token '17-71'."""
    t = [x[1] for x in toks]
    if len(t) >= 3 and t[-3].isdigit() and t[-2] == "-" and t[-1].isdigit():
        n = 3
    elif len(t) >= 2 and ((re.fullmatch(r"\d+-", t[-2]) and t[-1].isdigit())
                          or (t[-2].isdigit() and re.fullmatch(r"-\d+", t[-1]))
                          or (t[-2].isdigit() and t[-1] == "-")):     # '61 -' + '117' on the next line
        n = 2
    else:
        return toks
    rng = "".join(t[-n:])
    # one cell (~20pt wide), not two neighbouring columns
    ok = RANGE_RE.match(rng) and toks[-1][0] - toks[-n][0] < 30
    return toks[:-n] + [((toks[-n][0] + toks[-1][0]) / 2, rng)] if ok else toks


def is_numtok(t):
    return bool(NUMTOK.match(t)) or t in BLANKTOK


def split_line(ln, rng=False):
    """-> (label_tokens, value_tokens[(x,t)]); values = numeric tokens after the last word.
    rng: the last column holds a delay range ('17-71')."""
    toks = merge_range(tokens(ln)) if rng else tokens(ln)
    isnum = (lambda t: is_numtok(t) or bool(RANGE_RE.match(t))) if rng else is_numtok
    last_alpha = max((i for i, (x, t) in enumerate(toks) if not isnum(t)), default=-1)
    label = [t for x, t in toks[:last_alpha + 1]]
    vals = toks[last_alpha + 1:]
    return label, vals


def is_index_row(vals, label):
    nums = [to_num(t.strip("()")) for x, t in vals]
    if label or len(nums) < 4 or any(v is None for v in nums):
        return False
    return all(b == a + 1 for a, b in zip(nums, nums[1:]))


PROSE_STOP = re.compile(r"^(TABLE|Table|Chart|CHART|Note|NOTE|Source|\*|\$|\^|#)")


AS_ON = re.compile(r"\bas\s+on\b|\b(January|April|July|October)\s*-\s*(March|June|September|December)\b", re.I)
MONTH_WORD = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)


def parse_grid(lines, start, ncols_opts, max_rows=60, min_full=2, rng=False):
    """Generic row/column parser for a numeric table that starts after lines[start].
    Column centres come from rows carrying exactly ncols values; wrapped labels and
    split value lines are merged by y-proximity. Returns (ncols, rows) or (None, [])."""
    cand = []
    merged = []
    for ln in lines[start + 1:]:          # glue lines printed <4.5pt apart (e.g. serial set slightly higher)
        if merged and abs(ln["y"] - merged[-1]["y"]) < 4.5:
            sp = sorted(merged[-1]["spans"] + ln["spans"], key=lambda s: s[0])
            merged[-1] = {"y": merged[-1]["y"], "spans": sp, "x0": sp[0][0],
                          "text": clean(" ".join(s[4] for s in sp))}
        else:
            merged.append(ln)
    for ln in merged:
        label, vals = split_line(ln, rng)
        # paragraph text: long, few spans, many lowercase words (multi-column headers have many spans)
        prose = len(ln["text"]) > 60 and len(vals) < 2 and len(ln["spans"]) <= 3 and \
            len(re.findall(r"(?<!\S)[a-z]{2,}[,.;]?(?!\S)", ln["text"])) >= 6
        if cand and (PROSE_STOP.match(ln["text"]) or prose):
            break
        if not cand and prose:
            continue
        if is_index_row(vals, label):
            continue
        # '(as on October-December 2016)' / 'Status as on 30 th June 2014': a date header, not a data row
        if len(vals) <= 1 and (AS_ON.search(ln["text"]) or (
                vals and MONTH_WORD.search(" ".join(label)) and re.fullmatch(r"(19|20)\d\d\)?", vals[0][1]))):
            continue
        cand.append({"y": ln["y"], "label": label, "vals": vals, "text": ln["text"],
                     "xmax": max(x for x, t in tokens(ln))})
        if len(cand) > max_rows * 3:
            break
    for ncols in ncols_opts:
        full = []
        for c in cand:
            v = c["vals"]
            lab = [t for t in c["label"] if not re.fullmatch(r"\d{1,3}\.?", t)]
            if len(v) == ncols and lab:
                full.append([x for x, t in v])
            elif len(v) == ncols + 1 and not c["label"]:
                full.append([x for x, t in v[1:]])
        if len(full) < min_full:
            continue
        centers = [sorted(col)[len(col) // 2] for col in zip(*full)]
        gap = min(b - a for a, b in zip(centers, centers[1:])) if ncols > 1 else 40
        rows = []
        for c in cand:
            serial = None
            lab = list(c["label"])
            if lab and re.fullmatch(r"\d{1,3}\.?", lab[0]):
                serial = lab.pop(0)
            assigned = {}
            bad = False
            for x, t in c["vals"]:
                if x < centers[0] - 0.75 * gap:
                    if serial is None and not lab:
                        serial = t
                    continue
                k = min(range(ncols), key=lambda j: abs(centers[j] - x))
                if abs(centers[k] - x) > 0.75 * gap + 10:
                    continue
                if k in assigned:
                    bad = True
                assigned[k] = t
            rows.append({"y": c["y"], "serial": serial, "label": " ".join(lab), "vals": assigned,
                         "bad": bad, "text": c["text"],
                         # label-only line reaching into the value columns = column header text
                         # (a long wrapped label like 'ROAD TRANSPORT AND' may end just short of them)
                         "hdr": not c["vals"] and c["xmax"] > centers[0] - 0.2 * gap})
        # stop after the Total row (plus lines printed within 13pt of it)
        out, seen_total = [], None
        for r in rows:
            if seen_total is not None and r["y"] - seen_total > 13:
                break
            out.append(r)
            if re.match(r"^total", r["label"], re.I) and r["vals"]:
                seen_total = r["y"]
        return ncols, assemble(out, ncols)
    return None, []


def assemble(rows, ncols):
    """Merge wrapped label lines / split value lines into logical rows."""
    data = [r for r in rows if r["vals"]]
    if not data:
        return []
    use_serial = sum(1 for r in data if r["serial"]) >= 0.5 * len(data)
    anchors, orphans = [], []
    first_data_y = data[0]["y"]
    for r in (rows if use_serial else data):
        is_total = bool(re.match(r"^total", r["label"], re.I))
        if use_serial:
            if not r["vals"] and not (r["serial"] and r["y"] >= first_data_y - 12):
                continue            # label-only lines are attached below
            if r["serial"] or is_total:
                anchors.append({**r, "frags": [(r["y"], r["label"])] if r["label"] else [], "vals": dict(r["vals"]),
                                "src": id(r)})
                continue
        elif r["label"]:
            prev = anchors[-1] if anchors else None
            if prev and len(prev["vals"]) < ncols and not (set(prev["vals"]) & set(r["vals"])) \
                    and r["y"] - prev["y"] < 14 and not is_total:
                prev["vals"].update(r["vals"])
                prev["frags"].append((r["y"], r["label"]))
                continue
            anchors.append({**r, "frags": [(r["y"], r["label"])], "vals": dict(r["vals"])})
            continue
        orphans.append(r)
    done = set()
    # a number wrapped inside its cell ('191,155.3' / '5', '1,021,669' / '.2'): the tail sits on its own line
    # just below, in a column the row above already fills with fewer decimals than the rest of that column
    dec = lambda t: len(t.split(".")[1]) if "." in t else 0
    col_dec = {k: Counter(dec(a["vals"][k]) for a in anchors if k in a["vals"]).most_common(1)[0][0]
               for k in {k for a in anchors for k in a["vals"]}}
    def tail_ok(prev, t, k):
        if prev.endswith("-") and t.isdigit():          # delay range '61 -' / '117'
            return True
        return bool(re.fullmatch(r"\.?\d{1,2}", t) and re.search(r"[.,]", prev + t)
                    and dec(prev) < col_dec[k] == dec(prev + t))
    for oi, r in enumerate(orphans):
        above = [a for a in anchors if 0 < r["y"] - a["y"] < 14]
        if not r["vals"] or not above:
            continue
        a = max(above, key=lambda a: a["y"])
        glued = {k: a["vals"].get(k, "") + t for k, t in r["vals"].items()}
        if all(k in a["vals"] and tail_ok(a["vals"][k], t, k) for k, t in r["vals"].items()):
            a["vals"].update(glued)
            if r["label"]:
                a["frags"].append((r["y"], r["label"]))
            done.add(oi)
    # value lines without their own anchor: global nearest-first matching to anchors whose
    # columns are still free (values of a wrapped row may sit above or below its serial)
    lim = 25 if use_serial else 9
    pairs = sorted((abs(a["y"] - r["y"]), oi, ai) for oi, r in enumerate(orphans)
                   for ai, a in enumerate(anchors) if abs(a["y"] - r["y"]) < lim)
    for dist, oi, ai in pairs:
        r, a = orphans[oi], anchors[ai]
        if oi in done or set(a["vals"]) & set(r["vals"]):
            continue
        done.add(oi)
        a["vals"].update(r["vals"])
        if r["label"]:
            a["frags"].append((r["y"], r["label"]))
    if not use_serial:          # label printed on a separate line (e.g. below the values)
        anchors += [{**r, "frags": [], "vals": dict(r["vals"])} for oi, r in enumerate(orphans) if oi not in done]
    anchors.sort(key=lambda a: a["y"])
    if not anchors:
        return []
    first_y = min(a["y"] for a in anchors) - 13
    used = {a.get("src") for a in anchors}
    for r in sorted(rows, key=lambda r: r["y"]):
        if r["vals"] or not r["label"] or r["y"] < first_y or id(r) in used or r.get("hdr"):
            continue
        above = [a for a in anchors if a["y"] <= r["y"]]
        below = [a for a in anchors if a["y"] > r["y"]]
        up = max(above, key=lambda a: a["y"]) if above else None
        dn = min(below, key=lambda a: a["y"]) if below else None
        # distance to the row above counts from its lowest label line so far: 'HEALTH AND' / 'FAMILY' /
        # 'WELFARE' stays one label instead of 'WELFARE' drifting to the next row
        d_up = r["y"] - max([up["y"]] + [y for y, t in up["frags"] if y <= r["y"]]) if up else 1e9
        d_dn = dn["y"] - r["y"] if dn else 1e9
        # wrapped labels usually continue downwards: prefer the row above unless the row below is clearly closer
        a = up if (d_up < 14 and d_up <= d_dn + 3) else (dn if d_dn < 14 else None)
        if a is not None:
            a["frags"].append((r["y"], r["label"]))
    out = []
    for a in anchors:
        lab = clean(" ".join(t for y, t in sorted(a["frags"]))).rstrip(":*").strip()
        out.append({"label": lab, "vals": a["vals"], "y": a["y"], "bad": a["bad"]})
    return out


M_STATUS = ["n_ahead", "n_ahead_wrt_latest", "n_on_schedule", "n_on_schedule_wrt_latest", "n_delayed",
            "n_delayed_wrt_latest", "n_without_doc", "n_without_doc_wrt_latest", "n_without_odc_with_doc",
            "n_without_odc_with_doc_wrt_latest"]
M_FIN8 = ["n_projects", "cost_original_cr", "cost_anticipated_cr", "expenditure_upto_prev_march_cr",
          "balance_expenditure_cr", "outlay_cr", "expenditure_cr", "expenditure_pct"]
M_FIN7 = ["n_projects", "cost_original_cr", "cost_anticipated_cr", "expenditure_cr",
          "balance_expenditure_cr", "outlay_cr", "expenditure_pct"]
M_SECSTAT = ["n_projects", "n_within_time_cost", "n_cost_overrun_only", "n_time_overrun_only",
             "n_time_and_cost_overrun", "n_without_doc_within_cost", "n_without_doc_with_cost_overrun"]

TABLES = [
    # key, title regex (per line), ncols options, dimension, metrics by ncols, table_title
    ("status", r"(Original\s+Latest\s+){3,}", [10], "sector",
     {10: M_STATUS}, "Sector-wise implementation status w.r.t. original and latest schedule"),
    ("classification", r"Classification of Mega and Major|^TABLE\s*[-\u2013]?\s*1$", [5], "project_size",
     {5: ["n_projects", "cost_anticipated_cr", "cost_anticipated_share_pct", "expenditure_cr", "cost_original_cr"]},
     "Table-1 Classification of Mega and Major projects"),
    ("mega_major", r"Cost Estimates of Mega|^TABLE\s*[-\u2013]?\s*2$", [6], "sector",
     {6: ["n_projects", "cost_anticipated_cr", "cost_original_cr"] * 2},
     "Table-2 Sector-wise Mega/Major projects"),
    ("added_dropped", r"Summary of projects added", [4], "sector",
     {4: ["n_projects_start", "n_new", "n_dropped", "n_projects"]},
     "Table-3 Sector-wise projects added/dropped during the quarter"),
    ("financial", r"Financial Details of the Projects|planned and balance expenditure|Cumulative\.?\s+Balance",
     [8, 7], "sector",
     {8: M_FIN8, 7: M_FIN7}, "Sector-wise financial details (planned and balance expenditure)"),
    ("state", r"CENTRAL SECTOR PRO?JECTS", [4], "state",
     {4: ["n_projects", "cost_original_cr", "cost_anticipated_cr", "expenditure_cr"]},
     "Annexure-I State-wise central sector projects"),
    # TABLE-8/9 under 'PROJECTS REQUIRING EXAMINATION OF THE REVISED COST ESTIMATE': total projects, then Mega /
    # Major / Total pairs of 'approved cost less than anticipated cost (NAC)' and 'less than expenditure'
    ("rce", r"Sector-wise distribution of projects requiring review", [7], "sector",
     {7: ["n_projects"] + ["n_approved_below_anticipated", "n_approved_below_expenditure"] * 3},
     "Sector-wise distribution of projects requiring review/sanction of RCE"),
]
RCE_SUB = {1: "Mega", 2: "Mega", 3: "Major", 4: "Major", 5: "Total", 6: "Total"}
# Part-I sector-wise cost/time overrun tables (Table-5..7 / 6..8; 2014 Q1 titles them 'Sector-wise Details of ...').
# Columns: all projects (n, cost, anticipated, overrun %) then the subset with overruns (n, cost, anticipated,
# overrun %[, delay range in months]).
_OVR = r"(?:Extent of|Details of)\s+(?:the\s+)?{what}\s+overruns?\s+(?:in projects\s+)?(?:with respect to|w\.?\s*r\.?\s*t\.?)\s+{sched}"
OVR_TABLES = [   # key, what, schedule, subset count metric, subset label, base cost metric, has range
    ("ovr_cost_orig", "cost", "original", "n_cost_overrun", "projects with cost overrun", "cost_original_cr", False),
    ("ovr_time_orig", "time", "original", "n_delayed", "projects with time overrun", "cost_original_cr", True),
    ("ovr_cost_latest", "cost", "latest", "n_cost_overrun_wrt_latest", "projects with cost overrun",
     "cost_latest_cr", False),
    ("ovr_time_latest", "time", "latest", "n_delayed_wrt_latest", "projects with time overrun", "cost_latest_cr", True),
    ("ovr_tc_orig", r"time\s*(?:&|and)\s*cost", "original", "n_time_and_cost_overrun",
     "projects with time and cost overrun", "cost_original_cr", True),
]
OVR_SUBSET = {}
for _k, _what, _sched, _n, _sub, _base, _rng in OVR_TABLES:
    _m = ["n_projects", _base, "cost_anticipated_cr", "cost_overrun_pct", _n, _base, "cost_anticipated_cr",
          "cost_overrun_pct"] + (["delay_range_months"] if _rng else [])
    TABLES.append((_k, _OVR.format(what=_what, sched=_sched), [len(_m)], "sector", {len(_m): _m},
                   f"Sector-wise extent of {'time and cost' if _k == 'ovr_tc_orig' else _what} overruns "
                   f"w.r.t. {_sched} schedule"))
    OVR_SUBSET[_k] = _sub

UNITS = {"cost_anticipated_share_pct": "% of total anticipated cost", "expenditure_pct": "% of original cost"}


def unit_of(metric):
    if metric in UNITS:
        return UNITS[metric]
    if metric.endswith("_cr"):
        return "Rs crore"
    if "_pct" in metric:
        return "%"
    if metric.endswith("_months"):
        return "months"
    return "count"


def grid_to_summary(key, title, dim, ncols, metrics, rows, page, sector=None, bad_cols=()):
    """bad_cols: columns whose printed Total differs from the sum of the rows (Total kept as printed, flagged)."""
    out = []
    for r in rows:
        if r["bad"] or not r["label"]:
            continue
        is_total = bool(re.match(r"^total", r["label"], re.I))
        for k, txt in r["vals"].items():
            m = metrics[k]
            if m == "delay_range_months":       # '17-71' -> min / max
                rg = txt.split("-") if RANGE_RE.match(txt) and not txt.endswith("-") else None
                pairs = [("delay_range_min_months", to_num(rg[0])), ("delay_range_max_months", to_num(rg[1]))] \
                    if rg else []
            elif txt.endswith("."):         # '1043175.' whose decimals wrapped and were not recovered
                pairs = []
            else:
                pairs = [(m, to_num(txt))]
            for m, v in pairs:
                if v is None:
                    continue
                rec = {"page": page + 1, "table_title": title, "dimension": dim,
                       "dimension_value": "Total" if is_total else r["label"],
                       "sub_dimension_value": None, "metric": m, "value": v, "unit": unit_of(m), "_key": key}
                if key == "mega_major":
                    rec["sub_dimension_value"] = "Mega" if k < 3 else "Major"
                if key in OVR_SUBSET and k >= 4:
                    rec["sub_dimension_value"] = OVR_SUBSET[key]
                if key == "rce":
                    rec["sub_dimension_value"] = RCE_SUB.get(k)
                if key == "secstat":
                    rec["dimension_value"] = sector
                    rec["sub_dimension_value"] = "Total" if is_total else r["label"]
                if is_total and k in bad_cols:
                    rec["dq_note"] = "printed_total_mismatch"
                out.append(rec)
    return out


def total_check(rows, ncols, metrics=None):
    """Columns where component rows do not add up to the printed Total row (ratios skipped)."""
    tot = [r for r in rows if re.match(r"^total", r["label"], re.I)]
    comp = [r for r in rows if not re.match(r"^total", r["label"], re.I) and not r["bad"]]
    if not tot:
        return None
    bad = []
    for k in range(ncols):
        if metrics and metrics[k].endswith("_pct"):
            continue
        t = to_num(tot[0]["vals"].get(k, ""))
        vals = [to_num(r["vals"].get(k, "")) for r in comp]
        if t is None or not vals:
            continue
        s = sum(v for v in vals if v is not None)
        if abs(s - t) > max(1.0, 0.005 * abs(t)):
            bad.append(k)
    return bad


def parse_summaries(doc, pages, part2_status_pages, sector_of):
    """Run the TABLES configs over the given pages (Part I + annexures) and Part II status pages."""
    out, found, checks = [], Counter(), []
    for pno in pages:
        lines = content_lines(doc[pno])
        done_here = set()
        for i, ln in enumerate(lines):
            for key, pat, ncols_opts, dim, mets, title in TABLES:
                if key in done_here or not re.search(pat, ln["text"], 0 if key == "classification" else re.I):
                    continue
                if key == "state" and not any(re.search(r"\bSTATE", l["text"]) for l in lines[i:i + 8]):
                    continue
                if (key in ("mega_major", "added_dropped", "classification", "rce") or key in OVR_SUBSET) and pno > 80:
                    continue
                ncols, rows = parse_grid(lines, i, ncols_opts, rng="delay_range_months" in mets[ncols_opts[0]])
                if not ncols or not rows:
                    continue
                done_here.add(key)
                found[key] += 1
                chk = total_check(rows, ncols, mets[ncols])
                if chk:
                    checks.append(f"{key}@p{pno + 1}: printed Total != sum of rows in cols {chk}")
                if "delay_range_months" in mets[ncols]:
                    odd = [r["vals"][ncols - 1] for r in rows if ncols - 1 in r["vals"]
                           and r["vals"][ncols - 1] not in BLANKTOK
                           and not (RANGE_RE.match(r["vals"][ncols - 1]) and not r["vals"][ncols - 1].endswith("-"))]
                    if odd:
                        checks.append(f"{key}@p{pno + 1}: 'Range (in months)' column prints non-range values "
                                      f"({', '.join(odd[:4])}...), left blank")
                out += grid_to_summary(key, title, dim, ncols, mets[ncols], rows, pno, bad_cols=chk or ())
    for pno in part2_status_pages:
        lines = content_lines(doc[pno])
        for i, ln in enumerate(lines):
            if STATUS_RE.match(ln["text"]):
                ncols, rows = parse_grid(lines, i, [7, 5], max_rows=4, min_full=1)
                if ncols:
                    found["secstat"] += 1
                    chk = total_check(rows, ncols)
                    if chk:
                        checks.append(f"secstat@p{pno + 1}: printed Total != sum of rows in cols {chk}")
                    out += grid_to_summary("secstat", "Part-II sector status of projects (by category)", "sector",
                                           ncols, M_SECSTAT[:ncols], rows, pno, sector=sector_of.get(pno),
                                           bad_cols=chk or ())
                break
    return out, found, checks


HIGHLIGHTS = [
    (r"Total number of projects on the monitor", "n_projects"),
    (r"Total Original estimated cost", "cost_original_cr"),
    (r"Total latest approved cost", "cost_latest_cr"),
    (r"Total anticipated cost", "cost_anticipated_cr"),
    (r"^Total Expenditure", "expenditure_cr"),
    (r"Overall percentage cost overrun with respect to original", "cost_overrun_pct"),
    (r"Overall percentage cost overrun with respect to latest", "cost_overrun_pct_wrt_latest"),
    (r"projects showing cost overrun w\.?r\.?t\.? original", "n_cost_overrun"),
    (r"projects showing time overrun w\.?r\.?t\.? original", "n_delayed"),
    (r"Percentage cost overrun in \d+ delayed", "cost_overrun_pct_delayed_projects"),
    (r"due for commiss?ioning during the year", "n_due_for_commissioning_fy"),     # 'commisioning' in 3 reports
    (r"projects completed during the year", "n_completed_fy"),
    (r"Total Cost of the completed projects", "cost_completed_fy_cr"),
]


def parse_highlights(doc, pages):
    out = []
    for pno in pages:
        lines = content_lines(doc[pno])
        if not any("Total number of projects on the monitor" in l["text"] for l in lines):
            continue
        for ln in lines:
            for pat, metric in HIGHLIGHTS:
                if re.search(pat, ln["text"], re.I):
                    rest = re.split(pat, ln["text"], flags=re.I)[-1]
                    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", rest)
                    v = to_num(m.group()) if m else None
                    vals = [(metric, v)]
                    rg = re.search(r"Ranging\s+from\s+(\d+)\s*(?:to|-)\s*(\d+)\s*months", rest, re.I)
                    if rg:      # '346 (Ranging from 1 to 261 months)'
                        vals += [("delay_range_min_months", to_num(rg[1])), ("delay_range_max_months", to_num(rg[2]))]
                    for met, v in vals:
                        if v is not None:
                            out.append({"page": pno + 1, "table_title": "Highlights", "dimension": "overall",
                                        "dimension_value": "Total", "sub_dimension_value": None, "metric": met,
                                        "value": v, "unit": unit_of(met), "_key": "highlights"})
                    break
        break
    return out


def parse_foreword(doc, pages):
    """Overall totals stated in the Foreword paragraph 1 (all variants)."""
    for pno in pages:
        txt = clean(" ".join(l["text"] for l in content_lines(doc[pno])))
        if "Quarterly Project Implementation" not in txt:
            continue
        pats = [
            ("n_projects", r"(?:comprises|comprising|contains detailed information on|information on)\s+(\d[\d,]*)\s+projects"),
            ("cost_anticipated_cr", r"anticipated completion cost of these \d[\d,]*\s+(?:[a-z]{2}\s+)?projects is reported to (?:be )?Rs\.?\s*([\d,]+(?:\.\d+)?)"),
            ("expenditure_cr", r"total expenditure as on .{0,40}? was Rs\.?\s*([\d,]+(?:\.\d+)?)"),
            ("outlay_cr", r"total outlay of Rs\.?\s*([\d,]+(?:\.\d+)?)"),
        ]
        out = []
        for metric, pat in pats:
            m = re.search(pat, txt, re.I)
            if m and to_num(m[1]) is not None:
                out.append({"page": pno + 1, "table_title": "Foreword", "dimension": "overall",
                            "dimension_value": "Total", "sub_dimension_value": None, "metric": metric,
                            "value": to_num(m[1]), "unit": unit_of(metric), "_key": "foreword"})
        if out:
            return out
    return []


def parse_overview_counts(doc, pages):
    """Stated counts used to validate the appendix lists (first match in Foreword / Part-I text)."""
    pats = [("n_additional_delay", r"total of (\d+) projects? (?:had|have|has) reported additional delays?"),
            ("n_completed", r"(\d+) projects? (?:have|has|had) (?:reportedly )?been (?:completed|commissioned)")]
    out, got = [], set()
    for pno in pages:
        txt = clean(" ".join(l["text"] for l in content_lines(doc[pno])))
        for metric, pat in pats:
            if metric in got:
                continue
            prev = 0
            for m in list(re.finditer(pat, txt, re.I))[:2]:
                got.add(metric)
                met = metric
                if metric == "n_completed":     # 'During the year ..' / 'Upto 3rd quarter of the year ..' vs 'During the second quarter ..'
                    ctx = txt[max(prev, txt.rfind(". ", 0, m.start())):m.start()].lower()
                    met = "n_completed_fy" if re.search(r"\bup\s*to\b", ctx) or ("year" in ctx and "quarter" not in ctx) \
                        else "n_completed_qtr" if "quarter" in ctx else metric
                prev = m.end()
                out.append({"page": pno + 1, "table_title": "Foreword/Overview text", "dimension": "overall",
                            "dimension_value": "Total", "sub_dimension_value": None, "metric": met,
                            "value": to_num(m[1]), "unit": "count", "_key": "overview"})
                if metric != "n_completed":
                    break
    return out


# ------------------------------------------------------------ appendix lists
def sx0(s):
    """x0 of a span's first visible character (leading spaces skipped, width shared evenly)."""
    lead = len(s[4]) - len(s[4].lstrip())
    return s[0] + (s[2] - s[0]) * lead / max(len(s[4]), 1)


def colmap_from_header(lines, words):
    """x0 of the first span whose text starts with each header word."""
    xs = {}
    for ln in lines:
        for s in ln["spans"]:
            for w in words:
                if w not in xs and s[4].strip().startswith(w):
                    xs[w] = s[0]
    return xs


def parse_additional_delay(doc, pages):
    """'List Of Additionally Delayed Projects' -> rows with additional_delay_months."""
    rows, cur = [], None
    sector = agency = None
    cols = None
    as_on = None
    base_sz = 8.0
    for pno in pages:
        lines = content_lines(doc[pno])
        if not lines or not any(re.search(r"List Of Additionally Delayed", l["text"], re.I) for l in lines[:3]):
            continue
        hx = colmap_from_header(lines, ["SN", "Project", "DOA", "Cost", "DOC", "Add"])
        if len(hx) == 6:
            cols = hx
        hdr_sz = [s[6] for l in lines for s in l["spans"] if s[4].strip() == "SN"]
        if hdr_sz:
            base_sz = hdr_sz[0]     # column-header font size of this page
        if not cols:
            continue
        for ln in lines:
            t = ln["text"]
            if re.search(r"List Of Additionally Delayed", t, re.I):
                continue
            m = re.search(r"\bas on:?\s*(.+?)\)?\s*(?:Appendix.*)?$", t, re.I)
            if m and ln["y"] < min([l["y"] for l in lines if re.match(r"SN\b", l["text"])] or [130]):
                as_on = clean(m[1]).strip("() ")     # the date line above the first column header
                continue
            sizes = [s[6] for s in ln["spans"]]
            if all(s[5] & 16 for s in ln["spans"]):
                # sector heading ~1.75x the column-header size, agency heading ~1.4x (pages are scaled)
                if ln["x0"] < cols["DOA"] - 100 and not re.search(r"\bSN\b|Project Name", t) \
                        and max(sizes) >= 1.2 * base_sz:
                    if max(sizes) >= 1.55 * base_sz:
                        sector, agency = t, None
                    else:
                        agency = t
                continue
            # x of the printed text, not of the span: right-aligned costs come as '        3,492.00'
            # whose span starts left of the Cost header
            toks = [(sx0(s), s[2], s[4].strip()) for s in ln["spans"] if s[4].strip()]
            if not toks:
                continue
            if re.fullmatch(r"\d{1,4}", toks[0][2]) and toks[0][0] < (cols["SN"] + cols["Project"]) / 2:
                if cur:
                    rows.append(cur)
                cur = {"page": pno + 1, "sector_raw": sector, "agency": agency, "_name": [], "_cost": [],
                       "_doc": [], "_doa": None, "_add": None, "_as_on": as_on}
                toks = toks[1:]
            if cur is None:
                continue
            for x0, x1, tx in toks:
                if x0 < cols["DOA"] - 20:
                    cur["_name"].append(tx)
                elif x0 < cols["Cost"] - 2:
                    cur["_doa"] = cur["_doa"] or tx
                elif x0 < cols["DOC"] - 2:
                    cur["_cost"].append(tx)
                elif x0 < cols["Add"] - 2:
                    cur["_doc"].append(tx)
                else:
                    cur["_add"] = tx
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        docs = [to_ym(d) if d.strip("/ ") else None for d in r["_doc"]]
        cost = [to_num(c) for c in r["_cost"]] + [None, None]
        old = docs[1] if len(docs) >= 3 else None
        rem = (f"Anticipated DOC in previous quarter: {old}." if old else "") + \
              (f" List dated as on {r['_as_on']}." if r["_as_on"] else "")
        out.append({
            "page": r["page"], "sector_raw": r["sector_raw"], "agency": r["agency"],
            "project_name": clean(" ".join(r["_name"])), "doa_original": to_ym(r["_doa"]),
            "cost_original_cr": cost[0], "cost_anticipated_cr": cost[1],
            "doc_original": docs[0] if docs else None, "doc_anticipated": docs[2] if len(docs) >= 3 else None,
            "additional_delay_months": to_num(r["_add"]), "remarks": clean(rem) or None,
        })
    return out


def parse_completed(doc, pages):
    """'List of projects completed in <FY> as on <date>' -> completed rows."""
    rows, cur = [], None
    sector = agency = None
    prev_agency = False
    for pno in pages:
        page = doc[pno]
        lines = content_lines(page)
        if not lines or not any(re.search(r"List of projects completed", l["text"], re.I) for l in lines[:3]):
            continue
        hx = colmap_from_header(lines, ["commissioning", "Approved", "Cumulative", "Completed"])
        if len(hx) < 4:
            continue
        b_doc, b_cost, b_exp, b_done = hx["commissioning"] - 8, hx["Approved"] - 4, hx["Cumulative"] - 4, \
            hx["Completed"] - 25
        rev = [l["y"] for l in lines[:14] if "Revised" in l["text"]]
        hdr_bottom = max(rev) if rev else 0
        prev_agency = False
        # PDF text blocks separate the name lines from the location lines of a row
        blocks = {}
        for bi, b in enumerate(page.get_text("dict")["blocks"]):
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["text"].strip():
                        blocks[(round(s["bbox"][0]), round(s["bbox"][1]))] = bi
        for ln in lines:
            if ln["y"] <= hdr_bottom:
                continue
            t = ln["text"]
            m = re.match(r"^Sector\s+(.*)$", t)
            if m:
                new = clean(m[1])
                if not (sector and new.split()[0] == sector.split()[0]):
                    agency = None
                sector = new
                prev_agency = False
                continue
            sp = ln["spans"]
            if all(s[5] & 16 for s in sp) and ln["x0"] < b_doc:
                if all(s[5] & 2 for s in sp):       # bold-italic: wrapped sector name
                    # 'TELECOMMUNICATION' + 'S' is a broken word, 'ROAD TRANSPORT' + 'AND HIGHWAYS' is not
                    sector = (sector + t if len(t) <= 2 else clean(f"{sector} {t}")) if sector else t
                    prev_agency = False
                else:                                # bold: agency heading, may wrap over two lines
                    agency = clean(f"{agency} {t}") if prev_agency and agency else t
                    prev_agency = True
                continue
            # the 2nd line of a wrapped agency heading can share the y of the next row's serial:
            # 'MANGALORE' / '10 REFIN POLYPROPYLENE UNIT ...' -> agency 'MANGALORE REFIN'
            bold = [s for s in sp if s[5] & 16 and not s[5] & 2 and s[0] < b_doc]
            if bold:
                txt = clean(" ".join(s[4] for s in bold))
                agency = clean(f"{agency} {txt}") if prev_agency and agency else txt
                sp = [s for s in sp if s not in bold]
            prev_agency = False
            if not sp:
                continue
            first = sp[0][4].strip()
            # serial is its own span (a name line may itself start with digits, e.g. '3500 TEU ...')
            if re.fullmatch(r"\d{1,4}", first) and sp[0][0] < hx["commissioning"] - 100 and len(sp) > 1:
                if cur:
                    rows.append(cur)
                cur = {"page": pno + 1, "sector_raw": sector, "agency": agency, "_name": [], "_loc": [],
                       "_state": None, "_docs": [], "_costs": [], "_exp": None, "_done": [], "_nblock": None}
                spans = [(s[0], s[2], s[4].strip(), s) for s in sp[1:]]
            else:
                spans = [(s[0], s[2], s[4].strip(), s) for s in sp]
            if cur is None:
                continue
            for x0, x1, tx, s in spans:
                if not tx:
                    continue
                if x0 < b_doc:
                    bid = blocks.get((round(s[0]), round(s[1])))
                    if re.fullmatch(r"\(.*\)", tx):
                        cur["_state"] = tx.strip("() ")
                    elif cur["_nblock"] is None or bid == cur["_nblock"]:
                        cur["_nblock"] = bid
                        cur["_name"].append(tx)
                    else:
                        cur["_loc"].append(tx)
                elif x0 < b_cost:
                    cur["_docs"].append(tx)
                elif x0 < b_exp:
                    cur["_costs"].append(tx)
                elif x0 < b_done:
                    cur["_exp"] = tx
                else:
                    cur["_done"].append(tx)
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        d_orig = next((d for d in r["_docs"] if not d.startswith("(")), None)
        d_rev = next((d for d in r["_docs"] if d.startswith("(")), None)
        c_orig = next((c for c in r["_costs"] if not c.startswith("(")), None)
        c_rev = next((c for c in r["_costs"] if c.startswith("(")), None)
        done = clean(" ".join(x for x in r["_done"] if x.strip("()- ")))
        out.append({
            "page": r["page"], "sector_raw": r["sector_raw"], "agency": r["agency"],
            "project_name": clean(" ".join(r["_name"])), "location": clean(" ".join(r["_loc"])) or None,
            "state": r["_state"], "doc_original": to_ym(d_orig) if d_orig else None,
            "doc_revised": to_ym(d_rev.strip("()")) if d_rev else None,
            "cost_original_cr": to_num(c_orig) if c_orig else None,
            "cost_revised_cr": to_num(c_rev.strip("()")) if c_rev else None,
            "expenditure_cum_cr": to_num(r["_exp"]) if r["_exp"] else None,
            "remarks": f"Completed during {done}" if done else None,
        })
    return out


def index_row(lines, n_min=6):
    """The numbered column-index row ('1 2 3 ... n') under a list header -> (line, {col: x-centre})."""
    for l in lines:
        if len(l["spans"]) >= n_min and [s[4].strip() for s in l["spans"]] == [str(i) for i in range(1, len(l["spans"]) + 1)]:
            return l, {i + 1: (s[0] + s[2]) / 2 for i, s in enumerate(l["spans"])}
    return None, None


def parse_derived_lists(doc, pages):
    """Rows of the derived appendix lists (ahead / on schedule / delayed / without DOC, Annexure III-VII, ...):
    'NAME - [CODE]AGENCY,STATE' (wrapped) + values. Columns come from the numbered index row ('1 2 3 ... 10') and
    their meaning from the header words above each number; a row's 2nd line holds the revised cost / DOC.
    -> list of dicts: page, _key (normalised name), project_code, printed fields."""
    out = []
    for pno in pages:
        lines = content_lines(doc[pno])
        idx, cen = index_row(lines)
        if not idx:
            continue
        col = lambda s: min(cen, key=lambda i: abs(cen[i] - (s[0] + s[2]) / 2))
        head = {i: "" for i in cen}
        gap = min(b - a for a, b in zip(list(cen.values()), list(cen.values())[1:]))
        for l in lines:
            if l["y"] < idx["y"]:
                for s in l["spans"]:
                    if s[2] - s[0] < 1.5 * gap:     # not a title spanning several columns ('All Cost/ Expenditure ..')
                        head[col(s)] += " " + s[4]
        if not any("Approval" in h for h in head.values()):
            continue
        rows, cur = [], None
        body = [l for l in lines if l["y"] > idx["y"]]
        # serials sit left of the name indent; a wrapped name line may itself start with a number ('2 LANING ..')
        x_sn = min([l["spans"][0][0] for l in body if re.match(r"\d{1,4}\b", l["spans"][0][4].strip())] or [0])
        for l in body:
            if re.match(r"\d{1,4}\b", l["spans"][0][4].strip()) and l["spans"][0][0] <= x_sn + 3:
                cur = {"lines": []}
                rows.append(cur)
            if cur is not None:
                cur["lines"].append(l)
        for r in rows:
            text = clean(" ".join(s[4] for l in r["lines"] for s in l["spans"] if col(s) <= 2))
            text = re.sub(r"^\d{1,4}\s+", "", text)
            code = re.search(r"\[\s*([A-Za-z0-9]+)\s*\]", text)
            rec = {"page": pno + 1, "_key": norm_label(re.split(r"\s*-?\s*\[", text)[0]),
                   "project_code": code[1] if code else None}
            for li, l in enumerate(r["lines"][:2]):
                for s in l["spans"]:
                    k, v = col(s), s[4].strip()
                    h = head[k]
                    if k <= 2 or not v:
                        continue
                    if "Approval" in h:
                        f = "doa_original" if li == 0 else None
                    elif "Cumulative" in h or "Expenditure" in h:
                        f = "expenditure_cum_cr" if li == 0 else None
                    elif "Delay" in h:
                        f = "delay_months" if li == 0 and "Original" in h else None
                    elif "Cost" in h:
                        f = ("cost_anticipated_cr" if li == 0 else None) if "Antici" in h else                             ("cost_original_cr", "cost_revised_cr")[li] if "Original" in h else None
                    elif "Antici" in h:
                        f = "doc_anticipated" if li == 0 else None
                    elif "Original" in h:
                        f = ("doc_original", "doc_revised")[li]
                    else:
                        f = None
                    if f:
                        rec[f] = to_ym(v) if f.startswith("do") else to_num(v)
            out.append(rec)
    return out


PPP_RE = re.compile(r"Projects\s+Under\s*-?\s*Public\s+Private\s+Partnership", re.I)
PPP_NAME = re.compile(r"^(.*?)\s*-\s*(PPP\b[^\[]*?)\s*-?\s*\[\s*([A-Za-z0-9]*)\s*\]\s*$")


def parse_ppp(doc, pages):
    """Annexure-XII 'Details of Ongoing Projects Under Public Private Partnership Mode' (2015-16 Q4 .. 2016-17 Q2).
    Columns 1..9: SI.No, 'NAME - PPP (MODE) - [CODE]' (wrapped), DOA, Original / (Revised) cost, Anticipated cost,
    Original / (Revised) DOC, Anticipated DOC, cost overrun %, time overrun (months). Bold sector headings and
    sector 'Total' rows. A row's first line carries the values; its later lines the revised cost / DOC."""
    rows, totals, cur, sector, on = [], [], None, None, False
    fld = {3: "doa_original", 4: ("cost_original_cr", "cost_revised_cr"), 5: "cost_anticipated_cr",
           6: ("doc_original", "doc_revised"), 7: "doc_anticipated", 8: "cost_overrun_pct", 9: "delay_months"}
    for pno in pages:
        lines = content_lines(doc[pno])
        if any(PPP_RE.search(l["text"]) for l in lines[:4]):
            on = True
        if not on:
            continue
        idx, cen = index_row(lines)
        if not idx or len(cen) != 9:
            on = False
            continue
        # serial = a bare number left of the name column; any other text left of the DOA column is the name
        # (a short '[N24000426 ]' line would otherwise sit nearer the serial column's centre)
        col = lambda s: (1 if re.fullmatch(r"\d{1,4}", s[4].strip()) and s[0] < cen[2] - 40 else 2) \
            if s[0] < cen[3] - 25 else min(cen, key=lambda i: abs(cen[i] - (s[0] + s[2]) / 2))
        for l in lines:
            if l["y"] <= idx["y"]:
                continue
            if is_bold(l):
                if re.match(r"^(Grand\s+)?Total\b", l["text"], re.I):
                    tv = {col(s): to_num(s[4]) for s in l["spans"] if col(s) in (4, 5)}
                    totals.append((l["text"].startswith("Grand"), sector, tv))
                    if l["text"].startswith("Grand"):
                        on = False
                elif l["x0"] < cen[3] and re.search(r"[A-Z]{3}", l["text"]):
                    sector, cur = l["text"], None
                continue
            if cur is None:
                cur = {"page": pno + 1, "sector_raw": sector, "_name": [], "_n": 0}
                rows.append(cur)
            for s in l["spans"]:
                k, v = col(s), s[4].strip()
                if not v or k == 1:
                    continue
                if k == 2:
                    cur["_name"].append(v)
                    continue
                f = fld[k][min(cur["_n"], 1)] if isinstance(fld[k], tuple) else (fld[k] if cur["_n"] == 0 else None)
                if f:
                    cur[f] = to_ym(v) if f.startswith("do") else to_num(v)
            cur["_n"] += 1
            if "]" in " ".join(cur["_name"]):
                cur = None
        if not on and rows:
            break
    out = []
    for r in rows:
        full = clean(" ".join(r.pop("_name")))
        r.pop("_n")
        m = PPP_NAME.match(full)
        if not m or len(re.findall(r"\bPPP\b", full)) != 1:      # no code, or two rows run together
            continue
        mode = m[2].strip()
        inner = re.fullmatch(r"PPP\s*\((.+)\)", mode)
        out.append({**r, "project_name": clean(m[1]), "project_code": m[3] or None,
                    "remarks": f"ppp_mode: {inner[1].strip() if inner else mode}"})
    # printed sector totals of the original and anticipated cost vs the rows
    bad = []
    for grand, sec, tv in totals:
        mine = [r for r in out if grand or r["sector_raw"] == sec]
        for k, f in ((4, "cost_original_cr"), (5, "cost_anticipated_cr")):
            s = sum(r.get(f) or 0 for r in mine)
            if tv.get(k) is not None and abs(s - tv[k]) > 0.05:
                sec_sum = sum(t.get(k) or 0 for g, _, t in totals if not g)
                bad.append(f"{'Grand Total' if grand else sec} {f} {s:.2f} vs printed {tv[k]:.2f}"
                           + (" (the printed sector totals also add up to the rows' sum: source misprint)"
                              if grand and abs(sec_sum - s) < 0.05 else ""))
    return out, len(rows) - len(out), bad


MONTHWISE_RE = re.compile(r"Month\s*wise\s+List of Completed Projects", re.I)


def split_name_agency_code(full):
    """'NAME (AGENCY (ABBR)) - [N12000018]' -> (name, agency, code); agency = last balanced (...) group."""
    code = None
    m = re.search(r"-?\s*\[\s*([A-Za-z0-9]*)\s*\]\s*$", full)
    if m:
        code, full = m[1] or None, full[:m.start()].rstrip(" -")
    agency = None
    if full.endswith(")"):
        depth = 0
        for i in range(len(full) - 1, -1, -1):
            depth += {")": 1, "(": -1}.get(full[i], 0)
            if depth == 0:
                agency, full = full[i + 1:-1].strip(), full[:i]
                break
    return clean(full), agency, code


def parse_completed_monthwise(doc, pages):
    """July-Sep-2015 variant: 'Month wise List of Completed Projects Costing Rs.150 crore and above during 2015-2016'.
    Columns: Sl, 'NAME (AGENCY) - [CODE]' (wrapped), Original Cost, Original DOC, Cumulative Expenditure;
    bold sector headings."""
    rows, cur, sector, title = [], None, None, None
    for pno in pages:
        lines = content_lines(doc[pno])
        tl = next((l for l in lines[:3] if MONTHWISE_RE.search(l["text"])), None)
        if not tl:
            continue
        title = clean(tl["text"])
        hx = colmap_from_header(lines, ["Original Cost", "Original Date", "Cumulative", "Sl."])
        if len(hx) < 4:
            continue
        hdr_bottom = max(l["y"] for l in lines if re.search(r"Project Name|commissioning", l["text"]))
        for ln in lines:
            if ln["y"] <= hdr_bottom:
                continue
            sp = ln["spans"]
            if all(s[5] & 16 for s in sp) and ln["x0"] < hx["Original Cost"]:
                sector = ln["text"]
                continue
            if re.fullmatch(r"\d{1,3}", sp[0][4].strip()) and sp[0][0] < hx["Sl."] + 30 and len(sp) > 1:
                if cur:
                    rows.append(cur)
                cur = {"page": pno + 1, "sector_raw": sector, "_name": [], "_cost": None, "_doc": None, "_exp": None}
                sp = sp[1:]
            if cur is None:
                continue
            for s in sp:
                x, tx = sx0(s), s[4].strip()
                if not tx:
                    continue
                if x < hx["Original Cost"] - 5:
                    cur["_name"].append(tx)
                elif x < hx["Original Date"] - 5:
                    cur["_cost"] = tx
                elif x < hx["Cumulative"] - 5:
                    cur["_doc"] = tx
                else:
                    cur["_exp"] = tx
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        name, agency, code = split_name_agency_code(clean(" ".join(r["_name"])))
        out.append({"page": r["page"], "sector_raw": r["sector_raw"], "agency": agency, "project_code": code,
                    "project_name": name, "cost_original_cr": to_num(r["_cost"]), "doc_original": to_ym(r["_doc"]),
                    "expenditure_cum_cr": to_num(r["_exp"]), "remarks": f"Listed in '{title}'"})
    return out


# ------------------------------------------------------------ per-file driver
# Part-II sector headings seen across the family (a sector with no ongoing project in one report can still be a
# Part-I table row there, e.g. PETROCHEMICALS in 2017-18)
FAMILY_SECTORS = {"ATOMIC ENERGY", "CIVIL AVIATION", "COAL", "DEFENCE PRODUCTION", "FERTILISERS",
                  "HEALTH AND FAMILY WELFARE", "HEAVY INDUSTRY", "MINES", "PETROCHEMICALS", "PETROLEUM", "POWER",
                  "RAILWAYS", "ROAD TRANSPORT AND HIGHWAYS", "SHIPPING AND PORTS", "STEEL", "TELECOMMUNICATIONS",
                  "URBAN DEVELOPMENT", "WATER RESOURCES"}


def norm_label(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def canon_label(label, canon):
    """Printed sector label, possibly wrapped mid-word ('TELECOMMUNICATIO NS') or cut short ('URBAN DEVELOPMEN'),
    -> the report's Part-II sector heading; None when nothing matches unambiguously."""
    n = norm_label(label)
    by = {norm_label(c): c for c in canon}
    if n in by:
        return by[n]
    hits = [c for k, c in by.items() if len(n) >= 5 and k.startswith(n)]
    return hits[0] if len(hits) == 1 else None


def dedupe(rows):
    seen, out = set(), []
    for p in rows:
        k = (p["project_name"], p.get("doc_original"), p.get("cost_original_cr"))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def process_file(path):
    path = Path(path)
    src = rel(path)
    ym, q = period_from_name(path.name)
    base = {"report_period": ym, "report_type": REPORT_TYPE, "fiscal_year": fiscal_year(ym), "quarter": q,
            "source_file": src}
    notes = []
    doc = fitz.open(str(path))
    title = clean(" ".join(l["text"] for l in content_lines(doc[0])))
    mt = re.search(r"(January|April|July|October)\s*-\s*(March|June|September|December)\s*,?\s*(\d{4})", title, re.I)
    if mt:
        if to_ym(f"{mt[2]} {mt[3]}") != ym:
            notes.append(f"cover title says '{mt[0]}' but filename period is {ym}")
    else:
        notes.append("cover-page period text not found (image cover)")

    projects, info = parse_part2(doc)
    projects = [finalize_project(p) for p in projects]
    p2 = set(range(info["start"], info["end"] + 1)) if info["start"] is not None else set()
    other_pages = [i for i in range(doc.page_count) if i not in p2]
    derived = parse_derived_lists(doc, [i for i in other_pages if i > (info["end"] or 0)])
    by_code = {}
    for r in derived:
        if r["project_code"] and r.get("doa_original"):
            by_code.setdefault(r["project_code"], r)
    n_doa = 0
    for p in projects:
        # the 2017-18 Q3/Q4 detail tables leave column (1) empty: the DOA printed in the derived lists is the same
        # report's value
        hit = by_code.get(p.get("project_code")) if not p.get("doa_original") else None
        if hit:
            p["doa_original"] = hit["doa_original"]
            p["_dq"].append(f"doa_from_derived_list:p{hit['page']}")
            n_doa += 1
    if n_doa:
        notes.append(f"{n_doa} blank detail-table DOAs taken from the report's derived lists (Annexure III-VII)")
    for p in projects:
        if "header_and_table_not_printed" not in p["_dq"]:
            continue
        # recover code and values from the same report's derived list (ahead / on schedule / delayed / ...)
        hit = next((dict(r) for r in derived if r["_key"] == norm_label(p["project_name"])), None)
        if hit:
            pg = hit.pop("page")
            hit.pop("_key")
            p.update({k: v for k, v in hit.items() if v is not None})
            p["expenditure_upto"] = ym if hit.get("expenditure_cum_cr") is not None else None
            p["_dq"].append(f"values_from_derived_list:p{pg}")
        notes.append(f"p{p['page']}: project narrative '{p['project_name']}' printed without its header and value "
                     f"table (the page before it holds only a sector chart image); "
                     + (f"code and values taken from the report's derived list on p{pg}" if hit else
                        "numbers left blank"))
    uptos = Counter(p.get("expenditure_upto") for p in projects)
    if uptos and None in uptos and len(uptos) == 1:
        notes.append("detail tables print no '(upto dd.mm.yyyy)' header; expenditure_upto set to quarter end")
        for p in projects:
            p["expenditure_upto"] = ym
    elif uptos and uptos.most_common(1)[0][0] != ym:
        notes.append(f"detail-table expenditure date {uptos.most_common(1)[0][0]} != period {ym}")
    n_ph = sum(1 for p in projects if p.pop("_placeholder_doc", False))
    if n_ph:
        notes.append(f"{n_ph} placeholder original DOC '01/1999' (before approval date, or no DOA printed) blanked, "
                     "with the time overrun printed from it")
    n_z = Counter(d for p in projects for d in p["_dq"] if d.startswith("placeholder_zero"))
    if n_z:
        notes.append("OCMS '0.00' = not reported, blanked: " + ", ".join(
            f"{v} {k.split(':')[1]}" for k, v in sorted(n_z.items())))
    for p in projects:
        p.update(base, list_type="ongoing")
        loc = p.get("location") or ""
        if loc:     # 'KALPAKKAM,TAMIL NADU' -> state as printed after the last comma
            p["state"] = clean(loc.split(",")[-1]) or None

    add = parse_additional_delay(doc, other_pages)
    add_u = dedupe(add)
    for p in add_u:
        p.update(base, list_type="other:additionally_delayed")
    if len(add_u) < len(add):
        notes.append(f"additionally-delayed list printed twice; {len(add) - len(add_u)} duplicate rows dropped")
    as_on = next((re.search(r"as on (.+)\.$", p["remarks"] or "") for p in add_u if p["remarks"]), None)
    if as_on and ym[:4] not in as_on[1]:
        notes.append(f"additionally-delayed list header says 'as on {as_on[1]}' (report period {ym})")
    comp = parse_completed(doc, other_pages) + parse_completed_monthwise(doc, other_pages)
    comp_u = dedupe(comp)
    for p in comp_u:
        p.update(base, list_type="completed")
    if len(comp_u) < len(comp):
        notes.append(f"completed list printed twice; {len(comp) - len(comp_u)} duplicate rows dropped")
    ppp, ppp_bad, ppp_chk = parse_ppp(doc, other_pages)
    for p in ppp:
        p.update(base, list_type="other:ppp")
    if ppp:
        notes.append(f"Annexure-XII PPP list: {len(ppp)} rows (PPP mode in remarks)"
                     + (f", {ppp_bad} rows without a parsable 'NAME - PPP (MODE) - [CODE]'" if ppp_bad else "")
                     + ("; " + "; ".join(ppp_chk) if ppp_chk else "; sector and grand totals match the rows"))

    sector_of = {}
    for pno in info["status_pages"]:
        for l in content_lines(doc[pno])[:4]:
            m = re.match(r"^Sector\s*:\s*(.+)$", l["text"])
            if m:
                sector_of[pno] = clean(m[1])
    summ, found, checks = parse_summaries(doc, other_pages, info["status_pages"], sector_of)
    canon = {p["sector_raw"] for p in projects if p.get("sector_raw")} | set(sector_of.values()) | FAMILY_SECTORS
    unmatched = set()
    for r in summ:
        if r["dimension"] == "sector" and r["_key"] != "secstat" and r["dimension_value"] != "Total":
            c = canon_label(r["dimension_value"], canon)
            if c:
                r["dimension_value"] = c
            else:
                unmatched.add(r["dimension_value"])
    if unmatched:
        notes.append("sector labels not matching any Part-II sector heading (kept as printed): "
                     + ", ".join(sorted(unmatched)))
    summ += parse_highlights(doc, other_pages)
    summ += parse_foreword(doc, other_pages[:15])
    ov = parse_overview_counts(doc, other_pages[:40])
    summ += ov
    qn = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}[q]
    has_q = any(re.search(r"Qtr\.", p["remarks"] or "") for p in comp_u)
    cnt = {"n_additional_delay": len(add_u), "n_completed": len(comp_u), "n_completed_fy": len(comp_u),
           "n_completed_qtr": sum(1 for p in comp_u if re.search(rf"Qtr\.\s*{qn}\b", p["remarks"] or ""))
           if has_q else len(comp_u)}
    for r in ov:
        m, v = r["metric"], r["value"]
        other = {"n_completed_qtr": "n_completed_fy", "n_completed_fy": "n_completed_qtr"}.get(m)
        # the wording is not reliable ('During the second quarter of 2016-17, 67 projects' = 38 Q1 + 29 Q2):
        # when the list's 'Completed during Qtr.' column shows the number is the other count, store it as that
        if other and has_q and v != cnt[m] and v == cnt[other]:
            notes.append(f"text p{r['page']} words the {int(v)} completed projects as the "
                         f"{'quarter' if m == 'n_completed_qtr' else 'year'}'s count but the completed list shows "
                         f"it is the {'fiscal-year-to-date' if other == 'n_completed_fy' else 'quarter'} count; "
                         f"stored as {other}")
            r["metric"] = m = other
        if v != cnt[m]:
            notes.append(f"{m} stated {int(v)} (p{r['page']}) vs {cnt[m]} list rows")
    seen, summ_u = set(), []
    for r in summ:   # Part I is printed twice in some reports: keep first copy
        k = (r["table_title"], r["dimension"], r["dimension_value"], r["sub_dimension_value"], r["metric"])
        if k in seen:
            continue
        seen.add(k)
        summ_u.append({**base, **{c: r.get(c) for c in SUMMARY_COLS if c in r}})
    missing = [k for k, *_ in TABLES if not found.get(k)]
    if missing:
        notes.append("summary tables not found/parsed: " + ",".join(missing))
    notes.append(f"Part-II sector status tables parsed: {found.get('secstat', 0)}/{len(info['status_pages'])}")
    if checks:
        notes.append("; ".join(checks[:8]))
    stated = next((r["value"] for r in summ if r["metric"] == "n_projects" and r["dimension"] == "overall"), None)
    if stated is not None and projects:
        if len(projects) != stated:
            gap = (len(projects) - stated) / stated * 100
            notes.append(f"ongoing rows {len(projects)} vs stated {int(stated)} ({gap:+.2f}%)")
    else:
        notes.append("stated total not found")
    # per-sector: detail blocks vs the Part-II sector status table total
    per_sec = Counter(p["sector_raw"] for p in projects)
    for r in summ:
        if r["table_title"].startswith("Part-II") and r["metric"] == "n_projects"                 and r["sub_dimension_value"] == "Total" and per_sec.get(r["dimension_value"], 0) != r["value"]:
            notes.append(f"sector {r['dimension_value']}: {per_sec.get(r['dimension_value'], 0)} detail blocks vs "
                         f"{int(r['value'])} in its status table (p{r['page']})")
    if not add_u:
        notes.append("no 'List Of Additionally Delayed Projects' table in this report")
    if not comp_u:
        notes.append("no completed-projects list in this report")
    ok = projects and stated is not None and abs(len(projects) - stated) <= 0.02 * stated
    man = {**{k: base[k] for k in ("source_file", "report_type", "report_period")},
           "pages": doc.page_count, "parser_variant": "fitz spans: Part-II detail blocks + appendix lists + grid tables",
           "stated_total_projects": stated, "rows_ongoing": len(projects), "rows_completed": len(comp_u),
           "rows_other": len(add_u) + len(ppp), "rows_summary": len(summ_u), "rows_perf": None, "rows_perf_detail": None,
           "status": "ok" if ok else "partial", "notes": "; ".join(notes)}
    for r in projects + comp_u + add_u + ppp:
        r["dq_note"] = ";".join(dict.fromkeys(r.pop("_dq", []))) or None
    return {"projects": [{c: r.get(c) for c in PROJECT_COLS} for r in projects + comp_u + add_u + ppp],
            "summary": summ_u, "manifest": man}


def safe_process(path):
    try:
        return process_file(path)
    except Exception as e:  # noqa: BLE001 - recorded in manifest
        import traceback
        ym, q = period_from_name(Path(path).name)
        return {"projects": [], "summary": [], "manifest": {
            "source_file": rel(path), "report_type": REPORT_TYPE, "report_period": ym, "pages": None,
            "parser_variant": None, "stated_total_projects": None, "rows_ongoing": 0, "rows_completed": 0,
            "rows_other": 0, "rows_summary": 0, "rows_perf": None, "rows_perf_detail": None,
            "status": "failed", "notes": f"{type(e).__name__}: {e} | {traceback.format_exc()[-400:]}"}}


def cache_path(path):
    return CACHE / (re.sub(r"\W", "_", rel(path)) + ".json")


def run_one(path):
    res = safe_process(path)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_path(path).write_text(json.dumps(res, default=str), encoding="utf-8")
    m = res["manifest"]
    return m["source_file"], m["status"], m["rows_ongoing"], m["rows_completed"], m["rows_other"], m["rows_summary"]


XREPORT_FLAG = "placeholder_zero:{col}:earlier_report_positive"


def cross_report_placeholders(df):
    """'0.00' cumulative expenditure / physical progress after an earlier report printed a positive value for the same
    project is the OCMS 'not reported' default (neither can fall back to zero): blank + dq_note.
    -> (df, Counter of (source_file, column))."""
    hits = Counter()
    on = df[(df.list_type == "ongoing") & df.project_code.notna()]
    for col in ("expenditure_cum_cr", "physical_progress_pct"):
        per = on.groupby(["project_code", "report_period"])[col].max()
        prev = per.groupby(level=0).transform(lambda s: s.shift().cummax().ffill()).rename("_prev")
        j = on[["project_code", "report_period", col]].join(prev, on=["project_code", "report_period"])
        idx = j.index[(j[col] == 0) & (j["_prev"] > 0)]
        df.loc[idx, col] = None
        flag = XREPORT_FLAG.format(col=col)
        df.loc[idx, "dq_note"] = [f"{d};{flag}" if isinstance(d, str) and d else flag for d in df.loc[idx, "dq_note"]]
        hits.update((f, col) for f in df.loc[idx, "source_file"])
    return df, hits


def merge():
    import pandas as pd
    P, S, M = [], [], []
    for f in files():
        cp = cache_path(f)
        if not cp.exists():
            ym, q = period_from_name(f.name)
            M.append({"source_file": rel(f), "report_type": REPORT_TYPE, "report_period": ym,
                      "status": "failed", "notes": "not processed (no cache)"})
            continue
        res = json.loads(cp.read_text(encoding="utf-8"))
        P += res["projects"]
        S += res["summary"]
        M.append(res["manifest"])
    pdf = pd.DataFrame(P, columns=PROJECT_COLS)
    pdf, hits = cross_report_placeholders(pdf)
    for m in M:
        h = [f"{hits[(m['source_file'], c)]} {c}" for c in ("expenditure_cum_cr", "physical_progress_pct")
             if hits[(m["source_file"], c)]]
        if h:
            m["notes"] = (f"{m.get('notes') or ''}; '0.00' after a positive value in an earlier report, blanked: "
                          + ", ".join(h))
    write_part(pdf, FAMILY, "projects", PROJECT_COLS)
    write_part(pd.DataFrame(S, columns=SUMMARY_COLS), FAMILY, "summary", SUMMARY_COLS)
    write_part(pd.DataFrame(M, columns=MANIFEST_COLS), FAMILY, "manifest", MANIFEST_COLS)
    return pdf, S, M


# ------------------------------------------------------------ self-check
def selfcheck():
    # detail-table cell parser: brackets pick original / (revised) / [anticipated]
    centers = {1: 100, 2: 150, 3: 215, 4: 285, 5: 360, 6: 432, 7: 490}
    vals = [(86, 298, 118, 308, "01/2005"), (145, 288, 172, 298, "302.96"), (154, 298, 163, 308, "(310)"),
            (142, 308, 175, 318, "[1,302.96]"), (205, 288, 230, 298, "330.06 %"), (274, 288, 306, 298, "03/2010"),
            (284, 298, 296, 308, "(-)"), (271, 308, 309, 318, "[03/2018]"), (355, 288, 378, 298, "49.38"),
            (353, 298, 380, 308, "328.96"), (350, 308, 383, 318, "(329.10)"), (432, 288, 443, 298, "96"),
            (432, 298, 443, 308, "(-)"), (429, 308, 446, 318, "[96]"), (478, 293, 505, 303, "92.00")]
    f = parse_table(centers, vals, 10.5)
    assert f["doa_original"] == "2005-01" and f["cost_original_cr"] == 302.96
    assert f["cost_revised_cr"] == 310 and f["cost_anticipated_cr"] == 1302.96
    assert f["cost_overrun_pct"] == 330.06 and f["doc_original"] == "2010-03" and f["doc_revised"] is None
    assert f["doc_anticipated"] == "2018-03" and f["outlay_current_fy_cr"] == 49.38
    assert f["expenditure_cum_cr"] == 329.10 and f["delay_months"] == 96 and f["_pp_col"] == 92.0
    # outlay missing ('-') must not shift the cumulative expenditure into outlay
    f2 = parse_table(centers, [v if v[4] != "49.38" else (355, 288, 378, 298, "-") for v in vals], 10.5)
    assert f2["outlay_current_fy_cr"] is None and f2["expenditure_cum_cr"] == 329.10
    # delay printed only in the middle row ('-') must not become delay_months
    f3 = parse_table(centers, [v for v in vals if v[4] not in ("96", "[96]")], 10.5)
    assert f3["delay_months"] is None
    assert period_from_name("april-june-2014.pdf") == ("2014-06", "Q1")
    assert period_from_name("Jan-March_2018.pdf") == ("2018-03", "Q4")
    assert period_from_name("oct-dec_2015.pdf") == ("2015-12", "Q3")
    assert narrative_pp("Reported physical progress is 97.5%") == 97.5
    assert narrative_pp("physical progress 40% and later physical progress 60%") is None
    assert strip_heading("NEELAM REDEVELOPMENT PLAN, MUMBAI, MAHARASHTRA Project was approved", "NEELAM REDEVELOPMENT PLAN",
                         "MUMBAI,MAHARASHTRA", None) == "Project was approved"
    assert strip_heading("KK APP, TN, 2x2000 MW KK APP, TN Govt approved", "KK APP", "TN", "2x2000 MW") == "Govt approved"
    assert strip_heading("Project X was approved", "KK APP", "TN", None) == "Project X was approved"
    # grid parser: wrapped label with values split over two lines
    mk = lambda y, items: {"y": y, "text": " ".join(t for x, t in items), "x0": items[0][0],
                           "spans": [(x, y - 4, x + 6 * len(t), y + 4, t, 0, 9) for x, t in items]}
    L = [mk(10, [(60, "Sector"), (170, "Original"), (210, "Latest")]),
         mk(30, [(60, "COAL"), (180, "1"), (220, "2")]),
         mk(45, [(60, "ROAD"), (60 + 30, "TRANSPORT")]),
         mk(47, [(220, "9")]),
         mk(55, [(60, "HIGHWAYS"), (180, "4")]),
         mk(70, [(60, "Total"), (180, "5"), (220, "11")])]
    n, rows = parse_grid(L, 0, [2])
    assert n == 2 and [r["label"] for r in rows] == ["COAL", "ROAD TRANSPORT HIGHWAYS", "Total"], rows
    assert rows[1]["vals"] == {0: "4", 1: "9"} and total_check(rows, 2) == []
    # a number wrapped inside its cell + a 3-line label: 'WELFARE' belongs to the row above, not to RAILWAYS
    L2 = [mk(10, [(60, "Sector"), (170, "Original"), (230, "Anticipated")]),
          mk(30, [(40, "1"), (60, "COAL"), (180, "1,234.56"), (230, "2,000.00")]),
          mk(45, [(40, "2"), (60, "HEALTH"), (100, "AND"), (180, "191,155.3"), (230, "300.00")]),
          mk(55, [(60, "FAMILY"), (190, "5")]),
          mk(65, [(60, "WELFARE")]),
          mk(78, [(40, "3"), (60, "RAILWAYS"), (180, "10.00"), (230, "20.00")]),
          mk(95, [(60, "Total"), (180, "192,399.91"), (230, "2,320.00")])]
    n, rows = parse_grid(L2, 0, [2])
    assert [r["label"] for r in rows] == ["COAL", "HEALTH AND FAMILY WELFARE", "RAILWAYS", "Total"], rows
    assert rows[1]["vals"][0] == "191,155.35" and total_check(rows, 2) == []
    # delay-range cells: '17 - 71', '54- 71', '61 -' (max on the next line); two separate columns are not a range
    assert merge_range([(500, "0.0"), (550, "17"), (557, "-"), (569, "71")])[-1][1] == "17-71"
    assert merge_range([(500, "0.0"), (545, "54-"), (559, "71")])[-1][1] == "54-71"
    assert merge_range([(507, "56.5"), (548, "61"), (555, "-")])[-1][1] == "61-"
    assert merge_range([(470, "12"), (507, "15"), (552, "-")])[-1][1] == "-"
    assert canon_label("TELECOMMUNICATIO NS", FAMILY_SECTORS) == "TELECOMMUNICATIONS"
    assert canon_label("URBAN DEVELOPMEN", FAMILY_SECTORS) == "URBAN DEVELOPMENT"
    assert canon_label("WELFARE RAILWAYS", FAMILY_SECTORS) is None
    assert split_name_agency_code("BAILADILA DEPOSIT- 11B (NMDC) (NATIONAL MINERAL DEVELOPMENT CORPORATION (NMDC)) - "
                                  "[N12000018]") == ("BAILADILA DEPOSIT- 11B (NMDC)",
                                                     "NATIONAL MINERAL DEVELOPMENT CORPORATION (NMDC)", "N12000018")
    assert sx0((322.5, 0, 418.5, 0, "        3,492.00", 0, 10)) == 370.5
    assert SECTION_RE.match("PART-II Annexure") and not SECTION_RE.match("Annexure-I of the DPR")
    print("selfcheck ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--selfcheck"]:
        selfcheck()
    elif args[:1] == ["--one"]:
        f = next(p for p in files() if p.name == args[1] or rel(p) == args[1])
        print(run_one(f))
    elif args[:1] == ["--merge"]:
        pdf, S, M = merge()
        print(len(pdf), len(S), len(M))
    else:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=int(os.environ.get("QPISR_WORKERS", "4"))) as ex:
            for r in ex.map(run_one, files()):
                print(*r, flush=True)
        pdf, S, M = merge()
        print("projects", len(pdf), "summary", len(S), "manifest", len(M))
        selfcheck()
