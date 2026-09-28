# External factors research, September 2026

This report sums up the external-factors research of 27-28 September 2026: which public sources we found, what we
took from them, what matched, what did not help prediction and why, and what is still open. It is written for the
team. The details and the code are in docs/EXTERNAL_DATA_CROSSCHECK.md, dataset/raw/external/README.md,
pipeline/external.py, pipeline/parivesh.py, pipeline/hidden_delay.py and backend/live/portals.py.

## Credit

The starting point was Garvit's External Factors guide (docs/EXTERNAL_FACTORS_GUIDE.md). It named the two portals
that matter, Bhoomi Rashi for land acquisition and PARIVESH for forest clearance, and it found the trick that made
this work possible: the Bhoomi Rashi Highway Register can be pulled as one whole-state block, and the ".xls" it
returns is really an HTML table. His guide also set out the Parivesh approval rulebook, the 0-5 land complexity
rule and the composite score, and it said plainly what was still missing: a proposal-level forest tracker and land
data beyond Maharashtra. This research filled most of those gaps and tested his numbers against real projects. His
mock files stayed what they are, formula fixtures: we never trained, calibrated or scored on them.

## In short

- **Land data now covers 29 states, not one.** The whole-state Highway Register was pulled for every state with
  data: 3,026 NH stretches and 1.58 million parcels. Its area tracks what Parliament says was acquired through the
  portal (93% of it, state-level correlation 0.977).
- **Forest clearance is now visible at proposal level.** 10,025 proposals from the PARIVESH 1.0 online list, their
  timeline pages, and a hand review of 1,312 automatic project matches, of which we kept 470 links.
- **None of it improves the model.** Every backtest of the new data as model features came out within noise or
  worse. The data is therefore evidence and display only: the risk-profile checklist, the External Factors page and
  the early notice. The model's inputs did not change.
- **Garvit's guessed delay bands are replaced by measured ones,** each with its number of projects and a 95%
  interval. Most of his bands are not supported; two forest stages show a real but much smaller effect.
- **Two jobs now keep the data fresh:** a daily snapshot of the PARIVESH 2.0 dashboard (its only history) and a
  quarterly Bhoomi Rashi pull, off by default.

## Sources and how we accessed them

We used public government pages only. Every request carried a User-Agent naming the project, we made at most one
request per second, and we never solved or bypassed a captcha: where a search is captcha-gated we left it alone. We
did not find published terms of use on Bhoomi Rashi, the PARIVESH 1.0 legacy portal or the PARIVESH 2.0 dashboard,
and none of them publishes a machine-readable crawl policy (on 28 Sep 2026 forestsclearance.nic.in/robots.txt was
empty, parivesh.nic.in/robots.txt returned the application page and bhoomirashi.gov.in/robots.txt redirected to an
error page). We never store the PARIVESH "Pending Email" field, e-mail addresses or the names of private
individuals; a user agency name is kept only when it is plainly a government body or PSU.

| Source | What we took | Access |
|---|---|---|
| Bhoomi Rashi Highway Register, whole state | parcels by state, NH, chainage, district, village, area and Publish Date, aggregated to stretches | public form, no login or captcha |
| PARIVESH 1.0 online proposal list | 10,025 Form-A proposals received 2014 to mid-2022: state, number, name, category, area, status, Stage-I and Stage-II dates | public search, 30 rows a page, 2,970 rows per query (Road was split by state) |
| PARIVESH 1.0 timeline pages | the date each level received a proposal (150-proposal sample, plus the proposals our remarks name) | public page per proposal; some newer ones redirect to an error page |
| PARIVESH 2.0 FC Authority Dashboard | proposals pending by state and level (31,474 on 27 Sep 2026) | public page, refreshed daily |
| Lok Sabha answers | pending land-dispute cases, hectares acquired through Bhoomi Rashi, delayed NH projects by state; Railways land required and acquired by state | public PDFs on sansad.in |
| CAG Report 19 of 2023 (Bharatmala) | delay in fixing the appointed date for 62 projects, by cause | public PDF |
| FC Rules 2004, FC Rules 2022, Van Rules 2023 (with the 2025 amendment) | prescribed days to Stage-I and Stage-II by route and area band | public PDFs |
| PIB release of 5 Aug 2024 | the Ministry's average of 150 days for in-principle approval in 2023-24 | public page |

Every committed file, with its source link and retrieval date, is listed in dataset/raw/external/README.md. Raw
portal exports are not committed (the 29 Bhoomi Rashi exports alone are about 731 MB); only aggregated tables are.

## What matched

- **Garvit's rulebook side is faithful.** Every mock row that needs forest clearance uses a real scenario, and the
  authority level and complexity equal the rulebook on every row.
- **His land rule reproduces the real scores** on all 347 Maharashtra stretches, and the Maharashtra table in the
  repo is identical to a fresh pull on 27 Sep 2026. A live test pull of Delhi on 28 Sep 2026 also matched the
  committed table stretch for stretch.
- **The register looks like acquired land.** Its area by state is 93% of the area Parliament reports as acquired
  through Bhoomi Rashi (173,964 of 187,623 ha, correlation 0.977), for example Kerala 1,618 against 1,619 ha.
- **The remarks' proposal numbers are real.** All three forest proposal numbers written in our report remarks can
  be looked up. Two show blockers the report numbers never showed: FP/JH/MIN/44804/2020 (Muraidih) had no Stage-I
  76 months after filing, and FP/MP/RAIL/41734/2019 (Katni-Singrauli, 72.8 ha in Sanjay Tiger Reserve) has a DFO
  query from 17 Jan 2023 with no reply and is now noted as withdrawn. The third, FP/MP/RAIL/39172/2019, reached
  Stage-II on 6 Oct 2023.
- **The portal shows forest risk the reports miss.** 173 current projects have a hand-reviewed link to a PARIVESH
  proposal. At July 2026, 36 of them still had one open and 19 were past the rule limit. None of the 36 has an open
  forest event in its report remarks.

## Linking projects to the portals

Neither portal carries our project keys, so every link is a match on names, NH numbers, districts and km ranges.
We measured how often those matches are right before letting any of them rate a project.

**Land.** We hand-checked 100 current links, drawn after the rules were fixed on two earlier samples:

| Link method | Correct | Precision (Wilson 95% CI) | Used as |
|---|---|---|---|
| NH number and km range in the name (`nh_chainage`) | 21 of 25 | 84% (65-94%) | flagged or clear |
| NH number and a district in the name (`nh_district`) | 16 of 25 | 64% (45-80%) | possible only |
| NH number alone (`nh_only`) | 16 of 50 | 32% (21-46%) | possible only |

Only the km match rates a project. Of the 1,763 current projects, 412 are rated on it (135 flagged at complexity 4
or more, 277 clear) in 28 states, and 133 more have only a possible link (58 on the NH and a district, 75 on the NH
alone), which is shown but never flagged. Most of the rest are not road projects (771) or have no NH number in the
name (210). Before this work, 58 current projects were linked, all in Maharashtra.

**Forest.** An automatic matcher proposed 1,312 project-proposal pairs for 656 projects. We reviewed all of them by
hand and kept 470 links (396 projects, 376 proposals), each with its reason, in
dataset/raw/external/fc_project_links_reviewed.csv. 394 are specific (the same named section, km, package, mine or
line) and 76 are softer (a corridor-wide proposal, ancillary works, a mine proposal that names no phase). Our own
precision estimate is about 95% for the specific links and 70-80% for the softer ones; that is a self-check by the
reviewer, not an independent audit.

## What did not help prediction, and why

We tested every new source as model features on the repo's own backtest folds (three seeds, paired project
bootstrap), on the validation block and on the recent flash block.

- **Remark-derived features** (forest stage, land share, land step, cost causes, 14 features in all) changed
  validation PR-AUC by -0.003 to +0.001, inside seed noise (SD 0.001 to 0.004). At cutoffs that still have remark
  text the changes were within ±0.0026, and a target encoding of expected delay was significantly worse at four
  quarters (-0.0024, CI -0.0039 to -0.0011).
- **The all-state land table** changed PR-AUC by -0.004 to +0.003 on every target. Two results were significantly
  negative: flash-block slip within two quarters -0.0057 (CI -0.0096 to -0.0021) and roads-only four-quarter slip
  in validation -0.0036 (CI -0.0068 to -0.0003).
- **A PARIVESH state prior** (the share of a state's proposals reaching Stage-I within a year) made validation
  worse, -0.0059 (CI -0.0112 to -0.0008), and the flash block too, -0.0066 (CI -0.0114 to -0.0012).

The reasons are coverage and time, not bad data:

- **Land notifications are recent.** Most Bhoomi Rashi notifications date from after 2018, so only 13.2% of the
  pre-2023 road rows the model trains on have a linked stretch, and only 1.6% have complexity 4 or more. The model
  cannot learn from a feature that barely exists in training.
- **Report remarks stop in 2023-Q2.** Later reports print templates ("start: 2023-12"), not free text. So remark
  features reach only 50-67 rows per cutoff out of about 1,400, and at July 2026 the 67 current projects the remark
  rule still counts as open are all at least three years stale. The app now labels every remark-derived status with
  its as-of quarter and treats none of them as open today.
- **Effects did not repeat across eras.** The Stage-I effect seen in 2014-2023 did not show in the 2022-24 folds,
  and the state prior most likely acts as a drifting proxy for state and time.
- **The raw associations are confounded.** Projects with open land or forest remarks already carry far-out dates,
  so they slip less in the raw numbers; within the same months-to-deadline band they slip more. About half of the
  land-complexity association in the first analysis was this deadline effect.

So the model keeps its old external inputs. The gold land features still read the Maharashtra table with the old
link (the file is byte-identical), the gold version and the champion models are unchanged, and none of the new
tables is a feature.

## Measured priors in place of Garvit's bands

Garvit's mock gives each forest-clearance status and each land share a hidden delay in months. Those numbers were
guesses, and the mock outcomes were built from them. We measured the same groups on real projects
(pipeline/hidden_delay.py, dataset/gold/hidden_delay_priors.parquet): for every labelled key-quarter from 2014, the
extra months the anticipated completion moved over the next four quarters and the extra chance of a push of three
months or more, against matched projects with no forest or land mention (same sector and year for remark groups,
same months-to-deadline band for land complexity). Intervals are 95% project-cluster bootstrap intervals; groups
with fewer than 15 projects are not measured.

| Group | Garvit's band (months) | Projects | Extra push, next year (months) | Extra date-push risk (points) |
|---|---|---|---|---|
| Pending at state level | 15-32 | 53 | +0.1 (-2.7 to +3.2) | -5 (-16 to +6) |
| Pending at FAC / MoEFCC | 28-63 | 13 | too few to measure | too few to measure |
| Stage-I granted, awaiting Stage-II | 4-20 | 38 | +2.5 (+0.5 to +4.3) | +19 (+7 to +30) |
| Stage-II or final approval | 0-16 | 28 | +3.0 (-1.2 to +8.5) | +16 (+1 to +31) |
| Forest clearance awaited, no stage named | 15-32 | 105 | +1.5 (-0.7 to +3.5) | +12 (+4 to +21) |
| Land 50-80% acquired | about 12-29 | 31 | +1.1 (-2.4 to +4.7) | +4 (-10 to +16) |
| Land 80-95% acquired | about 3-12 | 24 | +0.3 (-3.3 to +4.2) | -5 (-20 to +8) |
| Land complexity 4-5, km-matched stretch | none (factor only) | 69 | -1.2 (-3.3 to +0.5) | +3 (-6 to +11) |
| Land complexity 4-5, NH or district link | none (factor only) | 184 | +0.3 (-0.8 to +1.1) | +6 (+1 to +11) |

The full table, with every group, is in docs/EXTERNAL_DATA_CROSSCHECK.md. What it says:

- Garvit's order and sizes are not supported. His numbers are a total hidden delay and ours are the extra slip over
  the next year, so they are not the same quantity, but no group comes near his bands.
- The clearest forest signal is Stage-I granted and Stage-II still awaited: about 2.5 extra months and 19 points
  more date-push risk. "Forest clearance awaited" with no stage adds 12 points. The groups were chosen after
  looking at the data, so these are exploratory; after a Holm correction over all groups and both outcomes only
  "awaited" stays below 0.05.
- Land share has no measurable effect in any band. His 0.59 months per point of land still to acquire is not
  supported; the real slope is 0.00 to 0.19 months per point.
- The land-complexity effect depends on the link. On the looser NH or district links it reproduces the earlier
  analysis (+6 points), but those links were right only 32-64% of the time; on the km-matched links the checklist
  rates, the estimate is +3 points with an interval that spans zero.
- The earlier research reported +7 months for FAC / MoEFCC on 16 projects. Counting only rows with a four-quarter
  label leaves 13 projects, so we show it as too few to measure.

The checklist now prints the matching line next to each project's forest and land rows, with the quarter the stage
or share is as of, and projects linked to PARIVESH also get the portal stage and the rule limit.

## Norms against reality

The 2004 rules, which governed the 2014-2022 proposals, allowed about 255 days to Stage-I for 40 ha or less and 300
days above that. In our 150-proposal timeline sample the median from submission to Stage-I was 16.6 months, and 69%
of that time was spent in the state machinery. That sample only holds proposals that reached Stage-I, so it
understates the delay. The Ministry reports a much faster 150 days on average for 2023-24, under the new rules, so
2014-2022 durations should not be applied to proposals filed after mid-2022.

On land, MoRTH rules stop an NH project being awarded before 80-90% of its land is in hand (by contract type), and
of the 62 Bharatmala projects the CAG found with a delayed appointed date, land alone was the cause for 39 (median
about 3.3 months, up to 31 months). The long tail is disputes over the last few percent of land, not a straight line in the share still to acquire, which
is why a land share in the remarks tells us little.

## Keeping the data fresh

Two backend jobs now run in the in-process scheduler (backend/live/portals.py):

- **PARIVESH snapshot, daily.** It archives the dashboard's state x level table to
  dataset/raw/external/parivesh2_snapshots/<date>.csv. The dashboard keeps no history, so these snapshots are the
  only way to build one. The first was taken on 28 Sep 2026 (31,477 proposals). Turn it off with
  `PARIVESH_SNAPSHOT=0`.
- **Bhoomi Rashi pull, quarterly, off by default.** With `BHOOMI_PULL=1` it pulls every state once a quarter, checks
  each export against its Content-Length and for a closing `</table>` (the Haryana export was once cut at 15.9 of
  51.0 MB and still parsed), retries a cut export once, and keeps only the aggregated stretches in
  dataset/raw/external/bhoomi_rashi_pulls/<date>.csv. The land step then reads each state from its newest pull.

Both write a row to the job log, can be started by an IPMD analyst from the API, and are tested on canned pages
with no network.

## Open gaps

- **Captcha-gated searches.** The Bhoomi Rashi project search (3a, 3A and 3D dates per project, compensation) and
  per-highway report, and the PARIVESH 2.0 "Track Your Proposal" search, need a captcha. We did not automate them.
  A real 3A-to-3D lag per project would need a person to query them, or e-Gazette searches.
- **PARIVESH 2.0 history exists only from now.** The dashboard keeps no past states, so any feature built on it
  cannot be backtested until snapshots have piled up. Its public proposal drilldown (proposals filed after June 2022,
  with submission, acceptance and approval dates and the prescribed and elapsed days) was tested on two Maharashtra
  pages only; ingesting it fully is about 1,600 pages.
- **The PARIVESH 1.0 list is not a census.** It lacks a known proposal (FP/MP/RAIL/41734/2019), holds only 42% of
  the Stage-II approvals Parliament reports for 2014-2024, diverges from official state receipts (Uttarakhand 189
  in the list against 860 officially, Gujarat 834 against 366) and effectively ends in mid-2022. We show its numbers as "proposals visible
  in the list", never as state totals.
- **The meaning of the Bhoomi Rashi Publish Date is unverified.** The portal does not say whether it is the 3A or
  the 3D notification date. The area match suggests acquired (3D) land, so we describe the notification span as
  staggered notification, not as a 3A-to-3D lag.
- **Forest stages at FAC / MoEFCC** have too few labelled projects to measure (13).
- **Compensation and possession status** is not in the register; only report remarks carry it, and they stop in
  2023-Q2.
- **Secondary or unreachable sources.** The NHAI circular on a 336-day land-acquisition timeline was found only in
  law-firm and news summaries, and the DoLR land-acquisition information system did not respond.
- **Terms of use** were not found for any of the three portals (see above). The jobs stay polite, but a person should
  confirm with the portal owners before the pull runs on a schedule.
- **Not taken from Garvit's guide on purpose:** the state fragmentation factors, the mock land rows outside
  Maharashtra, the fabricated outcomes, and the GatiShakti part of the composite (no real GatiShakti layers yet).

## Source links

- Bhoomi Rashi Highway Register (whole state): https://bhoomirashi.gov.in/auth/revamp/RepState.cshtml
- Bhoomi Rashi project search (captcha): https://bhoomirashi.gov.in/auth/revamp/search_proj.cshtml
- PARIVESH 1.0 online proposal list: https://forestsclearance.nic.in/Online_Status.aspx
- PARIVESH 1.0 timeline page (example): https://forestsclearance.nic.in/timeline.aspx?pid=FP/MP/RAIL/39172/2019
- PARIVESH 2.0 FC Authority Dashboard: https://parivesh.nic.in/fc-dashboard/FCDashboard.aspx
- PARIVESH 2.0 proposal drilldown (example): https://parivesh.nic.in/fc-dashboard/FC_Dashboard_Proposals.aspx?Approval2=YES&State=MAHARASHTRA
- PARIVESH 2.0 Track Your Proposal (captcha): https://parivesh.nic.in/newupgrade/#/trackYourProposal/V1
- Lok Sabha USQ 163 of 29 Jan 2026: https://sansad.in/getFile/lsapps/loksabhaquestions/annex/187/AU163_5uqS9c.pdf?source=lsapps
- Lok Sabha USQ 3006 of 6 Aug 2026: https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU3006_jMQaRJ.pdf?source=lsapps
- Lok Sabha USQ 843 of 23 Jul 2026: https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU843_Phz3XH.pdf?source=lsapps
- Lok Sabha USQ 4702 of 21 Aug 2025: https://sansad.in/getFile/lsapps/loksabhaquestions/annex/185/AU4702_2S5DmR.pdf?source=lsapps
- Lok Sabha USQ 2853 of 5 Aug 2026 (Railways): https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU2853_bz5BsG.pdf?source=lsapps
- CAG Report 19 of 2023 (Bharatmala): https://cag.gov.in/webroot/uploads/download_audit_report/2023/Report-No.-19-of-203--Bharatmala-English-064d5db7bc63c20.06754442.pdf
- FC Rules 2003 as amended 2004: https://faolex.fao.org/docs/pdf/ind61558.pdf
- FC Rules 2022: https://cpc.parivesh.nic.in/writereaddata/FCRule2022Notificationdated28062022.pdf
- Van (Sanrakshan Evam Samvardhan) Rules 2023: https://thc.nic.in/Central%20Governmental%20Rules/Van%20(Sanrakshan%20Evam%20Samvardhan)%20Rules,%202023.pdf
- PIB, 5 Aug 2024 (150 days in 2023-24): https://www.pib.gov.in/PressReleaseIframePage.aspx?PRID=2041465
- MoRTH land and forest milestones circular of 6 May 2025: https://bhoomirashi.gov.in/WriteReadData/whatsNew/File85301.pdf
- NHAI 336-day circular, secondary summary only: https://foxmandal.in/News/nhai-publishes-timeline-to-streamlines-land-acquisition-activities/
