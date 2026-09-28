# External data sources

Every file here comes from a public government portal or a published government document, except the synthetic
fixtures in `mock/`. None of them is a model feature: the 2026-09 research backtested the land register, the
PARIVESH state priors and the remark-derived factors and found no measurable lift, so they feed the risk profile, the
External Factors page and the early notice only. The model's land features still read
`land_acquisition_maharashtra.csv` alone (see `LA_MODEL_TABLE` in pipeline/external.py).

How we collected: public pages only, a User-Agent on every request, at most one request per second, and no captcha
solved or bypassed (the Bhoomi Rashi project search, the per-highway report and the PARIVESH 2.0 "Track Your
Proposal" search are captcha-gated, so they were not used). We did not find published terms of use on Bhoomi Rashi,
the PARIVESH 1.0 legacy portal or the PARIVESH 2.0 dashboard. None publishes a machine-readable crawl policy:
forestsclearance.nic.in/robots.txt is empty, parivesh.nic.in/robots.txt returns the application page and
bhoomirashi.gov.in/robots.txt redirects to an error page (checked 2026-09-28). We never store the PARIVESH
"Pending Email" field, e-mail addresses or the names of private individuals; a user agency name is kept only when it
is plainly a government body or PSU.

## Land acquisition

| File | What it is | Source | Retrieved |
|---|---|---|---|
| `land_acquisition_maharashtra.csv` | 347 Maharashtra NH stretches (the original table from the external-factors guide) | [Bhoomi Rashi Highway Register](https://bhoomirashi.gov.in/auth/revamp/RepState.cshtml) | 2026-09 (identical to a fresh pull on 2026-09-27) |
| `land_acquisition_india.csv` | 2,679 stretches of the other 28 states with data (1.49 M parcels), aggregated with pipeline/bhoomi_rashi.py; Arunachal Pradesh and Nagaland return empty tables | [Bhoomi Rashi Highway Register, whole-state export](https://bhoomirashi.gov.in/auth/revamp/RepState.cshtml): a multipart POST to `/auth/revamp/state_register1.cshtml` (EncHid from the page, act=1, type=2, highway_id=state name), no login or captcha | 2026-09-27 |
| `bhoomi_rashi/` | drop folder for raw state exports (not committed; the 29 states total about 731 MB) | same | |
| `bhoomi_rashi_pulls/<date>.csv` | stretches from the scheduled pull (backend/live/portals.py, off unless `BHOOMI_PULL=1`; quarterly, or `POST /api/jobs/bhoomi-pull`): each export is streamed to a temporary file, checked against its Content-Length and for a closing `</table>` (retried once), aggregated, and deleted; `load_land` reads a state from the newest pull that has it | same POST | from the first pull |
| `state_la_friction.csv` | per state: pending land-acquisition dispute cases, hectares acquired through Bhoomi Rashi, NH projects under construction and delayed, plus register statistics (parcels, spans, share of stretches with complexity 3+) | Lok Sabha unstarred questions [163 of 29 Jan 2026](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/187/AU163_5uqS9c.pdf?source=lsapps), [3006 of 6 Aug 2026](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU3006_jMQaRJ.pdf?source=lsapps), [843 of 23 Jul 2026](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU843_Phz3XH.pdf?source=lsapps), [4702 of 21 Aug 2025](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/185/AU4702_2S5DmR.pdf?source=lsapps) and the register above; the `source` column names each column's answer | 2026-09-27 |
| `rail_state_la_status.csv` | Railways land required and acquired by state (Tamil Nadu, Kerala, West Bengal, Karnataka, Telangana) over time | Lok Sabha Railways answers; the `source` column links each PDF (e.g. [USQ 2853 of 5 Aug 2026](https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU2853_bz5BsG.pdf?source=lsapps)) | 2026-09-27 |
| `cag_land_delay_bharatmala.csv` | delay in fixing the appointed date for 62 Bharatmala projects, by cause (right of way alone for 39, right of way and contractor conditions for 19, contractor conditions only for 4) | [CAG Report No. 19 of 2023, para 6.1.1 and Annexure 9](https://cag.gov.in/webroot/uploads/download_audit_report/2023/Report-No.-19-of-203--Bharatmala-English-064d5db7bc63c20.06754442.pdf) | 2026-09-27 |

## Forest clearance

| File | What it is | Source | Retrieved |
|---|---|---|---|
| `parivesh_fc_scenarios.csv` | the Parivesh approval rulebook (28 scenarios: route, authority, gates, complexity) from Garvit's external-factors guide | docs/EXTERNAL_FACTORS_GUIDE.md | 2026-09 |
| `parivesh_fc_proposals_legacy.csv` | 10,025 Form-A proposals **visible in the PARIVESH 1.0 online list, received 2014 to mid-2022; not a census** (it lacks known proposals such as FP/MP/RAIL/41734/2019, holds 42% of the Stage-II approvals Parliament reports for 2014-2024, and its state counts diverge from official receipts) | [PARIVESH 1.0 Online_Status.aspx](https://forestsclearance.nic.in/Online_Status.aspx), paged 30 rows at a time, Road split by state (a query caps at 2,970 rows) | 2026-09-27 |
| `parivesh_fc_timelines_sample.csv` | the date each level received 150 proposals (DFO, CF, nodal, state, RO, Stage-I, compliance, Stage-II); **a sample of proposals that reached Stage-I (148 of 150), so it is conditioned on success**; 94 of 150 are 5 ha or less and 3 are in Maharashtra | [PARIVESH 1.0 timeline.aspx](https://forestsclearance.nic.in/timeline.aspx?pid=FP/MP/RAIL/39172/2019) | 2026-09-27 |
| `parivesh_fc_timelines_remarks.csv` | the timeline pages of proposal numbers named in the report remarks, when the list lacks them (refresh with `python -m pipeline.parivesh timelines <proposal no>`) | same | 2026-09-28 |
| `parivesh2_fc_state_levels_2026-09-27.csv` | PARIVESH 2.0 pendency by state and level (UA, DFO, PSC, DC, CF, nodal, PCCF, Principal Secretary, IRO, MoEFCC, Stage-I, Stage-II, final order, delisted, total; 31,474 proposals) | [PARIVESH 2.0 FC Authority Dashboard](https://parivesh.nic.in/fc-dashboard/FCDashboard.aspx), last updated 27-Sep-2026 02:15 | 2026-09-27 |
| `parivesh2_snapshots/<date>.csv` | the same state x level table, archived once a day by the backend (backend/live/portals.py; `PARIVESH_SNAPSHOT=0` turns it off, `POST /api/jobs/parivesh-snapshot` takes today's now). The dashboard keeps no history, so these files are its only record over time | same dashboard | daily from 2026-09-28 |
| `fc_project_links_reviewed.csv` | 470 project to proposal links kept after a hand review of 1,312 automatic candidates, each with its reason | our review of the list above | 2026-09-28 |
| `fc_norms.csv` | prescribed days to Stage-I and Stage-II by rules, route and area band: FC Rules 2003 as amended 2004, FC Rules 2022 (Schedule II) and the Van (Sanrakshan Evam Samvardhan) Rules 2023 (Schedule I, with the 2025 amendment) | [2004 amendment](https://faolex.fao.org/docs/pdf/ind61558.pdf), [FC Rules 2022](https://cpc.parivesh.nic.in/writereaddata/FCRule2022Notificationdated28062022.pdf), [Van Rules 2023](https://thc.nic.in/Central%20Governmental%20Rules/Van%20(Sanrakshan%20Evam%20Samvardhan)%20Rules,%202023.pdf) | 2026-09-27 |

For comparison with the norms, the Ministry reported an average of 150 days for in-principle approval in 2023-24
([PIB, 5 Aug 2024](https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2041465)); the 2014-2022 legacy
proposals took a median of 16.6 months from submission to Stage-I in the timeline sample.

## Synthetic

`mock/`: Garvit's two mock files, formula fixtures only (see `mock/README.md`). Never model, feature or app input.
