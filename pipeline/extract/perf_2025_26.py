"""
perf_2025_26 - "Review of Infrastructure Sector Performance" monthly reports,
FY 2025-26 layout (Performance Monitoring/2025-26/*.pdf, 7 reports Jun 2025 - Jan 2026).

Outputs (dataset/clean/_parts/perf_2025_26/):
  perf.csv         Annexure-A: every row x {month, cumulative}      (PERF_COLS)
  perf_detail.csv  Highlights table + sector detail tables, long   (PERF_DETAIL_COLS)
  manifest.csv     one row per PDF                                  (MANIFEST_COLS)

Run from repo root:  python pipeline/extract/perf_2025_26.py

Method
- Annexure-A and Highlights are fully ruled Excel tables: PyMuPDF find_tables()
  gives reliable row bands / cell boxes; cell text is re-read from word boxes
  (find_tables clips words that overflow a cell, e.g. "(B" | "U 133.117").
  Column meaning of Annexure-A is keyed on the printed "(1)".."(11)" header row.
  A value in a vertically merged cell (one number spanning several sub-rows, e.g.
  a combined State PWD target printed across three road rows) is not given to any
  one row: it goes to perf_detail as 'Combined value (one merged cell) of: a + b + c'.
- Detail tables only have ruled headers; bodies are unruled and often run onto
  the next page.  Header cells from find_tables give column x-ranges + labels;
  body rows are rebuilt from word lines (values are right aligned, wrapped
  labels are bottom aligned so label-only lines are prefixes of the next row).
  Column alignment is checked against the table's own "% Variation" columns
  (a table where every check fails is skipped); lone numbers in ruled cells
  spanning several rows (merged cells) become 'Combined value' rows; tables whose
  every value is 0 are source placeholders and skipped; labels clipped by narrow
  cells are completed from other months. Per table, printed body numbers are
  reconciled against emitted values. Everything dropped/skipped is logged in the
  manifest notes. Telecom detail tables are skipped (period labels in the source
  are inconsistent; the same figures are in Annexure-A).
- '% Variation Over Actual <last year's period>' values carry the current period
  (the period whose growth they describe), like the Highlights '% change' columns.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, PERF_COLS, PERF_DETAIL_COLS,  # noqa: E402
                    fiscal_year, rel, to_num, to_ym, write_part)

FAMILY = "perf_2025_26"
SRC = DATASET / "Performance Monitoring" / "2025-26"
VARIANT = "perf_2025_26_v1"

SECTORS = {1: "Power", 2: "Coal", 3: "Steel", 4: "Cement", 5: "Fertilizers",
           6: "Petroleum & Natural Gas", 7: "Roads", 8: "Railways",
           9: "Shipping & Ports", 10: "Civil Aviation", 11: "Telecommunications"}
SECTOR_KEYS = [("power", "Power"), ("coal", "Coal"), ("steel", "Steel"), ("cement", "Cement"),
               ("fertili", "Fertilizers"), ("petroleum", "Petroleum & Natural Gas"),
               ("road", "Roads"), ("railway", "Railways"), ("shipping", "Shipping & Ports"),
               ("aviation", "Civil Aviation"), ("telecom", "Telecommunications")]
# detail-table title keywords -> sector (order matters: "coal handled at major ports" is ports)
TITLE_SECTOR = [("airport", "Civil Aviation"), ("port", "Shipping & Ports"),
                ("telecom", "Telecommunications"), ("freight", "Railways"),
                ("nhai", "Roads"), ("pwd", "Roads"), ("crude", "Petroleum & Natural Gas"),
                ("refinery", "Petroleum & Natural Gas"), ("natural gas", "Petroleum & Natural Gas"),
                ("fertili", "Fertilizers"), ("urea", "Fertilizers"), ("cement", "Cement"),
                ("coal", "Coal"), ("steel", "Steel"), ("power", "Power"), ("thermal", "Power"),
                ("nuclear", "Power"), ("hydro", "Power"), ("renewable", "Power")]

VAL_RE = re.compile(r"^(?:[-+]?\(?\d[\d,]*(?:\.\d+)?\)?%?|[-+]?\.\d+|\*+|\$|#|[-–—]+|NA|N\.A\.?|N\.R\.?|Nil|#DIV/0!|#N/A|#VALUE!|#REF!)$", re.I)
MARK_UPPER = re.compile(r"^(?:([IVX]+)\.\s+|\(([a-h])\)\s*)")  # I.  II.  (a)  (b)  (not 'V.O.Chidambaranar')
MARK_LOWER = re.compile(r"^(?:\(?([ivx]+)\)|([a-h])\))\s*")     # i)  (ii)  a)
MARK_LETTER = re.compile(r"^[A-H]\.\s")                          # A. NITROGEN
MONTH_RE = (r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
            r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b")
UNIT_MAP = {"bu": "BU", "mt": "MT", "mmt": "MMT", "mcm": "MCM", "kms.": "Kms", "kms": "Kms", "km": "Kms",
            "'th tonnes": "'000 Tonnes", "th tonnes": "'000 Tonnes", "tonnes": "Tonnes",
            "in million": "Million", "in kms": "Kms", "in numbers": "Numbers", "nos.": "Numbers",
            "in metric tonnes": "Tonnes", "in 'th": "'000 Numbers", "in lines": "Lines",
            "lakh": "Lakh", "'000 no.": "'000 Numbers", "rs. in crore": "Rs crore",
            "rs. in crores": "Rs crore",
            # detail table unit lines "(In ...)"
            "in billion units": "BU", "in million units": "MU", "in million tonnes": "MT",
            "in thousand tonnes": "'000 Tonnes", "in lakh tonnes": "Lakh Tonnes",
            "in million cubic metres": "MCM", "percentage": "%", "in percentage": "%"}
SECTOR_DEFAULT_UNIT = {"Roads": "Kms"}


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def add_dq(r, flag):
    """Append a data-quality flag to r['dq_note'] (';'-joined, no duplicates)."""
    cur = r.get("dq_note") or ""
    if flag not in cur.split(";"):
        r["dq_note"] = f"{cur};{flag}" if cur else flag


def is_val(t):
    return bool(VAL_RE.match(t))


def unit_of(label):
    """Unit from the parentheticals of a row label, or None."""
    for p in re.findall(r"\(([^()]*)\)", label or ""):
        u = UNIT_MAP.get(norm(p).lower().rstrip(":"))
        if u:
            return u
    return None


def xc(w):
    return (w[0] + w[2]) / 2


def yc(w):
    return (w[1] + w[3]) / 2


def make_lines(words, tol=2.5):
    """Cluster word boxes into text lines by vertical centre."""
    lines = []
    for w in sorted(words, key=lambda w: (yc(w), w[0])):
        if lines and abs(yc(w) - lines[-1]["yc"]) <= tol:
            L = lines[-1]
            L["words"].append(w)
            L["yc"] += (yc(w) - L["yc"]) / len(L["words"])
        else:
            lines.append({"yc": yc(w), "words": [w]})
    for L in lines:
        L["words"].sort(key=lambda w: w[0])
        L["y0"] = min(w[1] for w in L["words"])
        L["y1"] = max(w[3] for w in L["words"])
        L["x0"] = L["words"][0][0]
        L["text"] = " ".join(w[4] for w in L["words"])
    return lines


def text_in(box, words):
    """Text of the words whose centre lies in box, in reading order."""
    ws = [w for w in words if box[0] - 0.5 <= xc(w) <= box[2] + 0.5 and box[1] - 0.5 <= yc(w) <= box[3] + 0.5]
    return norm(" ".join(L["text"] for L in make_lines(ws)))


def join_label(a, b):
    """Join a wrapped label. A 1-3 letter lowercase tail is a broken word ('Internationa'+'l',
    'Domest'+'ic)'); a tail starting with ',' or ')' continues without a space."""
    if not a:
        return b
    if not b:
        return a
    if (re.fullmatch(r"[a-z]{1,3}\W*", b.split()[0]) and a[-1].isalpha()) or b[0] in ",)":
        return a + b
    return a + " " + b


# ---------------------------------------------------------------- periods

def add_months(ym, k):
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + k
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def months_between(a, b):
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def parse_period(label):
    """Column label -> (period_start, period_end) or (None, None).
    'Annual Target 2025- 2026' -> FY; 'April- July 2024 Actual' -> 2024-04..2024-07;
    'April,2025-January 2026' -> 2025-04..2026-01; 'Jul-25 Target' -> 2025-07..2025-07."""
    t = norm(label).lower().replace("–", "-").replace("—", "-")
    m = re.search(r"annual.*?\b(20\d\d)\s*-\s*(20\d\d|\d\d)\b", t)
    if m:
        y = int(m[1])
        return f"{y}-04", f"{y + 1}-03"
    m = re.search(MONTH_RE + r"[\s,']*(\d{4})?\s*-\s*" + MONTH_RE + r"[\s,'-]*(\d{4}|\d{2})\b", t)
    if m:
        end = to_ym(f"{m[3]} {m[4]}")
        if not end:
            return None, None
        if m[2]:
            start = to_ym(f"{m[1]} {m[2]}")
        else:
            sm = to_ym(f"{m[1]} 2000")
            smo, emo, ey = int(sm[5:]), int(end[5:]), int(end[:4])
            start = f"{ey if smo <= emo else ey - 1:04d}-{smo:02d}"
        return start, end
    m = re.search(MONTH_RE + r"[\s,'-]*(\d{4}|\d{2})\b", t)
    if m:
        ym = to_ym(f"{m[1]} {m[2]}")
        return ym, ym
    return None, None


def period_text(ps, pe):
    """Canonical period text of this family's labels: 'December 2025',
    'April-December 2025', 'April,2025-January 2026'."""
    mn = lambda ym: MONTH_NAMES[int(ym[5:]) - 1]   # noqa: E731
    if ps == pe:
        return f"{mn(pe)} {pe[:4]}"
    if ps[:4] == pe[:4]:
        return f"{mn(ps)}-{mn(pe)} {pe[:4]}"
    return f"{mn(ps)},{ps[:4]}-{mn(pe)} {pe[:4]}"


def norm_col_label(clab, ps, pe):
    """One template per measure: 'Jul-25 Target' -> 'July 2025 Target'; 'April,2025-June 2025'
    -> 'April-June 2025'; '% Variation Over December 2025 Target' -> '% Variation Over Target
    December 2025'; a bare '% Variation Over Target' gets its period (ps..pe = target period)."""
    t = re.sub(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(\d{2})\b",
               lambda m: f"{MONTH_NAMES[int(to_ym(m[1] + ' 2000')[5:]) - 1]} 20{m[2]}", clab)
    t = re.sub(r"\b([A-Z][a-z]+),(\d{4})-([A-Z][a-z]+) \2\b", r"\1-\3 \2", t)
    t = re.sub(r"^% Variation Over (.+?) (Target|Actual)$", r"% Variation Over \2 \1", t)
    if re.fullmatch(r"% Variation Over Target", t) and ps:
        t += " " + period_text(ps, pe)
    elif re.fullmatch(r"% Variation Over Actual", t) and ps:
        t += " " + period_text(add_months(ps, -12), add_months(pe, -12))
    return t


def col_role(label):
    """Measure of a detail-table column: target | annual | ach | actual | var | other."""
    low = label.lower()
    if "%" in low or "variation" in low or "utilisation" in low:
        return "var"
    if "target" in low:
        return "annual" if "annual" in low else "target"
    if "achievement" in low or ("traffic" in low and "during" not in low):
        return "ach"
    if re.search(r"\bactual$", low) or "traffic during" in low:
        return "actual"
    return "other"


def plausible_period(ps, pe, rm):
    """Detail-table periods must be recent (<= report month, >= 15 months back)
    and a cumulative range must start in April and span <= 12 months."""
    if not ps or not pe:
        return False
    if months_between(pe, rm) < 0 or months_between(pe, rm) > 15:
        # annual FY columns end in March after the report month
        return ps.endswith("-04") and months_between(ps, pe) == 11 and \
            fiscal_year(ps) in (fiscal_year(rm), fiscal_year(add_months(rm, -12)))
    if ps != pe:
        return ps.endswith("-04") and 0 < months_between(ps, pe) <= 11
    return True


# ---------------------------------------------------------------- report month

def report_month_from_name(name):
    stem = re.sub(r"(?i)^(complete)?\s*review\s*report\s*", "", Path(name).stem)
    return to_ym(stem.strip())


def title_months(doc):
    """Months named in the report's own titles (highlights heading, annexure title)."""
    found = {}
    for i in range(min(6, doc.page_count)):
        t = norm(doc[i].get_text())
        m = re.search(r"for the Month of\s+([A-Za-z]+)\s*-\s*(\d{4})", t)
        if m and "highlights" not in found:
            found["highlights"] = to_ym(f"{m[1]} {m[2]}")
        m = re.search(r"Monthly Performance of Key Infrastructure Sectors during\s+([A-Za-z]+)\s+(\d{4})", t)
        if m and "monthly_section" not in found:
            found["monthly_section"] = to_ym(f"{m[1]} {m[2]}")
    return found


# ---------------------------------------------------------------- Annexure-A

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
ANNEX_MERGED_TITLE = ("Annexure-A: Performance of Key Infrastructure Sectors - target printed in one "
                      "merged cell across several sub-rows")
COMBINED = "Combined value (one merged cell) of: "
ANNEX_EXPECT = {2: "target", 3: "production", 4: "achiev", 5: "production", 6: "growth",
                7: "target", 8: "production", 9: "achiev", 10: "production", 11: "growth"}


def find_annexure_page(doc):
    for i in range(doc.page_count):
        t = doc[i].get_text()
        if re.search(r"Annexure\s*-?\s*A\b", t) and "(11)" in t and "Target" in t:
            return i
    return None


def sector_from_heading(txt):
    low = txt.lower()
    for k, s in SECTOR_KEYS:
        if k in low:
            return s
    return None


def parse_annexure(page, ctx, notes):
    words = page.get_text("words")
    tb = max(page.find_tables().tables, key=lambda t: t.row_count)
    ext = tb.extract()
    hdr = next(i for i, r in enumerate(ext)
               if sum(1 for c in r if c and re.fullmatch(r"\(\d+\)", c.strip())) >= 5)
    col = {}
    for j, c in enumerate(ext[hdr]):
        m = c and re.match(r"\((\d+)\)", c.strip())
        if m:
            col[int(m[1])] = j
    assert set(range(1, 12)) <= set(col), f"annexure header columns {sorted(col)}"
    xr = {n: (tb.rows[hdr].cells[j][0], tb.rows[hdr].cells[j][2]) for n, j in col.items()}
    # semantic check of the printed header words above "(n)"
    fy = fiscal_year(ctx["rm"])
    cur_fy = f"FY {fy[2:4]}-{fy[5:7]}"
    prev_fy = f"FY {int(fy[2:4]) - 1:02d}-{int(fy[2:4]):02d}"
    for n, key in ANNEX_EXPECT.items():
        h = norm(ext[hdr - 1][col[n]] or "")
        assert key in h.lower().replace(" ", ""), f"annexure col ({n}) header {h!r}"
    h5, h2 = norm(ext[hdr - 1][col[5]]), norm(ext[hdr - 1][col[2]])
    if prev_fy not in h5 or cur_fy not in h2:
        notes.append(f"annexure header FY check failed: ({2})={h2!r} ({5})={h5!r}")
    tm =re.search(r"Performance during\s+([A-Za-z]+)\s+(\d{4})", norm(" ".join(c or "" for c in ext[0])))
    if tm and to_ym(f"{tm[1]} {tm[2]}") != ctx["rm"]:
        notes.append(f"annexure table sub-title says '{tm[1]} {tm[2]}' (typo; report month {ctx['rm']} from file name/page title)")
    carried = carried_forward(page.get_text(), ctx["rm"])

    val_x0 = xr[2][0]
    raw = []   # parsed rows before classification
    for i in range(hdr + 1, len(tb.rows)):
        cells = tb.rows[i].cells
        lc = cells[col[1]]
        if lc is None:
            continue
        y0, y1 = lc[1], lc[3]
        band = [w for w in words if y0 <= yc(w) <= y1 and tb.bbox[0] - 2 <= xc(w) <= tb.bbox[2] + 2]
        full = lc[2] > val_x0 + 5
        label_w, vals, merged_vals = [], {}, []
        for w in sorted(band, key=lambda w: (round(yc(w)), w[0])):
            if full or xc(w) < val_x0 or not is_val(w[4]):
                label_w.append(w)
        label = norm(" ".join(L["text"] for L in make_lines(label_w)))
        if not full:
            for n in range(2, 12):
                toks = [w for w in band if is_val(w[4]) and xc(w) >= val_x0
                        and xr[n][0] - 1 <= xc(w) <= xr[n][1] + 1]
                if not toks:
                    continue
                c = cells[col[n]]
                merged = c is None or (c[3] - c[1]) > (y1 - y0) + 3
                txt = [w[4] for w in toks]
                nums = [t for t in txt if to_num(t) is not None]
                if merged:
                    box = c if c is not None else min(
                        (b for b in tb.cells if b and b[0] - 0.5 <= xc(toks[0]) <= b[2] + 0.5
                         and b[1] - 0.5 <= yc(toks[0]) <= b[3] + 0.5),
                        key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), default=None)
                    if len(nums) == 1 and box:
                        merged_vals.append((n, nums[0], box))
                        notes.append(f"p{page.number + 1} '{label[:40]}' col({n}) value {nums[0]} is one merged "
                                     f"cell spanning several rows - kept in perf_detail as a combined target")
                    elif nums:
                        notes.append(f"p{page.number + 1} '{label[:40]}' col({n}) value {nums} spans merged rows - dropped")
                    continue
                if len(nums) > 1:
                    notes.append(f"p{page.number + 1} '{label[:40]}' col({n}) several values {txt} - dropped")
                    continue
                vals[n] = nums[0] if nums else txt[0]
        elif any(xc(w) > val_x0 and to_num(w[4]) is not None for w in band):
            notes.append(f"p{page.number + 1} full-width row '{label[:40]}' holds numbers - ignored")
        raw.append({"label": label, "full": full, "vals": vals, "merged": merged_vals, "y": (y0 + y1) / 2})

    rows, extra = [], []
    sector = sector_head = None
    cur_group = cur_unit = None
    group_from_upper = False
    sector_last_unit = None
    for k, r in enumerate(raw):
        lab = r["label"]
        if r["full"]:
            m = re.match(r"^(\d{1,2})\.\s*(.+)$", lab)
            if m and sector_from_heading(m[2]):
                sector = sector_from_heading(m[2])
                sector_head = norm(m[2].rstrip("*"))
                cur_group = cur_unit = sector_last_unit = None
                group_from_upper = False
            elif sector and lab and not re.match(r"^[*#$]|.*\w\s*:\s", lab):
                # merged full-width sub-heading, e.g. Sep-25 'I. Passenger Traffic Handled at (In Numbers)'
                up = MARK_UPPER.match(lab)
                cur_group = lab[up.end():] if up else lab
                cur_unit, group_from_upper = unit_of(cur_group), True
            continue
        if sector is None or not lab:
            continue
        has_any = bool(r["vals"])
        up, lo = MARK_UPPER.match(lab), MARK_LOWER.match(lab)
        bare = lab[(up or lo).end():] if (up or lo) else lab
        if not has_any:                       # heading row, e.g. "I. Passenger Traffic Handled at (In Numbers)"
            cur_group, cur_unit, group_from_upper = bare, unit_of(bare), True
            continue
        nxt = next((x for x in raw[k + 1:] if not x["full"]), None)
        is_total = bool(re.match(r"(?i)^(total|all india|grand total)\b", bare))
        if up:
            cur_group, cur_unit, group_from_upper = bare, unit_of(bare), True
            group, unit = bare, unit_of(bare)
        elif lo:
            group = cur_group or sector_head
            unit = unit_of(bare) or cur_unit
        elif is_total:
            group, unit = sector_head, unit_of(bare) or sector_last_unit
            cur_group, cur_unit, group_from_upper = None, None, False
        elif nxt and MARK_LOWER.match(nxt["label"]) and nxt["vals"]:
            cur_group, cur_unit, group_from_upper = bare, unit_of(bare), False
            group, unit = bare, unit_of(bare)
        elif cur_group and group_from_upper:
            group, unit = cur_group, unit_of(bare) or cur_unit
        else:
            group, unit = sector_head, unit_of(bare)
        unit = unit or SECTOR_DEFAULT_UNIT.get(sector)
        if unit and (up or (not lo and not is_total)):
            sector_last_unit = unit
        v ={n: to_num(r["vals"].get(n)) for n in range(2, 12)}
        base = dict(report_month=ctx["rm"], fiscal_year=fiscal_year(ctx["rm"]), source_file=ctx["src"],
                    page=page.number + 1, sector=sector, indicator_group=group, indicator=bare,
                    unit=unit, is_total=is_total)
        for n, val, box in r["merged"]:
            # e.g. the State PWD/BRO target printed once across its three road sub-rows
            span = [x["label"] for x in raw if not x["full"] and box[1] <= x["y"] <= box[3]]
            if n not in (2, 7) or len(span) < 2:
                notes.append(f"annexure merged cell col({n}) {val} on '{bare[:40]}' not attributable - dropped")
                continue
            pt = "month" if n == 2 else "cumulative"
            par = next((x for x in rows if x["indicator"] == group and x["period_type"] == pt), None)
            if par and par["target"] is not None and abs(par["target"] - to_num(val)) > 0.01:
                notes.append(f"annexure source inconsistency: parent row '{group[:45]}' {pt} target "
                             f"{par['target']} != combined sub-row target {val} in the merged cell (both kept)")
            mon = f"{MONTH_NAMES[int(ctx['rm'][5:]) - 1]} {ctx['rm'][:4]}"
            clab = f"{mon} Target" if n == 2 else f"April-{mon} Target"
            extra.append(dict(report_month=ctx["rm"], fiscal_year=fiscal_year(ctx["rm"]), source_file=ctx["src"],
                              page=page.number + 1, sector=sector, table_title=ANNEX_MERGED_TITLE,
                              row_group=group, row_label=COMBINED + " + ".join(span),
                              column_label=clab, period_start=ctx["rm"] if n == 2 else ctx["fy_start"],
                              period_end=ctx["rm"], value=to_num(val), value_text=val, unit=unit))
        for ptype, (t, a, pa, pv, g) in (("month", (2, 3, 4, 5, 6)), ("cumulative", (7, 8, 9, 10, 11))):
            if all(v[n] is None for n in (t, a, pa, pv, g)):
                continue
            row = {**base, "period_type": ptype,
                   "period_start": ctx["rm"] if ptype == "month" else ctx["fy_start"],
                   "period_end": ctx["rm"],
                   "annual_target": None, "target": v[t], "actual": v[a],
                   "prev_year_actual": v[pv], "pct_var_target": None,
                   "pct_var_prev_year": v[g], "pct_achievement": v[pa]}
            for f, n in (("target", t), ("actual", a), ("prev_year_actual", pv)):
                if row[f] is not None and row[f] < 0:
                    # a negative target/production level is impossible (Sep-25 NSL cumulative
                    # target '-54.573'): blank, keep the printed text in the flag
                    add_dq(row, f"negative_level_blanked:{f}={r['vals'][n]}")
                    notes.append(f"p{page.number + 1} '{bare[:30]}' {ptype} {f} printed {r['vals'][n]} "
                                 f"(impossible negative level) - blanked")
                    row[f] = None
            dm = carried.get(sector)
            if dm:
                # data month earlier than the report month ('11. Telecommunications*' in Jan-26:
                # December 2025 data carried forward): date the row by its data month
                fy0 = f"{fiscal_year(dm)[:4]}-04"
                row["period_start"], row["period_end"] = (dm, dm) if ptype == "month" else (fy0, dm)
                add_dq(row, f"carried_forward:{dm}")
            rows.append(row)
    for sec, dm in carried.items():
        n = sum(1 for x in rows if x["sector"] == sec)
        notes.append(f"annexure: {sec} data is {dm} data carried forward (report note); {n} rows dated {dm} "
                     f"with dq_note carried_forward:{dm}")
    return rows, extra


CF_RE = re.compile(r"performance of\s+(\w+)\s+sector\s+is\s+(?:based on|reported as on\s+\d{1,2}\w*)\s+"
                   r"([A-Za-z]+)\s+(\d{4})", re.I)


def carried_forward(text, rm):
    """{sector: data month} for sectors the page says are carried forward from an earlier
    month, e.g. Jan-26 '... the performance of telecommunication sector is based on December
    2025-2026 over December 2024-25' + '*: Data carried forward as per non availability'."""
    t = norm(text)
    out = {}
    if re.search(r"carried forward", t, re.I):
        for m in CF_RE.finditer(t):
            sec, dm = sector_from_heading(m[1]), to_ym(f"{m[2]} {m[3]}")
            if sec and dm and months_between(dm, rm) > 0:
                out[sec] = dm
    return out


# ---------------------------------------------------------------- Highlights

def parse_highlights(page, ctx, notes):
    words = page.get_text("words")
    tb = max(page.find_tables().tables, key=lambda t: t.row_count)
    ext = tb.extract()
    h = next(i for i, r in enumerate(ext) if any(c and norm(c) == "Sector" for c in r))
    sj = next(j for j, c in enumerate(ext[h]) if c and norm(c) == "Sector")
    vcols = [j for j in range(sj + 1, tb.col_count) if tb.rows[h].cells[j] and norm(ext[h][j])]
    tops = [(b, text_in(b, words)) for b in tb.rows[h - 1].cells if b]
    labels = {}
    for j in vcols:
        b = tb.rows[h].cells[j]
        c = (b[0] + b[2]) / 2
        top = next((t for tb_, t in tops if tb_[0] <= c <= tb_[2] and t), "")
        labels[j] = norm(f"{top} {text_in(b, words)}")
    out, sector, group, pend = [], None, None, None
    for i in range(h + 1, len(tb.rows)):
        cells = tb.rows[i].cells
        if cells[sj] is None:
            continue
        lab = text_in(cells[sj], words)
        sl = text_in(cells[0], words) if cells[0] else ""
        if re.match(r"^[A-Za-z#*$ ]{1,6}\s*:", lab) or not lab:
            if re.match(r"^[A-Za-z#*$ ]{1,6}\s*:", lab):
                break
            continue
        if re.fullmatch(r"\d{1,2}", sl):
            sector, group, pend = SECTORS.get(int(sl)), None, None
        vals = {j: text_in(cells[j], words) for j in vcols if cells[j]}
        if not any(to_num(v) is not None for v in vals.values()):
            g = norm(re.sub(r":-$|:$", "", lab))
            if lab.rstrip().endswith((":-", ":")) or re.search(r"#$", lab):
                group, pend = norm(g.rstrip("#")), None
            else:
                pend = g          # e.g. "Railway Revenue Earning" + next row "Freight Traffic (MT)"
            continue
        row_label = join_label(pend, lab) if pend and not MARK_LOWER.match(lab) else lab
        if pend and MARK_LOWER.match(lab):
            group = pend
        pend = None
        unit = unit_of(row_label)
        for j, v in vals.items():
            if to_num(v) is None:
                continue
            if len(v.split()) > 1:
                notes.append(f"highlights '{row_label}' cell {v!r} has several tokens - skipped")
                continue
            ps, pe = parse_period(labels[j])
            out.append(dict(report_month=ctx["rm"], fiscal_year=fiscal_year(ctx["rm"]),
                            source_file=ctx["src"], page=page.number + 1, sector=sector,
                            table_title="Infrastructure Sector Performance Highlights - growth during "
                                        "April-to-month and last three years",
                            row_group=group, row_label=row_label, column_label=labels[j],
                            period_start=ps, period_end=pe, value=to_num(v), value_text=v,
                            unit="%" if "percent" in labels[j].lower() else unit))
    # self consistency: % change = cur/prev - 1
    by = defaultdict(dict)
    for r in out:
        by[r["row_label"]][r["column_label"]] = r["value"]
    ok = bad = 0
    for lab, d in by.items():
        ach = [(k, v) for k, v in d.items() if k.lower().startswith("achievement")]
        pct = [(k, v) for k, v in d.items() if k.lower().startswith("percent")]
        for (_, a0), (_, a1), (_, p) in zip(ach, ach[1:], pct):
            if a0 and a1 is not None and p is not None:
                if abs((a1 / a0 - 1) * 100 - p) <= max(0.2, abs(p) * 0.01):
                    ok += 1
                else:
                    bad += 1
    if bad:
        notes.append(f"highlights: {bad}/{ok + bad} printed % changes disagree with printed achievements (source arithmetic)")
    return out


# ---------------------------------------------------------------- detail tables

def is_body_cell(c):
    toks = (c or "").split()
    return bool(toks) and all(is_val(t) for t in toks)


def header_spec(tb, words, page_no):
    """Ruled header of a detail table -> spec dict (columns with x-range + label) or None.
    Column x-ranges come from header cells plus the first body row's cells; columns
    whose header cell is not ruled (gaps) are filled in and labelled from the words."""
    ext = tb.extract()
    first_body = next((i for i, r in enumerate(ext) if any(is_body_cell(c) for c in r[1:])), None)
    lim = first_body if first_body is not None else len(ext)
    # a header row has >= 2 filled cells and no page-sized cell (page-border tables, Oct-25 p36)
    cand = [i for i in range(lim) if sum(1 for c in ext[i] if c and c.strip()) >= 2
            and not any(b and (b[3] - b[1]) > 120 for b in tb.rows[i].cells)]
    if not cand:
        return None
    hrows = [cand[0]]
    for i in cand[1:]:
        if i != hrows[-1] + 1:
            break
        hrows.append(i)
    # a spanning group header ('Capacity Utilisation' over the period columns) can be the
    # only ruled cell of its row when the label-column header is unruled (Oct-25 Table 36)
    i = hrows[0] - 1
    if i >= 0:
        fc = [b for j, b in enumerate(tb.rows[i].cells) if b and (ext[i][j] or "").strip()]
        if len(fc) == 1 and fc[0][0] > tb.bbox[0] + 5 and fc[0][3] - fc[0][1] < 40:
            hrows.insert(0, i)
    # header extent from cells that carry text (empty cells can be page-border artefacts)
    filled = [(i, j, b) for i in hrows for j, b in enumerate(tb.rows[i].cells) if b and (ext[i][j] or "").strip()]
    last = [b for i, j, b in filled if i == hrows[-1] and j > 0] or [b for i, j, b in filled if i == hrows[-1]]
    bottom = max(b[3] for b in last)
    top = min(b[1] for i, j, b in filled)
    cells = [(b, j) for i in hrows for j, b in enumerate(tb.rows[i].cells)
             if b and b[3] <= bottom + 2 and b[1] >= top - 2]
    grid = list(cells)
    if first_body is not None:
        grid += [(b, j) for j, b in enumerate(tb.rows[first_body].cells) if b]
    cols = []
    for j in range(tb.col_count):
        cb = [b for b, jj in grid if jj == j]
        if cb:
            cols.append({"x0": min(b[0] for b in cb), "x1": min(b[2] for b in cb), "j": j})
    cols.sort(key=lambda c: c["x0"])
    if first_body is not None and any(b["x0"] < a["x1"] - 5 for a, b in zip(cols, cols[1:])):
        # header and body rulings disagree (Nov-25 Table 58: header splits the two
        # % columns at x=518, the body at 536): values follow the body ruling
        cols = sorted(({"x0": b[0], "x1": b[2], "j": j} for j, b in enumerate(tb.rows[first_body].cells) if b),
                      key=lambda c: c["x0"])
    filled = []
    left = tb.bbox[0]
    for c in cols + [{"x0": tb.bbox[2], "x1": tb.bbox[2], "j": None}]:
        if c["x0"] - left > 15:                       # unruled column between ruled ones
            filled.append({"x0": left, "x1": c["x0"], "j": -1})
        if c["j"] is not None:
            filled.append(c)
        left = max(left, c["x1"])
    cols = filled
    if len(cols) < 3:
        return None
    for c in cols:
        x = (c["x0"] + c["x1"]) / 2
        parts = []
        for b, _ in sorted(cells, key=lambda t: (t[0][1], t[0][0])):
            if b[0] - 1 <= x <= b[2] + 1:
                t = text_in(b, words)
                if t and t not in parts:
                    parts.append(t)
        if not parts:
            parts = [text_in((c["x0"], top, c["x1"], bottom), words)]
        c["label"] = fix_breaks(norm(" ".join(parts)))
    merged = [cols[0]]
    for c in cols[1:]:                    # clipped glyph columns ('r' of 'October') -> left neighbour
        if not re.search(r"[A-Za-z0-9]{3,}", c["label"]) and c["x1"] - c["x0"] < 20:
            merged[-1]["x1"] = c["x1"]
        else:
            merged.append(c)
    cols = merged
    # '% Variation Over' top cell can be lost (header split at a page break). Real
    # Target/Actual columns read '<period> Target'; 'Target <period>' is always the
    # sub-header under '% Variation Over'.
    for c in cols:
        if re.match(r"(Target|Actual)\s.*\d{4}", c["label"]) and "Variation" not in c["label"]:
            c["label"] = "% Variation Over " + c["label"]
    return {"cols": cols, "top": top, "bottom": bottom, "page": page_no,
            "x0": cols[0]["x0"], "x1": cols[-1]["x1"], "head0": cols[0]["label"]}


HEADER_WORDS = ["January", "February", "March", "April", "June", "July", "August", "September",
                "October", "November", "December", "Achievement", "Provisional", "Variation", "Target",
                "Actual", "Traffic", "Capacity", "Utilisation", "Installed", "Throughput", "Prorated"]
_BREAK_RES = [(re.compile(r"\b" + r"\s?".join(w) + r"\b"), w) for w in HEADER_WORDS]


def fix_breaks(label):
    """Header words broken by narrow Excel cells: 'Septemb er' -> 'September',
    'Achieve ment' -> 'Achievement', 'April,2 024' -> 'April,2024', 'April- July' -> 'April-July'."""
    t = re.sub(r"(\w)- (\w)", r"\1-\2", label)
    for rx, w in _BREAK_RES:
        t = rx.sub(w, t)
    return re.sub(r"(?<=\d) (?=\d)", "", t)


def col_index(spec, x):
    best, bd = 0, 1e9
    for k, c in enumerate(spec["cols"]):
        if c["x0"] - 1 <= x <= c["x1"] + 1:
            return k
        d = min(abs(x - c["x0"]), abs(x - c["x1"]))
        if d < bd:
            best, bd = k, d
    return best


NOTE_RE = re.compile(r"^(note|source|\*|\$|#|na\s*:|th\s*:|bu\s*:)", re.I)
HEAD_WORDS = {"Physical", "Financial"}


def split_line(L, spec):
    """Word line -> {'labels': {k: text}, 'vals': {k: [words]}, 'y', 'lx0' (label x0)}."""
    labels, vals, lx0 = defaultdict(list), defaultdict(list), None
    for w in L["words"]:
        if not (spec["x0"] - 12 <= xc(w) <= spec["x1"] + 12):
            continue
        k = col_index(spec, xc(w))
        if spec["kind"][k] == "text":
            labels[k].append(w[4])
            lx0 = w[0] if lx0 is None else min(lx0, w[0])
        elif is_val(w[4]):
            vals[k].append(w)
        else:
            labels[0].append(w[4])        # overflow of a long label into a value column
    return {"labels": {k: " ".join(v) for k, v in labels.items()}, "vals": dict(vals),
            "y": L["yc"], "x0": L["x0"], "lx0": lx0, "text": L["text"]}


def merge_fragments(recs):
    """Numbers wrapped inside narrow cells: a line with long digit strings whose
    missing trailing digits sit right-aligned on the next line ('11682761' / '3')."""
    out, i = [], 0
    while i < len(recs):
        P = recs[i]
        D = recs[i + 1] if i + 1 < len(recs) else None
        longs = {k: ws[0] for k, ws in P["vals"].items()
                 if len(ws) == 1 and re.fullmatch(r"\d{6,}", ws[0][4])}
        if D and longs and not P.get("merged_fragment") and D["y"] - P["y"] < 13.5 and all(
                k in D["vals"] and len(D["vals"][k]) == 1 and re.fullmatch(r"\d{1,3}", D["vals"][k][0][4])
                and abs(D["vals"][k][0][2] - longs[k][2]) < 2 for k in longs) and \
                all(k in longs for k, ws in P["vals"].items() if any(ch.isdigit() for w in ws for ch in w[4])):
            for k, w in longs.items():
                d = D["vals"][k][0]
                D["vals"][k] = [(d[0], d[1], d[2], d[3], w[4] + d[4])]
            for k, t in P["labels"].items():
                D["labels"][k] = join_label(norm(t), norm(D["labels"].get(k, "")))
            if P.get("lx0") is not None:
                D["lx0"] = P["lx0"] if D.get("lx0") is None else min(P["lx0"], D["lx0"])
            D["merged_fragment"] = True
            i += 1
            continue
        out.append(P)
        i += 1
    return out


def marked(t):
    """'a) Public Sector' is a list item; a bare 'c)' is the tail of a broken word."""
    m = MARK_LOWER.match(t)
    return bool(m) and len(t) > m.end()


def _ptxt(p):
    return norm(" ".join(p["labels"].get(k, "") for k in sorted(p["labels"])))


def assemble(recs, spec, issues, dropped):
    """Word-line records of one table body -> data rows.
    Label-only lines are resolved against their neighbours: a heading (lettered /
    'Physical' / followed by an indented or marked row), a tail of the row above
    ('(Kms.)', '(VISL)', lower-case continuation, clearly nearer the row above),
    or else a wrapped prefix of the row below (Excel bottom-aligns values)."""
    recs = merge_fragments(recs)
    rows, pending, state = [], [], {"heading": None, "ffill": None}
    two_text = sum(1 for k in spec["kind"] if k == "text") > 1

    def resolve(nxt):
        prefix, prefix_started = defaultdict(str), False
        for n, p in enumerate(pending):
            ptxt = _ptxt(p)
            nn = pending[n + 1] if n + 1 < len(pending) else nxt
            nlab = _ptxt(nn) if nn else ""
            prev = rows[-1] if rows else None
            d_prev = p["y"] - prev["_y"] if prev else 1e9
            d_next = nn["y"] - p["y"] if nn else 1e9
            tail_like = ptxt.startswith("(") or ptxt[:1].islower()
            if prev is not None and not prefix_started and (
                    (tail_like and d_prev < 14 and d_prev <= d_next + 1) or (d_prev < 9 and d_prev + 2 < d_next)):
                prev["row_label"] = norm(prev["row_label"] + " " + ptxt) if prev["row_label"] else ptxt
                continue
            is_head = (MARK_UPPER.match(ptxt) or MARK_LETTER.match(ptxt) or ptxt in HEAD_WORDS
                       or (nn is not None and (marked(nlab) or MARK_LETTER.match(nlab)
                                               or (nn.get("lx0") is not None and p.get("lx0") is not None
                                                   and nn["lx0"] > p["lx0"] + 3)))
                       or (d_next > 16 and d_prev > 16))
            if nlab.startswith("(") and d_next < 14 and ptxt not in HEAD_WORDS:
                is_head = False               # 'C. DGH' + '(JVC/Private)' is one wrapped label
            if is_head:
                state["heading"], prefix, prefix_started = ptxt, defaultdict(str), False
            else:
                prefix_started = True
                for k, t in p["labels"].items():
                    prefix[k] = join_label(prefix[k], norm(t))
        pending.clear()
        return prefix

    for r in recs:
        vals = dict(r["vals"])
        if not vals:
            if NOTE_RE.match(r["text"]):
                break                         # footnotes end the table body
            if any(norm(t) for t in r["labels"].values()):
                pending.append(r)
            continue
        if any(len(ws) > 1 for ws in vals.values()):
            issues.append(f"several tokens in one cell on line '{r['text'][:50]}'")
        prefix = resolve(r)
        labels = {k: join_label(prefix.get(k, ""), norm(r["labels"].get(k, "")))
                  for k in set(prefix) | set(r["labels"])}
        lab0 = labels.get(0, "")
        heading = state["heading"]
        if two_text:
            if lab0:
                state["ffill"] = lab0
            sec = next((k for k in sorted(labels) if k > 0 and labels[k]), None)
            row_label = labels[sec] if sec is not None else lab0
            group = state["ffill"] if sec is not None else heading
            if sec is not None and row_label.startswith("(") and lab0:   # '(International+Domestic)'
                row_label, group = join_label(lab0, row_label), heading
        else:
            row_label, group = lab0, heading
        if re.match(r"(?i)^(all india|total\s*\(|grand total|gross production)", row_label) or \
                MARK_LETTER.match(row_label):
            state["heading"] = None
            if not two_text:
                group = None
        rows.append({"row_group": group, "row_label": row_label, "vals": vals, "_y": r["y"],
                     "page": r.get("page")})
    resolve(None)                              # trailing tails like '(Kms.)'
    out = []
    for row in rows:
        if row["row_label"]:
            out.append(row)
            continue
        nums = [w[4] for ws in row["vals"].values() for w in ws if to_num(w[4]) is not None]
        if len(nums) <= 1:
            dropped.append(f"unlabelled value {nums} (merged cell spanning rows)")
        else:
            issues.append(f"data line without label: {[w[4] for ws in row['vals'].values() for w in ws]}")
    return out


UNIT_LINE = re.compile(r"\(((?:In|in)\s[^()]*|Percentage|Rs\.? in Crores?)\)")


def table_title_unit(lines, before_y, after_y, carried=None):
    """Last 'Table - n: ...' title (+ up to 3 continuation lines while the title has
    no month/year yet) and the unit line '(In ...)' between after_y and before_y.
    carried = title started at the foot of the previous page; its continuation is
    the first lines of this page."""
    tl = [L for L in lines if after_y <= L["yc"] < before_y]
    title = unit = None
    idx = [i for i, L in enumerate(tl) if re.match(r"^Table\s*-\s*\d", L["text"])]
    if idx:
        tl = tl[idx[-1]:]
        title, rest, last_y = norm(tl[0]["text"]), tl[1:], tl[0]["yc"]
    elif carried:
        title, rest, last_y = carried, tl, None
    for L in (rest[:3] if title else []):
        if (UNIT_LINE.fullmatch(norm(L["text"])) or re.search(r"(\d{4}|-\d{2})\s*$", title)
                or (last_y is not None and L["yc"] - last_y >= 25)):
            break
        sep = "" if re.search(r"\S-$", title) else " "      # 'during - April-' + 'October 2025'
        title, last_y = norm(title + sep + L["text"]), L["yc"]
    for L in tl:
        u = UNIT_LINE.fullmatch(norm(L["text"]))
        if u:
            unit = UNIT_MAP.get(norm(u[1]).lower(), norm(u[1]))
    return title, unit


BOUND_RE = re.compile(r"^(Table\s*-\s*\d|\d{1,2}\.\d{0,2}\s*[A-Z][A-Za-z]|\d{1,2}\.\d{1,2}$)")
FOOT_RE = re.compile(r"\|\s*P\s*a\s*g\s*e")


def collect_tables(doc, start):
    """Phase 1: find every detail table header and the word lines of its body,
    following bodies that run onto the next page. Returns list of specs."""
    specs_all, open_spec, pending, sec_num = [], None, None, None
    page_cells = {}                       # page -> ruled cell boxes, for merged-cell detection
    for pno in range(start, doc.page_count):
        page = doc[pno]
        words = page.get_text("words")
        lines = make_lines(words, tol=3.6)
        if not lines:
            open_spec = None
            continue
        foot_y = min([L["y0"] for L in lines if FOOT_RE.search(L["text"])] + [1e9])
        lines = [L for L in lines if L["y0"] < foot_y - 0.5]
        tabs = page.find_tables().tables
        page_cells[pno + 1] = [c for tb in tabs for c in tb.cells if c]
        specs = [s for s in (header_spec(tb, words, pno + 1) for tb in tabs) if s]
        for s in specs:
            s["page_cells"] = page_cells
        specs.sort(key=lambda s: s["top"])
        bounds = sorted(L["y0"] for L in lines if BOUND_RE.match(L["text"]) and L["x0"] < 300)
        heads = [(L["yc"], int(m[1])) for L in lines
                 if (m := re.match(r"^(\d{1,2})\.(\d{1,2})?\s*[A-Z]", L["text"])) and L["x0"] < 80
                 and 1 <= int(m[1]) <= 11]
        first = min([s["top"] for s in specs] + bounds + [foot_y])
        if open_spec is not None:
            open_spec["parts"].append((pno + 1, [L for L in lines if L["yc"] < first]))
        prev = 0
        for s in specs:
            title, unit = table_title_unit(lines, s["top"], prev)
            if title is None and pending and not any(prev <= b < s["top"] for b in bounds):
                title, unit2 = table_title_unit(lines, s["top"], prev, carried=pending[0])
                unit = unit or unit2 or pending[1]
            pending = None
            hs = [n for y, n in heads if y < s["top"]]
            if hs:
                sec_num = hs[-1]
            s.update(title=title, unit=unit, sector_num=sec_num, parts=[])
            end = min([b for b in bounds if b > s["bottom"] + 1] +
                      [t["top"] for t in specs if t["top"] > s["bottom"]] + [foot_y])
            s["parts"].append((pno + 1, [L for L in lines if s["bottom"] + 0.5 <= L["yc"] < end]))
            s["ran_to_foot"] = end >= foot_y
            specs_all.append(s)
            prev = s["bottom"]
        tails = [L for L in lines if re.match(r"^Table\s*-\s*\d", L["text"]) and L["yc"] > prev]
        if tails:
            pending = table_title_unit(lines, 1e9, tails[-1]["y0"] - 1)
        if heads:
            sec_num = heads[-1][1]
        open_spec = specs[-1] if specs and specs[-1]["ran_to_foot"] and not tails else \
            (open_spec if not specs and not bounds else None)
    return specs_all


def sector_of_table(s):
    t = (s.get("title") or "").lower()
    for k, v in TITLE_SECTOR:
        if k in t:
            return v
    return SECTORS.get(s.get("sector_num"))


def check_alignment(rows, cols):
    """Compare '% Variation Over Target/Actual' columns with the table's own
    Target / Achievement / Actual columns.
    Returns {'target': [ok, bad], 'actual': [ok, bad], 'fails': [...]}."""
    lab = [c["label"].lower() for c in cols]

    def find(pred):
        return next((k for k, l in enumerate(lab) if pred(l)), None)
    tgt = find(lambda l: "target" in l and "annual" not in l and "%" not in l and "variation" not in l)
    ach = find(lambda l: "achievement" in l or l.endswith("pax traffic"))
    act = find(lambda l: ("actual" in l or "traffic during" in l) and "%" not in l and "variation" not in l)
    vt = find(lambda l: "variation" in l and "target" in l)
    va = find(lambda l: "variation" in l and "actual" in l)
    res = {"target": [0, 0], "actual": [0, 0], "fails": [], "bad": set()}
    for r in rows:
        v = {k: to_num(ws[0][4]) if len(ws) == 1 else None for k, ws in r["vals"].items()}
        a = v.get(ach)
        for kind, base, var in (("target", tgt, vt), ("actual", act, va)):
            b, p = v.get(base), v.get(var)
            if base is None or var is None or a is None or not b or p is None:
                continue
            good = abs((a / b - 1) * 100 - p) <= max(0.6, abs(p) * 0.02)
            res[kind][0 if good else 1] += 1
            if not good:
                res["fails"].append(f"{r['row_label'][:25]}:{kind} {a}/{b}->{p}")
                res["bad"].add((id(r), var))          # the printed % cell that disagrees
    return res


def drop_merged_cells(recs, page_cells, spec, dropped, merged):
    """A lone number inside a ruled cell that spans several ruled label rows is a
    merged cell (e.g. one State PWD target printed across three road rows): drop it.
    Returns recs without lines that held nothing but such a cell (otherwise a lone
    merged '*' line would later read as a '* ...' footnote and end the table body)."""
    c0 = spec["cols"][0]
    emptied = set()
    for i, r in enumerate(recs):
        cells = page_cells.get(r["page"], [])
        label_cells = [c for c in cells if abs(c[0] - c0["x0"]) < 3 and c[2] <= c0["x1"] + 3]
        for k in list(r["vals"]):
            keep = []
            for w in r["vals"][k]:
                boxes = [c for c in cells
                         if c[0] - 0.5 <= xc(w) <= c[2] + 0.5 and c[1] - 0.5 <= yc(w) <= c[3] + 0.5]
                if boxes:
                    c = min(boxes, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
                    spans = sum(1 for lc in label_cells
                                if min(c[3], lc[3]) - max(c[1], lc[1]) > 0.5 * (lc[3] - lc[1]))
                    toks = [x for q in recs if q["page"] == r["page"] for ws in q["vals"].values() for x in ws
                            if c[0] - 0.5 <= xc(x) <= c[2] + 0.5 and c[1] - 0.5 <= yc(x) <= c[3] + 0.5]
                    if spans >= 2 and len(toks) == 1:
                        if to_num(w[4]) is not None:
                            merged.append((k, w, c, r["page"]))
                        continue
                keep.append(w)
            if keep:
                r["vals"][k] = keep
            else:
                del r["vals"][k]
                if not r["vals"] and not any(norm(t) for t in r["labels"].values()):
                    emptied.add(i)
    return [r for i, r in enumerate(recs) if i not in emptied]


def col_period(clab, title, rm):
    """(period_start, period_end) of a detail-table column; a label without a period takes
    the table's period; '% Variation Over Actual <last year>' carries the current period."""
    ps, pe = parse_period(clab)
    if ps is None and len(re.findall(MONTH_RE + r"[\s,'-]*\d{2,4}\b", title.lower())) == 1:
        ps, pe = parse_period(title)          # label without a period -> table period
    if not plausible_period(ps, pe, rm):
        return None, None
    low = clab.lower()
    if "variation" in low and "actual" in low and months_between(pe, rm) >= 12:
        # '% Variation Over Actual <last year>' is this period's growth: same
        # convention as the Highlights 'Percent change ... <this period>' columns
        ps, pe = add_months(ps, 12), add_months(pe, 12)
    return ps, pe


def continued_span(span, plain, k, x, pno, page0, page_cells):
    """A merged cell that reaches the last row of its page continues over the next page's
    leading rows of the same table that have no ruled cell of their own in that column
    (Jul-25 Table 47: '104.00' spans two rows at the foot of p48 and four rows at the top
    of p49). Returns those continuation rows; a row with its own value in column k ends
    the span. page0 = the table's first page (row _y has +2000 per continuation page)."""
    on_page = [r for r in plain if r.get("page") == pno]
    if not span or max(r["_y"] for r in on_page) > max(r["_y"] for r in span):
        return []
    cells, off = page_cells.get(pno + 1, []), (pno + 1 - page0) * 2000
    out = []
    for r in sorted((r for r in plain if r.get("page") == pno + 1), key=lambda r: r["_y"]):
        y = r["_y"] - off
        if k in r["vals"] or any(b[0] - 0.5 <= x <= b[2] + 0.5 and b[1] - 0.5 <= y <= b[3] + 0.5
                                 for b in cells):
            break
        out.append(r)
    return out


def parse_details(doc, start, ctx, notes, skipped):
    out = []
    for s in collect_tables(doc, start):
        title = s.get("title") or ""
        tno = (re.match(r"Table\s*-\s*(\d+\s*[A-Z]?)", title) or [None, "?"])[1].replace(" ", "")
        tag = f"p{s['page']} Table {tno}"
        sector = sector_of_table(s)
        if sector == "Telecommunications":
            skipped.append(f"{tag} telecom detail (inconsistent period labels in source; values duplicated in Annexure-A)")
            continue
        lines = [(pno, L) for pno, ls in s["parts"] for L in ls]
        if not lines:
            continue
        # column kinds: text if most body tokens in it are not numbers
        cnt = defaultdict(lambda: [0, 0])
        for _, L in lines:
            for w in L["words"]:
                k = col_index(s, xc(w))
                cnt[k][0 if is_val(w[4]) else 1] += 1
        s["kind"] = ["text" if k == 0 or cnt[k][1] > cnt[k][0] else "value" for k in range(len(s["cols"]))]
        recs = []
        for pno, L in lines:
            r = split_line(L, s)
            r["page"] = pno
            r["y"] += (pno - s["page"]) * 2000        # continuation pages sort after, never 'near'
            recs.append(r)
        issues, dropped, merged = [], [], []
        recs = merge_fragments(recs)
        recs = drop_merged_cells(recs, s["page_cells"], s, dropped, merged)
        rows = assemble(recs, s, issues, dropped)
        plain = list(rows)
        for k, w, c, pno in merged:
            # one number printed across several rows (NHAI / State PWD targets): a combined
            # value of the rows the ruled cell spans, never the value of the row it sits on
            off = (pno - s["page"]) * 2000
            span = [r for r in plain if r.get("page") == pno and c[1] - 1 <= r["_y"] - off <= c[3] + 1]
            span += continued_span(span, plain, k, xc(w), pno, s["page"], s["page_cells"])
            units = {unit_of(r["row_label"]) for r in span}
            if len(span) >= 2:
                rows.append({"row_group": span[0]["row_group"], "vals": {k: [w]}, "_y": span[-1]["_y"], "page": pno,
                             "row_label": COMBINED + " + ".join(r["row_label"] for r in span),
                             "combined": True, "unit": units.pop() if len(units) == 1 else None})
            else:
                dropped.append(f"'{w[4]}' (merged cell spanning rows, not attributable)")
        if dropped:
            notes.append(f"{tag}: dropped {'; '.join(dropped)}")
        combined = [r for r in rows if r.get("combined")]
        rows = [r for r in rows if not r.get("combined")]
        chk = check_alignment(rows, s["cols"])
        # the source often mis-computes one of the two % columns (e.g. 109.08 for
        # 12545/13316), so a table is only treated as misaligned when all checks fail
        ok, bad = chk["target"][0] + chk["actual"][0], chk["target"][1] + chk["actual"][1]
        vcols = [k for k, kd in enumerate(s["kind"]) if kd == "value"]
        # skip on misalignment: every available check fails for most rows
        fails = [kind for kind in ("target", "actual") if sum(chk[kind]) >= 2 and chk[kind][1] > chk[kind][0]]
        misaligned = fails and len(fails) == sum(1 for kind in ("target", "actual") if sum(chk[kind]) >= 2)
        if issues or misaligned or not rows or not vcols:
            skipped.append(f"{tag} '{title[:60]}' skipped: issues={issues[:2]} align ok={ok} bad={bad} "
                           f"{chk['fails'][:3]}")
            continue
        nums = [to_num(ws[0][4]) for r in rows for ws in r["vals"].values() if to_num(ws[0][4]) is not None]
        # a table whose every printed value is 0 (Oct/Dec airport cargo) is a 'not reported'
        # placeholder: its cells are emitted blank by mark_placeholders(), not skipped
        # reconciliation: every number printed in the body is emitted or logged as dropped
        n_print = sum(1 for r in recs for ws in r["vals"].values() for w in ws if to_num(w[4]) is not None)
        n_unlab = sum(1 for d in dropped if d.startswith("unlabelled value ['"))
        if n_print - len(nums) - n_unlab:
            notes.append(f"{tag}: {n_print - len(nums) - n_unlab} of {n_print} printed body numbers not emitted")
        rows += combined
        for r in combined:
            notes.append(f"{tag}: '{next(iter(r['vals'].values()))[0][4]}' printed in one merged cell across "
                         f"{r['row_label'].count(' + ') + 1} rows - emitted as a combined row")
        nb = chk["target"][1] + chk["actual"][1]
        if nb:
            notes.append(f"{tag}: {nb}/{nb + chk['target'][0] + chk['actual'][0]} printed % variations "
                         f"disagree with the table's own columns (source arithmetic): {chk['fails'][:3]}")
        tlow = title.lower()
        per = {k: col_period(c["label"], title, ctx["rm"]) for k, c in enumerate(s["cols"])}
        role = {k: col_role(c["label"]) for k, c in enumerate(s["cols"])}
        ach_per = {per[k] for k in role if role[k] == "ach" and per[k][0]}
        m_tno = re.match(r"Table\s*-\s*(\d+\s*[A-Z]?)", title)
        typo = {}
        for k in role:
            if role[k] == "actual" and per[k][0] and per[k] in ach_per:
                # the previous-year 'Actual' header printed with the current year (Jun-25 Table 45
                # 'June 2025 Actual' next to 'Jun-25 Achievement'; its '% Variation Over Actual
                # June 2024' confirms): the column is the report period - 12 months
                old = s["cols"][k]["label"]
                ps, pe = add_months(per[k][0], -12), add_months(per[k][1], -12)
                s["cols"][k]["label"] = re.sub(r"^.*?(?=\bActual$)", period_text(ps, pe) + " ", old)
                per[k], typo[k] = (ps, pe), f"header_typo:printed '{old}'"
                notes.append(f"{tag}: header '{old}' is the previous-year column (typo) - dated {ps}..{pe}, "
                             f"labelled '{s['cols'][k]['label']}'")
        for ri, r in enumerate(rows):
            for k, ws in r["vals"].items():
                txt = ws[0][4]
                val = to_num(txt)
                if val is None and (role[k] == "var" or r.get("combined")):
                    continue
                clab = s["cols"][k]["label"]
                low = clab.lower()
                ps, pe = per[k]
                dq = typo.get(k)
                if r.get("combined"):
                    unit = r["unit"]                      # blank when the spanned rows mix Kms and Nos.
                elif any(key in low for key in ("%", "variation", "utilisation", "plf")) or (
                        ("utilisation" in tlow or "plf" in tlow)
                        and not any(key in low for key in ("capacity", "throughput"))):
                    unit = "%"
                else:
                    unit = unit_of(r["row_label"]) or unit_of(r["row_group"] or "") or s.get("unit") or unit_of(s["head0"])
                if val is not None and (id(r), k) in chk["bad"]:
                    dq = f"{dq};printed_pct_mismatch" if dq else "printed_pct_mismatch"
                rec = dict(report_month=ctx["rm"], fiscal_year=fiscal_year(ctx["rm"]), source_file=ctx["src"],
                           page=r.get("page") or s["page"], sector=sector, table_title=title or None,
                           row_group=r["row_group"], row_label=r["row_label"],
                           column_label=norm_col_label(clab, ps, pe),
                           period_start=ps, period_end=pe, value=val, value_text=txt, unit=unit, dq_note=dq,
                           # internal, used by mark_placeholders()/fill_units() and dropped before writing
                           _tid=f"{ctx['src']}|{tag}", _rid=ri, _tno=m_tno[1].replace(" ", "") if m_tno else None,
                           _role=role[k], _marker=val is None, _combined=bool(r.get("combined")),
                           _tunit=s.get("unit"))
                out.append(rec)
    return out


# ---------------------------------------------------------------- validation + main

def perf_checks(rows):
    """Arithmetic checks on Annexure rows -> list of note strings."""
    notes, bad_ach, bad_g, n_ach, n_g = [], [], [], 0, 0
    for r in rows:
        t, a, p = r["target"], r["actual"], r["prev_year_actual"]
        if t and a is not None and r["pct_achievement"] is not None:
            n_ach += 1
            if abs(a / t * 100 - r["pct_achievement"]) > max(0.1, r["pct_achievement"] * 0.002):
                bad_ach.append(f"{r['indicator'][:30]}/{r['period_type']}")
                add_dq(r, "printed_pct_mismatch")
        if p and a is not None and r["pct_var_prev_year"] is not None:
            n_g += 1
            if abs((a / p - 1) * 100 - r["pct_var_prev_year"]) > max(0.1, abs(r["pct_var_prev_year"]) * 0.01):
                bad_g.append(f"{r['indicator'][:30]}/{r['period_type']}")
                add_dq(r, "printed_pct_mismatch")
    if bad_ach:
        notes.append(f"annexure: {len(bad_ach)}/{n_ach} printed achievement% != actual/target ({'; '.join(bad_ach[:4])})")
    if bad_g:
        notes.append(f"annexure: {len(bad_g)}/{n_g} printed growth% != actual/prev-1 ({'; '.join(bad_g[:4])})")
    # component rows vs their group row
    groups = defaultdict(list)
    for r in rows:
        groups[(r["sector"], r["indicator_group"], r["period_type"])].append(r)
    bad_sum = []
    for (sec, g, pt), rs in groups.items():
        head = [r for r in rs if r["indicator"] == g]
        kids = [r for r in rs if r["indicator"] != g and not r["is_total"]]
        if len(head) == 1 and len(kids) >= 2 and head[0]["actual"] is not None and \
                all(k["actual"] is not None for k in kids):
            tot = sum(k["actual"] for k in kids)
            if abs(tot - head[0]["actual"]) > max(0.01, abs(head[0]["actual"]) * 0.005):
                bad_sum.append(f"{g[:35]}/{pt}: parts {tot:.3f} vs {head[0]['actual']}")
    if bad_sum:
        notes.append("annexure component sums differ from group row: " + "; ".join(bad_sum[:5]))
    return notes


def process(path):
    src = rel(path)
    doc = fitz.open(path)
    notes, skipped = [], []
    rm = report_month_from_name(path.name)
    tms = title_months(doc)
    if not rm:
        rm = tms.get("highlights")
        notes.append("report month not in file name; taken from highlights title")
    for k, v in tms.items():
        if v != rm:
            notes.append(f"{k} title says {v} but file name says {rm}")
    fy = fiscal_year(rm)
    ctx = {"rm": rm, "src": src, "fy_start": f"{fy[:4]}-04"}
    ap = find_annexure_page(doc)
    perf, detail = parse_annexure(doc[ap], ctx, notes)
    notes += perf_checks(perf)
    hp = ap + 1
    assert "HIGHLIGHTS" in doc[hp].get_text().upper(), "highlights page not after annexure"
    detail += parse_highlights(doc[hp], ctx, notes)
    detail += parse_details(doc, hp + 1, ctx, notes, skipped)
    if skipped:
        notes.append(f"{len(skipped)} detail tables skipped: " + " || ".join(skipped))
    if not any(r["sector"] == "Telecommunications" for r in perf):
        notes.append("no Telecommunications rows in Annexure-A (not published in this report)")
    man = dict(source_file=src, report_type="performance_review", report_period=rm, pages=doc.page_count,
               parser_variant=VARIANT, rows_perf=len(perf), rows_perf_detail=len(detail),
               status="ok" if perf and detail and all("telecom detail" in x or "placeholder:" in x for x in skipped) else "partial",
               notes=" | ".join(notes))
    return perf, detail, man, skipped


def complete_label(lab, pool):
    """If lab is a strict prefix of exactly one longer label in pool, return that label."""
    stem = lab.rstrip()
    cands = {p for p in pool if p != lab and len(p) > len(stem) and p.startswith(stem)}
    return cands.pop() if len(cands) == 1 else None


def complete_clipped(perf, detail):
    """Some reports print labels clipped by the cell ('Power Generation: Non-',
    'Crude Oil Processed (M', 'Singareni Collieries Compan'). Complete them from the
    same sector's labels in the other reports of this family. Annexure labels: any
    label seen in only this report that is a prefix of exactly one other label.
    Detail labels: only visibly clipped ones (unbalanced '(')."""
    fixed, annex_map = defaultdict(set), {}
    balanced = lambda s: s.count("(") == s.count(")")      # noqa: E731
    for pass_ in (1, 2):
        seen = defaultdict(lambda: defaultdict(set))       # sector -> label -> files
        for r in perf:
            for f in ("indicator", "indicator_group"):
                if r[f]:
                    seen[r["sector"]][r[f]].add(r["source_file"])
        for r in perf:
            for f in ("indicator", "indicator_group"):
                lab = r[f]
                if not lab:
                    continue
                if pass_ == 1 and not balanced(lab):       # visibly clipped: '(BU', '(BR'
                    pool = {x for x in seen[r["sector"]] if balanced(x)}
                elif pass_ == 2 and len(seen[r["sector"]][lab]) == 1:
                    pool = {x for x, fs in seen[r["sector"]].items() if len(fs) >= 2}
                else:
                    continue
                full = complete_label(lab, pool)
                if full:
                    fixed[r["source_file"]].add(f"'{lab}'->'{full}'")
                    r[f] = full
                    add_dq(r, "label_restored")
                    annex_map[(r["source_file"], lab)] = full
    for r in perf:
        r["unit"] = r["unit"] or unit_of(r["indicator"]) or unit_of(r["indicator_group"] or "")
    for r in detail:
        if r["table_title"] == ANNEX_MERGED_TITLE and (r["source_file"], r["row_group"]) in annex_map:
            r["row_group"] = annex_map[(r["source_file"], r["row_group"])]
            add_dq(r, "label_restored")
    dseen = defaultdict(set)
    for r in detail:
        dseen[r["sector"]].add(r["row_label"])
    for r in detail:
        lab = r["row_label"]
        if lab.count("(") > lab.count(")"):
            full = complete_label(lab, {x for x in dseen[r["sector"]] if x.count("(") == x.count(")")})
            if full:
                if not r.get("_marker"):
                    fixed[r["source_file"]].add(f"'{lab}'->'{full}'")
                r["row_label"] = full
                add_dq(r, "label_restored")
    return fixed


def main():
    files = sorted(SRC.glob("*.pdf"))
    perf, detail, manifest = [], [], []
    for f in files:
        try:
            p, d, m, sk = process(f)
        except Exception as e:  # keep going; the manifest records the failure
            p, d, sk = [], [], []
            m = dict(source_file=rel(f), report_type="performance_review",
                     report_period=report_month_from_name(f.name), parser_variant=VARIANT,
                     status="failed", notes=f"{type(e).__name__}: {e}")
        perf += p
        detail += d
        manifest.append(m)
        print(f"{f.name}: perf={len(p)} skipped_tables={len(sk)} status={m['status']}")
    extra = defaultdict(list)                       # source_file -> manifest notes
    for f, n in complete_clipped(perf, detail).items():
        extra[f].append("labels clipped in the source completed from other months (dq_note label_restored): "
                        + "; ".join(sorted(n)))
    for f, n in fill_units(detail).items():
        extra[f].append(f"{n} detail rows whose table prints no unit line here take the unit the same "
                        f"table prints in the other reports (dq_note unit_from_other_months)")
    for f, c in mark_placeholders(detail).items():
        extra[f].append(f"placeholder zeros blanked (value empty, value_text kept, dq_note placeholder_zero): "
                        f"{sum(c.values())} cells - " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    for f, n in stale_repeats(perf).items():
        extra[f].append("source repeats a value printed in an earlier report for a different period "
                        "(kept as printed, dq_note stale_repeat_of): " + "; ".join(n))
    for f, n in highlight_xcheck(detail).items():
        extra[f].append("highlights values inconsistent with the report's own detail table (kept as printed, "
                        "dq_note inconsistent_with_table_<n>): " + "; ".join(n))
    detail = [{k: v for k, v in r.items() if not k.startswith("_")} for r in detail if not r.get("_marker")]
    for m in manifest:
        m["rows_perf_detail"] = sum(1 for r in detail if r["source_file"] == m["source_file"])
        m["notes"] = " | ".join(x for x in [m.get("notes")] + extra.get(m["source_file"], []) if x)
    # a Target/Actual sub-header that lost its '% Variation Over' parent would label
    # percentages as quantities (Table 40 before the header_spec regex fix)
    bad = {r["column_label"] for r in detail if re.match(r"(Target|Actual)\s", r["column_label"])}
    assert not bad, f"column labels missing the % Variation prefix: {sorted(bad)[:5]}"
    assert not any(r["value"] == 0 and "placeholder_zero" in (r["dq_note"] or "") for r in detail)
    write_part(perf, FAMILY, "perf", PERF_COLS)
    write_part(detail, FAMILY, "perf_detail", PERF_DETAIL_COLS)
    write_part(manifest, FAMILY, "manifest", MANIFEST_COLS)
    return perf, detail, manifest


LEVEL = ("target", "annual", "ach", "actual", "other")
TOTAL_RE = re.compile(r"(?i)^(total|all india|grand total)\b")


def mark_placeholders(detail):
    """Zeros the source prints for 'not reported' -> value blank + dq_note placeholder_zero
    (value_text keeps the printed '0.00'). Decided per cell from the report's own structure
    and the other reports of the family; a zero is a placeholder when
      table   every number printed in the table is 0 (Oct/Dec airport cargo);
      column  a target/level column holds no non-zero number (renewable and coking-coal
              targets, coal 'Annual Target 2025-2026' 0.000 everywhere);
      target  a target is 0 while the row's achievement for that period is not (Dec Table 1
              Renewable Energy '0.000' target, 23.332 BU achieved; the report says renewable
              targets are not reported);
      marker  the same cell (table no., row, measure) prints a not-reported marker ('*', '$',
              'NA', '-') in another report while its column there holds real numbers (NHAI
              'Total Expenditure' '$' in Jun/Jul, '0.00' later);
      row     a row with no non-zero level and no numeric % that carries such a marker, or
              a 'marker' cell (SAIL plants: target '*'/'NA' where SAIL Conversion Agent has
              one; production 0.00 while SAIL-Total holds everything); and
      group   every such row under a subtotal row that is itself 'row' (cement A. Public
              Sector: 'Total - A' prints '-' where CCI/Others print 0.00).
    An achievement 0 that a printed numeric % variation uses (-100.00) is real. Annual
    target markers are not evidence against a row (a '-' annual target of the shut CPCL
    Narimanam refinery says nothing about its 0 production). Returns {file: Counter}."""
    cells = [r for r in detail if r.get("_tid") and not r["_combined"]]
    col_nz = defaultdict(bool)
    for r in cells:
        col_nz[(r["_tid"], r["column_label"])] |= bool(r["value"])

    def specific(c):     # a not-reported marker where the column has real numbers elsewhere
        return c["_marker"] and c["value_text"].lower() != "nil" and col_nz[(c["_tid"], c["column_label"])]

    def key(c):
        return c["_tno"], c["row_label"], c["_role"], c["period_start"] == c["period_end"]
    evidence = defaultdict(set)
    for c in cells:
        if specific(c):
            evidence[key(c)].add(c["report_month"])
    tables = defaultdict(lambda: defaultdict(list))
    for c in cells:
        tables[c["_tid"]][c["_rid"]].append(c)
    hits = defaultdict(Counter)
    for tid, rows in tables.items():
        allc = [c for rs in rows.values() for c in rs]
        ph = {}

        def zero(c):
            return c["value"] == 0 and c["_role"] in LEVEL

        def used(c):     # a 0 achievement that a printed % (e.g. -100.00) was computed from
            return c["_role"] == "ach" and any(x["_role"] == "var" and x["value"] is not None for x in rows[c["_rid"]])

        def empty(rs):   # no non-zero level, no numeric %
            return not any(c["value"] for c in rs if c["_role"] in LEVEL) and \
                not any(c["value"] is not None for c in rs if c["_role"] == "var")
        if not any(c["value"] for c in allc):
            ph = {id(c): "table" for c in allc if c["value"] == 0}
        for c in allc:
            if zero(c) and id(c) not in ph and not col_nz[(tid, c["column_label"])] and not used(c):
                ph[id(c)] = "column"
        for rs in rows.values():
            ach = [a for a in rs if a["_role"] == "ach" and a["value"]]
            for c in rs:
                if zero(c) and id(c) not in ph and c["_role"] in ("target", "annual") and any(
                        c["_role"] == "annual" or (a["period_start"], a["period_end"]) == (c["period_start"], c["period_end"])
                        for a in ach):
                    ph[id(c)] = "target"
        for c in allc:
            if zero(c) and id(c) not in ph and evidence[key(c)] - {c["report_month"]} and not used(c):
                ph[id(c)] = "marker"
        dead = {rid for rid, rs in rows.items() if empty(rs) and any(
            c["_role"] != "annual" and (specific(c) or ph.get(id(c)) == "marker") for c in rs)}
        for rid in list(dead):
            head = rows[rid][0]
            if head["row_group"] and TOTAL_RE.match(head["row_label"]):
                dead |= {r2 for r2, rs in rows.items() if rs[0]["row_group"] == head["row_group"] and empty(rs)}
        for rid in dead:
            for c in rows[rid]:
                if zero(c) and id(c) not in ph:
                    ph[id(c)] = "row"
        for c in allc:
            if id(c) in ph:
                c["value"] = None
                add_dq(c, "placeholder_zero")
                hits[c["source_file"]][ph[id(c)]] += 1
    return hits


def fill_units(detail):
    """A detail table printed without its '(In ...)' unit line (Oct-25 Table 20, Jan-26 Table 52)
    takes the unit the same table number gives that row - else the table - in the other
    reports, when that is unambiguous. Returns {file: n}."""
    rows = [r for r in detail if r.get("_tno") and not r["_combined"]]
    by_row, by_tab = defaultdict(set), defaultdict(set)
    for r in rows:
        if r["unit"] and r["unit"] != "%":
            by_row[(r["_tno"], r["row_label"])].add((r["source_file"], r["unit"]))
        if r["_tunit"]:
            by_tab[r["_tno"]].add((r["source_file"], r["_tunit"]))
    n = Counter()
    for r in rows:
        if r["unit"] is None:
            cand = {u for f, u in by_row[(r["_tno"], r["row_label"])] if f != r["source_file"]} or \
                   {u for f, u in by_tab[r["_tno"]] if f != r["source_file"]}
            if len(cand) == 1:
                r["unit"] = cand.pop()
                add_dq(r, "unit_from_other_months")
                n[r["source_file"]] += not r["_marker"]
    return n


def stale_repeats(perf):
    """The same actual / previous-year value printed for a different period in an earlier
    report (Export Cargo previous-year Apr-Jun, Apr-Jul and Apr-Sep all 333311; Main Producers
    Sep and Oct both 7388) is a stale copy: flag stale_repeat_of:<first report>:<field>, keep
    the value. Only values with >= 4 significant digits (round numbers repeat by chance)."""
    first, out = {}, defaultdict(list)
    for r in sorted(perf, key=lambda r: r["report_month"]):
        for f in ("actual", "prev_year_actual"):
            x = r[f]
            if not x or len(f"{abs(x):g}".replace(".", "").strip("0")) < 4:
                continue
            k = (r["sector"], r["indicator"], r["period_type"], f, x)
            if k in first and first[k][1] != r["period_end"]:
                add_dq(r, f"stale_repeat_of:{first[k][0]}:{f}")
                out[r["source_file"]].append(f"{r['indicator'][:40]}/{r['period_type']} {f} {x:g} "
                                             f"(also in the {first[k][0]} report)")
            else:
                first.setdefault(k, (r["report_month"], r["period_end"]))
    return out


HL_TITLE = "Infrastructure Sector Performance Highlights"
HL_XCHECK = {"Power (BU)": ("2", "Total")}     # highlights row -> (table no., its total row)


def highlight_xcheck(detail):
    """Highlights achievements must equal the same period's total in the report's own detail
    table (Power = Table 2 'Total', current achievement and previous-year actual). Sep/Oct-25
    print non-renewable generation for 2024/2025 but total generation for 2021-23 (a series
    break, -19.61%): flag the achievement and the % changes built on it, keep the values."""
    ref = {(r["source_file"], r["_tno"], r["row_label"], r["period_start"], r["period_end"]): r["value"]
           for r in detail if r.get("_role") in ("ach", "actual") and r["value"] is not None}
    bad, out = defaultdict(set), defaultdict(list)
    hl = [r for r in detail if (r["table_title"] or "").startswith(HL_TITLE) and r["row_label"] in HL_XCHECK]
    for r in hl:
        tno, lab = HL_XCHECK[r["row_label"]]
        v = ref.get((r["source_file"], tno, lab, r["period_start"], r["period_end"]))
        if r["column_label"].lower().startswith("achievement") and v is not None and \
                abs(v - r["value"]) > max(0.01, abs(v) * 0.005):
            add_dq(r, f"inconsistent_with_table_{tno}")
            bad[(r["source_file"], r["row_label"])].add(r["period_end"])
            out[r["source_file"]].append(f"'{r['row_label']}' {r['period_start']}..{r['period_end']} "
                                         f"{r['value']:g} vs Table {tno} {lab} {v:g}")
    for r in hl:
        pe = r["period_end"]
        if r["column_label"].lower().startswith("percent") and pe and \
                {pe, add_months(pe, -12)} & bad[(r["source_file"], r["row_label"])]:
            add_dq(r, f"inconsistent_with_table_{HL_XCHECK[r['row_label']][0]}")
    return out


def selfcheck():
    assert report_month_from_name("CompleteReviewReportJune2025.pdf") == "2025-06"
    assert report_month_from_name("Review Report Dec 25.pdf") == "2025-12"
    assert report_month_from_name("Review Report Jan26.pdf") == "2026-01"
    assert report_month_from_name("ReviewReportSep25.pdf") == "2025-09"
    assert parse_period("Annual Target 2025- 2026") == ("2025-04", "2026-03")
    assert parse_period("April- July 2024 Actual") == ("2024-04", "2024-07")
    assert parse_period("April,2025-January 2026 Target") == ("2025-04", "2026-01")
    assert parse_period("% Variation Over Target April- January 2026") == ("2025-04", "2026-01")
    assert parse_period("Jul-25 Target") == ("2025-07", "2025-07")
    assert parse_period("July 2024 Actual") == ("2024-07", "2024-07")
    assert parse_period("Achievement (as per units applicable) April - January 2022") == ("2021-04", "2022-01")
    assert not plausible_period(*parse_period("April,2025-July 2026 Target"), "2025-07")   # telecom typo
    assert not plausible_period(*parse_period("April,2024-July 2025 Actual"), "2025-07")  # 16 months
    assert plausible_period("2025-04", "2026-03", "2025-07")
    assert unit_of("I. Production of Finished Steel ('Th Tonnes): Main Producers") == "'000 Tonnes"
    assert unit_of("(b) State PWD and Border Road Organisation (BRO)") is None
    assert join_label("Internationa", "l") == "International"
    assert join_label("North Eastern", "Region") == "North Eastern Region"
    # wrapped numbers inside a narrow cell are re-joined; ordinary small values are not
    spec = {"cols": [{"x0": 40, "x1": 190}, {"x0": 290, "x1": 340}, {"x0": 350, "x1": 400}],
            "x0": 40, "x1": 400, "kind": ["text", "value", "value"]}

    def L(y, ws):
        return {"yc": y, "x0": ws[0][0], "text": " ".join(w[2] for w in ws),
                "words": [(x0, y - 3, x1, y + 3, t) for x0, x1, t in ws]}
    recs = [split_line(L(382, [(295, 339, "11682761"), (355, 399, "11082177")]), spec),
            split_line(L(393, [(172, 214, "Domestic"), (334, 339, "3"), (394, 399, "4")]), spec),
            split_line(L(408, [(42, 80, "Mumbai"), (334, 339, "0"), (390, 399, "12")]), spec)]
    rows = assemble(recs, spec, [], [])
    assert [r["vals"][1][0][4] for r in rows] == ["116827613", "0"], rows
    assert rows[0]["vals"][2][0][4] == "110821774"
    # label-only prefix line joins the next row; a lettered line is a heading
    recs = [split_line(L(100, [(42, 60, "A."), (62, 100, "NITROGEN")]), spec),
            split_line(L(112, [(50, 90, "Cooperative")]), spec),
            split_line(L(124, [(42, 71, "Sector"), (300, 339, "303.90"), (360, 399, "363.20")]), spec)]
    rows = assemble(recs, spec, [], [])
    assert rows[0]["row_label"] == "Cooperative Sector" and rows[0]["row_group"] == "A. NITROGEN", rows
    # values centred on a 3-line label: prefix above, '(Kms.)' tail below; 'V.O.' is not a marker
    recs = [split_line(L(234, [(54, 90, "Widening/"), (93, 144, "Strengthening/")]), spec),
            split_line(L(245, [(54, 72, "weak"), (74, 109, "pavement")]), spec),
            split_line(L(251, [(303, 339, "350.00"), (364, 399, "289.00")]), spec),
            split_line(L(256, [(54, 78, "(Kms.)")]), spec),
            split_line(L(268, [(54, 130, "V.O.Chidambaranar")]), spec),
            split_line(L(280, [(54, 90, "(Tuticorin)"), (300, 339, "3929"), (360, 399, "3545")]), spec)]
    rows = assemble(recs, spec, [], [])
    assert [r["row_label"] for r in rows] == ["Widening/ Strengthening/ weak pavement (Kms.)",
                                             "V.O.Chidambaranar (Tuticorin)"], rows
    assert rows[1]["row_group"] is None
    assert fix_breaks("% Variation Over Actual April,2 024-Januar y 2025") == \
        "% Variation Over Actual April,2024-January 2025"
    # a line holding only a merged-cell '*' is dropped, not read as a '* ...' footnote that
    # ends the body (Jun/Jul Table 48 lost their last rows)
    cells = [(40, 100, 190, 120), (40, 120, 190, 140), (40, 140, 190, 160), (290, 100, 340, 160),
             (350, 100, 400, 120), (350, 120, 400, 140), (350, 140, 400, 160)]
    recs = [split_line(L(110, [(42, 150, "Widening four lanes (Kms.)"), (360, 399, "193.70")]), spec),
            split_line(L(126, [(312, 317, "*")]), spec),
            split_line(L(132, [(42, 150, "Widening two lanes (Kms.)"), (360, 399, "790.90")]), spec),
            split_line(L(150, [(42, 150, "Strengthening (Kms.)"), (360, 399, "94.42")]), spec)]
    for r in recs:
        r["page"] = 1
    merged = []
    recs = drop_merged_cells(recs, {1: cells}, spec, [], merged)
    rows = assemble(recs, spec, [], [])
    assert [r["vals"][2][0][4] for r in rows] == ["193.70", "790.90", "94.42"], rows
    # a title wrapped over three lines, with a dangling 'April-'
    tl = [{"yc": y, "text": t} for y, t in ((383, "Table - 48: Performance of State"),
                                             (395, "PWD and BRO during - April-"), (406, "October 2025"))]
    assert table_title_unit(tl, 420, 370)[0] == \
        "Table - 48: Performance of State PWD and BRO during - April-October 2025"
    assert join_label("(International+Domest", "ic)") == "(International+Domestic)"
    assert not marked("c)") and marked("a) Public Sector")
    print("selfcheck ok")


if __name__ == "__main__":
    selfcheck()
    main()
