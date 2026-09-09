# Cuepass: win conditions

Agentic Cinema (Google + Devpost), **Parallel track**. Answered 2026-09-09, before
the ADK and Parallel-Extract work started.

Scoreboard: 28 rival repos verified on the Parallel track, 3 places. Winning archetypes own a research brief; assets are Parallel Search snippets, count 1 search call per run, 0 Extract calls.
Bar to beat: 3rd place of 29 on the Parallel track. Concretely, beat a cited-research-brief entry that makes exactly 1 Search call and 0 Extract calls per run.
Asset we will own: the cited-spec evidence ledger. Obtained at runtime by Parallel Search then Parallel Extract, keyed by URL, holding the verbatim clause plus extract_id behind every threshold measured against, resolved across as many pages as it takes: a Netflix profile is spread over 3 pages and each threshold keeps the one it was read from. Its sharpest output is the profile contrast: 61 cues on the seed run clear one published Netflix profile and fail another, a figure that cannot exist in a tool with the threshold in its source.
Off-platform buyer: Priya, localization and accessibility QC lead at an indie distributor, reached through subtitling practitioner communities.
Single entry: Cuepass.
Verb the brief names: "orchestrate", and "show off a deterministic, multi-step agent".
Our product performs that verb: yes. `cuepass_agents.build_workflow()` returns a `google.adk.workflow.Workflow` whose edges fix the order; `agent.run_agent()` drives it.
Metric plan: timing violations before repair to timing violations after repair, per profile, the after number from a second `measure.measure_subtitles()` call on the repaired file. Seed run iron_mask-69b5d4cf: 88 to 38 at 20 cps (English USA guide) and 149 to 75 at 17 cps (Subtitle Templates guide), the two reading speeds Netflix publishes on two different pages, both fetched live in the same run, and unchanged across 3 consecutive live runs. Secondary and the one a Parallel judge should carry away: 61 cues legal under the looser published profile and illegal under the stricter, checkable by clicking the number on the landing screen, which filters the sheet to exactly those cues. The pair excludes line-length failures because retiming cannot shorten a line; those are carried in the breakdown beside it, so repair is never credited with a cue it cannot touch. A profile publishing no timing rule shows its total instead, labelled as such.
Live by: live now, https://sixteen-seventeen-387894104564.us-central1.run.app , seed run iron_mask-69b5d4cf served at zero clicks.
Deviation from research: 2. Parallel Monitor dropped as ornamental. Parallel Task API dropped on latency, Search plus Extract used instead.

## Scoreboard

Four criteria, equally weighted, scored by 23 judges. On the Parallel track the
two that decide it are **Technological Implementation** (Google Cloud *and* the
partner service, judged by 2 Parallel MTS engineers who build the product being
integrated) and **Quality of the Idea** (non-obvious use of Google Cloud +
Partner). Design and Potential Impact are scored off what the live URL actually
demonstrates, not off the README. Top 3 of 29 repos on this track place.

## Bar to beat

The verified field is 28 other Parallel-track repos. The archetypes that will
fill it: script-to-clearance rights research, location scouting, casting
availability, screenplay fact-check, greenlight comps, P&A trend watch. All of
them do the same thing with Parallel: one `client.search(objective=...)`, stuff
the snippets into Gemini, emit a cited research brief. That is Parallel's own
quickstart with a film noun on it. The bar is not "beat a better subtitle tool",
there is no other subtitle tool here. The bar is **be the entry that uses
Parallel as an operational input to a gate rather than as a paragraph
generator**, and to have a real ADK graph while most of the field wraps one
`generate_content` call and calls it multi-agent.

## Asset we will own

The **cited-spec evidence ledger**: for every buyer, the URL Parallel Extract
actually opened this run, the verbatim clause on that page that states each
threshold, and the extract id. Nobody else on the track has a reason to build
one, because nobody else is measuring a file against a number that has to be
defensible. It is the thing that makes the buyer matrix auditable rather than
assertable: run id, URL, clause, measured value, verdict, with no model in the
chain that produced the number.

## Off-platform buyer

Localization and accessibility QC leads at indie distributors and localization
vendors, who deliver the same master to several platforms and eat the
re-delivery cycle when one of them rejects on caption spec. They are reached
off Devpost through subtitling practitioner communities, not through a
hackathon gallery. The artefact they want is the exceptions file, which is why
it is a download and not a screenshot.

## Single entry

One entry, one track. Cuepass goes to Parallel only. The sibling projects go to
different tracks; no two of ours compete in the same bucket.

## Verb the brief names

The brief says *orchestrate*, and asks for a "**deterministic, multi-step
agent**", explicitly not chat. It also steers: "build agents natively using the
Agent Development Kit (ADK) instead of external wrapper libraries."

## Our product performs that verb

The run is a `google.adk.workflow.Workflow` graph. One research desk per delivery
profile, each an `LlmAgent`, researches that profile's own published spec
concurrently with Parallel Search and Extract. A `JoinNode` holds until every desk
reports. Then a chain of `FunctionNode`s that never touch a model binds the cited
specs, measures, repairs and re-measures. Then one `LlmAgent` triages what is left
into editorial actions. Counts come from `graph_shape()` reading the built graph,
never from prose.

Deterministic where it must be, model only where a decision is genuinely a
judgement. The order is fixed by the graph, not by a prompt.

## Metric plan

Primary: **timing violations before repair to timing violations after repair**,
per buyer, where the "after" number is a second run of the same check against
the repaired file. That is the pair the landing screen leads with, and it counts
only what retiming can address: a line that is simply too long is excluded from
it and carried in the breakdown instead, so repair is never credited with a cue
it cannot touch. A buyer whose page publishes no timing rule shows its total
instead, labelled as such. Secondary: cues retimed, how many of the four rules
each buyer's page actually publishes, and the count of buyers the same file
passes versus fails. Every number on screen is produced by `measure.py` against
a threshold that came out of a page Parallel opened this run. The landing screen
holds no placeholder: it is a persisted real run with its timestamp shown, and
when nothing is stored it says so rather than drawing something.

## Live by

Live now at https://sixteen-seventeen-387894104564.us-central1.run.app , health
returns ok. Deploys are owned by the orchestrator. The remaining work is
landing-state, ADK graph, Extract chain and UI, all of which ship into the same
already-live service.

## Deviation from research

Adversarial review (Grok, `docs/grok-critique-cuepass.md`) named two things I am
deliberately not doing. **Monitor**: recommended against, caption style guides
do not change inside a judging window, so a Monitor call would be a README
ornament. Not shipped. **Parallel Task API**: genuinely the right tool for typed
output with per-field `basis` citations, but its processors run 15s to 10min per
run, and one run per delivery profile, which would make the live demo a wait. The
Search plus Extract chain gets the same evidence (URL, page text, verbatim
clause) inside a few seconds, so that is what ships. Recorded here so the choice
reads as a decision rather than an omission.
