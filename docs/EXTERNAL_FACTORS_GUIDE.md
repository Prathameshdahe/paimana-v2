Author: Garvit (team). Imported Sep 2026; see docs/EXTERNAL_DATA_CROSSCHECK.md for the cross-check against real data.

# External Factors — Land Acquisition & Forest Clearance Data Guide

This document compiles research, extraction steps, and dataset structures for the **External Factor tab** of the PAIMANA time/cost overrun prediction model. External Factors currently covers two hidden-cause variables: **Land Acquisition (LA)** and **Forest Clearance (FC)**. It replaces the earlier draft, which covered LA only and contained inaccuracies corrected below (see §6).

---

## 1. Core Portals & Access

### A. PARIVESH Portal (Environmental Hub)
- **Entity:** [Ministry of Environment, Forest and Climate Change (MoEFCC)](https://parivesh.nic.in/)
- **Data footprint:** Environmental (EC), Forest (FC), Wildlife (WL), Coastal Regulation Zone (CRZ) clearances.
- **Two distinct data types — do not conflate them:**
  1. **Scenario Sheet (rulebook)** — a static routing-logic table: given a proposal's violation status, shape, Form (A–H), area, and category, it maps to an approving authority tier and which review gates (PSC/REC/FAC/site inspection) apply. National scope, no state field, ~27 fixed scenarios. This is what we currently have (`fc_scenario_dataset.csv`), extractable as `.xlsx`/`.pdf` from the public dashboard, no login required.
  2. **Proposal Tracker (project-level records)** — the actual case-by-case FC applications: proposal ID, project name, state/district, application date, area diverted, category, current stage, approval/rejection date, live status. **This is what's still missing** and is required to know how long any *real* project's FC case actually took. Not yet extracted.
- For GIS boundaries, PARIVESH 2.0 supports `.kml` layer downloads per clearance.

### B. Bhoomi Rashi Portal (Land Acquisition Register)
- **Entity:** [Ministry of Road Transport & Highways (MoRTH)](https://bhoomirashi.gov.in/)
- **Data footprint:** State-sponsored land acquisition for National Highway networks; links revenue survey records to compensation payout pipelines.
- **Bulk extraction:** the [Highway Register](https://bhoomirashi.gov.in/auth/revamp/RepState.cshtml) can be pulled as a single whole-state block, bypassing the district-by-district / agency-by-agency drill-down UI.
- **Format gotcha:** the exported file is served with an `.xls` extension but is actually a **raw HTML table**, not a binary Excel file. `pd.read_excel()` will fail on it — must be parsed with `pd.read_html()` (see corrected code, §5).
- **Current coverage: Maharashtra only.** One state-wide extraction obtained so far — **not** a single-district file (corrected from earlier draft, see §6). To go national, this same whole-state pull needs repeating for every other state in scope.

### C. PM GatiShakti National Master Plan (NMP)
- Integrates GIS layers across central infrastructure/logistics ministries.
- Private orgs can register on the [PM GatiShakti UGI Portal](https://ugi.pmgatishakti.gov.in/home/) to pull approved, non-sensitive spatial layers.
- **Status: not yet explored in this pipeline** — flagged here as a candidate source for a future third External Factor (e.g. right-of-way conflicts across ministries), not yet integrated or tested.

---

## 2. Forest Clearance — Scenario Sheet Schema

Extracted into `fc_scenario_dataset.csv`, 27 rows, one per MoEFCC scenario. Fields:

| Field | Meaning |
|---|---|
| `scenario_id` | Scenario code (e.g. `2_main`, `5_violation`, `exempt_def_10ha`) |
| `violation` | Whether the proposal involves a violation (encroachment before/after clearance) |
| `shape`, `form`, `area_ha_condition`, `project_category` | Eligibility conditions that route a proposal to this scenario |
| `approving_authority` / `authority_level` | Ordinal 1 (DFO) → 4 (Ministry/MoEFCC) — proxy for how many organizational layers a case must clear |
| `psc_required`, `rec_required`, `fac_required`, `site_inspection_required` | Binary review-gate flags |
| `complexity_score` | Sum of authority_level + review gates — single delay-risk proxy, range 1–7 |
| `notes` | Assumptions where the source PDF was ambiguous (violation branches especially — flagged lower-confidence) |

Two sub-tracks exist inside the same scenario logic: a lighter **Survey/Amendment track** (gated by felling/borehole/shot-hole counts, not area) and an **Exempted-category fast-track** for defence and 12 listed public-utility project types, which skips PSC and culminates at DFO/State level unless violated.

---

## 3. Land Acquisition — Revenue Register Schema

Raw Bhoomi Rashi export fields (Maharashtra, ~89,950 parcel rows, 90 highways, 34 districts, dated 2005–2025):

1. **State / District / Sub-District / Village** — hierarchical geography, but only populated on the *first* row of each highway/chainage group; every subsequent row is blank and must be forward-filled.
2. **Highway Name & Chainage** — asset identifier + km range (e.g. `0.000 - 27.970`).
3. **Survey No** — individual revenue parcel identifier.
4. **Area (ha)** — parcel size.
5. **Publish Date** — Section-3 gazette notification date. **This is not the possession/handover date** — it only marks when the acquisition intent was legally published, not when land actually changed hands or compensation was settled.

### Engineered feature table (`land_acquisition_dataset.csv`, one row per Highway+Chainage stretch)

| Feature | Extraction source | Predictive value |
|---|---|---|
| `num_parcels`, `parcels_per_km` | `Survey No` count per stretch | Ownership fragmentation — more parcels ≈ more individual negotiations/litigation risk |
| `total_area_ha`, `area_ha_per_km` | Sum of `Area` | Acquisition scale/intensity |
| `num_districts`, `num_subdistricts`, `num_villages` | Distinct geography touched | Coordination overhead across jurisdictions |
| `first_notif_date`, `last_notif_date`, `notif_span_days` | `Publish Date` range | **Staggered-acquisition proxy** — wide spread signals a fragmented, slow-rolling process (real example: Highway 3, chainage 470.8–539.0 spans 5,391 days) |
| `acquisition_complexity_score` | Composite of the above (multi-district, span≥1yr, span≥3yr, ≥200 parcels, ≥20 ha) | Single 0–5 delay-risk proxy, mirrors FC's `complexity_score` |

---

## 4. Composite External Factor & Mock Bootstrap

Because neither FC proposal-level data nor multi-state LA data exists yet, a **synthetic bootstrap dataset** (`external_factor_mock_dataset.csv`) was built to unblock model development ahead of the submission deadline:

- Each mock project independently draws an FC profile (sampled from the real 27-scenario rulebook, applicable nationwide) and an LA profile (sampled from real Maharashtra parcel/stretch patterns).
- `external_factor_composite_score` = 0.5 × (FC complexity ÷ 7) + 0.5 × (LA complexity ÷ 5).
- LA figures are scaled by a **per-state fragmentation factor** (e.g. Bihar 1.5×, UP 1.35×, Maharashtra 1.0× baseline, Rajasthan 0.85×) so mock projects outside Maharashtra aren't clones of it — this factor is a guessed placeholder, not measured.
- The overrun target (`actual_time_overrun_days`, `overrun_flag`) is fabricated but deliberately correlated to the composite score (r ≈ 0.88) so the pipeline has a learnable signal for the demo.
- **Must be disclosed as synthetic** in any submission — real project outcomes are not yet linked in.

---

## 5. Preprocessing Pipeline (corrected)

The original draft's ingestion code had two bugs: it used `pd.read_excel()` on a file that is actually HTML, and used the deprecated `fillna(method=...)` syntax. Corrected version, extended with chainage parsing and stretch-level aggregation:

```python
import pandas as pd
import numpy as np

def clean_land_acquisition(file_path):
    # File is HTML with an .xls extension — NOT a binary Excel file
    df = pd.read_html(file_path)[0]
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)

    # Forward-fill grouping columns (blank on all but the first row of each group)
    fill_cols = ['State', 'Highway Name', 'Chainage', 'District', 'Sub District', 'Village']
    df[fill_cols] = df[fill_cols].ffill()

    df['Area'] = pd.to_numeric(df['Area'], errors='coerce')
    df['Publish Date'] = pd.to_datetime(df['Publish Date'], format='%d/%m/%Y', errors='coerce')

    # Split chainage into numeric start/end km
    ch = df['Chainage'].str.split(' - ', expand=True)
    df['chainage_start_km'] = pd.to_numeric(ch[0], errors='coerce')
    df['chainage_end_km'] = pd.to_numeric(ch[1], errors='coerce')

    return df

def aggregate_to_stretch_features(df):
    agg = df.groupby(['Highway Name', 'Chainage'], dropna=False).agg(
        num_parcels=('Survey No', 'count'),
        total_area_ha=('Area', 'sum'),
        num_districts=('District', 'nunique'),
        first_notif=('Publish Date', 'min'),
        last_notif=('Publish Date', 'max'),
    ).reset_index()
    agg['notif_span_days'] = (agg['last_notif'] - agg['first_notif']).dt.days
    return agg
```

---

## 6. Corrections to the Prior Draft

| Prior claim | Correction |
|---|---|
| "Ahmednagar District, Maharashtra Master Register" | The extraction is a **whole-state** Maharashtra register (90 highways, 34 districts), not limited to Ahmednagar district. Ahmednagar is one of the 34 districts present, not the scope of the file. |
| `pd.read_excel(file_path)` | File is HTML-formatted despite the `.xls` extension; must use `pd.read_html()`. |
| `.fillna(method='ffill')` | Deprecated pandas syntax; use `.ffill()`. |
| No mention of Forest Clearance | FC is an equal-weight External Factor alongside LA — added in full (§2). |
| No mention of the PARIVESH Proposal Tracker gap | The Scenario Sheet is rulebook logic only, not project records — added as an explicit open gap (§1A). |
| No mention of the project↔asset crosswalk gap | Neither FC nor LA data carries a PAIMANA project ID — LA links only via Highway Name + Chainage, FC has no linking key at all. A crosswalk from PAIMANA's project master list to these identifiers is still required and does not yet exist. |
| `Publish Date` framed as a general "temporal velocity" milestone | Clarified: it is specifically the *gazette notification* date, not land possession or compensation-settlement date — a proxy for delay, not a ground-truth duration. |

---

## 7. Open Gaps (as of this draft)

- **PARIVESH Proposal Tracker** — real FC application-level records not yet obtained.
- **Multi-state Bhoomi Rashi exports** — LA data exists for Maharashtra only; national coverage requires repeating the same whole-state pull per state.
- **Project↔FC↔LA crosswalk** — no shared identifier yet links PAIMANA project records to FC proposals or LA highway/chainage stretches.
- **Compensation/possession data** — Bhoomi Rashi's notification date is a proxy; actual dispute/disbursement status (the more common real-world delay driver) is not captured in the current schema.
- **PM GatiShakti integration** — identified as a candidate source, not yet explored.

---

## 8. Use Case Applications

- **Logistics & Supply Chain:** Combine LA acquisition velocity with active route corridors to flag construction delay margins.
- **ESG Compliance:** Cross-reference high-volume acquisition areas against FC-flagged forest/water-line proximity to estimate encroachment footprint.
- **Portfolio Risk Scoring:** Use `external_factor_composite_score` to rank projects by combined FC+LA delay exposure before construction even begins.
