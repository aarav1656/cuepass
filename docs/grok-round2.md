# Grok round 2: Cuepass

Second pass of the critic loop. Round 1 criticised Cuepass, the code was then
rebuilt, and nobody went back to Grok to ask whether the rebuild survives. This is
that return trip.

## Conditions

Conducted 2026-09-09 over the `grokweb` CLI on the x.com transport.

**Model: grok-3, not grok-4.** grok-4 was exhausted at the account level before this
session began: "You've reached your limit of 15 Grok 4 questions per 20 hours."
grok-3-mini returned an empty stream. grok-3 answered.

Sent through `grokweb ask` rather than `grokweb chat`: `chat` hardwires a 120 second
timeout that truncates a reply this long, and `ask` carries no conversation memory,
which prevents the cross-thread contamination recorded in round 1, where a Cuepass
reply came back under the Checkprint conversation header. Every claim is restated
inside the question. Grok retrieved the live run JSON and the repo before answering.

## What was put to it

Nine lines from round 1, quoted back verbatim, including the ceiling of "4th".
Then the rebuild: the 13 node `google.adk.workflow.Workflow` named
`cuepass_delivery_desk`, `__START__` fanning out to five delivery-profile `LlmAgent`
desks, a real `JoinNode`, five `FunctionNode`s that run no model, then the triage
`LlmAgent`; Parallel as a Search then Extract chain threaded by session id with real
recorded extract ids and character counts; every live-path threshold parsed in Python
carrying its verbatim clause and URL; two Netflix profiles at 20 versus 17 cps with 61
cues diverging on The Iron Mask; DELIVER and HOLD replacing "illegal".

Four things disclosed rather than hidden: only Netflix publishes an extractable spec,
so three of five desks return nothing by design with a recorded model-written reason
each; the repair still leaves 105 of 179 violations and both verdicts are HOLD; there
is exactly one stored run and it is flagged `is_seed:true`; and `min_duration_s` has a
pinned fallback, unused on this run.

## Grok's answer, verbatim

Grok's replies are reproduced with their wording unchanged, with one
mechanical exception: em dashes have been replaced with commas or full stops to
satisfy this repo's writing rules, and the fixed-width line wrapping the CLI
applies has been joined. No words were added, removed or reordered.

> The live index is one seed run. iron_mask-69b5d4cf: 516 cues, 179 to 105, both profiles HOLD, buyers netflix_en_us / netflix_templates only. That is the artifact I am scoring.
>
> Q1. Better costume. Not a different failure.
>
> 1. "QC script wearing an agent costume." Wounded. cuepass_delivery_desk is a real google.adk.workflow.Workflow: five LlmAgent desks, JoinNode, five FunctionNodes, then triage_leftovers. Models run before measure; no model sits between measure and repair. That is no longer a single generate_content taped onto a script. The thing that changes the file is still measure.py / remediate_subtitles (extend out-times, 1-frame gap, no rewrite, no split). The graph is real. The product is still a QC script with research and triage agents at the edges.
>
> 2. "Cheapest Parallel that still compiles" / "decorative grounding." Wounded, extract half is dead. Live path is two SDK calls, session-threaded: Search then Extract. Recorded: extract_03022b05f1592f6eedf54d82d6b4af4c (80,965 chars) and extract_f3ca7d78e8538a70f97e3f8f34760722 (44,094 chars). An engineer who opens the client will find extract, not only search. They will not find MCP web_fetch, Task schema, or Monitor. "Decorative" is no longer fair. "Cheapest surface that proves the requirement" is still fair.
>
> 3. "Zero ADK, zero Agent Engine, zero playbook, one generate_content." Split. ADK Workflow: dead. One generate_content: dead. Agent Engine: untouched (Cloud Run + FastAPI). Playbook: untouched. The old sentence as a unit is wounded. The hosting/platform half is intact.
>
> 4. "'Illegal to ship' is a credibility kill." Dead. Shipped API verdicts are HOLD / HOLD. README states DELIVER/HOLD on purpose. That verb is gone from output.
>
> 5. "Netflix/Amazon/BBC/FCC mixed into one live Search..." Dead as stated. Five desks, no staple. Empty columns with a model-written reason is the correct refusal. The mixing bug is fixed. What it left behind is a two-column matrix, which is now line 7's problem, not line 5's.
>
> 6. "Search used once to fetch constants for a local algorithm." Wounded. The second clause still describes this. Extract opening the page and hanging the verbatim clause on the number kills "Search used once" and kills "a blog's 20 cps." It does not kill "constants for a local algorithm." Downstream is still deterministic Python: regex parse, measure_every_buyer, repair_every_buyer, remeasure_every_buyer. Parallel does not decide a cue, does not retime, does not author a cps value. That is the right QC design. It is also exactly the neighboring failure: web stack used to bind constants (and to document missing constants) for a local timer. Line 6 is not dead.
>
> 7. Two Netflix profiles do not collapse. That does not pass the test. 20.0 vs 17.0, clauses from two different Netflix pages, 61 cues pass one and fail the other. The collapse-to-one-number test on those two pages is passed. "If all four collapse" was never only about Netflix disagreeing with itself. Four names were in the graph because the advertised feature was a buyer matrix. Three desks return nothing by design. Live /api/runs lists buyers: ["netflix_en_us", "netflix_templates"]. Two profiles from one buyer satisfy "do not hardcode 17." They do not satisfy "this feature exists across buyers." Line 7 is wounded, not cleared.
>
> 8. "You advertise a fixer that leaves a reject." Untouched. 179 before, 105 after. Both overall verdicts HOLD. Repair cannot touch line length (README: 30 before, 30 after on the 20 cps profile). Triage explains the pile. It does not clear it. The live button still presents a remediator whose output is a reject.
>
> 9. Ceiling 4th, punchers' chance at 3rd, not 1st. Untouched as a budget. Fake-Parallel and fake-ADK are off the table, so the floor is higher. 28 repos, one seed title, one buyer with numbers, fixer leaves HOLD: do not budget 3rd. 4th with a punchers' chance at 3rd if the tape is better than the product.
>
> Same failure in a better costume? The costume objections (2, 3-ADK, 4, 5) are dead or wounded-to-dead. The product objections (1, 6-algorithm, 7-buyers, 8) are the same failure with citations attached.
>
> Q2. One reason.
>
> The only clickable proof is one seeded Netflix HOLD on one ASR file.
>
> A Parallel-track judge comparing 28 repos will score what /api/runs contains: is_seed: true, one title, two profiles from one publisher, 105 leftovers, verdict HOLD. The five-desk graph, JoinNode, and 80k-char extracts are scaffolding around that row. That is why it loses.
>
> Q3. One change: (iv).
>
> (iii) drop the min_duration_s pin. On this run every Netflix threshold is provenance: "live". Removing an unused fallback is hygiene. It does not move a criterion. Last.
>
> (ii) more titles. Kills the single-seed smell. Every extra archive.org ASR file will HOLD against the same two pages and reprint line 8. A judge will not watch four more Iron Masks. Weak.
>
> (i) a second extractable buyer. This is the correct product answer to lines 6 and 7. Amazon/BBC/FCC are already known-dead for Extract. A new publisher in ten hours is a research gamble, not a patch. If it fails you have no tape.
>
> (iv) change the tape, not the graph. Required artifact, currently zero. Criteria are Implementation, Design, Impact, Idea, all scored off a 3-minute functioning demo, not off node count. Code is already public. Ten hours spent on (i) or (ii) that never appear in the first 90 seconds are invisible. (iv) is the only change that is guaranteed to exist at 2:00 p.m. PDT and that can stop the judge from encoding line 1 and line 8 in the opening shot.
>
> Why (iv) beats (i): (i) is higher ceiling if it lands; expected value in ten hours against three already-failed extract targets is near zero. The tape can use the 61-cue split you already have.
>
> First fifteen seconds, in this order, nothing else:
>
> 1. Two sentences on screen, URLs visible: "Adult programs: Up to 20 characters per second" / "Adult programs: Up to 17 characters per second."
> 2. One Iron Mask cue: same index, pass at 20, fail at 17. Super: 61 cues.
> 3. Cut to the two extract ids and character counts. Say once: "Search found the page. Extract opened it. Python read the sentence. The model did not pick 17."
>
> Do not open on five desks (three empty). Do not open on 179 to 105 HOLD (that is line 8 in second three). Do not say "fixer." Show HOLD later as the honest leftover queue with the cited clause attached. That is the product you actually shipped.

## Verdict on each claim

| Grok's claim | Verdict | Evidence |
|---|---|---|
| `remediate_subtitles` extends out-times, leaves a 1-frame gap, does not rewrite or split | **REAL, and quoted almost exactly** | `measure.py:331` defines it; the docstring at `:339` reads "Never shorten a cue, never create overlaps, leave a 1-frame gap (~42ms at 24fps)", and `:360` repeats the 42ms rationale. Grok described the repair correctly without being told. |
| The repair cannot touch line length, "README: 30 before, 30 after on the 20 cps profile" | **REAL** | `README.md:226`, table row `| Line length | 42 chars | 30 | 30 |`, and `README.md:241`, "extends out-times; it cannot shorten a 45-character line". This is the mechanism behind line 8 surviving and it is our own documented number. |
| An engineer will not find MCP `web_fetch`, Task schema or Monitor in the client | **REAL** | Zero occurrences of `monitor`, `task_run` or `web_fetch` in the non-test Python. Worth noting the surfaces are genuinely available: installed `parallel-web` 1.3.3 exposes `search`, `extract`, `monitor`, `task_run`, `task_group` and `beta` on the client, so this is an unused real surface rather than an invented API. Round 1 had flagged `client.monitor` as a probable hallucination; it is not. |
| One seed run, `is_seed:true`, 516 cues, 179 to 105, both HOLD, buyers `netflix_en_us` / `netflix_templates` only | **REAL** | Live `/api/runs` and `/api/run/iron_mask-69b5d4cf`, read directly. |
| The 13 node Workflow with five desks, a JoinNode, five model-free FunctionNodes and a triage LlmAgent | **REAL** | Live `/api/run/.../graph` returns exactly that node and edge list, every FunctionNode with `runs_model:false`. Built at `cuepass_agents.py:485`. All named ADK symbols exist in the installed `google-adk` 2.8.0. |
| On this run every Netflix threshold is `provenance:"live"`, so the pin is unused | **REAL** | Confirmed in the stored run; the pin lives at `parallel_spec.py:540-567` and is labelled `provenance:"fallback"` when it fires. |
| Amazon, BBC and FCC are "already known-dead for Extract" | **REAL** | The run records a model-written reason for each, e.g. for the FCC, "No measurable closed-captioning quality rules ... could be found on the examined FCC official web pages and PDF documents." |
| "Agent Engine: untouched (Cloud Run + FastAPI)" | **REAL** | Deployed on Cloud Run; the 404 bodies are FastAPI's `{"detail":"Not Found"}`. Nothing runs on Vertex Agent Engine. |
| Line 7 is "wounded, not cleared": two profiles from one buyer satisfy "do not hardcode 17" but not "this feature exists across buyers" | **REAL as an argument, and it is the fair reading** | A judgement rather than a fact, but it concedes precisely what was proven (the numbers did not collapse) and holds only the part that was not (a cross-buyer matrix). This is the honest limit we put to it, returned intact rather than waved away. |
| "Criteria are Implementation, Design, Impact, Idea, all scored off a 3-minute functioning demo" | **UNVERIFIABLE** | A claim about the judging rubric. Not checked against the submission page from here. Round 1 invented named human judges, so treat every statement it makes about who scores and how as unsupported until read off the official page. |
| "guaranteed to exist at 2:00 p.m. PDT" | **UNVERIFIABLE, probably confabulated** | Nobody gave it a deadline time. Do not act on this figure; confirm the real cutoff on the submission page. |
| The five listed "Sources" | **REJECTED** | Unlike the Checkprint and Redslip rounds, where it cited the actual repos, the citations here are unrelated (an AI-manipulation hackathon report, a Jane Street blog post, a Dwarkesh interview, a LinkedIn post, an unrelated repo). Its substantive claims were nonetheless verifiable against the live API and the repo, so the retrieval that mattered happened; the source list is noise and should not be quoted. |

## Where this leaves Cuepass

Its own summary is the accurate one: "The costume objections are dead or
wounded-to-dead. The product objections are the same failure with citations attached."

- **Dead:** line 4 ("illegal to ship") and line 5 (four buyers stapled into one Search).
- **Dead in part:** line 3, on the ADK and single `generate_content` halves. The Agent
  Engine and playbook halves are untouched, correctly.
- **Wounded:** lines 1, 2, 6, 7.
- **Untouched:** line 8, the fixer that leaves a reject, because 105 of 179 remain and
  line length is structurally unrepairable by a retimer. And line 9, the ceiling.

Single highest value fix it named: the video, ranked explicitly above chasing a second
extractable buyer, above running more titles, and above removing the unused pin. Its
reasoning for rejecting the second buyer is sound and is based on evidence already in
the run: three desks have already failed against Extract, so a new publisher inside ten
hours is a research gamble with no fallback.

The concrete instruction is the opening fifteen seconds: lead with the two conflicting
Netflix sentences and their URLs, then one cue that passes at 20 cps and fails at 17
with the 61-cue count, then the two extract ids. Do not open on the five desks with
three empty, and do not open on 179 to 105 HOLD. Present HOLD later as an honest
leftover queue with the cited clause attached.
