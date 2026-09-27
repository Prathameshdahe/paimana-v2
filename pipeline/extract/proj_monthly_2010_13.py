"""
Extractor for MoSPI IPMD monthly Flash Reports, FY 2010-11 .. 2012-13
(Project Monitoring/monthly/2010-11, 2011-12, 2012-13; 36 PDFs).

Run from repo root:  python pipeline/extract/proj_monthly_2010_13.py

Outputs (dataset/clean/_parts/proj_monthly_2010_13/):
  projects.csv  - ongoing master list ("Sector Wise Details"), month-wise completed
                  list (Annexure-I), month-wise deleted list, list of projects added,
                  list of projects completed/dropped/frozen in current month, list of
                  projects reporting additional delays.
  summary.csv   - executive-summary sector table, sectorwise analysis, sector totals of
                  the master list, project status / cost tables, milestones,
                  "Extent of ... overrun" tables (sector / state wise), state-wise
                  annexure, sector-wise current status pages.
  manifest.csv  - one row per PDF.

All tables are parsed from PyMuPDF word coordinates (pdftotext -layout scrambles
several of these pages). Hindi pages are skipped.
"""
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, PROJECT_COLS, SUMMARY_COLS,  # noqa: E402
                    fiscal_year, rel, to_num, to_ym, write_part)

FAMILY = "proj_monthly_2010_13"
SRC = DATASET / "Project Monitoring" / "monthly"
FY_DIRS = ["2010-11", "2011-12", "2012-13"]
REPORT_TYPE = "monthly_flash"

DATE_RE = re.compile(r"^\d{1,2}/\d{4}$")
NUM_RE = re.compile(r"^-?[\d,]*\.?\d+$")
DELAY_RE = re.compile(r"^(-?\d+)\((O|R\d*)\)$")
MS_RE = re.compile(r"^\d+/\d+$")
CODE_RE = re.compile(r"\s*-?\s*\[\s*([A-Za-z]?\d{6,})\s*\]\s*")

SECTORS = {
    "atomic energy", "civil aviation", "coal", "fertilisers", "fertilizers", "mines",
    "steel", "petroleum", "petrochemicals", "power", "health & family welfare",
    "health & fw", "railways", "road transport & highways", "road transport and highways",
    "shipping & ports", "shipping and ports", "telecommunications", "telecommunication",
    "urban development", "water resources", "information technology",
    "information & broadcasting", "i & b", "sports", "science & technology",
    "petroleum & natural gas",
}
MONTH_HEAD_RE = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*,?\s*'?\s*(\d{4})$",
                           re.I)


# ---------------------------------------------------------------- basics
def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def page_lines(page):
    """Words grouped into visual lines: [{'yc','y0','y1','w':[words sorted by x]}]."""
    ws = sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in ws:
        yc = (w[1] + w[3]) / 2
        if lines and abs(yc - lines[-1]["yc"]) <= 1.5:
            lines[-1]["w"].append(w)
        else:
            lines.append({"yc": yc, "y0": w[1], "y1": w[3], "w": [w]})
    for ln in lines:
        ln["w"].sort(key=lambda w: w[0])
        ln["text"] = " ".join(w[4] for w in ln["w"])
    return lines


def xc(w):
    return (w[0] + w[2]) / 2


def is_hindi(text):
    return sum(1 for c in text if "ऀ" <= c <= "ॿ") > 50


def nearest(x, centers):
    return min(range(len(centers)), key=lambda i: abs(x - centers[i]))


def ym(tok):
    return to_ym(tok) if tok else None


def period_from_name(path):
    m = re.search(r"fr_([a-z]+)_(\d{4})", path.stem, re.I)
    return to_ym(f"{m[1]} {m[2]}")


def join_wrapped(parts, keep_apart=frozenset()):
    """Join the printed lines of a wrapped name. A line that ends in a hyphen attached to a word
    ('NATIONAL HYDRO-' / 'ELECTRIC ...', '(25-' / '35) MTY') continues that word, so no space is
    put after it; a free-standing ' - ' is kept as printed, and so is a next line that is a whole
    agency (the VIII list prints it under a name cut at 'PHASE-'). Returns (text, joined_any)."""
    out, joined = "", False
    for p in (clean(x) for x in parts):
        if not p:
            continue
        if re.search(r"[A-Za-z0-9.)]-$", out) and re.match(r"[A-Za-z0-9]", p) and p not in keep_apart:
            out, joined = out + p, True
        else:
            out = f"{out} {p}" if out else p
    return out, joined


def add_dq(row, flag):
    row["dq_note"] = ";".join(x for x in (row.get("dq_note"), flag) if x)


def split_code(name):
    """'KAIGA 3 and 4 UNITS (NPCIL) - [020100041]NPCIL,Karnataka'
    -> ('KAIGA 3 and 4 UNITS (NPCIL)', '020100041', 'NPCIL,Karnataka')"""
    m = CODE_RE.search(name)
    if not m:
        return clean(name).rstrip(" -"), None, ""
    return clean(name[:m.start()]).rstrip(" -").strip(), m[1], clean(name[m.end():])


def split_agency_paren(name):
    """'SIPAT STPP STAGE - I (NTPC)(NATIONAL THERMAL POWER CORPORATION)'
    -> ('SIPAT STPP STAGE - I (NTPC)', 'NATIONAL THERMAL POWER CORPORATION').
    Only the last balanced (...) group with >= 2 words is treated as agency."""
    s = name.rstrip()
    if not s.endswith(")"):
        return name, None
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                inner = s[i + 1:-1].strip()
                if len(inner.split()) >= 2 and not re.search(r"\d", inner.split()[0]):
                    return clean(s[:i]), clean(inner)
                return name, None
    return name, None


def is_sector_heading(text):
    t = clean(text).lower().replace(" and ", " & ")
    return t in SECTORS or t.replace("&", "and") in SECTORS


# ---------------------------------------------------------------- ongoing list
def find_colnum_row(lines):
    """The '1 2 3 ... 10' column-number row under the list header."""
    for i, ln in enumerate(lines):
        t = [w[4] for w in ln["w"]]
        if t == [str(k) for k in range(1, 11)]:
            return i, [xc(w) for w in ln["w"]]
    return None, None


def ongoing_header(lines):
    txt = " ".join(ln["text"] for ln in lines[:25])
    if not ("Approval" in txt and "Cumm" in txt and "Expendi" in txt):
        return None
    i, cols = find_colnum_row(lines)
    if i is None:
        return None
    name_x0 = None
    for ln in lines[:i]:
        for w in ln["w"]:
            if w[4] == "Project":
                name_x0 = w[0]
    if name_x0 is None:
        return None
    return {"row": i, "cols": cols, "name_x0": name_x0}


def parse_ongoing(doc, pages, ctx):
    """pages: list of 0-based page idx forming the master list."""
    projects, summary, issues = [], [], []
    sector = None
    rec = None
    snos = []

    def close():
        nonlocal rec
        if rec:
            projects.append(finish_ongoing(rec, ctx, issues))
        rec = None

    for pi in pages:
        lines = page_lines(doc[pi])
        hdr = ongoing_header(lines)
        cols, name_x0 = hdr["cols"], hdr["name_x0"]
        c3 = cols[2]
        prev_yc = lines[hdr["row"]]["yc"]
        for ln in lines[hdr["row"] + 1:]:
            ws = ln["w"]
            if ln["yc"] > 735 and len(ws) == 1 and ws[0][4].isdigit():
                continue  # page number
            gap = ln["yc"] - prev_yc
            prev_yc = ln["yc"]
            sno = None
            if ws[0][4].isdigit() and ws[0][2] <= name_x0 + 1.5:
                sno = int(ws[0][4])
                ws = ws[1:]
            name_ws, cells = [], {}
            for w in ws:
                if xc(w) < c3 - 13:
                    name_ws.append(w[4])
                else:
                    cells.setdefault(nearest(xc(w), cols) + 1, []).append(w[4])
            name_txt = " ".join(name_ws)
            if sno is None and re.match(r"^(Grand\s+)?Total$", name_txt, re.I):
                close()
                tot = {k: "".join(v) for k, v in cells.items()}
                if not tot:
                    continue
                grand = name_txt.lower().startswith("grand")
                dv = "Total" if grand else sector
                for col, metric in ((4, "cost_original_cr"), (5, "cost_anticipated_cr"),
                                    (6, "expenditure_cr")):
                    v = to_num(tot.get(col))
                    if v is not None:
                        summary.append(srow(ctx, pi, "Sector wise details - totals",
                                            "sector", dv, metric, v, "Rs crore"))
                ms = tot.get(10)
                if ms and MS_RE.match(ms):
                    a, b = ms.split("/")
                    summary.append(srow(ctx, pi, "Sector wise details - totals", "sector", dv,
                                        "n_milestones_achieved", float(a), "count"))
                    summary.append(srow(ctx, pi, "Sector wise details - totals", "sector", dv,
                                        "n_milestones_total", float(b), "count"))
                ctx.setdefault("sector_totals", {})[dv] = {k: to_num(tot.get(k)) for k in (4, 5, 6)}
                continue
            if sno is None and not cells and name_txt and (gap > 18 or rec is None):
                if name_txt.lower().startswith("sector wise"):
                    continue
                close()
                sector = clean(name_txt)
                ctx.setdefault("sectors", set()).add(sector.lower())
                continue
            if sno is not None:
                close()
                snos.append(sno)
                rec = {"sno": sno, "sector": sector, "page": pi + 1, "name": [], "cells": {}}
            if rec is None:
                if ws and any(w[4] != "-" for w in ws):
                    issues.append(f"p{pi+1}: orphan line '{ln['text'][:60]}'")
                continue
            rec["name"].append(name_txt)
            for k, v in cells.items():
                rec["cells"].setdefault(k, []).append("".join(v))
    close()
    return projects, summary, issues, snos


def finish_ongoing(rec, ctx, issues):
    c = rec["cells"]
    g = lambda k, i=0: (c.get(k) or [None] * (i + 1))[i] if len(c.get(k) or []) > i else None  # noqa: E731
    txt, joined = join_wrapped(rec["name"])
    name, code, tail = split_code(txt)
    agency = state = None
    if tail:
        if "," in tail:
            agency, state = [clean(x) for x in tail.split(",", 1)]
        else:
            agency = tail
    remarks = []
    delay = None
    for i, tok in enumerate(c.get(9) or []):
        m = DELAY_RE.match(tok)
        if not m:
            if tok not in ("-", "N.A.", "NA"):
                issues.append(f"sno {rec['sno']}: odd delay token {tok!r}")
            continue
        if m[2] == "O" and i == 0:
            delay = float(m[1])
        else:
            remarks.append(f"Delay w.r.t. revised schedule ({m[2]}): {m[1]} months")
    ms = g(10)
    if ms and MS_RE.match(ms):
        remarks.append(f"Milestones achieved/total: {ms}")
    for k, lim in ((3, 2), (4, 2), (5, 1), (6, 1), (7, 2), (8, 1), (10, 1)):
        if len(c.get(k) or []) > lim:
            issues.append(f"sno {rec['sno']}: col{k} has {c[k]}")
    row = base_row(ctx, rec["page"], "ongoing")
    row.update(
        project_code=code, project_name=name, sector_raw=rec["sector"], agency=agency, state=state,
        doa_original=ym(g(3)), doa_revised=ym(g(3, 1)),
        cost_original_cr=to_num(g(4)), cost_revised_cr=to_num(g(4, 1)),
        cost_anticipated_cr=to_num(g(5)), expenditure_cum_cr=to_num(g(6)),
        doc_original=ym(g(7)), doc_revised=ym(g(7, 1)), doc_anticipated=ym(g(8)),
        delay_months=delay, remarks="; ".join(remarks) or None,
    )
    if joined:
        add_dq(row, "hyphen_linebreak_joined")
    row["_sno"] = rec["sno"]
    return row


def base_row(ctx, page, list_type):
    return {"report_period": ctx["period"], "report_type": REPORT_TYPE,
            "fiscal_year": fiscal_year(ctx["period"]), "quarter": None,
            "source_file": ctx["src"], "page": page, "list_type": list_type}


def srow(ctx, pi, title, dim, dv, metric, value, unit, sub=None):
    return {"report_period": ctx["period"], "report_type": REPORT_TYPE,
            "fiscal_year": fiscal_year(ctx["period"]), "quarter": None,
            "source_file": ctx["src"], "page": pi + 1, "table_title": title,
            "dimension": dim, "dimension_value": dv, "sub_dimension_value": sub,
            "metric": metric, "value": value, "unit": unit}


# ---------------------------------------------------------------- small lists
LIST_TITLES = [
    (re.compile(r"Month\s*wise\s*List\s*of\s*Completed", re.I), "completed"),
    (re.compile(r"Month\s*wise\s*List\s*of\s*Delete", re.I), "dropped"),
    (re.compile(r"List\s+of\s+projects\s+completed", re.I), "other:completed_dropped_frozen_current_month"),
    (re.compile(r"List\s+of\s+projects\s+added", re.I), "newly_added"),
    (re.compile(r"List\s+of\s+projects\s+reporting\s+additional", re.I), "other:additionally_delayed"),
]
SECTION_RE = re.compile(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s|^(Extent|Trend|Graphical|Sectorwise|Summary)\b",
                        re.I)
# (field, type) per list layout; type D=date, N=number, I=integer
LIST_FIELDS = {
    "mw": [("cost_original_cr", "N"), ("doc_original", "D"), ("expenditure_cum_cr", "N")],
    "V": [("doa_original", "D"), ("cost_original_cr", "N"), ("doc_original", "D"),
          ("cost_anticipated_cr", "N"), ("doc_anticipated", "D"), ("expenditure_cum_cr", "N")],
    "VI": [("doa_original", "D"), ("cost_original_cr", "N"), ("doc_original", "D"),
           ("cost_anticipated_cr", "N"), ("doc_anticipated", "D")],
    "VIII": [("cost_original_cr", "N"), ("cost_anticipated_cr", "N"), ("doc_original", "D"),
             ("doc_last_month", "D"), ("doc_anticipated", "D"), ("additional_delay_months", "I")],
}
KIND = {"completed": "mw", "dropped": "mw", "other:completed_dropped_frozen_current_month": "V",
        "newly_added": "VI", "other:additionally_delayed": "VIII"}


def list_header(lines, kind):
    """(header_line_index, [column x-centers], sno_x1 or None) for a small list."""
    for i, ln in enumerate(lines):
        t = [w[4] for w in ln["w"]]
        cen = None
        if kind == "mw" and "Commissioning" in t:
            rs = [w for w in ln["w"] if w[4].startswith("(Rs")]
            cm = [w for w in ln["w"] if w[4] == "Commissioning"][0]
            if len(rs) >= 2:
                cen = [rs[0][0] + 20, xc(cm), rs[1][0] + 20]
        elif kind in ("V", "VI") and "DOA" in t and "DOC" in t:
            want = ["DOA", "Cost", "DOC", "Cost", "DOC"] + (["Expenditure"] if kind == "V" else [])
            ws = [w for w in ln["w"] if w[4] in ("DOA", "Cost", "DOC", "Expenditure")]
            if [w[4] for w in ws][:len(want)] == want:
                cen = [xc(w) + (8 if w[4] == "Cost" else 0) for w in ws[:len(want)]]
        elif kind == "VIII" and "Anticipated" in t and "Last" in t and "This" in t:
            o = [w for w in ln["w"] if w[4] == "Original"]
            a = [w for w in ln["w"] if w[4] == "Anticipated"][0]
            la = [w for w in ln["w"] if w[4] == "Last"][0]
            th = [w for w in ln["w"] if w[4] == "This"][0]
            dl = [w for w in ln["w"] if w[4].startswith("(in")]
            if len(o) >= 2 and dl:
                cen = [xc(o[0]), xc(a), xc(o[1]), la[0] + 20, th[0] + 20, dl[0][0] + 15]
        if cen:
            sno_x1 = None
            for ln2 in lines[max(0, i - 3):i + 1]:
                for w in ln2["w"]:
                    if w[4].lower().rstrip(".") in ("s.no", "sl", "no") and w[0] < 110:
                        sno_x1 = max(sno_x1 or 0, w[2])
            return i, cen, sno_x1
    return None, None, None


def token_type(t):
    if DATE_RE.match(t):
        return "D"
    if NUM_RE.match(t):
        return "N"
    return None


def parse_list_segment(lines, pi, list_type, ctx, vocab, issues, state):
    """Parse one titled list on one page (lines = that list's lines only).
    state carries sector / month heading and the last record across pages.
    Returns raw records; finish_list_row() turns them into rows."""
    kind = KIND[list_type]
    fields = LIST_FIELDS[kind]
    hi, cen, sno_x1 = list_header(lines, kind)
    if hi is None:
        issues.append(f"p{pi+1}: no header for {list_type}")
        return []
    name_max = min(cen) - 15
    items = []  # (yc, kind, payload)
    for ln in lines[hi + 1:]:
        ws = ln["w"]
        if ln["yc"] > 735 and len(ws) == 1 and ws[0][4].isdigit():
            continue
        if re.match(r"^Number\s+of\s+projects", ln["text"], re.I):
            items.append((ln["yc"], "stop", None))
            continue
        if re.match(r"^ANNEXURE", ln["text"]) or (
                sno_x1 and len(ws) == 1 and ws[0][4].isdigit() and ws[0][2] <= sno_x1 + 8):
            continue  # annexure tag / blank numbered row
        sno = None
        if (sno_x1 and ws[0][4].isdigit() and ws[0][2] <= sno_x1 + 8
                and len(ws) > 1 and ws[1][0] - ws[0][2] > 3):
            sno = int(ws[0][4])
            ws = ws[1:]
        name_ws, cells = [], {}
        for w in ws:
            if xc(w) < name_max:
                name_ws.append(w[4])
                continue
            tt = token_type(w[4])
            idx = [i for i, (_, t) in enumerate(fields)
                   if tt is None or (tt == "D") == (t == "D")] or list(range(len(fields)))
            j = min(idx, key=lambda i: abs(xc(w) - cen[i]))
            cells.setdefault(j, []).append(w[4])
        name_txt = clean(" ".join(name_ws))
        gap = ln["yc"] - (items[-1][0] if items else lines[hi]["yc"])
        if re.match(r"^(Grand\s+)?Total\b", name_txt, re.I) and sno is None:
            items.append((ln["yc"], "stop", None))
        elif sno is None and not cells and name_txt.isdigit() and gap > 20:
            # unlabelled count printed under the list (FY2011-12 Mar+ VIII lists), not a name part
            items.append((ln["yc"], "stop", None))
            state["printed_count"] = int(name_txt)
        elif sno is not None or any(token_type(v) or v in ("-", "N.A.", "NA")
                                    for vs in cells.values() for v in vs):
            items.append((ln["yc"], "anchor", {"sno": sno, "name": name_txt, "cells": cells}))
        elif MONTH_HEAD_RE.match(name_txt):
            items.append((ln["yc"], "month", name_txt))
        elif is_sector_heading(name_txt) or name_txt.lower() in vocab:
            items.append((ln["yc"], "sector", name_txt))
        elif name_txt:
            items.append((ln["yc"], "name", name_txt))
    anchors = [it for it in items if it[1] == "anchor"]
    if not anchors:
        return []
    # top-anchored (name starts on the data line) vs vertically centred data line
    top_mode = sno_x1 is not None or sum(1 for a in anchors if a[2]["name"]) >= len(anchors) / 2
    recs, loose, seg, cur = [], [], 0, None
    sector, month = state.get("sector"), state.get("month")
    for yc, k, p in items:
        if k in ("sector", "month", "stop"):
            seg, cur = seg + 1, None
            if k == "sector":
                sector = p
            elif k == "month":
                month = p
        elif k == "anchor":
            cur = {"yc": yc, "seg": seg, "sector": sector, "month": month, "sno": p["sno"], "page": pi + 1,
                   "name": [(yc, p["name"])] if p["name"] else [], "cells": p["cells"]}
            recs.append(cur)
        elif top_mode:
            if cur is not None:
                cur["name"].append((yc, p))
            elif seg == 0 and state.get("last") is not None:
                state["last"]["name"].append((1e6 + yc, p))  # name continued from previous page
            else:
                issues.append(f"p{pi+1}: {list_type} orphan line '{p[:50]}'")
        else:
            loose.append((yc, seg, p))
    for yc, sg, p in loose:
        cands = [r for r in recs if r["seg"] == sg]
        if cands:
            min(cands, key=lambda r: abs(r["yc"] - yc))["name"].append((yc, p))
        else:
            issues.append(f"p{pi+1}: {list_type} orphan line '{p[:50]}'")
    state.update(sector=sector, month=month, last=recs[-1] if recs else state.get("last"))
    return recs


def finish_list_row(r, list_type, ctx, issues):
    fields = LIST_FIELDS[KIND[list_type]]
    pi = r["page"] - 1
    txt, joined = join_wrapped((t for _, t in sorted(r["name"])),
                               ctx.get("agencies", set()) if KIND[list_type] == "VIII" else frozenset())
    name, code, tail = split_code(txt)
    agency = None
    if tail:
        name = clean(f"{name} {tail}")
        issues.append(f"p{pi+1}: text after code in {list_type}: {txt[:60]}")
    if KIND[list_type] == "mw":
        name, agency = split_agency_paren(name)
    row = base_row(ctx, pi + 1, list_type)
    row.update(project_code=code, project_name=name, sector_raw=r["sector"], agency=agency)
    remarks = []
    for j, (f, t) in enumerate(fields):
        vals = r["cells"].get(j) or []
        if len(vals) > 1:
            issues.append(f"p{pi+1}: {list_type} '{name[:30]}' {f} has {vals}")
        v = vals[0] if vals else None
        if f == "doc_last_month":
            if ym(v):
                remarks.append(f"DOC reported last month: {ym(v)}")
            continue
        row[f] = ym(v) if t == "D" else to_num(v)
    if r["month"]:
        verb = {"completed": "Completed", "dropped": "Deleted"}.get(list_type, "Month")
        mo = ym(r["month"])
        if mo and mo <= ctx["period"]:
            remarks.append(f"{verb} during: {mo}")
            if list_type == "completed":  # Annexure-I groups completed projects under their month
                row["date_completed_actual"] = mo
        else:  # e.g. 'November,2011' printed in the Jan-2011 report: keep the raw heading
            remarks.append(f"{verb} during (as printed, later than report month): {r['month']}")
    row["remarks"] = "; ".join(remarks) or None
    if joined:
        add_dq(row, "hyphen_linebreak_joined")
    row["_sno"] = r["sno"]
    return row


def split_trailing_agency(rows, agencies):
    """From Oct 2010 the VIII (additional delays) list prints the agency abbreviation after
    the project name ('... (NLC) NLC'). When most rows of the report end with an agency
    of that report's master list, move that trailing agency into `agency`."""
    def tail(name):
        t = (name or "").split()
        return next((n for n in (3, 2, 1) if len(t) > n and " ".join(t[-n:]) in agencies), 0)
    vi = [r for r in rows if r["list_type"] == "other:additionally_delayed"]
    if not vi or sum(1 for r in vi if tail(r["project_name"])) < 0.5 * len(vi):
        return
    for r in vi:
        n = tail(r["project_name"])
        if n:
            t = r["project_name"].split()
            r["project_name"], r["agency"] = " ".join(t[:-n]), " ".join(t[-n:])


def parse_lists(doc, texts, upto, ctx, issues):
    """Scan pages before the master list for the titled small lists."""
    vocab = set(ctx.get("sectors", set()))
    recs, states = [], {}
    for pi in range(1, upto):
        if is_hindi(texts[pi]):
            continue
        if not any(rx.search(texts[pi]) for rx, _ in LIST_TITLES):
            continue
        lines = page_lines(doc[pi])
        segs, cur = [], None
        for ln in lines:
            hit = next((lt for rx, lt in LIST_TITLES if rx.search(ln["text"])), None)
            if hit:
                cur = (hit, [])
                segs.append(cur)
            elif cur is not None and SECTION_RE.match(ln["text"]):
                cur = None
            elif cur is not None:
                cur[1].append(ln)
        for lt, lns in segs:
            if lt in ("completed", "dropped") and not any(
                    w[4] == "Commissioning" for ln in lns for w in ln["w"]):
                continue  # contents-page mention, not the list
            st = states.setdefault(lt, {})
            recs += [(lt, r) for r in parse_list_segment(lns, pi, lt, ctx, vocab, issues, st)]
    for lt, st in states.items():
        n = sum(1 for t, _ in recs if t == lt)
        if st.get("printed_count") is not None and st["printed_count"] != n:
            ctx.setdefault("src_notes", []).append(f"{lt} rows {n} vs count printed under the list {st['printed_count']}")
    return [finish_list_row(r, lt, ctx, issues) for lt, r in recs]


# ---------------------------------------------------------------- summary tables
def grid_rows(lines, cols, label_xmax, skip_sno=True, num_values=False):
    """Generic row reader: label = words left of label_xmax (leading S.No dropped),
    numeric tokens right of it assigned to the nearest column centre.
    cols = [(metric, x_centre)]. Returns [(label, {metric: raw}, line)]."""
    out = []
    centres = [c for _, c in cols]
    for ln in lines:
        ws = ln["w"]
        if skip_sno and ws and ws[0][4].isdigit() and len(ws) > 1 and xc(ws[0]) < label_xmax:
            ws = ws[1:]
        isval = [(num_values and bool(NUM_RE.match(w[4]))) or
                 (xc(w) >= label_xmax and (bool(NUM_RE.match(w[4])) or w[4] == "-")) for w in ws]
        lab = clean(" ".join(w[4] for w, v in zip(ws, isval) if not v and xc(w) < label_xmax))
        vals = {}
        for w, v in zip(ws, isval):
            if v:
                k = cols[nearest(xc(w), centres)][0]
                if k in vals:
                    vals[k] += w[4]  # split token, e.g. '1,23' '4.5'
                else:
                    vals[k] = w[4]
        out.append((lab, vals, ln))
    return out


def find_word(lines, text, start=0, after_x=-1):
    for i in range(start, len(lines)):
        for w in lines[i]["w"]:
            if w[4] == text and w[0] > after_x:
                return i, w
    return None, None


def parse_exec_table(lines, pi, ctx, out, issues):
    i, mon = find_word(lines, "Monitor")
    j, dl = find_word(lines, "Delayed")
    if mon is None or dl is None:
        return
    hdr = max(i, j)
    cols = [("n_projects", xc(mon)), ("n_additional_delay", xc(dl))]
    comp, total = {}, None
    for lab, vals, ln in grid_rows(lines[hdr + 1:], cols, xc(mon) - 40, num_values=True):
        if not lab or not vals:
            continue
        if lab.lower() == "total":
            total = vals
            lab = "Total"
        else:
            comp[lab] = vals
        for m, v in vals.items():
            if to_num(v) is not None:
                out.append(srow(ctx, pi, "Executive summary - sector-wise projects on monitor",
                                "sector", lab, m, to_num(v), "count"))
    if total:
        for m in ("n_projects", "n_additional_delay"):
            s = sum(to_num(v.get(m)) or 0 for v in comp.values())
            if to_num(total.get(m)) is not None and abs(s - to_num(total[m])) > 0.5:
                issues.append(f"p{pi+1}: exec table {m} sum {s} != total {total[m]}")
    ctx["exec_total"] = to_num((total or {}).get("n_projects"))
    ctx["exec_addl"] = to_num((total or {}).get("n_additional_delay"))


NARR_TITLE = "Executive summary (narrative) - sector-wise projects on monitor"


def narr_metric(words):
    """Column heading words -> metric. 'Additionally delayed Mega Projects' (Aug 2012+) before
    'Additionally delayed during the month' / 'Additional delays'; 'Delayed Projects w.r.t
    latest schedule' (Jul 2012+) vs plain 'Delayed Projects' (Jun 2012)."""
    t = " ".join(words).lower()
    for key, m in (("mega", "n_additional_delay_mega"), ("additional", "n_additional_delay"),
                   ("online", "n_reported_online"), ("monitor", "n_projects")):
        if key in t:
            return m
    if "delayed" in t:
        return "n_delayed_wrt_latest" if "latest" in t else "n_delayed"
    return None


def is_header_line(ln):
    """Column-heading line: its words sit apart in separate columns, or it lies wholly right
    of the label column (a one-word heading line). Paragraph text fails both tests."""
    ws = ln["w"]
    return ws[0][0] > 250 or any(b[0] - a[2] > 20 for a, b in zip(ws, ws[1:]))


def parse_narrative_sector_table(lines, pi, ctx, out, issues, addl_rows):
    """Executive-summary narrative table: S.No | Sector | Projects on monitor | then, by year,
    [Reported Online] | Additional delays, or [Delayed Projects (w.r.t latest schedule)] |
    Additionally delayed during the month | [Additionally delayed Mega Projects].
    The column map comes from the heading words; the heading can span up to 9 lines."""
    note = ctx.setdefault("src_notes", []).append
    i = None
    for k, ln in enumerate(lines):  # heading line with 'monitor', and 'Sector' + an S.No column nearby
        near = [w for x in lines[max(0, k - 2):k + 2] for w in x["w"]]
        if any(w[4] == "monitor" for w in ln["w"]) and is_header_line(ln) \
                and any(w[4] == "Sector" for w in near) and any(w[4] in ("S.", "No.", "S.No.") for w in near):
            i = k
            break
    if i is None:
        note(f"narrative sector table p{pi+1}: heading not found, not extracted")
        return
    hdr = []
    for j in range(i, -1, -1):  # heading lines above the 'monitor' line
        if j < i and (lines[j + 1]["yc"] - lines[j]["yc"] > 45 or not is_header_line(lines[j])):
            break
        hdr.append(lines[j])
    body, loose = [], []
    for ln in lines[i + 1:]:
        t0 = ln["w"][0][4]
        if body and body[-1]["w"][0][4] == "Total" and ln["yc"] - body[-1]["yc"] > 12:
            break  # the paragraph after the table ('3. The total original cost ...')
        if re.fullmatch(r"\d+\.", t0) or (t0 == "Total" and body):
            # a lone S.No is printed a few points off its row (FR_FEB_2013 '14.'): the row is a loose line
            body.append({**ln, "w": list(ln["w"])})
        elif body and ln["yc"] - body[-1]["yc"] > 30:
            break
        elif not body and is_header_line(ln) and not any(NUM_RE.match(w[4]) for w in ln["w"]):
            hdr.append(ln)  # heading lines below the 'monitor' line
        else:
            loose.append(ln)  # values / wrapped names printed a few points off the S.No row
    tot = next((b for b in body if b["w"][0][4] == "Total"), None)  # before loose words join it
    for ln in loose:
        if not body or ln["yc"] > body[-1]["yc"] + 12:
            continue
        near = min(body, key=lambda b: abs(b["yc"] - ln["yc"]))
        if abs(near["yc"] - ln["yc"]) < 14:  # keep reading order (line, then x) for the label
            near["w"] = sorted(near["w"] + ln["w"], key=lambda w: (round((w[1] + w[3]) / 2), w[0]))
    for b in body:  # the S.No token must stay first for grid_rows / the label clean-up
        b["w"].sort(key=lambda w: (not re.fullmatch(r"\d+\.", w[4]), round((w[1] + w[3]) / 2), w[0]))
    mon = next(w for w in lines[i]["w"] if w[4] == "monitor")
    lab_x = xc(mon) - 40
    cen = sorted(xc(w) for w in (tot or {}).get("w", []) if xc(w) > lab_x and NUM_RE.match(w[4]))
    heads = {}
    for w in (w for ln in hdr for w in ln["w"] if cen and xc(w) > cen[0] - 45):
        heads.setdefault(nearest(xc(w), cen), []).append(w)
    names = [narr_metric([w[4] for w in sorted(heads.get(c, []), key=lambda w: (round(w[1]), w[0]))])
             for c in range(len(cen))]
    if not cen or None in names or len(set(names)) != len(names) or names[0] != "n_projects":
        note(f"narrative sector table p{pi+1} skipped: column headings not understood {names}")
        return
    cols = list(zip(names, cen))
    rows, comp, total = [], {}, None
    for lab, vals, ln in grid_rows(body, cols, lab_x, num_values=True):
        lab = re.sub(r"^(\d+\.\s*)+", "", lab)
        if not lab or not vals:
            continue
        if lab.lower() == "total":
            lab, total = "Total", vals
        else:
            comp[lab] = vals
        for m, v in vals.items():
            rows.append(srow(ctx, pi, NARR_TITLE, "sector", lab, m, to_num(v), "count"))
    # this table repeats the sector counts; keep it only when every column adds up to its Total
    bad = [m for m, _ in cols if total is None or to_num(total.get(m)) is None or
           abs(sum(to_num(v.get(m)) or 0 for v in comp.values()) - to_num(total[m])) >= 0.5]
    if bad:
        note(f"narrative sector table p{pi+1} skipped: rows do not add up to the printed Total in {bad}")
        return
    # values of the right-hand columns are printed a few points off their row: confirm the row
    # alignment against the executive-summary sector table (same counts, parsed from another page).
    # Every n_projects must match. A few n_additional_delay values may differ as printed
    # (FR_DEC_2012: 82 here and in the list of additionally delayed projects, 85 in the executive-
    # summary table; FR_NOV_2012: 30 here and in its paragraph, 35 in both others): keep, flag.
    # Many conflicts with both references would mean misread rows: skip the table.
    ex = {(norm_sector(r["dimension_value"]), r["metric"]): r["value"] for r in out
          if r["table_title"].startswith("Executive summary - ")}
    # counts from the report's own list of additionally delayed projects; 'Mega' = anticipated
    # cost of Rs 1000 crore and above (matches 109 of the 112 printed sector values)
    listed = {"n_additional_delay": {}, "n_additional_delay_mega": {}}
    for r in addl_rows:
        for m in ("total", norm_sector(r["sector_raw"])):
            listed["n_additional_delay"][m] = listed["n_additional_delay"].get(m, 0) + 1
            if (r.get("cost_anticipated_cr") or 0) >= 1000:
                listed["n_additional_delay_mega"][m] = listed["n_additional_delay_mega"].get(m, 0) + 1
    conflict = {}  # (label, metric) -> dq flags
    for lab, vals in list(comp.items()) + [("Total", total)]:
        key = norm_sector(lab)
        e, v = ex.get((key, "n_projects")), to_num(vals.get("n_projects"))
        if e is not None and v is not None and v != e:
            note(f"narrative sector table p{pi+1} skipped: {lab} n_projects {v:.0f} != executive-summary table {e:.0f}")
            return
        for m in ("n_additional_delay", "n_additional_delay_mega"):
            v, lc = to_num(vals.get(m)), listed[m].get(key, 0)
            e = ex.get((key, m))
            fl = ([f"conflicts_with_exec_table:{e:g}"] if e is not None and v is not None and v != e else []) +                 ([f"conflicts_with_list_count:{lc:g}"] if addl_rows and v is not None and v != lc else [])
            if fl:
                conflict[(lab, m)] = fl
    if sum(1 for (k, m), f in conflict.items() if k != "Total" and m == "n_additional_delay" and len(f) > 1) > 2:
        note(f"narrative sector table p{pi+1} skipped: additional delays of {sorted(conflict)} disagree with "
             "the executive-summary table and the list (rows may be misaligned)")
        return
    for r in rows:
        if (r["dimension_value"], r["metric"]) in conflict:
            r["dq_note"] = ";".join(conflict[(r["dimension_value"], r["metric"])])
    if conflict:
        note(f"narrative sector table p{pi+1}: values as printed differ from the executive-summary table / the list "
             "of additionally delayed projects: " + ", ".join(
                 f"{k} {m} {to_num((total if k == 'Total' else comp[k])[m]):g} ({'/'.join(f)})"
                 for (k, m), f in conflict.items()))
    out += [r for r in rows if r["value"] is not None]  # '-' printed = nil, left blank


def parse_sector_analysis(lines, pi, ctx, out, issues):
    ti = next((i for i, ln in enumerate(lines) if re.search(r"Sectorwise", ln["text"], re.I)), -1)
    hi, sec = find_word(lines, "Sector", ti + 1)
    _, org = find_word(lines, "Original", ti + 1)
    _, lat = find_word(lines, "Latest", ti + 1)
    _, ant = find_word(lines, "Anticipated", ti + 1)
    _, prj = find_word(lines, "projects", ti + 1)
    if None in (sec, org, lat, ant, prj):
        issues.append(f"p{pi+1}: sectorwise analysis header not found")
        return
    cols = [("n_projects", xc(prj)), ("cost_original_cr", org[2] - 5), ("cost_latest_cr", lat[2] + 5),
            ("cost_anticipated_cr", ant[2] + 5)]
    _, exp = find_word(lines, "Expenditure")
    if exp is not None:
        cols.append(("expenditure_cr", exp[2] - 10))
    start = max(ln_i for ln_i, ln in enumerate(lines) if any(w[4] in ("Sector", "projects", "Original")
                                                               for w in ln["w"]) and ln["yc"] < 200)
    comp, total = {}, None
    for lab, vals, ln in grid_rows(lines[start + 1:], cols, prj[0] - 15, skip_sno=False, num_values=True):
        if not lab or not vals or ln["yc"] > 735:
            continue
        if re.match(r"grand\s+total", lab, re.I):
            lab, total = "Total", vals
        else:
            comp[lab] = vals
        for m, v in vals.items():
            if to_num(v) is not None:
                out.append(srow(ctx, pi, "Sectorwise analysis of projects", "sector", lab, m, to_num(v),
                                "count" if m == "n_projects" else "Rs crore"))
    if total:
        for m, _ in cols:
            s = sum(to_num(v.get(m)) or 0 for v in comp.values())
            t = to_num(total.get(m))
            if t is not None and abs(s - t) > max(1, 0.001 * t):
                issues.append(f"p{pi+1}: sectorwise analysis {m} sum {s:.2f} != total {t}")
    ctx["sa_total"] = to_num((total or {}).get("n_projects"))


# Section I 'Project Added / Completed / Dropped / Frozen' labels -> metric (first match wins).
_COST = r"(\s+Cost\s+\(Rs\.\s*1[05]0\s+Cr\.\s*&\s*above\))?"
SEC1_MAP = [
    (r"not\s+reported", "n_not_reported"),
    (r"Removed", "n_removed"),
    (r"Duplicate", "n_duplicates"),
    (r"Completed\s*(/|and)\s*Dropped.*Previous\s+Month", "n_completed_dropped_frozen_prev_month"),
    (r"Completed\s*(/|and)\s*Dropped", "n_completed_dropped_frozen"),
    (r"Dropped\s+Cost\s+\(Less|\bless\s+th[ae]n", "n_crossed_threshold_down"),
    (r"gre?a?ter\s+th[ae]n", "n_crossed_threshold_up"),
    (r"\badded\b", "n_new"),
    (rf"^No\.?\s+of\s+Projects{_COST}\s+in\s+Previous\s+Month$", "n_projects_prev_month"),
    (rf"^No\.?\s+of\s+Projects{_COST}\s+in\s+Current\s+Month$", "n_projects"),
]
# previous month - completed/dropped (reported last month and this month) - fell below the cost
# threshold + crossed above it + added - duplicates - removed - not reported = current month
SEC1_BALANCE = {"n_projects_prev_month": 1, "n_completed_dropped_frozen_prev_month": -1,
                "n_completed_dropped_frozen": -1, "n_crossed_threshold_down": -1, "n_crossed_threshold_up": 1,
                "n_new": 1, "n_duplicates": -1, "n_removed": -1, "n_not_reported": -1}


def sec1_metric(label):
    return next((m for rx, m in SEC1_MAP if re.search(rx, label, re.I)), None)


def sec1_rows(lns):
    """[(label, value)]: the value is the right-most integer (x > 300); a label that wraps
    onto the next line (no value there) is joined to the row above."""
    rows, pend = [], None
    for ln in lns:
        ws = ln["w"]
        if ws[-1][0] > 300 and re.fullmatch(r"[\d,]+", ws[-1][4]):
            pend = [clean(" ".join(w[4] for w in ws[:-1])), to_num(ws[-1][4]), ln["yc"]]
            rows.append(pend)
        elif pend is not None and ln["yc"] - pend[2] < 16:
            pend[0] = clean(pend[0] + " " + ln["text"])
    return [(lab, v) for lab, v, _ in rows]


def parse_status_page(lines, pi, ctx, out, issues):
    """'I. Project Added/Completed/Dropped/Frozen', 'II. Project status',
    'III.(A)/(B) ... cost', 'IV. Additional Delayed Project cost' blocks."""
    blocks, cur = [], None
    for ln in lines:
        m = re.match(r"^(I|II|III|IV|V|VI|VII|VIII)\.\s*(.*)$", ln["text"])
        if m:
            cur = [clean(ln["text"]), []]
            blocks.append(cur)
        elif re.match(r"^(Extent|Trend|Graphical|Sectorwise)\b", ln["text"]):
            cur = None
        elif cur is not None:
            cur[1].append(ln)
    for title, lns in blocks:
        if title.startswith("I. Project Added"):
            sec1 = {}
            for lab, v in sec1_rows(lns):
                metric = sec1_metric(lab)
                if metric is None:  # never drop a printed row
                    metric = "n_" + re.sub(r"[^a-z0-9]+", "_", lab.lower()).strip("_")
                    issues.append(f"p{pi+1}: section I label not in vocabulary, kept as {metric}: '{lab}'")
                out.append(srow(ctx, pi, "Project added / completed / dropped / frozen", "overall",
                                lab, metric, v, "count"))
                sec1[metric] = sec1.get(metric, 0) + v
            ctx["sec1_total"] = sec1.get("n_projects")
            ctx["sec1_new"] = sec1.get("n_new")
            bal = sum(sgn * sec1.get(m, 0) for m, sgn in SEC1_BALANCE.items())
            if "n_projects" in sec1 and "n_projects_prev_month" in sec1 and bal != sec1["n_projects"]:
                ctx.setdefault("src_notes", []).append(
                    f"section I: previous month +/- printed movements = {bal:.0f}, printed current month "
                    f"{sec1['n_projects']:.0f}")
        elif title.startswith("II. Project status"):
            names = [("n_delayed", "Delayed"), ("n_ahead", "Ahead"), ("n_on_schedule", "schedule"),
                     ("n_without_odc_doc_available", "available"), ("n_without_doc", "D.O.C"),
                     ("n_projects", "Total"), ("pct_delayed", "(%)")]
            cols = []
            for m, t in names:
                _, w = find_word(lns, t)
                if w is None:
                    break
                cols.append((m, xc(w)))
            if len(cols) != len(names):
                issues.append(f"p{pi+1}: project status header incomplete")
                continue
            hy = max(ln["yc"] for ln in lns if any(w[4] == "D.O.C" for w in ln["w"]))
            for lab, vals, ln in grid_rows([ln for ln in lns if ln["yc"] > hy + 2], cols, 190,
                                           skip_sno=False):
                if not lab or not vals:
                    continue
                for m, v in vals.items():
                    if to_num(v) is not None:
                        out.append(srow(ctx, pi, "Project status", "overall", lab, m,
                                        to_num(v), "pct" if m == "pct_delayed" else "count"))
                n = [to_num(vals.get(m)) for m, _ in cols[:5]]
                if None not in n and to_num(vals.get("n_projects")) is not None and \
                        abs(sum(n) - to_num(vals["n_projects"])) > 0.5:
                    ctx.setdefault("src_notes", []).append(
                        f"project status '{lab}': printed parts sum {sum(n):.0f} != printed total {vals['n_projects']}")
        elif re.match(r"^(III|IV)\.", title):
            tt = title
            hi = next((i for i, ln in enumerate(lns) if {"Sanctioned", "Anticipated"} <= {w[4] for w in ln["w"]}),
                      None)
            if hi is None:
                issues.append(f"p{pi+1}: cost table header not found: {title}")
                continue
            hw = lns[hi]["w"]
            pick = lambda t: [w for w in hw if w[4] == t or w[4].startswith(t)]  # noqa: E731
            pr, sa, an, ex, pc = pick("Projects"), pick("Sanctioned"), pick("Anticipated"), pick("Expenditure"),                 pick("%")
            cr = pick("Crore")
            if not (pr and sa and an and ex and cr) or len(pc) < 2:
                issues.append(f"p{pi+1}: cost table header incomplete: {title}")
                continue
            cols = [("n_projects", xc(pr[0])), ("cost_sanctioned_cr", xc(sa[0]) + 5),
                    ("cost_anticipated_cr", xc(an[0]) + 5), ("expenditure_cr", xc(ex[0]) + 5),
                    ("expenditure_pct", xc(pc[0])), ("cost_overrun_cr", xc(cr[0])),
                    ("cost_overrun_pct", xc(pc[1]))]
            prev = None
            for lab, vals, ln in grid_rows(lns[hi + 1:], cols, 170, skip_sno=False):
                if vals and lab:
                    prev = []
                    for m, v in vals.items():
                        if to_num(v) is not None:
                            r = srow(ctx, pi, tt, "overall", lab, m, to_num(v),
                                     "count" if m == "n_projects" else "pct" if m.endswith("pct") else "Rs crore")
                            out.append(r)
                            prev.append(r)
                elif prev and lab and re.match(r"^\(?\s*(RCE|OCE)\s*\)?$", lab):
                    for r in prev:  # label wrapped onto the next line
                        r["dimension_value"] = clean(r["dimension_value"] + " " + lab)
                    prev = None
        elif title.startswith("VII. Milestones"):
            parse_milestones(lns, pi, ctx, out)


def parse_milestones(lns, pi, ctx, out):
    for ln in lns:
        m = re.match(r"^(Total|Achieved up to month)\s+([\d,]+)$", ln["text"])
        if m:
            out.append(srow(ctx, pi, "Milestones (cumulative due & achieved)", "overall", m[1],
                            "n_milestones_total" if m[1] == "Total" else "n_milestones_achieved",
                            to_num(m[2]), "count"))


EXTENT_KIND = [  # order matters: "time & cost" before "cost"
    (r"time\s*&\s*cost\s+overrun.*latest", "time_cost_overrun_latest"),
    (r"time\s*&\s*cost\s+overrun.*original", "time_cost_overrun_original"),
    (r"cost\s+overrun.*original", "cost_overrun_original"),
    (r"cost\s+overrun.*latest", "cost_overrun_latest"),
    (r"time\s+overrun.*original", "time_overrun_original"),
    (r"time\s+overrun.*latest", "time_overrun_latest"),
]


def extent_header(lines):
    """(dimension, [basis of cost column 1, basis of cost column 5]) from the column
    header words. The row-label header says 'Sector' or 'State' (the title does not
    always say 'State Wise'); the cost columns say 'Original' or 'Latest approved'
    (the 'cost overrun w.r.t. latest schedule' table prints Latest approved cost)."""
    hdr = [w for ln in lines for w in ln["w"]]
    lab = next((w[4] for w in sorted(hdr, key=lambda w: w[0]) if w[4] in ("Sector", "State")), None)
    basis = [w[4].lower() for w in sorted(hdr, key=lambda w: w[0]) if w[4] in ("Original", "Latest")]
    return {"State": "state", "Sector": "sector"}.get(lab), basis


def parse_extent(lines, pi, ctx, out, issues):
    title = clean(lines[0]["text"])
    k = next((k for rx, k in EXTENT_KIND if re.search(rx, title, re.I)), None)
    if k is None:
        issues.append(f"p{pi+1}: unknown extent table '{title}'")
        return
    hdr_end = 0
    for i, ln in enumerate(lines):
        if any(w[4] in ("(%)", "Base", "(Months)") for w in ln["w"]):
            hdr_end = i
    dim, basis = extent_header(lines[1:hdr_end + 1])
    if dim is None or len(basis) != 2:
        issues.append(f"p{pi+1}: extent table '{title}' header not understood ({dim}, {basis})")
        return
    # one title per table across months: FR_FEB_2012+ append '(Sector Wise)' to the sector table (the
    # dimension column says so); the state table keeps '(State Wise)', added where the title lacks it
    title = re.sub(r"\s*\(\s*Sector\s*Wise\s*\)\s*$", "", title, flags=re.I)
    if dim == "state" and "state" not in title.lower():
        title += "(State Wise)"
    # sub-population prefix: projects with cost overrun / time overrun / time & cost overrun
    sub = {"cost": "overrun_projects", "time": "delayed_projects", "time_cost": "time_cost_overrun_projects"}[
        "time_cost" if k.startswith("time_cost") else k.split("_")[0]]
    nsub = {"overrun_projects": "n_cost_overrun", "delayed_projects": "n_delayed",
            "time_cost_overrun_projects": "n_time_and_cost_overrun"}[sub]
    if k == "time_overrun_latest":
        nsub = "n_delayed_wrt_latest"
    last = "range" if "time" in k else "pct"
    metrics = ["n_projects", f"cost_{basis[0]}_cr", "cost_anticipated_cr", "cost_overrun_pct", nsub,
               f"{sub}_cost_{basis[1]}_cr", f"{sub}_cost_anticipated_cr",
               f"{sub}_cost_increase_pct" if last == "pct" else "delay_range_months"]
    # data rows: lines starting with an integer S.No or 'Total'
    rows, prev_yc = [], None
    for ln in lines[hdr_end + 1:]:
        ws = ln["w"]
        if not ws or (ln["yc"] > 735 and len(ws) == 1):
            continue
        if ws[0][4].isdigit() and len(ws) > 2:
            ws = ws[1:]
        elif not ws[0][4].lower().startswith("total"):
            if rows and prev_yc and ln["yc"] - prev_yc < 12 and not any(NUM_RE.match(w[4]) for w in ws):
                rows[-1] = (clean(rows[-1][0] + " " + ln["text"]), rows[-1][1])  # wrapped label
            continue
        prev_yc = ln["yc"]
        # label: leading non-numeric words
        lab, j = [], 0
        while j < len(ws) and not NUM_RE.match(ws[j][4]):
            lab.append(ws[j][4])
            j += 1
        toks = [w for w in ws[j:]]
        rows.append((clean(" ".join(lab)), toks))
    full = [r for r in rows if len(r[1]) >= 7]
    if not full:
        issues.append(f"p{pi+1}: extent table '{title}' no rows")
        return
    # column centres from rows with a complete set of the first 7 values
    cen = []
    for c in range(7):
        xs = sorted(xc(r[1][c]) for r in full if all(NUM_RE.match(t[4]) for t in r[1][:7]))
        cen.append(xs[len(xs) // 2] if xs else None)
    if None in cen:
        issues.append(f"p{pi+1}: extent table '{title}' columns unresolved")
        return
    comp, total = {}, None
    for lab, toks in rows:
        vals = {}
        rest = []
        for t in toks:
            if xc(t) > cen[6] + 20:
                rest.append(t[4])
                continue
            c = nearest(xc(t), cen)
            vals[metrics[c]] = t[4]
        tail = "".join(rest)
        if last == "range":
            m = re.match(r"^(-?\d+)-(-?\d+)$", tail)
            if to_num(vals.get(nsub)) == 0:  # '0- 0' printed for a group with no delayed projects:
                if tail not in ("", "-", "0-0"):  # a placeholder, not a range
                    issues.append(f"p{pi+1}: range '{tail}' printed for 0 projects in '{title}', not kept")
            elif m:
                out.append(srow(ctx, pi, title, dim, "Total" if lab.lower() == "total" else lab,
                                "delay_range_min_months", float(m[1]), "months"))
                out.append(srow(ctx, pi, title, dim, "Total" if lab.lower() == "total" else lab,
                                "delay_range_max_months", float(m[2]), "months"))
            elif tail not in ("", "-", "0-0"):
                issues.append(f"p{pi+1}: odd range '{tail}' in '{title}'")
        elif tail:
            vals[metrics[7]] = tail
        is_tot = lab.lower().startswith("total")
        dv = "Total" if is_tot else lab
        if is_tot:
            total = vals
        else:
            comp[dv] = vals
        for m, v in vals.items():
            if to_num(v) is not None:
                out.append(srow(ctx, pi, title, dim, dv, m, to_num(v),
                                "count" if m.startswith("n_") else "pct" if m.endswith("pct") else "Rs crore"))
    if total:
        for m in ("n_projects", nsub):
            s = sum(to_num(v.get(m)) or 0 for v in comp.values())
            t = to_num(total.get(m))
            if t is not None and abs(s - t) > 0.5:
                issues.append(f"p{pi+1}: '{title[:50]}' {m} sum {s} != total {t}")


def parse_state_annex(lines, pi, ctx, out, issues):
    """State-wise summary annexure. Printed variants: 'CENTRAL SECTOR PROJECTS / SN
    STATE_NAME NO OF PROJECTS ...', 'Summary of Central Sector Projects in Various
    States/UTs' and 'STATE WISE SUMMARY OF ONGOING PROJECTS AS ON ...'."""
    hi = next((k for k, ln in enumerate(lines) if re.search(r"original", ln["text"], re.I)
               and any(re.search(r"anticipated", x["text"], re.I) for x in lines[k:k + 3])), None)
    if hi is None:
        issues.append(f"p{pi+1}: state annexure header not found")
        return
    hdr = [w for ln in lines[max(0, hi - 2):hi + 4] for w in ln["w"] if not NUM_RE.match(w[4])]
    pick = lambda rx: [w for w in hdr if re.fullmatch(rx, w[4], re.I)]  # noqa: E731
    org, ant, exp = (pick(r"original") or [None])[0], (pick(r"anticipated") or [None])[0], \
        (pick(r"expenditure") or [None])[0]
    npj = max((w for w in pick(r"projects") if org and w[2] < org[0]), key=lambda w: w[0], default=None)
    if None in (npj, org, ant, exp):
        issues.append(f"p{pi+1}: state annexure header incomplete")
        return
    cols = [("n_projects", xc(npj)), ("cost_original_cr", xc(org) + 5), ("cost_anticipated_cr", xc(ant) + 5),
            ("expenditure_cr", xc(exp) + 5)]
    hdr_y = max((w[1] + w[3]) / 2 for w in (npj, org, ant, exp))
    body = [ln for ln in lines if ln["yc"] > hdr_y + 3 and ln["yc"] < 735]
    rows = grid_rows(body, cols, xc(npj) - 25, num_values=True)
    comp, total = {}, None
    for lab, vals, ln in rows:
        if not vals or re.search(r"crore", lab, re.I):
            continue
        if not lab:  # label printed a few points off the value line (e.g. TOTAL)
            near = [r for r in rows if not r[1] and r[0] and abs(r[2]["yc"] - ln["yc"]) < 5]
            lab = near[0][0] if near else ""
        if not lab and len(vals) >= 3:  # a full data row printed without its state name: keep it
            s0 = ln["w"][0]
            sno = s0[4] if s0[4].isdigit() and xc(s0) < xc(npj) - 25 else "?"
            lab = f"(state not printed; S.No {sno})"
            ctx.setdefault("src_notes", []).append(f"state annexure p{pi+1}: S.No {sno} printed without a state name")
        if not lab:
            issues.append(f"p{pi+1}: state row without a state name skipped: {vals}")
            continue
        if re.fullmatch(r"TOTA\s*L?|total(\s+all\s+states)?", lab, re.I):
            lab, total = "Total", vals
        else:
            comp[lab] = vals
        for m, v in vals.items():
            if to_num(v) is not None:
                out.append(srow(ctx, pi, "State-wise summary of ongoing central sector projects", "state", lab, m,
                                to_num(v), "count" if m == "n_projects" else "Rs crore"))
    if total:
        for m, _ in cols:
            s = sum(to_num(v.get(m)) or 0 for v in comp.values())
            t = to_num(total.get(m))
            if t is not None and abs(s - t) > max(1, 0.001 * t):
                ctx.setdefault("src_notes", []).append(f"state annexure {m}: rows sum {s:.2f} != printed total {t}")


SS_MAP = [(r"Wo_?Odc", "n_without_odc"), (r"Wo_?Doc|Without\s+Date\s+Of\s+Commissioning", "n_without_doc"),
          (r"Without\s+Original\s+Date|Without\s+ODC", "n_without_odc"),
          (r"on\s+schedule", "n_on_schedule"), (r"Delayed", "n_delayed"), (r"Ahead", "n_ahead"),
          (r"^Number\s+of\s+Projects$", "n_projects")]


def parse_sector_status(lines, pi, ctx, out, issues):
    """'Sector wise current status' pages: 'Number of Projects ... N' lines."""
    sector = None
    txt = [ln["text"] for ln in lines]
    for t in txt[:8]:
        m = re.search(r"Sector\s*:\s*-\s*(.+)$", t)
        if m:
            sector = clean(m[1])
    if sector is None:
        for k, t in enumerate(txt[:6]):
            if re.search(r"Sector\s+wise\s+current\s+status", t, re.I) and k + 1 < len(txt):
                sector = clean(txt[k + 1])
    if not sector:
        return
    seen = set()
    nums = [ln for ln in lines if re.fullmatch(r"[\d,]+", ln["text"])]
    for k, ln in enumerate(lines):
        m = re.match(r"^(N?umber\s+of\s+Projects.*?)\s+([\d,]+)$", ln["text"])
        if not m and re.match(r"N?umber of Projects", ln["text"]):
            # value printed a point or two off the label's baseline
            near = [n for n in nums if abs(n["yc"] - ln["yc"]) < 5]
            nxt = lines[k + 1] if k + 1 < len(lines) else None
            if len(near) == 1:
                m = [None, ln["text"], near[0]["text"]]
            elif nxt and nxt["yc"] - ln["yc"] < 22 and not nxt["text"].startswith("Number"):
                m2 = re.match(r"^(.*?)\s+([\d,]+)$", nxt["text"])  # label wrapped onto 2 lines
                if m2:
                    m = [None, ln["text"] + " " + m2[1], m2[2]]
        if not m:
            continue
        label = clean(m[1])
        metric = next((mm for rx, mm in SS_MAP if re.search(rx, label, re.I)), None)
        if metric is None or metric in seen:
            continue
        seen.add(metric)
        out.append(srow(ctx, pi, "Sector wise current status of projects", "sector", sector, metric,
                        to_num(m[2]), "count", ))


def parse_derived_summary(lines, pi, ctx, out, issues):
    """FY2012-13 'Sectorwise Summary of Project Without Original Date of Commissioning /
    Without Date of Commissioning / On Schedule / Without Milestone' tables:
    Sector | Number of projects | Original | Revised | Anticipated cost | Total Cumm Expenditure.
    The title can sit below a list on the same page, so the table starts at its title line."""
    s0 = next((i for i, ln in enumerate(lines) if re.match(r"Sectorwise\s+Summary\b", ln["text"])), None)
    if s0 is None:
        return
    lines = lines[s0:]
    title = clean(lines[0]["text"])
    hw = [w for ln in lines[1:5] for w in ln["w"]]
    pick = lambda t: next((w for w in hw if w[4] == t), None)  # noqa: E731
    prj, org, rev, ant, exp = (pick(t) for t in ("projects", "Original", "Revised", "Anticipated", "Expenditure"))
    if None in (prj, org, rev, ant, exp):
        issues.append(f"p{pi+1}: '{title}' header not found")
        return
    cols = [("n_projects", xc(prj) + 20), ("cost_original_cr", xc(org) + 10), ("cost_revised_cr", xc(rev) + 10),
            ("cost_anticipated_cr", xc(ant) + 10), ("expenditure_cr", exp[2] - 10)]
    hy = max((w[1] + w[3]) / 2 for w in (prj, org, rev, ant, exp))
    comp, total = {}, None
    for lab, vals, ln in grid_rows([ln for ln in lines if hy + 3 < ln["yc"] < 735], cols, xc(prj) - 30,
                                   skip_sno=False, num_values=True):
        if not lab or not vals:
            continue
        if re.fullmatch(r"grand\s+total", lab, re.I):
            lab, total = "Total", vals
        else:
            comp[lab] = vals
        for m, v in vals.items():
            if to_num(v) is not None:  # '.00' revised cost = no project in the sector has a revised cost
                out.append(srow(ctx, pi, title, "sector", lab, m, to_num(v),
                                "count" if m == "n_projects" else "Rs crore"))
    for m, _ in cols:
        s = sum(to_num(v.get(m)) or 0 for v in comp.values())
        t = to_num((total or {}).get(m))
        if t is None or abs(s - t) > max(1, 0.001 * t):
            issues.append(f"p{pi+1}: '{title[:40]}' {m} rows sum {s:.2f} != total {t}")


def page_ranges(pages):
    """[26, 27, 28, 80] -> 'p26-28, p80'"""
    out, a = [], None
    for i, p in enumerate(pages):
        if a is None:
            a = p
        if i + 1 == len(pages) or pages[i + 1] != p + 1:
            out.append(f"p{a}" if a == p else f"p{a}-{p}")
            a = None
    return ", ".join(out)


# ---------------------------------------------------------------- driver
STATUS_TITLES = re.compile(r"^(I\.\s*Project\s+Added|II\.\s*Project\s+status|III\.\s*\((A|B)\)|"
                           r"IV\.\s*Additional\s+Delayed|VII\.\s*Milestones)", re.I)


def files():
    out = []
    for fy in FY_DIRS:
        out += sorted((SRC / fy).glob("*.pdf"))
    return out


def stated_total(texts):
    for t in texts[:25]:
        m = re.search(r"status\s+of\s+(?:the\s+)?([\d,]+)\s*(?:projects|Central)", t, re.I)
        if m:
            return int(m[1].replace(",", ""))
    return None


def ongoing_pages(doc, texts):
    """First contiguous run of master-list pages (header 'Date of Approval ... Cumm.
    Expenditure' plus the 1..10 column-number row, no 'List of ...' title)."""
    run = []
    for i in range(doc.page_count):
        if is_hindi(texts[i]):
            continue
        hit = ("Approval" in texts[i] and "Cumm" in texts[i] and "Expendi" in texts[i]
               and not re.search(r"List of", texts[i][:400], re.I))
        if hit and ongoing_header(page_lines(doc[i])):
            run.append(i)
        elif run:
            break
    return run


def title_period(doc, texts):
    """Month named on the cover / in the '(Mon,YYYY)' tag of the master list."""
    m = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|"
                  r"December)\s*,?\s*(\d{4})", texts[0], re.I)
    return to_ym(f"{m[1]} {m[2]}") if m else None


def norm_sector(s):
    s = (s or "").lower().replace(" and ", " & ").replace("fertilizers", "fertilisers")
    s = s.replace("telecommunication", "telecommunications").replace("telecommunicationss", "telecommunications")
    return re.sub(r"\s+", " ", s).strip()


def process(path):
    doc = fitz.open(path)
    texts = [p.get_text() for p in doc]
    ctx = {"src": rel(path), "period": period_from_name(path)}
    notes, issues = [], []
    tp = title_period(doc, texts)
    if tp != ctx["period"]:
        notes.append(f"cover month {tp} != filename month {ctx['period']}")
    pages = ongoing_pages(doc, texts)
    projects, summary, oi, snos = parse_ongoing(doc, pages, ctx) if pages else ([], [], [], [])
    issues += [i for i in oi if "orphan line '-'" not in i]
    tag = re.search(r"\((\w{3}),(\d{4})\)", texts[pages[0]]) if pages else None
    if tag and to_ym(f"{tag[1]} {tag[2]}") != ctx["period"]:
        notes.append(f"master-list tag {tag[0]} != filename month")
    ctx["agencies"] = {p["agency"] for p in projects if p.get("agency")}
    lists = parse_lists(doc, texts, pages[0] if pages else doc.page_count, ctx, issues)
    split_trailing_agency(lists, ctx["agencies"])
    exec_done = sa_done = False
    narr_pi = None
    img_pages = []
    for pi in range(doc.page_count):
        t = texts[pi]
        if pi in pages or is_hindi(t) or pi == 0:
            continue
        head = t[:300]
        lines = None
        if not exec_done and "EXECUTIVE SUMMARY" in t and re.search(r"\bMonitor\b", t) and "Delayed" in t:
            parse_exec_table(page_lines(doc[pi]), pi, ctx, summary, issues)
            exec_done = "exec_total" in ctx
        if narr_pi is None and re.search(r"Projects\s+on\s+monitor", t) and "S." in t:
            narr_pi = pi  # found by content (FY2012-13 puts 7 Hindi pages first); parsed after the loop
        if not sa_done and re.search(r"Sectorwise\s+analysis\s+of\s+projects", head, re.I):
            parse_sector_analysis(page_lines(doc[pi]), pi, ctx, summary, issues)
            sa_done = True
        if any(STATUS_TITLES.match(ln.strip()) for ln in t.split("\n")):
            lines = page_lines(doc[pi])
            parse_status_page(lines, pi, ctx, summary, issues)
        if re.search(r"^\s*Extent\s+of", t, re.M):
            lines = page_lines(doc[pi])
            starts = [i for i, ln in enumerate(lines)
                      if ln["text"].startswith("Extent of") and "projects" in ln["text"]]
            for a, b in zip(starts, starts[1:] + [len(lines)]):
                parse_extent(lines[a:b], pi, ctx, summary, issues)
        if (re.search(r"(?i:STATE\s*WISE\s*SUMMARY|STATE[\s_]+NAME)|Various\s+States|\bSTATE\s*\n", t)
                and re.search(r"anticipated", t, re.I) and "Andhra" in t
                and not re.search(r"PROJ_TITLE|\bSN\s*\n\s*PROJECT", t)):
            parse_state_annex(page_lines(doc[pi]), pi, ctx, summary, issues)
        if re.search(r"Sector\s*:\s*-|Sector\s+wise\s+current\s+status", t, re.I):
            parse_sector_status(page_lines(doc[pi]), pi, ctx, summary, issues)
        if re.search(r"^\s*Sectorwise\s+Summary\b", t, re.M):
            parse_derived_summary(page_lines(doc[pi]), pi, ctx, summary, issues)
        if len(t.strip()) < 20 and doc[pi].get_images():
            img_pages.append(pi + 1)

    if narr_pi is None:
        notes.append("narrative sector table ('Projects on monitor') not found")
    else:  # parsed once the executive-summary table and the additional-delay list are known
        addl = [r for r in lists if r["list_type"] == "other:additionally_delayed"]
        parse_narrative_sector_table(page_lines(doc[narr_pi]), narr_pi, ctx, summary, issues, addl)

    # ---- validation against totals printed in the report itself
    st_narr = stated_total(texts)
    st = ctx.get("exec_total") or ctx.get("sec1_total") or st_narr
    st = int(st) if st else None
    n = len(projects)
    if st_narr and st and st_narr != st:
        notes.append(f"narrative says {st_narr} projects; sector table/total says {st}")
    if st and abs(n - st) > 0:
        notes.append(f"ongoing rows {n} vs stated {st}")
    if snos:
        miss = sorted(set(range(1, max(snos) + 1)) - set(snos))
        dups = sorted({s for s in snos if snos.count(s) > 1})
        if miss or dups:
            notes.append(f"S.No gaps {miss[:5]} duplicates {dups[:5]} as printed")
    # sector counts vs executive summary table
    exec_counts = {norm_sector(r["dimension_value"]): r["value"] for r in summary
                   if r["table_title"].startswith("Executive summary - ") and r["metric"] == "n_projects"}
    got = {}
    for p in projects:
        got[norm_sector(p["sector_raw"])] = got.get(norm_sector(p["sector_raw"]), 0) + 1
    bad = [f"{k}: list {got.get(k, 0)} vs table {int(v)}" for k, v in exec_counts.items()
           if k != "total" and got.get(k, 0) != v]
    if bad:
        notes.append("sector count mismatch " + "; ".join(bad[:4]))
    # sector cost / expenditure totals vs the 'Total' rows printed in the master list
    for sec, tots in (ctx.get("sector_totals") or {}).items():
        for col, f in ((4, "cost_original_cr"), (5, "cost_anticipated_cr"), (6, "expenditure_cum_cr")):
            tot = tots.get(col)
            if tot is None:
                continue
            s = sum(p[f] or 0 for p in projects if sec == "Total" or p["sector_raw"] == sec)
            if abs(s - tot) > max(1.0, 0.0005 * tot):
                issues.append(f"sector '{sec}' {f} sum {s:.2f} != printed total {tot}")
    for p in projects + lists:  # a printed 0.00 cost is a placeholder, not a cost
        for f in ("cost_original_cr", "cost_revised_cr", "cost_anticipated_cr"):
            if p.get(f) == 0:
                p[f] = None
                p["remarks"] = "; ".join(x for x in (p.get("remarks"), f"{f} printed as 0.00") if x)
                add_dq(p, f"placeholder_zero:{f}")
    n_new = sum(1 for r in lists if r["list_type"] == "newly_added")
    if ctx.get("sec1_new") is not None and n_new != ctx["sec1_new"]:
        notes.append(f"newly_added rows {n_new} vs stated {int(ctx['sec1_new'])}")
    n_ad = sum(1 for r in lists if r["list_type"] == "other:additionally_delayed")
    if ctx.get("exec_addl") is not None and n_ad != ctx["exec_addl"]:
        notes.append(f"additionally_delayed rows {n_ad} vs stated {int(ctx['exec_addl'])}")
    status = "ok" if pages and st and abs(n - st) <= max(2, 0.02 * st) else "partial"
    if not pages:
        status = "failed"
        notes.append("master list not found")
    if img_pages:
        notes.append("image-only pages, no text layer, not extracted (trend charts / scanned tables): "
                     + page_ranges(img_pages))
    n_state = sum(1 for r in summary if r["table_title"].startswith("State-wise summary"))
    if ctx["period"] >= "2010-07" and not n_state:  # Apr-Jun 2010 reports print no state table
        notes.append("state-wise annexure not extracted: not found in the text layer"
                     + (" (the annexure appears to be one of the image-only pages)" if img_pages else ""))
    notes += ctx.get("src_notes", [])
    if issues:
        notes.append(f"{len(issues)} parse warnings: " + " | ".join(issues[:3]))
    man = {
        "source_file": ctx["src"], "report_type": REPORT_TYPE, "report_period": ctx["period"],
        "pages": doc.page_count,
        "parser_variant": "fy2010-11" if ctx["period"] < "2011-04" else
        ("fy2011-12" if ctx["period"] < "2012-04" else "fy2012-13"),
        "stated_total_projects": int(st) if st else None, "rows_ongoing": n,
        "rows_completed": sum(1 for r in lists if r["list_type"] == "completed"),
        "rows_other": sum(1 for r in lists if r["list_type"] != "completed"),
        "rows_summary": len(summary), "rows_perf": None, "rows_perf_detail": None,
        "status": status, "notes": "; ".join(notes) or None,
    }
    return projects + lists, summary, man, issues


def main(only=None):
    allp, alls, mans = [], [], []
    for f in files():
        if only and not any(o.lower() in f.name.lower() for o in only):
            continue
        try:
            p, s, man, issues = process(f)
        except Exception as e:  # keep going; record the failure
            man = {"source_file": rel(f), "report_type": REPORT_TYPE, "report_period": period_from_name(f),
                   "status": "failed", "notes": f"{type(e).__name__}: {e}"}
            p, s, issues = [], [], []
        allp += p
        alls += s
        mans.append(man)
        print(f"{f.name:24s} {man.get('report_period')} {man.get('status'):8s} ongoing={man.get('rows_ongoing')} "
              f"stated={man.get('stated_total_projects')} other={man.get('rows_other')} "
              f"completed={man.get('rows_completed')} summary={man.get('rows_summary')} warn={len(issues)}")
        if man.get("notes"):
            print("    ", man["notes"][:400])
    for r in allp:
        r.pop("_sno", None)
    if not only:
        write_part(allp, FAMILY, "projects", PROJECT_COLS)
        write_part(alls, FAMILY, "summary", SUMMARY_COLS)
        write_part(mans, FAMILY, "manifest", MANIFEST_COLS)
    return allp, alls, mans


def self_check():
    assert split_code("KAIGA 3 and 4 UNITS (NPCIL) - [020100041]") == ("KAIGA 3 and 4 UNITS (NPCIL)", "020100041", "")
    assert split_code("GAGAN PROJECT - [N04000065]AAI,Multi State") == ("GAGAN PROJECT", "N04000065",
                                                                       "AAI,Multi State")
    assert split_agency_paren("SIPAT STPP STAGE - I (NTPC)(NATIONAL THERMAL POWER CORPORATION)") == (
        "SIPAT STPP STAGE - I (NTPC)", "NATIONAL THERMAL POWER CORPORATION")
    assert split_agency_paren("REBUILDING OF COKE OVEN(STEEL AUTHORITY OF INDIA LIMITED (SAIL))") == (
        "REBUILDING OF COKE OVEN", "STEEL AUTHORITY OF INDIA LIMITED (SAIL)")
    assert split_agency_paren("KRISHNASHILA (NCL) (4MTY)") == ("KRISHNASHILA (NCL) (4MTY)", None)
    # a synthetic master-list record: delay basis and milestone handling
    ctx = {"src": "x.pdf", "period": "2010-04"}
    rec = {"sno": 1, "sector": "Coal", "page": 5, "name": ["KUSMUNDA", "EXPN.OCP - [N06000008]SECL,Chhatisgarh"],
           "cells": {3: ["06/2006"], 4: ["737.65", "-"], 5: ["1,188.31"], 6: ["583.32"], 7: ["03/2011", "03/2013"],
                     8: ["03/2013"], 9: ["0(R3)"], 10: ["0/4"]}}
    iss = []
    r = finish_ongoing(rec, ctx, iss)
    assert r["project_code"] == "N06000008" and r["agency"] == "SECL" and r["state"] == "Chhatisgarh"
    assert r["cost_original_cr"] == 737.65 and r["cost_revised_cr"] is None and r["cost_anticipated_cr"] == 1188.31
    assert r["doc_original"] == "2011-03" and r["doc_revised"] == "2013-03" and r["delay_months"] is None
    assert "R3" in r["remarks"] and "0/4" in r["remarks"] and not iss
    # section I labels -> metrics (adjustment rows must never become n_projects)
    for lab, m in [("No of Projects in Current Month", "n_projects"),
                   ("No of Projects Cost (Rs. 150 Cr. & above) in Current Month", "n_projects"),
                   ("No of Projects Cost (Rs. 100 Cr. & above) in Previous Month", "n_projects_prev_month"),
                   ("No of Projects with Anticipated Cost Greater than Rs.150 Cr. In Current Month",
                    "n_crossed_threshold_up"),
                   ("No. of projects with Anticipated grater then Rs. 150 Cr in Current Mont", "n_crossed_threshold_up"),
                   ("No of Projects Dropped Cost (Less then 150 Cr.) in Current Month", "n_crossed_threshold_down"),
                   ("No of Projects Completed and Dropped in Current Month", "n_completed_dropped_frozen"),
                   ("No of Projects Completed/Dropped/Frozen in Previous Month", "n_completed_dropped_frozen_prev_month"),
                   ("Number of Projects Dropped (duplicate) in Current month", "n_duplicates"),
                   ("No. of Projects Removed from the System", "n_removed"),
                   ("No of Projects Cost (Rs. 150 Cr. & above) added in Current Month", "n_new")]:
        assert sec1_metric(lab) == m, (lab, sec1_metric(lab))
    W = lambda t, x, y: (x, y - 4, x + 6 * len(t), y + 4, t)  # noqa: E731
    lns = [{"yc": y, "w": [W(t, x, y) for t, x in ws], "text": " ".join(t for t, _ in ws)} for y, ws in [
        (140, [("No.", 90), ("of", 103), ("projects", 112), ("with", 140), ("Anticipated", 155), ("grater", 193),
               ("then", 215), ("Rs.", 231), ("150", 244), ("Cr", 259), ("in", 270), ("3", 341)]),
        (150, [("Current", 90), ("Mont", 117)]),
        (158, [("No.", 90), ("of", 105), ("Cr", 301), ("in", 314), ("Current", 323), ("Months", 353), ("1", 485)])]]
    assert sec1_rows(lns) == [("No. of projects with Anticipated grater then Rs. 150 Cr in Current Mont", 3.0),
                              ("No. of Cr in Current Months", 1.0)]
    # extent header: row label and cost basis come from the header words
    hl = [{"w": [W("S.No.", 36, 115), W("State", 114, 115), W("No.", 188, 115)]},
          {"w": [W("Latest", 253, 161), W("Anticipated", 298, 161), W("Latest", 438, 161)]}]
    assert extent_header(hl) == ("state", ["latest", "latest"])
    rows = [{"list_type": "other:additionally_delayed", "project_name": "TPS-II EXPANSION (NLC) NLC", "agency": None},
            {"list_type": "other:additionally_delayed", "project_name": "MUMBAI BERTH MUMBAI PORT TRU", "agency": None}]
    split_trailing_agency(rows, {"NLC", "MUMBAI PORT TRU"})
    assert [(r["project_name"], r["agency"]) for r in rows] == [("TPS-II EXPANSION (NLC)", "NLC"),
                                                               ("MUMBAI BERTH", "MUMBAI PORT TRU")]
    assert page_ranges([26, 27, 28, 80]) == "p26-28, p80"
    assert join_wrapped(["LOWER SUBANSIRI (NHPC)(NATIONAL HYDRO-", "ELECTRIC POWER CORPORATION)"]) == (
        "LOWER SUBANSIRI (NHPC)(NATIONAL HYDRO-ELECTRIC POWER CORPORATION)", True)
    assert join_wrapped(["GEVRA EXPANSION OCP (SECL) (25-", "35) MTY"]) == ("GEVRA EXPANSION OCP (SECL) (25-35) MTY", True)
    assert join_wrapped(["SIPAT STPP STAGE -", "I (NTPC)", "- [N18000001]"]) == ("SIPAT STPP STAGE - I (NTPC) - [N18000001]",
                                                                              False)
    assert join_wrapped(["650K LINES (PH-", "(BHARAT SANCHAR NIGAM LIMITED)"])[1] is False
    assert join_wrapped(["KARANPUR MORADABAD-", "KASHIPUR-RUDRAPUR", "PIPELINE PROJECT PHASE-", "GAIL"], {"GAIL"}) == (
        "KARANPUR MORADABAD-KASHIPUR-RUDRAPUR PIPELINE PROJECT PHASE- GAIL", True)
    for words, m in [("Projects on monitor", "n_projects"), ("Reported Online", "n_reported_online"),
                     ("Additional delays", "n_additional_delay"), ("Delayed Projects", "n_delayed"),
                     ("Delayed Projects w.r.t latest Scheduled", "n_delayed_wrt_latest"),
                     ("Additionally delayed during the month under report", "n_additional_delay"),
                     ("Additionally delayed (Mega Projects)", "n_additional_delay_mega")]:
        assert narr_metric(words.split()) == m, (words, narr_metric(words.split()))
    print("self-check ok")


if __name__ == "__main__":
    self_check()
    main(sys.argv[1:] or None)
