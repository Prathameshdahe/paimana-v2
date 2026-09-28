# PAIMANA help

## What PAIMANA is

PAIMANA is an early-warning tool for the central sector infrastructure projects that the Ministry of Statistics and
Programme Implementation (MoSPI) monitors: roads, railways, coal, petroleum, power and other projects of Rs 150
crore and above. It reads the monitoring reports published since 2005, links the reports of each project
into one history, and estimates which current projects are likely to report a delay or a cost increase in their next
reports. Next to that estimate it shows outside evidence that can explain a delay: land acquisition records, forest
clearance proposals, issues named in the report remarks, and news and research with their sources.

PAIMANA does not replace the official reports, decide anything about a project or change any figure an agency has
reported.

## What the risk tiers mean

For every current project with an anticipated completion date, the model estimates how likely a slip is: that within
the next 2 quarters its anticipated completion date moves out by 3 months or more, or its anticipated cost goes up by
5% or more. It also estimates a date push and a cost revision on their own, a slip within 4 quarters, and how much
further the completion date is likely to move.

Projects are ranked by that estimate and tiered by rank:

- **Critical**: the riskiest 5% of scored projects.
- **High**: the next 15% (Critical and High together are the top 20%).
- **Medium**: the next 30%.
- **Low**: the remaining 50%.

Tiers are relative. "High" means riskier than most of the current portfolio, not a fixed level of danger.

## The outlook in words

Next to its tier, each project shows its outlook for the next two quarters in words. A push of the completion date
and a cost revision are each **very likely**, **likely**, **possible** or **unlikely**, and the likely further slip
of the completion date is **under 6 months**, **6 to 12 months**, **1 to 2 years** or **over 2 years**. The words
are fixed bands of the model's estimate, which ranks projects against each other rather than counting how often such
projects slip: read "likely" as "more likely to slip than most", not as a promise. The main reasons for the tier are
given the same way: what raises or lowers the risk, and whether its effect is strong, moderate or slight.

## The Watch tier

Some reports give no anticipated completion date for a project. Without it the model cannot estimate a date slip, so
these projects are not ranked and sit in the **Watch** tier instead. Watch does not mean low or high risk; it means the
date needed to score the project is missing. Watch projects are listed by the number of flagged risk checks, then by
the chance of a cost revision. That order has not been tested against past outcomes.

## What "Stalled" means

The **Stalled** badge appears when a project's reported physical progress has barely moved for 2 or more quarters
while at least 30% of its planned time has passed and it is below 95% complete. It is a badge only: it does not change
the tier, because in tests on past reports stalled projects slipped no more often than the others.

## Risk checks and top risks

Each current project gets a checklist of 12 risk checks plus one combined land-and-forest row. Each is **flagged**,
**clear** or **unknown**. Unknown means we found no evidence either way; it is never the same as clear.

The checks are: a likely date push or cost revision (the project is in the top 20% for that chance); work slowed or
stopped; spending out of step with work done; the cost or date revised twice or more already; the sector behind its
targets; the agency's past projects finishing later than planned; land not fully acquired; a forest or environment
clearance pending; a court case; contractor problems; and a gap of more than 3 months before the latest report or a
low data-quality score.

The project page shows up to three flagged checks in plain words, for example "Land for the project is not fully
acquired yet." The **early notice** flag marks a project with a flagged outside factor (land, forest, a court case,
the contractor, utility shifting or an approval from another agency) that shows no slip so far in its reports or
is still in the Low or Medium tier.

## Where the data comes from

- **MoSPI project monitoring reports**: monthly and quarterly reports from 2005 onward, the newer flash reports and
  the project monitoring portal export. Progress, cost, expenditure and dates are as the agencies reported them.
- **Report remarks**: the free-text remarks in the reports, read for land, forest, court, contractor, funding,
  utility, approval, law-and-order and weather issues. Reports print free-text remarks only up to mid-2023, so these
  issues describe the situation up to 2023.
- **Land acquisition**: the Bhoomi Rashi highway land register (national highway land notifications, 29 states). A
  road project is rated only when a kilometre range in its name places it on notified stretches; a link by highway
  number or district alone is shown as "possible", and everything else is unknown.
- **Forest clearance**: PARIVESH forest clearance proposals linked to projects, with their stage, and the time limits
  in the forest clearance rules.
- **News**: headlines from Google News and the Press Information Bureau, linked to projects automatically by place
  names. A headline is a lead, not a confirmed fact.
- **Web research**: short notes on project blockers and progress found in public sources, each with its source link
  and date.

## How old the data is

Scores are recalculated when a new report arrives, and every score carries the date it is "as of": the date of the
latest report the scores are based on. Each page shows the current as-of date, and the assistant can tell you it.
Every current project is in the latest report, but a report can leave a field blank, and then that figure is
unknown. Remark issues end in 2023. The land register and the PARIVESH lists are read from their portals from time to
time, not live, and news is searched daily for a rotating set of projects.

## What the assistant can do

The assistant answers questions about PAIMANA data in plain English. It works the same way for everyone but only reads
what your role may see.

**Everyone, including the public, can ask it to:**

- find projects by name, state, sector, ministry or tier, and count or summarise them;
- show a project's tier, progress, cost, completion date and top risks, and how its progress has changed;
- compare a few projects side by side;
- show research notes and outside factors (land, forest clearance) with their sources;
- explain the terms on this page.

**Signed-in officials can also ask**, within their scope, why the model placed a project in its tier (its main
drivers), which checks are flagged and on what evidence, which news is linked to a project, PARIVESH proposal details,
and agency and bottleneck summaries. An agency official sees their agency's projects, a ministry official their
ministry's, and an IPMD analyst every project.

**It cannot:** see projects or details outside your role; change any data, tier or alert; send messages or approve
anything; search the web live; or know anything that is not in PAIMANA's data. It does not give legal, financial or
engineering advice, and it does not decide what should be done about a project.

## How answers are checked

The assistant first looks up the data, then writes a short answer from what it found, citing its sources as [1],
[2] and so on. Every number and date in the written answer is checked against the data it looked up. If one is not
there, the answer is rewritten once; if it still fails, you get a plain summary built directly from the data instead.
An answer that passed shows a "checked against the data" note. Wording can still be wrong, so check the cards and
sources for anything that matters. Where the data is silent, the assistant says "unknown" or "not in the data".

## Limitations

- The model ranks projects by patterns in past reports. It misses some slips, flags some projects that finish on
  time, and only sees what the reports record.
- Figures are as reported by the agencies. Errors or gaps in a report carry through, and many reports leave the
  anticipated cost or completion date blank.
- Remark-based issues stop in 2023, and unknown is not clear: a project with no flagged issue may still have one.
- Land records cover national highway stretches only, and the PARIVESH list we read is not complete.
- News is linked by place names and can be linked to the wrong project.
- This is a prototype: choosing a role on the sign-in page separates views but is not a secure login.
