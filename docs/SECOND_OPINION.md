# Second opinion

The second opinion is the local LLM's reading of one project's evidence, shown to officials next to the model's
tier. It answers one question: given what the reports, the portals, the web research and the news say about this
project now, how concerned should an officer be? It is a checked, cited summary of the evidence, not a prediction.

Code: `llm/second_opinion.py` (evidence pack, prompt, checks, cache), `backend/live/opinions.py` (the nightly job),
`backend/db.py` (`second_opinions` table), `GET /api/projects/{key}/second-opinion` and
`POST /api/jobs/second-opinion` in `backend/routes.py`, schemas `SecondOpinionOut`, `SecondOpinionNone`,
`SecondOpinionRejected`, `SecondOpinionUnavailable` in `backend/schemas.py`. Tests: `tests/test_second_opinion*.py`.

## What it gives

| Field | Meaning |
|---|---|
| `concern` | `none`, `watch` or `concern`. |
| `headline` | At most 15 words (the prompt asks for 12). |
| `narrative` | At most 90 words (the prompt asks for 60), with a citation `[E4]` after each claim. |
| `keyEvidence` | The 1 to 3 items that decide the concern. |
| `gaps` | Up to 3 short notes on what the evidence does not show. |
| `vsModel` | `agrees`, `higher` or `lower`: the concern against the tier's level. Critical and High count as `concern`, Medium and the Watch tier as `watch`, Low as `none` (`modelLevel`). Computed, not asked of the LLM. |
| `cited` | The ids the narrative cites. Citations are stored in one form, `[E1, E2]` (the model's `[e1; e2]` or `[ E5 ]` are accepted and rewritten), so the UI's chip parser and the chat's strip see the same text. |
| `evidence` | Every item of the pack, with its id, kind, date, direction, severity, stale flag, source, text and (research facts and headlines) `url`. The LLM read the items whose direction is not `context` (all of them when the pack is nothing but context). The UI lists the cited ones. |
| `nEvidenceRead` | How many of the `evidence` items the LLM read: the count to show, since `evidence` also holds the context items it never saw. |
| `tier`, `modelVersion`, `asof` | The rating it was set against. |
| `evidenceHash`, `model`, `promptVersion`, `generatedAt`, `cached` | Which evidence, LLM and prompt produced it, when, and whether it came from the store. |
| `attempts`, `nNumbersChecked`, `llmMs` | 1 or 2 asks, how many numbers and dates were checked, LLM time. |

## What it never does

- **It never changes the tier.** It does not touch the probabilities, the checklist, the early notice or the alert
  feed, and it raises no alert.
- **It sends nothing.** There is no memo, message or approval step. It is text on the page.
- **The public never sees it.** The route needs `insights` (officials only); a scoped official gets 404 outside
  the scope.
- **The chat never generates one.** The chat reads `second_opinion.cached(key)` only.
- **It never reads a source.** It reads our one-line summaries of the sources (report remarks, portal lines, research
  summaries, headlines).
- **It is not anchored to the tier.** The LLM does not see the model's rating (see the prompt, below).

## The evidence pack

`pack(key)` builds items `E1..En`, sorted into five groups:

1. **Current hold-ups**: negative, recent, severity 2 or 3. Only observed items: a report or checklist finding, an
   overdue PARIVESH proposal, a web research fact, a headline the research agent judged about the project.
2. **Minor current issues**: negative, severity 1, including the risk ratings (a land complexity rating, the forest
   rulebook's estimate) and headlines nobody has judged.
3. **Progress and neutral items** (recent).
4. **Old items**: dated over a year before the reports, or marked resolved; not known to be solved either.
5. **Context**: the latest report (status line), the model's rating and the web research summary. Never grounds for a
   concern.

| Kind | Source | Notes |
|---|---|---|
| `status` | The latest CUF row | Progress, cost against the original, spend, completion against the schedule, slip so far, share of the planned time elapsed. Context. |
| `model` | Scores | Tier and probabilities (ranking scores, not frequencies). Context. |
| `check` | Flagged checklist rows (`ml/risk_profile.py`) | Leaves out the model's own two rows, the composite, rows another item already states (PARIVESH, land register, web research), and sector headwind and agency optimism (the sector's and the agency's record, not the project's). At most 6. The forest rulebook's estimate ("high clearance complexity expected", source `parivesh_rules`) is severity 1, and is left out when PARIVESH lists the project's proposals. |
| `parivesh` | PARIVESH proposals at asof | Stage, months in it, the rule limit, overdue. |
| `land` | Bhoomi Rashi rating | Flagged, possible or clear. An unknown rating is left out. Flagged means acquisition complexity 4 or more of 5 over the notifications: a rating, not a reported hold-up, so severity 1. |
| `event` | Open report-remark events | At most 4. Remarks are free text only up to 2023, so an event not mentioned in the last 4 quarters is old. |
| `research` | Web research (sweep and research agent) | The latest status line (context), then at most 6 facts, live blockers first. A negative fact that is not live is old, and so is progress older than 4 quarters. |
| `news` | Scout headlines of severity 2 or more | At most 3. Keyword-classified and unverified. Leaves out items the research agent judged not about the project, items already turned into a fact, and headlines that name a private person. Severity 1 unless the research agent judged the item about the project: the scout's severity is a negative word in a headline. |

All outside text is cut to one clean line at a word boundary (at most 240 characters), `|` and the prompt's quote
markers are blanked out of it, and it goes into the prompt between `<<<EVIDENCE` and `EVIDENCE>>>` as quoted data,
never as instructions.

`evidenceHash` is the sha256 of the pack's canonical JSON: the asof, the model version and every item, context
included. A new report, a new research fact or a new headline makes a new hash, so the opinion is asked again. Nothing
in the pack depends on the clock.

## The prompt

- The LLM sees groups 1 to 4 only. The context items stay in the pack (for the officer, the API and the hash) but are
  left out of the prompt whenever there is other evidence (`citable()`). In tuning, given the context, the LLM closed
  its narrative with a sentence restating the status line or the rating and misread it (a "significant cost overrun"
  on a project whose cost had not changed; "on track for March 2027" when the item said that target was at risk). Told
  not to, it restated it anyway; shown the context without ids, it cited it as `[status, model]`. A project with
  nothing but context is shown the context with ids, so its narrative can cite something.
- The user message names the levels the evidence allows (see the checks) and, when there are current hold-ups, their
  ids: "Current hold-ups: E1, E2. The concern is 'concern' unless the items say every one of them has been solved or
  is being solved; a 'watch' cites each of them and the item that says so." With the rule alone, the LLM answered
  `watch` on High and Critical projects whose hold-ups no item said were being solved, reading progress elsewhere as
  an offset.
- The rules: the narrative first, then the concern decided from it; each claim says only what its cited items say (no
  joining items, no forecast dates); no description of the overall progress, cost or rating (the officer sees them);
  only numbers and dates written in the items, in digits; no advice; no names of people, officials by office.
- One compact JSON line, `max_tokens` 300, temperature 0.1. About 1,000 to 1,250 prompt tokens on the richest packs.

## How it is checked

A reply is rejected unless all of these hold:

- **Citations:** every cited id (narrative, headline, key evidence, gaps) is one the prompt showed, the narrative
  cites at least one, and it cites only as `[E4]` or `[E4, E7]` (not `[status]` or `[none]`; a bracket that is part of
  the project's name is allowed). An id outside a citation ("E42 says", "(E7)") is rejected unless the project name or
  a shown item writes it.
- **Numbers and dates:** every number and date in the headline, narrative and gaps is in the items the prompt showed
  (`backend.brief.validate` against the project name and those items, citations taken out first). A figure from the
  context the LLM never saw is rejected: the status line's progress or months late, or a model probability, as is or
  as a percent (0.91 as "91%"). A number in words ("three") is rejected unless an item uses the same word.
- **Numbers where they are cited:** each number and date in a narrative claim must be in the items that claim cites.
  The claim is the text before a citation, from the start of its sentence, plus the rest of the sentence after its
  last citation. "The stretch is 83% done [E7]" is rejected when only E2 says 83%, and so is "overdue [E7], with 83%
  done".
- **Privacy:** no honorific plus a person's name (`pipeline.research.private_names`).
- **Concern fits the evidence** (`allowed()`):
  - a current hold-up allows `watch` or `concern`, never `none`;
  - only minor or old issues allow `none` or `watch`;
  - nothing negative allows only `none`;
  - `concern` must cite a current negative item of severity 2 or 3;
  - `watch` must cite a negative item and, when there are current hold-ups, each of them (it says each is being
    solved; a `watch` citing a minor item and some progress, without a word on the hold-ups, is rejected).
- **Lengths:** headline, narrative and each gap within their limits. More than 3 gaps are cut to 3, and an empty key
  evidence list is filled with the narrative's citations. Neither adds content.

A rejected reply is asked again once: the same prompt with the reasons appended, at temperature 0.3. (Given the
rejected reply as the assistant's turn, at 0.1, the model sent it back unchanged.) A person asking holds the LLM
through the retry; the nightly job lets it go between the two asks, so a chat answer waiting for the LLM goes first.
A second rejection is stored as rejected and returned with its reasons. A rejection never replaces an accepted
opinion: when a newer prompt's reply is rejected for evidence that already has an accepted opinion, the rejection is
noted on that row (`last_rejected`: prompt version, time, reasons). Either way the nightly job does not ask again
until the evidence or the prompt version changes. A stored opinion is checked again when it is read, and by the
nightly job, so an opinion that a tightened check would reject is asked again.

What the checks cannot catch: a claim that misreads its cited item without a wrong number ("the utility hold-up
remains unresolved" when the item says work on it is in progress; "overdue by 75.7 months" when the item says 75.7
months in the stage against a limit of 9.9). The checks bound the ids, the numbers and the level, not the reasoning.
That is why the evaluation below includes a human review.

## API and job

**`GET /api/projects/{key}/second-opinion`** (officials, `insights`)

| Case | HTTP | Body |
|---|---|---|
| Accepted, generated now or stored for the current evidence | 200 | `SecondOpinionOut` (`status: 'ok'`, fields above) |
| Both replies failed the checks | 422 | `SecondOpinionRejected {status: 'rejected', key, reasons, attempts, llmMs}` |
| LM Studio unreachable, too slow, or busy | 503 | `SecondOpinionUnavailable {status: 'llm_unavailable', detail, busy, down}`: `down` true when the connection was refused (start LM Studio; remembered 30 s), `busy` true when the gate stayed taken, neither when LM Studio is up but slow or erring (`detail` says, e.g. no model loaded) |
| Not in the scored portfolio, or outside the viewer's scope | 404 | `{detail}` |
| Public viewer | 403 | `{detail}` |
| `?cached=1` and no accepted opinion for the current evidence | 200 | `SecondOpinionNone {status: 'none', key, detail}` |

- On demand it takes about 20 to 40 seconds (up to about 1 minute with the retry) when LM Studio is free.
- `?cached=1` never generates: the stored opinion, or `status: 'none'`.
- A person asking takes the LLM gate as a chat request, so background jobs let it go first; it waits at most 90 s for
  the gate (`busy: true` after that). An LM Studio that refuses connections is remembered for 30 s through the
  client's breaker, shared with the chat and the brief, so the next ask returns at once (`down: true`); a slow answer
  does not trip it.

**`llm.second_opinion.cached(key)`** returns the same dict as the 200 body (snake_case keys, `cached: True`) for the
current evidence, or `None` (no accepted opinion, or not scored). It makes no LLM call.

**`POST /api/jobs/second-opinion[?project_key=]`** (IPMD, `jobs`) runs the job now, in the background, for one
project or the next batch. It returns `JobStarted {started, detail, pending}`; `started: false` while a run is going.

**The nightly job `second_opinion`** (`backend/live/opinions.py`) covers Critical, High and Watch projects, least
recently asked first, then by tier and risk:

- it skips a project with nothing but context (no evidence about the project itself);
- it skips a project already asked under the current prompt version for its current evidence and LLM: an accepted
  opinion that still passes the checks, a rejection, or a rejection noted on an older prompt's accepted opinion;
- a project it asked moves to the back of the rotation, whether the reply was accepted or rejected;
- it waits while a chat request uses the LLM (at most 10 minutes) and stops early when LM Studio is down;
- it records `job_runs` with counts per status and concern level; `LiveStatus.secondOpinion` shows the last run.

| Variable | Default | Meaning |
|---|---|---|
| `SECOND_OPINION_JOB` | `1` | `0` turns the job off (an official can still ask on the project page). |
| `SECOND_OPINION_PER_RUN` | `15` | Projects asked per run. |
| `SECOND_OPINION_INTERVAL_H` | `24` | Hours between runs. |

The first run starts 45 minutes after the backend starts, after the research agent's first run. At 20 to 60 seconds a
project, 15 projects take 5 to 15 minutes of LLM time a night.

## Tuning run (28 September 2026, qwen2.5-coder-14b in LM Studio on the laptop)

Five projects with the richest evidence (web research facts, PARIVESH, checklist rows), plus one Critical project
whose evidence holds only a minor issue. Prompt `second-opinion-v6`, through `generate()`; the time is the LLM's.

| Project | Tier | Concern | vs model | Attempts | Prompt / reply tokens | Time |
|---|---|---|---|---|---|---|
| PRJ-002112 Goa/Karnataka border to Kundapur (NHAI) | High | concern | agrees | 1 | 1,247 / 101 | 27 s |
| PRJ-000698 Vishnugad Pipalkoti HEP (THDC) | Medium | concern | higher | 1 | 982 / 116 | 32 s |
| PRJ-004326 Bangalore-Chennai Expressway Pkg IV (NHAI) | Critical | concern | agrees | 1 | 1,099 / 94 | 22 s |
| PRJ-001354 Muraidih UG (BCCL) | Medium | concern | higher | 1 | 1,057 / 107 | 25 s |
| PRJ-005236 Bihta civil enclave (AAI) | Watch | concern | higher | 1 | 1,118 / 127 | 33 s |
| PRJ-005544 Khariar ROB on NH-353 (MoRTH) | Critical | watch | lower | 2 | 784 / 66, 842 / 64 | 32 s |

Headlines and narratives (citations as written):

- **PRJ-002112** "Forest clearance and land acquisition delays project." Forest clearance and land acquisition are
  hold-ups [E1, E2]. Minor issues include checklist revisions [E4]. Progress includes resumption of four-laning in
  Bhatkal [E5]. Old items mention unresolved land handing over and contractor disputes [E6, E7].
- **PRJ-000698** "Natural disasters halt progress; minor issues persist." Current hold-ups include a water and debris
  burst [E1] and a landslide [E2]. Minor issues like checklist revisions [E3] are noted. Progress includes target
  dates for commissioning [E4] and installation of the Main Inlet Valve [E5]. The officer should be concerned about
  unresolved natural events.
- **PRJ-004326** "Utility and land issues persist; progress uncertain." Utility shifting and land issues remain
  unresolved [E1, E2]. Minor expenditure lag and repeated revisions noted [E3, E4]. Forest clearance finalized [E5].
  Progress on remaining sections expected [E6].
- **PRJ-001354** "Hold-ups persist; forest clearance delayed." Current hold-ups include checklist execution
  stagnation [E1], delayed forest clearance [E2, E3], and repeated revisions [E4]. Forest clearance is overdue by 75.7
  months [E2]. No items indicate these issues are being solved.
- **PRJ-005236** "Checklist, terminal, taxiway hold-ups persist." Checklist execution stagnates [E1], Russian
  contractor halts terminal work [E2], and taxiway progress is slow [E3]. These hold-ups indicate ongoing issues. The
  foundation stone was laid in 2025 [E4], but the runway extension is deferred [E5], and utility shifting needs
  resolution [E7].
- **PRJ-005544** "Expenditure lag; project reviewed." Minor expenditure lag flagged [E1]. Odisha's Works Minister
  reviewed progress [E2]. (The first reply cited `[none]` and was asked again.)

Reading them against their items: the levels follow the rules, every citation points at the right kind of item, and
no number is invented. Three claims overreach their item: "remain unresolved" (PRJ-004326 E1 says work on the tower
is in progress, though E2's land issue is not said to be solved, so `concern` still holds), "overdue by 75.7 months"
(PRJ-001354: 75.7 months in the stage) and "repeated revisions" listed as a hold-up (a minor item).

How the prompt got there (the same five projects each time):

| Prompt | Change | Outcome |
|---|---|---|
| v1 (committed first) | Concern rule in the system prompt; retry with the first reply as the assistant's turn | `watch` on High and Critical projects with current hold-ups; one rejection after the retry sent back the same reply |
| v2 | Sharper rule: progress elsewhere, how far along, or a new target do not solve a hold-up | 4 accepted, all `watch` although each had a current hold-up no item said was being solved; the same retry failure; 44 to 88 s an ask while LM Studio was shared |
| v3 | The hold-ups' ids named in the user message; the retry re-sends the prompt with the reasons, at 0.3 | 5 of 5 accepted first time, levels right; each closed by restating the status line or the rating, twice wrongly |
| v4 | Told not to restate the context | Still restated in 3 of 5; "on track for March 2027" against an item saying at risk |
| v5 | Context shown without ids | Restated and cited as `[status, model]` |
| v6 | Context left out when there is other evidence; `[status]`-style citations rejected; numbers checked against the items each claim cites | 5 of 5 accepted first time, no restatement; the extra project accepted on the retry |
| v7 (after review) | The hold-ups line adds "a 'watch' cites each of them and the item that says so"; with it, the pack and check fixes below | 8 of 8 accepted (below), 7 first time |

The per-claim number check, replayed on the earlier replies, catches one that the pack-wide check let through: "the
stretch is 83% done [E7]" (83% is in E2; E7, the status line, said 89.97%).

### Review fixes and the v7 run

A review of v6 found checks that let wrong replies through and items graded too high:

- numbers were checked against the whole pack, so a figure from the status line or the model, which the LLM never
  saw, passed ("97.94% built, 122 months late", "91%" for p = 0.91);
- the text after a sentence's last citation, and ids outside brackets ("E42 (E77) says"), were not checked;
- a `watch` citing only a minor item and progress passed on a project with three current hold-ups;
- a land complexity rating, the forest rulebook's estimate and an unjudged headline counted as current hold-ups: the
  land rating was the only one on 29 Critical, High or Watch projects and a headline on 11, and on a Low project the
  rulebook row stood as the hold-up while PARIVESH showed the proposal with final approval;
- after a prompt change, a rejected reply left the project due, so the nightly job asked it first every night.

All six v6 opinions pass the new checks against the packs they were made from. Re-run under v7 (28 September 2026,
the job's path `generate(fresh=True)`), with two projects whose only hold-up the fixes reclassified:

| Project | Tier | Hold-ups | Concern | vs model | Attempts | Time |
|---|---|---|---|---|---|---|
| PRJ-002112 | High | E1 to E3 | concern | agrees | 1 | 29 s |
| PRJ-000698 | Medium | E1, E2 | concern | higher | 1 | 25 s |
| PRJ-004326 | Critical | E1, E2 | concern | agrees | 1 | 24 s |
| PRJ-001354 | Medium | E1 to E3 | concern | higher | 1 | 24 s |
| PRJ-005236 | Watch | E1 to E3 | concern | higher | 1 | 32 s |
| PRJ-005544 | Critical | none | watch | lower | 2 | 30 s |
| PRJ-004601 NH-80 km 132.9 to 190.2 widening (MoRTH) | Critical | none (the land rating is now minor) | watch | lower | 1 | 17 s |
| PRJ-004880 Ambala-Chandigarh greenfield section (NHAI) | Critical | none (the border closure headline is now minor) | watch | lower | 1 | 18 s |

The six v6 projects kept their levels. The two reclassified projects, whose packs used to rule out `none` and name a
hold-up the prompt called 'concern' unless solved, got `watch`: the `lower` disagreement that step 3 of the
evaluation tracks. They also show what the checks still cannot catch: on
PRJ-004880 the LLM wrote "border closure temporarily affects progress [E3]" from a traffic headline, and on PRJ-005544
"no current hold-ups reported [E1]" cites the expenditure lag row for an absence.

## How to evaluate it prospectively

Every stored row (`second_opinions`) keeps the asof, the tier and model version it was set against, the concern, the
narrative, the cited ids and the full evidence it read. The log is prospective by construction: an opinion is made
before the outcome report exists, and an old row is never regenerated for an older asof. A row is replaced only for the
same evidence and LLM by a newer prompt's accepted opinion (the nightly job), or when the stored one is a rejection or
fails a tightened check; a newer prompt's rejection is only noted on an accepted row (`last_rejected`).

1. **Label.** Once the report 2 quarters after the asof is in silver, join each accepted row to its outcome, the same
   `y_any` that `/api/models` live accuracy uses (`dataset/gold/labels_h2.parquet`, `period = asof`). Use only rows
   whose `generated_at` is before that report was ingested (`sources.ingested_at`).

   ```sql
   -- SQLite rows (db.second_opinions()) exported to a frame `opinions`, then in DuckDB:
   SELECT o.project_key, o.asof, json_extract_string(o.json, '$.tier') AS tier,
          json_extract_string(o.json, '$.concern') AS concern, l.y_any
   FROM opinions o JOIN read_parquet('dataset/gold/labels_h2.parquet') l
     ON l.project_key = o.project_key AND l.period = CAST(o.asof AS DATE)
   WHERE json_extract_string(o.json, '$.status') = 'ok' AND l.y_any IS NOT NULL
   ```
2. **Does it add anything to the tier?** Compare slip rates by concern within each tier (Critical, High, Watch), with
   Wilson 90% intervals. It adds information only if, within a tier, `concern` rows slip more often than `watch` rows.
   Read nothing into a cell with fewer than 30 realised rows; a handful of asofs will be needed.
3. **Disagreements.** `vsModel = lower` on a Critical or High project is the case that matters: the model says slip,
   and the evidence reading finds only minor or old issues, or hold-ups being solved. Track the realised rate of those
   against `agrees` rows of the same tier.
4. **Faithfulness.** Each quarter an analyst reads a random 20 accepted opinions with their cited items and marks each
   sentence supported, partly supported or not supported. The checks cannot do this.
5. **Operations.** Track the acceptance rate on the first and second attempt, the rejection reasons, seconds per
   opinion (`llmMs`) and the citation mix by kind (an opinion citing only old items is weak).

Until steps 2 to 4 have data, present it as what it is: a checked summary of the evidence, not a better predictor.

## Known limits

- **The level follows the evidence groups closely.** With the hold-ups named, every project with a current severity 2
  or 3 item got `concern` in tuning unless an item said the hold-up was being solved. The judgement the LLM adds is
  whether a hold-up is being solved, and the wording. So `concern` on a Medium or Watch project (`higher`) often only
  means that a current negative item exists; the informative cases are `watch` or `none` against a high tier.
- **A small model misreads.** The model is a 14B coder model (`LLM_MODEL`; `LLM_CHAT_MODEL` does not change it). It
  can overstate an item ("remains unresolved" for a hold-up being worked on), mislabel a minor item as a hold-up, or
  add an uncited closing remark. The checks bound the ids, numbers and level, not the reasoning.
- **Severity comes from upstream.** Which items are hold-ups (severity 2 or 3, recent) is decided by the checklist,
  the research sweep, the research agent and the PARIVESH rule limits, not by the LLM. A headline makes a hold-up only
  when the research agent judged it about the project; the scout's keyword severity still picks which headlines are
  shown.
- **News is headline only.** A news item is a headline classified by keywords. Web research facts are summaries from
  a checked sweep, but coverage favours large, much-reported projects. No news is not no problem.
- **Remarks end in 2023.** Report remarks stop being free text in 2023, so every open remark event is old today.
- **No project evidence means little to say.** A project with only the status line and the model can only get
  `none`, and the nightly job skips it.
- **Speed.** About 3 to 4 tokens a second: 20 to 40 seconds an opinion when LM Studio is free, more while the chat
  or the research agent uses it (one LLM call at a time).
