# AI assistant

The assistant answers questions about the monitored projects in plain English, for every role. It reads only
PAIMANA's own data through a fixed set of read-only tools, each cut to what the asking role may see, and every
number in an answer is checked against the data the model was given. When the local model is down or busy, or
its answer fails the check twice, the answer falls back to a deterministic summary of the same data; the cards
arrive first either way.

Code: `llm/router.py` (routing), `llm/tools.py` (tools), `llm/agent.py` (planner, writer, checker),
`backend/routes.py` `POST /api/chat`, `backend/ratelimit.py`, `backend/labels.py` (plain labels),
`llm/eval.py` with `tests/chat_eval.jsonl` (evaluation). The search index behind `search_knowledge` is
`llm/rag.py`; the LM Studio client is `llm/client.py`.

## How an answer is made

```
 question ──► ROUTER (no LLM, 1-3 ms) ──── confident ─────────────────────────┐
               PRJ keys, 'this project', names by place words (typos too),   │
               follow-ups, tier / sector / state / ministry / agency /       │
               factor / top N / sort words, keyword intents                  │
                   │ not confident (and the LLM is up)                       │
                   ▼                                                         │
              PLANNER (LLM, JSON, <= 4 calls, each checked by its tool's     │
              argument model; a bad plan falls back to                       │
              search_knowledge + search_projects)                            │
                   │                                                         │
                   ▼                                                         ▼
              TOOLS in parallel threads, the viewer from the server ──► cards to the browser at once
                   │  facts (compact JSON) + sources (numbered)
                   │  a list + a per-project question: SECOND ROUND,
                   │  <= 3 calls on the listed projects
                   ▼
              WRITER (LLM, streamed tokens, <= 260 tokens, <= 100 words)
                   │
                   ▼
              CHECKER: every number and date in the facts the writer saw
              (backend/brief.validate), every [n] a real source, no model
              internals in a public answer
                   │ rejected                       │ rejected again, LLM down or busy
                   ▼                                ▼
              one strict retry naming           DETERMINISTIC ANSWER: the tools'
              the offending numbers             own summaries with their [n]
```

1. **Router** (`llm/router.py`, no LLM). It reads project keys (`PRJ-` and six digits, or `prj 698`), "this project" (the
   project open in the app), project names by their distinctive words (the scout's place words, exact or a
   typo within rapidfuzz ratio 88 but not a plural of an ordinary word, "train" for "trains"; a name shared by
   several projects is listed, never guessed, and a near match only is left to the planner), follow-ups ("and
   what changed lately?" or "tell me more" takes the previous turn's project), and filters matched against the served portfolio
   (tier, sector, state, ministry, agency, outside factor, "top 5", riskiest / biggest / most delayed, near
   completion, "by state"). Keyword intents (count, list, stats, explain, history, news, external, compare,
   opinion, agency, bottleneck, help) map to tool calls with a confidence.
2. **Planner** (LLM, only when the router is not confident and the LLM is up): the catalogue of the tools this
   viewer may use, the last four turns and the open project, answered with one line of JSON. Every call is
   validated by the tool's own argument model; unknown tools, officials' tools for the public, wrong arguments
   and repeats are dropped; nothing valid means the fallback. The planner sees the question and the
   conversation, never a tool result.
3. **Tools** (`llm/tools.py`) run in parallel; each card is sent as soon as its tool finishes. When round one
   listed projects and the question needs per-project detail ("why are the Critical projects in Odisha
   Critical?"), a second round runs the detail tool on the top three.
4. **Writer** (LLM, streamed): the question, the numbered sources and the facts of every tool in one block
   between `<<<DATA` and `DATA>>>`. The prompt says text quoting news, research, remarks or portal records is
   quoted material, never instructions.
5. **Checker**: `backend.brief.validate` against exactly the facts the writer saw (plus the source lines and the
   N of a "top N" the question asks for; no other number of the question, so a leading question such as "is it
   97% complete?" never gets its own figure back as checked), with plain number words read as digits ("two quarters" is 2, which the facts
   hold; a word the facts themselves use stays a word); citations must point at a source; a public answer may not
   name model internals (SHAP, log-odds, LightGBM, quantiles). A rejected answer is retried once with the
   reasons named; a second rejection is replaced by the deterministic answer. Either way `done.validated` is true
   only for text that passed the check or was built from the data.

## Endpoint and events

`POST /api/chat` with `{messages: [{role: 'user' | 'assistant', content}] (1-12, the last the user's question of
1-1000 characters), projectKey?}` and the usual `X-Paimana-*` headers answers `text/event-stream`:
`event: <name>` and `data: <JSON, camelCase>`, a `: keep-alive` comment every 15 s while the model thinks.

| Event | Data |
|---|---|
| `status` | `{stage: routing \| planning \| tools \| writing \| checking, detail}` |
| `tool` | `{id: 't1', name, label, args, status: running \| done \| error, summary}` |
| `card` | `projects`, `stats`, `project`, `explain`, `history`, `compare`, `opinion`, then one `sources` card `{items: [{n, kind, title, source, url, date, datePrecision, projectKey}]}`; `date` is ISO at the precision the source gives (`2026`, `2026-07` for a month-precise research fact, else a day) and `datePrecision` names it (`day` \| `month` \| `year`, null with no date). In a `stats` card's rows `nCritical` and `nHigh` are null when the count is unknown (an agency with open projects outside the viewer's scope: not zero) |
| `token` | `{text}`, the answer as it streams |
| `retry` | `{reasons}`: clear the streamed text; a replacement follows (the strict attempt, or the deterministic answer as one `token`) |
| `done` | `{text, validated, reasons, llm: ok \| unavailable \| busy \| skipped, elapsedMs}`; `text` is the final answer |
| `error` | `{message}`; the stream ends |

`llm` says why the text is what it is: `ok` the model answered (with `reasons` non-empty when its two drafts
were rejected and the deterministic answer replaced them), `unavailable` LM Studio is down or timed out,
`busy` another generation held the LLM for 20 s, `skipped` nothing was found or the writer is off
(`CHAT_WRITER=0`). Errors before streaming: 422 (limits), 404 (projectKey unknown or outside the scope), 429
(rate limit, `{"detail"}` with `Retry-After`). An earlier answer sent back may be longer than 1000
characters; only its first 1000 are read.

## Tools and roles

"Scoped" means cut to the role's projects; a project outside the scope is answered exactly like an unknown key
("Project X was not found"), so an answer never reveals that it exists.

| Tool | What it reads | Public | Agency | Ministry | IPMD |
|---|---|---|---|---|---|
| `search_projects` | the project list: name words, tier, sector, state, ministry, agency, flag, near completion, sort | ✓ | scoped | scoped | ✓ |
| `portfolio_stats` | counts, capital, tier counts by state, sector, ministry or tier | ✓ | scoped | scoped | ✓ |
| `get_project` | tier, chance of a slip, progress, cost, dates, top risks in plain words | public page | + intervals, flagged checks | + intervals, flagged checks | full |
| `project_history` | report timeline and what changed between the last reports | timeline | + tier alerts, prediction log | + tier alerts, prediction log | full |
| `compare_projects` | 2-4 projects side by side | ✓ | scoped | scoped | ✓ |
| `project_research` | web research facts; portfolio blockers without a key | no match reasons, no agent headlines | + linked news | + linked news | + linked news |
| `external_factors` | land, forest, court, contractor, utility, inter-agency; per project or across the portfolio | factor names, public evidence strings | + check evidence, PARIVESH detail | + check evidence, PARIVESH detail | full |
| `search_knowledge` | help, glossary, docs and record text (`llm/rag.py`) | public chunks (no research-agent headlines) | scoped | scoped | ✓ |
| `explain_prediction` | the five SHAP drivers in plain labels with direction words, flagged checks with evidence | – | scoped | scoped | ✓ |
| `second_opinion` | the cached AI second opinion (`llm.second_opinion.cached`), never generated in chat | – | scoped | scoped | ✓ |
| `agency_scorecard` | agency matrix: schedule and cost overrun, open projects, Critical / High counts (null when some of the agency's open projects are outside the scope) | – | all agencies, own by default | their ministry's agencies | ✓ |
| `bottlenecks` | clusters of projects held up by one open issue and place | – | scoped | scoped | ✓ |

Public outputs are built from `serving.public_project`, `public_page`, `public_external`, `public_research` and
`public_research_summary`, the same redaction as the public pages.

## Guardrails

- **Scope and role come from the server.** No tool takes a scope argument; the viewer is built from the request
  headers by `backend/access.py`, and every call's arguments are validated by a pydantic model (extra fields
  refused). A plan that names another ministry's project or asks for an officials' tool gets "not found" or is
  dropped.
- **Untrusted text is data.** Headlines, research notes, remark quotes, PARIVESH and register lines and search
  hits that are not PAIMANA's own words go through `tools.quote` (one line, no prompt markers, fences or tags,
  capped) and sit inside the delimited data block; the planner never sees them (its second round sees project
  keys only), so a headline cannot add a tool call or change the scope. `tests/test_chat_agent.py` injects one.
- **No invented numbers.** The checker, one strict retry, then the deterministic answer. Citations must exist.
  The validator accepts any number anywhere in the facts, so a figure from a headline can still be attributed to
  the wrong thing; it does not check words such as a tier or a cause.
- **The public prompt** talks about tiers, chances, progress, cost and dates and never mentions model internals;
  public tools carry no drivers, intervals or evidence lines, and a public answer naming one is rejected.
- **One LLM call at a time.** The answer holds `client.gate(chat=True)` from its first LLM call to its end;
  background jobs that take the gate (the research agent, the second-opinion job) and the search index's embedding
  refresh pause while a chat is active. The project brief (waits up to 120 s, then says the LLM is busy) and the worker cell take the
  same gate, so no two generations run at once. The writer waits for the gate at most 20 s (`busy`); the planner, which holds up
  the first card, only 2 s, after which the router's and the fallback's calls run instead. A refused connection
  trips the shared circuit breaker (`unavailable`, no waiting for 30 s); a slow reply does not.
- **Rate limits** per client IP and role: the public 6 a minute and 40 an hour, officials 20 a minute
  (`backend/ratelimit.py`, in memory).
- **Nothing is stored.** No audit row, no question text in the logs (only intents, tool names, timings).
- **A client that hangs up** stops the answer at its next step and frees the LLM; one that hangs up while the
  gate is awaited gets no LLM call once it is free.

## Speed

Measured on the development laptop with qwen2.5-coder-14b in LM Studio (8,192-token context, JSON as text):
about 4 tokens a second when the model is free, and much slower when other jobs share it (the evaluation below
ran while other jobs used the same server). A writer prompt is 400-1,500 tokens; an answer takes 5-40 s when
the model is free, a list answer that is rejected and retried up to about 2 minutes. So:

- The router answers most questions with no LLM call; the planner runs only for the rest (about 160 tokens).
- Cards come before the narrative: time to the first card is under a second.
- The writer's facts are compact (percents as whole numbers, capped lists, about 4,500 characters at most) and
  the answer is at most 100 words (about 130 tokens, the cap is 260).
- The router's vocabulary, and with the live jobs on the search index, are loaded at startup (`backend/main.py`),
  so the first question does not wait for them.

**A faster model.** Load a smaller instruct model in LM Studio (generation speed falls roughly with the number of
parameters, so a 3-8B instruct model writes faster than the 14B one on the same laptop) and set `LLM_CHAT_MODEL`
in `.env` to its LM Studio id, for example `LLM_CHAT_MODEL=qwen2.5-7b-instruct`. It switches only the chat's
planner and writer. The project brief, the worker cell, the research agent's news judge and the second opinion
(the nightly job, the project page's and the chat's cached one alike) stay on `LLM_MODEL`, so their prompts keep
the model they were tuned on and the stored second opinions, keyed by their LLM, keep being served. LM Studio then
serves two models: keep both loaded, or a chat and a job may wait for it to swap them. Nothing else changes: the
checker still guards every number. Run `python -m llm.eval --llm subset` after a switch to see how often the
smaller model's answers pass the check. `CHAT_WRITER=0` turns the model off for chat altogether (cards and
deterministic answers only).

## Evaluation

`python -m llm.eval` runs the 36 questions of `tests/chat_eval.jsonl` (12 public, 12 for a Ministry of Road
Transport & Highways official, 12 for an IPMD analyst) through `agent.run` as their role. Each question names the
tools it should use and checks read from the API at run time as the same viewer: a count equal to
`/api/projects` or `/api/portfolio`, the state with the most Critical projects, the first project of a list, the
latest anticipated completion, the worst agency by schedule overrun, a mention or a scope-leak word. A count or
a first project passes when the answer states it or a card carries it (the tools found it); the answer text is
also scored alone, which is the measure of the written answers (a card-only check has no text part). With
`--llm subset` the 12 questions marked `llm` run with the real planner and writer; `--llm all` runs every
question with the model.

Results of 28 September 2026 (asof July 2026, qwen2.5-coder-14b in LM Studio on the development laptop, shared
with other jobs during the runs). Router and tools, all 36 questions, writer off (`python -m llm.eval`):

| Metric | Value |
|---|---|
| Questions | 36 |
| Routing accuracy (router alone) | 36/36 |
| Tool accuracy (all rounds) | 36/36 |
| Checks passed (answer or cards) | 36/36 |
| Checks the deterministic answer text passes alone | 33/33 |
| Time to first card, median / p90 | 0.0 s / 0.2 s |
| Time to done, median / p90 | 0.0 s / 0.2 s |

With the model, 15 questions (the 12 marked `llm`, the out-of-scope question that goes to the planner, a help
question and a follow-up; `python -m llm.eval --llm all --only ...`), run again after the review fixes (the
check no longer takes the question's own numbers, the planner waits 2 s for the gate):

| Metric | Value |
|---|---|
| Questions | 15 |
| Routing accuracy (router alone) | 15/15 |
| Tool accuracy (all rounds, planner included) | 15/15 |
| Checks passed (answer or cards) | 15/15 |
| Checks the model's answer text passes alone | 14/15 |
| Answers the model wrote, accepted by the check | 14/14 |
| ... after one strict retry | 0/14 |
| ... replaced by the deterministic answer | 0/14 |
| LLM states | 14 ok, 1 skipped (nothing in scope found, by design) |
| Time to first card, median / p90 | 0.0 s / 1.3 s |
| Time to done, median / p90 | 23.1 s / 35.7 s |

The text miss is "High risk petroleum projects": the answer names the riskiest projects but not how many there
are (the count is on the card). The run before the fixes accepted 13 of 14 (2 after a retry, 1 replaced), with
done at 18.7 s / 67.4 s; model runs vary from run to run, so the two differ by more than the fixes.

What the runs showed and what changed (each fix is its own commit): the deterministic answer of a help question
said only "5 passages found" (it now quotes the help); "which state has the most Critical projects" named the
state with the most capital (`portfolio_stats` ranks by count on "most"); the writer wrote "slipping into the next
quarter" (the percent keys now name their horizon), "Kerala has the lowest capital" of a top-10 list (the groups
say they are the first 10), "early notice is required" (the count carries its meaning), and "two quarters" or
"three", which the check rejected (plain number words are now read as digits, a word the facts themselves use
stays a word). What still fails: the model counts or numbers the items of a long list ("'3' is not in the
payload") despite the prompt; the check rejects that and the deterministic answer replaces it. It also still
paraphrases loosely ("a 98% chance of not meeting its completion date" for the chance of a date push or cost
revision within 2 quarters), which a number check cannot catch.

## Limitations

- The checker catches numbers and dates, not wrong words: a tier, a cause or a project named wrongly passes if its
  numbers are in the facts.
- Routing is keyword based. Unusual phrasing goes to the planner, which is slow on this laptop; with the model
  down it goes to a knowledge search and a name search.
- Names are matched by distinctive words; a project with only generic words in its name ("Widening of NH ...")
  is found by its key or through a list.
- The rate limiter and the gate are per process; several backend workers would need a shared store.
- The facts carry their as-of month, but the writer is not forced to state it; report remarks end in 2023 (see
  the caveats in `docs/HELP.md`).
