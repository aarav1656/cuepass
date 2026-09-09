# Grok adversarial critique: Cuepass, Parallel track

Multi-turn conversation over the `grokweb` CLI on the x.com transport,
conversation id `cuepass-critique`, model grok-4 with reasoning enabled.
Three completed exchanges, 2026-09-09. Prompts and replies unedited.

A fourth exchange was written and sent and did not complete: the account hit
the x.com Grok quota, "15 Grok 4 questions per 20 hours", and a retry on grok-3
returned the same account-level limit. The unanswered fourth prompt is included
at the end so the conversation can be finished later, and so it is clear it was
asked rather than skipped.

Grok invents API names, so nothing here was acted on before being checked
against the installed `parallel-web` 1.3.3 and `google-adk` 2.8.0 source. The
single most valuable thing it produced was something I would not have found:
that `SequentialAgent`, `ParallelAgent` and `LoopAgent` are all deprecated in
google-adk 2.8 in favour of `google.adk.workflow.Workflow`. That was true.

Note on turn 3: the reply came back with another conversation's header on it
(`Conversation: checkprint-kill | Turn: 3`) and its opening paragraphs answer a
different project's question about loudness and ClickHouse. That is a grokweb
routing fault, not an edit. The sections that answer what was asked, C7 and C8
on ADK topology, are intact and are the parts that were acted on. It is left in
as received.

## Verification log

Every factual claim, checked before use.

| Grok claim | Checked against | Verdict |
|---|---|---|
| `client.search`, `client.extract`, `client.task_run.create`/`.result`, `client.monitor.create` exist | `parallel/_client.py`, `parallel/resources/task_run.py`, `resources/monitor.py` | CORRECT, all present |
| Search returns excerpts only; Extract returns page markdown | `types/search_result.py`, `types/extract_result.py` | CORRECT |
| `session_id` links Search and Extract as one piece of agent work | docstrings on both methods | CORRECT, now used in `parallel_spec.py` |
| Task returns `output.basis` with per-field citations, reasoning, confidence | `types/field_basis.py`, `types/citation.py` | CORRECT |
| Naming a field `source*` in a Task output schema triggers a redundancy warning | not verifiable without running Task | UNVERIFIED, not relied on |
| Task processors run 15s to 10min | not verifiable locally | ACCEPTED as a latency risk, and the reason Task is not shipped |
| SequentialAgent / ParallelAgent / LoopAgent deprecated in favour of Workflow | `@deprecated` decorators in `google/adk/agents/{sequential,parallel,loop}_agent.py` | CORRECT, and it changed the build |
| `Workflow`, `FunctionNode`, `JoinNode`, `START`, `Edge`, `RetryConfig` under `google.adk.workflow` | `google/adk/workflow/__init__.py` | CORRECT |
| A plain callable can be a graph node | `utils/_graph_parser.py`, NodeLike accepts callables | CORRECT |
| `LlmAgent` supports `output_schema` together with `tools` | `agents/llm_agent.py` line 415 note | CORRECT |
| MCP is not on the Parallel track's list of accepted integration paths, so SDK Search is the compliance call | the track requirement text in the brief | CORRECT reading, and followed |

## Acted on

1. **Search may not produce a number.** Search returns candidate URLs; Extract
   opens the page; every threshold is read from the extracted text in Python and
   carries the verbatim sentence. `parallel_spec.py`.
2. **The graph is a real ADK `Workflow`**, model nodes only where a decision is a
   judgement, deterministic FunctionNodes for everything that produces a number.
   `cuepass_agents.py`.
3. **"Illegal" removed.** The verdict is DELIVER or HOLD. A caption style guide is
   a buyer's acceptance criterion, not a statute, and the legal claim was a
   credibility hole with a Google AI-integrity judge.
4. **The leftover cues became the product**, each with the reason retiming could
   not clear it and an editorial action, exported as an exceptions file.
5. **No LLM in the tool loop on a threshold.** Grok's argument that MCPToolset
   deciding the numbers reads worse to a Parallel engineer than SDK calls bound
   by Python was correct and is why the desks' output schema has no numeric field.

## Rejected, with reasons

- **Parallel Task API.** Right tool on the merits: typed output with per-field
  `basis` citations is exactly this job. Wrong tool on latency. Four buyers means
  four runs at 15s to 10min, which makes a judge wait at the one moment they are
  paying attention. Search plus Extract yields the same evidence, URL and page
  text and clause, in seconds.
- **Monitor.** Grok itself called it jewelry and it is. Caption guides do not
  change inside a judging window.
- **Pre-warming Task runs and presenting them as live.** A result already on disk
  is not the live call it would be presented as.
- **A fabricated fourth buyer column.** Grok's B1 winning feature was a four-buyer
  pass or fail matrix. Only Netflix publishes a spec that Extract can actually
  open and read: the BBC's guidelines are client-rendered and return 285
  characters of shell, Amazon's is a PDF behind a help shell, and the FCC
  publishes no reading-speed number at all. The other three are shown as
  unavailable with the reason their desk gave. Grok warned "if all four collapse
  to one number you do not have this feature"; three of them collapsed to no
  number, and the honest report is the product.

---


## Turn 1

Sent 2026-09-09T08:04:54Z, model grok-4.

### Prompt

```text
I am 12 hours from the deadline of the "Agentic Cinema: The Blockbuster Hackathon" (Google + Devpost, agentic-cinema.devpost.com). Be a brutal adversarial judge, not a cheerleader. I need reasons I LOSE.

THE BRIEF (verbatim extracts):
"Build a functional agent powered by Gemini and Google Cloud Agent Builder that integrates a Partner Entity's product or MCP to power a real media & entertainment workflow."
Rules narrow the audience: "solve critical bottlenecks across the entertainment and media value chain, specifically targeting the workflows of filmmakers, screenwriters, studio crews, or fans."
Verbs used: orchestrate, solve enterprise friction, "show off a deterministic, multi-step agent". Not chat.
Explicit Google steer: "build agents natively using the Agent Development Kit (ADK) instead of external wrapper libraries."

JUDGING CRITERIA (4, equally weighted):
1. Technological Implementation: how well built, how effectively it uses Google Cloud AND the Partner services.
2. Design: a complete, coherent product experience, not a technical proof of concept.
3. Potential Impact: credible, specific case for a real problem for a real audience, and does the solution actually address it based on what is demonstrated.
4. Quality of the Idea: creative, non-obvious use of Google Cloud + Partner, and genuine understanding of the problem space.

MY TRACK: Parallel. Hard runtime requirement, verbatim: "Must actively use Parallel's Search API at runtime, via the parallel-web SDK (Py/TS), @parallel-web/ai-sdk-tools, LangChain ParallelWebSearchTool, or Gemini Grounding with Parallel as search provider. README mention does not count." Parallel also ships Extract, Task and Monitor APIs plus an MCP server.

JUDGES: 23 total. On my track: 2 Parallel MTS engineers (working engineers on the product, they will spot a decorative integration instantly), plus ~13 Google engineers and PMs (Cloud SQL, Play Ads, Search Intelligence, AI Integrity, GDC networking, Forward Deployed GenAI). Infra engineers, not media people.

COMPETITION: 28 other repos are verified on this same Parallel track. Five identical prize buckets, one per partner track, top 3 per track win.

MY PROJECT: "Cuepass". An agent that proves a film's subtitles are illegal to ship, then retimes them until they are not.
- Named user: a localization/accessibility QC lead at an indie distributor. The incident: a distributor uploads a finished restoration, four weeks later it comes back rejected because 105 of 516 subtitle cues exceed the Netflix 17 characters/second reading-speed limit. Nobody read them wrong, the numbers were never measured before delivery. Re-deliver cycle costs weeks plus a QC vendor invoice.
- Pipeline: fetch a real public-domain film plus its real .srt from archive.org (2,407 films with real subtitle files) -> Parallel Search fetches the CURRENT published caption spec for Netflix/Amazon/BBC/FCC at runtime and returns a citation URL, so the thresholds (chars per second, min cue duration, max line chars, max lines) are NOT hardcoded -> deterministic measure of every cue against that live spec -> Gemini classifies each violation auto-fixable vs needs editorial review -> deterministic repair extends cue out-times into free space without creating overlaps -> re-measure the repaired file with the SAME check and prove the delta.
- Real verified numbers on The Iron Mask (1929), 516 cues: 149 timing violations before, re-measured to 75 after. 78 cues changed. Line-length violations are honestly reported as not auto-fixable because shortening a line means rewriting text.
- Removing Parallel raises a hard error, there is no silent fallback to constants. Same for Gemini.
- UI: dark spotting-sheet, Anton display type, Space Mono for timecode and cps, mint accent, huge "N to M" verdict pair, the cited spec URL in the header, each failing cue row shows index, timecode, cue text, measured cps and why the retime could not clear it.

WEAKNESSES I ALREADY KNOW: there is currently ZERO ADK, the code calls google-genai generate_content directly. Only Parallel Search is used, none of Extract/Task/Monitor/MCP. The film is a 1929 public-domain ASR subtitle track, not a modern delivery master.

Questions, answer each one specifically and separately:
1. Why will this NOT win the Parallel track? Be brutal. Rank the reasons.
2. What are the other 28 entries on the Parallel track almost certainly doing? Name the archetypes you would bet on, and say which archetype the 2 Parallel engineers will be most tired of seeing by entry 20.
3. How do I not look like them?
4. Where exactly do I lose points against each of the 4 criteria, with the specific sentence a judge would write in the scoring box?

Do not give me a generic "add more polish" answer. Give me the specific failure modes.
```

### Reply

```text
I'll inspect the official brief, Parallel's required APIs, and what's actually showing up on the track so the critique is specific rather than generic.The brief and a few competing repos are enough to see the pattern; next I’ll pull judging language, ADK wording, and Parallel’s product surface.This is a well-made QC script wearing an agent costume. Against 28 Parallel-track repos and a room of product engineers, that costume is what gets scored. Official Parallel ideas are research/fact-check/trend agents; official Google packaging is Gemini + Agent Builder/ADK. Your rules-legal Search call does not change that.

---

## 1. Why this will not win the Parallel track

Ranked by how fast a judge stops taking you seriously.

**1. Parallel is a config fetch, not the product they sell.**  
The hard requirement is Search-at-runtime. You meet the letter. You fail the spirit that the two Parallel MTS engineers are there to enforce. Parallel’s stack is Search → Extract (URL/PDF → markdown) → Task (structured multi-hop research) → Monitor (spec pages that change). You do one Search, display a URL, then run local arithmetic. That is the cheapest possible “we used Parallel” that still compiles. Search snippets are the wrong artifact for numeric thresholds; Extract exists specifically because Search is not a spec parser. A working engineer will open the client, look for `extract` / MCP `web_fetch` / Task schema / Monitor, find none, and write “decorative grounding.”

**2. It is not an Agent Builder agent.**  
The submission object is “a functional agent powered by Gemini and Google Cloud Agent Builder.” Resources explicitly say build natively on ADK, not wrapper SDKs. Rules will not DQ `google-genai` alone — they list `google-adk`, `google-genai`, `google-generativeai`, `google-cloud-aiplatform` as accepted Google packages — but the 13 Google engineers are scoring “how effectively it uses Google Cloud.” Zero ADK, zero Agent Engine, zero playbook, one `generate_content` is a Python job with an LLM in the middle. Competing Parallel repos already show ADK graphs, `LlmAgent`s, Agent Engine, Secret Manager, Cloud Run. You lose the Google half of criterion 1 before they watch the demo.

**3. The demonstrated product does not finish the job you named.**  
Named incident: file rejected, redelivery cycle. Demonstrated result on *The Iron Mask*: 149 timing violations → 75. Half still fail. Line-length left as “needs a human.” So the QC lead still cannot ship, still pays the vendor, still burns the week. Criterion 3 is not “did you measure a real number.” It is “does the solution actually address the problem based on what is demonstrated.” You demonstrated a partial mitigator and a leftover fail pile.

**4. “Illegal to ship” is a credibility kill.**  
Netflix 17 cps is a platform timed-text style rule, not a statute. FCC captioning rules exist; they are not “105 cues over 17 cps = illegal.” Quality-of-idea asks for genuine understanding of the problem space. That verb tells a Google AI-Integrity / Search-Intelligence judge you do not work in this domain. The rest of the writeup then gets read as costume.

**5. Gemini is a checkbox on a function you already wrote.**  
Measure is deterministic. Repair is deterministic. “Auto-fixable vs editorial” is “can I extend out-time into free space without overlap?” That is a boolean from the same pass that does the repair. Paying Gemini to narrate a branch the code already knows makes the model look bolted on — the exact pattern Google PMs are tired of after a summer of hackathons.

**6. Wrong file, wrong spec target, wrong station in the chain.**  
Archive.org 1929 ASR `.srt` is not a delivery master. Real reject loops are IMSC/TTML/ITT/SCC against picture, frame rate, drop-frame, safe area, shot changes, speaker IDs. Netflix/Amazon/BBC/FCC mixed into one live Search is how you get a blog’s 20 cps and a 2019 PDF stapled together. No Ooona/EZTitles/Subtitle Edit/vendor report shape. Indie-distributor QC is a real job; this artifact would not be the file that job opens.

**7. Google Cloud usage is a single SDK.**  
Partner-track winners in this format are usually “Gemini + ADK + one real Cloud surface + partner as a load-bearing tool.” You have Gemini API. That is not “Google Cloud” to a Cloud SQL / GDC / Agent Engine judge sitting next to someone who deployed a workflow graph.

**8. Design is a poster of a fail state.**  
Dark spotting sheet, Anton, Space Mono, mint, huge N→M is craft. The product experience of a QC tool is: ingest the real package, pick a buyer profile, gate ship/no-ship, export the repaired package plus a vendor-shaped exception list. You ship a beautiful sheet that still says 75 fails. Complete product ≠ coherent aesthetic.

**9. 28 other verified Parallel repos exist; three prizes.**  
Originality helps you not die in the first minute. It does not beat an ADK multi-agent that fans Search out per entity and hosts on Agent Engine. You are fighting CinePilot-shaped and clearance-agent-shaped entries with a better niche and a thinner stack.

---

## 2. What the other 28 are almost certainly doing

**Archetypes I would bet on**

1. **Script-to-clearance / rights research.** Parse `.fdx`, extract brands/songs/likenesses, Parallel Search per entity, cite owners, risk rank. This already exists on the track (ADK workflow, Cloud Run, Agent Engine). It is the official “licensing research” prompt made concrete.
2. **Location scout.** Scene headings → Parallel Search for real venues → Gemini ranks → map pins → PDF package. Also already exists. Official-adjacent, photogenic, multi-agent.
3. **Casting / availability / “who is free and what did they just do.”** One Search per character against trades + IMDb-class pages. Looks agentic, citations look native to Parallel.
4. **Claim / fact-check the screenplay or the campaign.** Official idea #2. Gemini extracts claims, Parallel verifies, red/yellow/green dossier.
5. **Greenlight / comps / market brief.** Search box office, genre comps, festival heat, attach a slide.
6. **Music / clip licensing lookup.** Song in scene → current publisher/master owner.
7. **Trend / sentiment watch for P&A.** Official idea #3. A few will actually touch Monitor; most will fake it with one Search.
8. **Fan recommender / “what to watch” chat** with Parallel grounding. Out of audience, still numerous.
9. **Newsroom / trailer-claim verifier** for publicity, not production.
10. **The workshop clone:** Gemini Grounding with Parallel as search provider, inspect `groundingMetadata`, call it an agent. That is what Parallel’s own build session taught.

**What the two Parallel MTS engineers will be sick of by entry 20**

Not location scouts. Not even clearance, if the fan-out is real.

The thing they will be done with:

> One `client.search(objective=...)`, stuff snippets into Gemini, emit a “research brief” with URLs in footnotes, dark cinema UI, README that says “grounded agent.”

That is their own quickstart plus a film noun. It uses Search the way a tutorial uses Search. By entry 20 they are only asking: did you *need* live web, did you go Search→Extract on the actual page, did you fan out, did you structure the output, did you fail closed, or is this Grounding-demo fanfic?

Your project is not that clone. It is the neighboring failure: Search used once to fetch constants for a local algorithm. Different costume, same “we needed a URL” smell.

---

## 3. How you do not look like them

You will not become an ADK multi-agent research mesh in 12 hours. You can stop looking like “Search as seasoning.”

**Do these, in this order, or don’t bother.**

1. **Search is not allowed to produce numbers.** Search may only return candidate spec URLs. Extract (or MCP `web_fetch`) must pull the page/PDF. Thresholds parse from extracted text with the quoted clause stored next to cps/min-duration/max-line. If Extract cannot find a cps rule, hard error. That is the Parallel-shaped pipeline. Search-only thresholding is what they will mock in Slack.

2. **Wrap the existing functions as ADK tools under one `SequentialAgent` / workflow.** Tools: `search_spec_urls`, `extract_spec`, `measure`, `repair`, `remeasure`, `verdict`. Gemini may classify only after Extract+measure, and only where the boolean is not already known. Import `google.adk`. Point the README at `root_agent`. Google judges grep. Without this you look like you ignored the resource guide on purpose.

3. **Kill the word illegal.** Verdict string: `FAIL — 75 cues still exceed Netflix Timed Text Style Guide reading-speed rule as extracted 2026-09-09 from <url>, clause: "…"`. Ship gate is binary: remaining violations > 0 ⇒ not for delivery. Put that on the huge N→M so the poster matches the physics.

4. **Show one modern file.** Keep *Iron Mask* as the regression fixture. Add a second run on a current `.srt`/`.vtt` or, if you can do it without heroics, IMSC/TTML. 1929 ASR as the only demo tells every media-literate skeptic you never saw a delivery package.

5. **Make the leftover 75 the product, not the apology.** Editorial queue: cue index, measured cps, head/tail slack, why retime could not close it, suggested human action (split / rewrite / ignore with waiver). Export `repaired.srt` + `exceptions.json`. That is the QC lead’s actual next action. Right now you advertise a fixer that leaves a reject.

6. **One Cloud surface beyond the Gemini API.** Cloud Run URL or Agent Engine deploy + Secret Manager for the two keys. Rules require a hosted project URL. A local spotting sheet is a proof of concept under criterion 2.

7. **Do not add Extract/Task/Monitor as README jewelry.** If you add Monitor, it watches the spec URL and the next run must use the latest extracted snapshot. If you cannot wire that in 12 hours, don’t mention Monitor.

What *not* to do in the remaining hours: more typefaces, more films from archive.org, a chat sidebar, a second partner API “for completeness,” or a multi-agent org chart that still calls `generate_content` in a for-loop.

---

## 4. Where you lose points — the sentence in the scoring box

Criteria are equally weighted. Assume 1–10. These are the notes, not a pep talk.

### Technological Implementation  
*“Meets Parallel Search runtime rule with a single lookup used as a constants service; no Extract/Task/Monitor/MCP. Gemini is a raw `generate_content` call, not Agent Builder/ADK, so Google Cloud usage is the model API only. Pipeline is competent Python, not an agentic system on the stack we asked for.”*

Deduct for: no ADK/Agent Engine; Search not followed by Extract; Gemini not a tool-using agent; no GCP control plane.

### Design  
*“Coherent QC aesthetic and honest leftover-violation rows, but the experience is a lab report on one public-domain SRT. No ingest of a real timed-text package, no buyer-profile workflow, no ship/no-ship export a distributor could file. Still a polished proof of concept.”*

Deduct for: poster UI around an incomplete gate; 1929-only artifact; missing hosted product loop (upload → profile → repair → package out).

### Potential Impact  
*“Problem is real (platform caption QC reject, redelivery cost). Demonstration does not solve it: 149→75 timing fails, line-length untouched, file still unshippable. Audience is named, artifact is not what that audience delivers. Impact case is a blog post attached to a half-fix.”*

Deduct for: residual fail rate; wrong asset type; overclaim vs demo.

### Quality of the Idea  
*“Non-obvious compared with location/casting/clearance clones, and the fail-closed Parallel/Gemini hooks show some taste. Then they call style-guide fails ‘illegal,’ fetch thresholds from Search instead of extracting the spec, and use Gemini to label a deterministic branch. Understands that QC exists; does not understand timed-text delivery or Parallel’s actual product surface.”*

Deduct for: legal sloppiness; Search-as-config; LLM-on-a-boolean; 1929 ASR as stand-in for a master.

---

**Net:** you lose to a worse idea with a better stack before you lose to a better idea. The brutal read is not “subtitles are a small niche.” It is “you built the only interesting tool on the track and then used Parallel and Google the way a checklist uses them.” Twelve hours will not invent Iyuno. Twelve hours can make Search→Extract the source of truth, put the pipeline behind ADK, and stop claiming a 75-fail file is a pass.
```


## Turn 2

Sent 2026-09-09T08:09:14Z, model grok-4.

### Prompt

```text
Specific follow-up. Do not repeat yourself. I will verify every API name you give against the installed parallel-web Python SDK, so if you invent a method I discard the answer.

A. PARALLEL SURFACE DEPTH
A1. Name Parallel's four APIs (Search, Extract, Task, Monitor) and what each is actually FOR in Parallel's own framing. What does Task return that Search does not, and what is the processor/tier concept?
A2. My job: get the current numeric caption delivery thresholds out of Netflix's Timed Text Style Guide, Amazon's, BBC's and the FCC's pages, WITH the exact sentence stating each number. Which Parallel API is the right tool and why? Is Task with a structured output schema better here than Search then Extract?
A3. If I define a Task output schema of {max_cps, min_duration_s, max_line_chars, max_lines, each with a verbatim quoted clause and its source URL}, is that a legitimate Task use or the same "constants service" smell you criticised? Argue both sides, then pick.
A4. Is Monitor genuinely useful here in a 12-hour window, or jewelry? Do not tell me to add it if it is jewelry.
A5. What is the Parallel MCP server and what tools does it expose? If I wire it through ADK MCPToolset so a Gemini agent CALLS Parallel as a tool instead of my Python calling it as a library, does that read better or worse to the two Parallel MTS engineers?

B. THE ONE FEATURE THAT WINS
B1. Assume I fix the stack (Search then Extract with quoted clauses, real ADK multi-agent, ship gate not "illegal", exceptions export). What is the ONE feature that makes a Parallel engineer stop scrolling? One thing, argued.
B2. Nobody else on this track can make this move: because my thresholds are LIVE, the SAME FILE can pass for one buyer and fail for another, and the verdict flips when a platform revises its spec. Is that the winning feature or just a reframing of what I have? If it wins, what is the exact demonstrable artifact in a 3 minute video?
B3. Honest ceiling. Perfect execution in 12 hours: top 3 on this track, or strong fourth? Give the number.
```

### Reply

```text
I’ll verify Parallel’s current SDK method names and Task/Monitor/MCP contracts before answering so nothing is invented.Verify these names on the wheel before you write anything:

```python
from parallel import Parallel
c = Parallel()
assert hasattr(c, "search") and callable(c.search)
assert hasattr(c, "extract") and callable(c.extract)
assert hasattr(c.task_run, "create") and hasattr(c.task_run, "result")
assert hasattr(c.monitor, "create")
```

Official current Python is `client.search(...)`, `client.extract(...)`, `client.task_run.create(...)`, `client.task_run.result(...)`, `client.monitor.create(...)`. Package `parallel-web>=1.0.1`, import `from parallel import Parallel`. If your install only has `client.beta.search`, you are on the legacy `/v1beta` path; docs say new integrations use `/v1`. Do not use `client.search.create`, `client.task.create`, or `client.extract.create` unless `dir()` shows them.

---

## A1. The four APIs

Parallel’s own table: Search = one round-trip, objective + keyword queries → LLM-optimized excerpts. Extract = URL → clean markdown (JS pages and PDFs), after you already have the URL. Task = multi-hop research agent, seconds to hours, “cited structured output; answers you can't get in one search.” Monitor = scheduled natural-language query + webhook on change.

**Task returns what Search does not:** a `run_id`, then `output.content` shaped to your spec, plus `output.basis` — per-field `citations`, `reasoning`, `confidence`. Search returns `results[]` with `url` / `title` / `excerpts`. No schema, no basis.

**Processors** are Task execution engines, not Search modes. Any run can use any processor. Documented guidance: `lite`/`base` for simple enrichment, `core` for accuracy up to ~10 fields, `pro`/`ultra` when depth matters. Field/latency bands: `lite` ~2 fields, 10s–2min; `base` ~5 fields, 15s–3min; `core`/`core2x` ~10 fields, 1–10min; `pro` ~20 fields, 2–10min; `ultra` and `ultra2x`/`4x`/`8x` deeper, minutes to hours. You pay per successful run.

---

## A2. Right tool for numbers + the sentence

**Task is the right tool for the typed object. Search then Extract is the right tool for pinning that object to a page you can defend. You need Search in the path because the track rule names Search, not Task.**

Search alone cannot give you a verbatim clause from the official guide. It returns excerpts. Partner PDFs and style-guide pages are why Extract exists. Extract alone cannot emit `{max_cps: 17, clause: "..."}` with per-field evidence; it returns markdown. Task is the API they describe as: submit an objective, it plans retrieval, fetches URLs, returns JSON that matches your schema, with basis on every field. That is enrichment, which they document as a first-class Task job.

Practical chain:

1. `client.search(objective=..., search_queries=[...])` once per buyer. Queries stay 3–6 word keywords. No `site:` operator (their Search best-practices forbid it in the tool schema).
2. Pick a URL from `search.results` against an official-host allowlist. No match → hard error. No constant cps.
3. `client.task_run.create` with that URL in `input`, `processor="core"` if the schema is ~8 fields, `processor="base"` if you split to ~4 fields. Block with `client.task_run.result(run_id, api_timeout=3600)`.
4. Keep `client.extract(urls=[chosen], objective="reading speed characters per second, minimum cue duration, maximum characters per line, maximum lines")` as the exhibit: the markdown the judge can scroll. Task is the typed verdict input. Extract is the page.

Four buyers = four Task runs, not one nested mega-schema. Their processor table is field-count guidance; nesting four buyers is how you eat `core` latency and schema warnings.

Do not run `ultra` in a 3-minute video. Pre-warm the four `base`/`core` runs. On camera, Search + Extract is the live call. Task results are already on disk with visible `run_id`s. Kick one fresh `base` run only if it finishes inside the remaining time.

---

## A3. That schema — both sides, then pick

**Your schema as written is half-legal and half against their own spec.**

They already return citations on `output.basis`. Putting `citations`, `source`, `sources`, `source_urls`, `reasoning`, `confidence`, or `evidence` in `output_schema` is a documented warning: redundant, worse-structured, less reliable than built-in basis. So `{max_cps, min_duration_s, max_line_chars, max_lines, each with clause AND source URL}` will get you that warning the moment a field is named like a source. Drop the URL fields. Keep four numbers and four `quoted_clause` strings. Read URL + excerpt from `output.basis[i].citations`.

**Side that says legitimate:** this is their enrichment quickstart with different nouns. Input = buyer + official URL from Search. Output = missing numeric fields. Basis supplies the sentence and the URL. That is the worked example in their docs (“founding date,” “employee count”), not a hack.

**Side that says constants-service smell:** if Task runs once, you stash the JSON, and every later file is measured against that cache, Task was a boot-time config fetch. Same smell as Search-for-17. If Search is skipped and Task is allowed to wander onto a 2019 blog, you also lose the “official page” claim.

**Pick:** Task with a flat schema of the four numbers + four clauses is legitimate **if and only if** (1) Search selected the URL that went into `input`, (2) URLs come from `basis`, not from schema fields named `source*`, (3) a missing field or low `basis.confidence` hard-fails that buyer profile instead of substituting a constant. Cache the `run_id` and the extract markdown next to the numbers so a judge can replay the evidence. Re-run Task when the operator hits “refresh specs,” not only at process start.

---

## A4. Monitor in 12 hours

Jewelry. Do not add it.

Monitor’s job is “continuous tracking (news, regulatory, competitive watchlists).” Frequency is `1h`–`30d`. First run is at create, then on the schedule. Caption style guides do not move in a 3-minute video or a 12-hour judging peek. MCP does not even expose Monitor; only CLI/SDK do. A snapshot monitor needs a completed Task `run_id` and then waits for the JSON to change. `client.monitor.trigger` can force an off-schedule run; it will almost certainly return the same snapshot. That is a create-call for the README.

The buyer-to-buyer flip is the change you can show today. A platform revision flip is a sentence in the writeup, not a demo.

---

## A5. MCP, and whether ADK-MCPToolset helps

Two hosted servers: Search MCP `https://search.parallel.ai/mcp` tools **`web_search`**, **`web_fetch`** (Search + Extract). Task MCP `https://task-mcp.parallel.ai/mcp` tools documented as **Create task**, **Create group**, **Get result**. Monitor is SDK/CLI only. Search MCP may be used anonymously; production use is Bearer `PARALLEL_API_KEY`.

Track letter: Search must be used via `parallel-web` SDK, `@parallel-web/ai-sdk-tools`, LangChain `ParallelWebSearchTool`, or Gemini Grounding with Parallel as provider. MCP is not on that list. Treat SDK `client.search` as the compliance call. MCP as the only Parallel path is a rules risk.

To the two MTS engineers: **MCPToolset as the thing that decides the numbers is worse.** That is their chat/workshop shape: Gemini picks URLs, Gemini reads `web_fetch`, Gemini invents 17. Your product’s claim is deterministic measure against a cited clause. An LLM in the tool loop on the threshold is the failure mode they built Task basis to avoid.

**SDK Search → allowlist → Task/Extract, wrapped as ADK `FunctionTool`s, is better.** The agent orchestrates; Python binds the evidence; Gemini does not author cps.

Use MCP only if you want a side-by-side “agent can also ask Parallel in English” panel that is clearly not on the measurement path.

---

## B1. The one feature

**The same file scored live against four buyer profiles, producing a pass/fail matrix where each cell is a number taken from Task `content` plus the clause and URL taken from Task `basis`.**

That is the only thing on this track that uses Parallel the way the company sells it: web research as an operational input to a gate, not as a paragraph generator. Location scouts and clearance dossiers produce text. You produce a ship/no-ship that changes when the cited page says a different number. An MTS engineer stops because they can audit `run_id` → `basis.citations[0].url` → clause → measured cps → FAIL without trusting Gemini.

---

## B2. Live thresholds / same file / different buyers

That **is** the winning feature if the video shows the matrix, not if you only narrate it. “Verdict flips when Netflix revises the guide” is framing you cannot prove in three minutes. Do not spend demo time on a revision that does not occur.

Exact artifact to film:

1. One SRT on screen (`The Iron Mask` or the modern file, not both in the first 30 seconds).
2. Four-column header filled from live Task/Extract results: buyer, `max_cps`, quoted clause (one line), source URL, `run_id`.
3. Four verdicts on that same file, e.g. Netflix FAIL 149 / Amazon PASS *n* / BBC FAIL *m* / FCC PASS *k* — real counts, not invented. If two buyers return the same cps, say so; a fake spread is worse than a thin spread.
4. Click one FAIL cell → cue row + measured cps + the clause that cell was scored against.
5. Export: `exceptions.netflix.json` vs `exceptions.amazon.json` and a binary ship gate per buyer.

If Amazon and Netflix collapse to the same 17, the matrix still works if min-duration or max-line-chars differ. If all four collapse to one number, you do not have this feature. Then the feature is dead and you are a well-built QC script. Check the four extracts **before** you cut the video.

---

## B3. Ceiling

**4th.**

Perfect 12-hour execution makes you the best *compliance-shaped QC tool* on the track. First through third will still go to an ADK research agent that fans Search out across many entities and looks like the official Parallel prompt list, unless two of those are hollow. You can steal 3rd if the matrix is real and their Search calls are single-shot briefs. Do not budget as 3rd. Budget as 4th with a punchers’ chance at 3rd. Not 1st.
```


## Turn 3

Sent 2026-09-09T08:11:27Z, model grok-4.

### Prompt

```text
Verified so far against the installed parallel-web 1.3.3 wheel: client.search, client.extract, client.task_run, client.task_group, client.monitor, client.beta all exist. Extract signature is client.extract(urls=[...], objective=..., search_queries=[...], advanced_settings={...}, session_id=...) returning ExtractResponse with results[].excerpts, .full_content, .publish_date, .title, .url, plus errors[], extract_id, session_id, usage, warnings. Search returns SearchResult with results[], search_id, session_id. session_id is documented as the way to link search and extract calls in one larger task. So your Search-then-Extract chain is real and I am building it. I am checking task_run.create/result and output.basis next.

Now: GOOGLE ADK. You have live retrieval, so tell me what is actually shipping right now, not what the docs said a year ago. google-adk 2.8.0 is what I have installed. Answer each separately and name real symbols with real import paths, because I will read the installed source before I write anything and discard your answer if you invent one.

C1. In current google-adk, what are the actual orchestration primitives? I believe: LlmAgent, SequentialAgent, ParallelAgent, LoopAgent, BaseAgent. What are their real import paths and what does each one actually do to the invocation?
C2. output_key state passing. How does an LlmAgent write into session state, and how does the next agent in a SequentialAgent read it? What is the exact template syntax in an instruction string to interpolate prior state?
C3. sub_agents delegation versus AgentTool. What is the real behavioural difference, when should I use each, and which one keeps control deterministic?
C4. FunctionTool. If I have a plain python function that calls parallel-web's client.search, what exactly does ADK need from it (type hints, docstring, return shape) for the LlmAgent to call it reliably? Does returning a dict matter?
C5. Callbacks and planners. Which callbacks exist and which one would I use to capture, for a UI, the exact sequence of agent -> tool -> result that actually ran, so I can render the real topology instead of a drawing of it?
C6. Runner. InMemoryRunner versus Runner with a session service. What is the minimal correct way to run a root agent once from inside a FastAPI request handler and collect the final output plus the intermediate events?
C7. Judging reality check: what are winning ADK projects actually shipping right now? What does a real ADK multi-agent look like versus the fake version where someone wraps one generate_content call in an LlmAgent and calls it a multi-agent system? Give me the tell that a Google engineer uses to spot the fake in 10 seconds.
C8. Given my pipeline (Search picks candidate spec URLs, Extract pulls the official page, thresholds parsed with verbatim clause, deterministic measure, deterministic repair, deterministic re-measure, then classification of leftovers into editorial actions, across FOUR buyer profiles for the same file), what is the correct ADK topology? Where exactly does ParallelAgent belong, where does SequentialAgent belong, and which steps must NOT be an agent because they are deterministic?
```

### Reply

```text
I’ll inspect the live ADK 2.8 source and current docs so the import paths and primitives match what you have installed.ADK 2.8 shifted toward `Workflow`; I’ll confirm which 1.x names still exist in that wheel and the exact state/tool/runner symbols.Confirm these on the wheel before you type. In 2.8.0 the public package exports `Agent`, `Context`, `Event`, `Runner`, `Workflow` from `google.adk`. `google.adk.agents` still exports `LlmAgent`, `SequentialAgent`, `ParallelAgent`, `LoopAgent`, `BaseAgent`. `SequentialAgent` / `ParallelAgent` / `LoopAgent` are **deprecated in favor of `Workflow`** and still run. A Google 2.x engineer will notice if you only ship the deprecated trio and never a `Workflow` or a `FunctionNode`. Use the old trio only if `Workflow` edges fight you in the remaining hours.

```python
import google.adk, google.adk.agents, google.adk.tools, google.adk.runners, google.adk.sessions
print(google.adk.__all__ if hasattr(google.adk, "__all__") else dir(google.adk))
print([n for n in dir(google.adk.agents) if n[0].isupper()])
print([n for n in dir(google.adk.tools) if "Tool" in n or "MCP" in n])
print([n for n in dir(google.adk.runners) if "Runner" in n])
```

---

## C1. Orchestration primitives

Real symbols in 2.8.0:

```python
from google.adk import Agent          # alias of LlmAgent
from google.adk.agents import (
    BaseAgent,
    LlmAgent,
    SequentialAgent,
    ParallelAgent,
    LoopAgent,
)
from google.adk import Workflow       # 2.x graph runtime
```

| Class | What it does on invoke |
|---|---|
| `LlmAgent` / `Agent` | Calls the model. Model may emit text and/or function calls. Tools run. Loop until the model stops calling tools or hits a limit. **The model decides the next step.** |
| `SequentialAgent` | Runs `sub_agents` **in list order**. No model on the shell. Shared session state. Deterministic order. Deprecated, still works. |
| `ParallelAgent` | Runs `sub_agents` concurrently (`asyncio.gather` in the 2.8 source). Isolated branches, then join. No model on the shell. Deprecated, still works. |
| `LoopAgent` | Repeats `sub_agents` until a sub-agent calls `exit_loop` / escalates or `max_iterations`. Set `max_iterations`. |
| `BaseAgent` | Abstract. Override `_run_async_impl` and `yield` `Event`s. Use this for a deterministic Python step that is *not* an LLM and *not* a tool-of-an-LLM. |
| `Workflow` | Graph: agents, tools, and plain functions as nodes + edges. This is what 2.8 advertises. Fan-out is multiple edges from `START`, not `ParallelAgent`. |

`Agent` is the documented alias of `LlmAgent`. Prefer `LlmAgent` in names so a judge can grep “LLM vs workflow.”

---

## C2. `output_key` and `{key}`

`LlmAgent(..., output_key="netflix_spec")` writes the agent’s **final response** into `session.state["netflix_spec"]`. If `output_schema` is set, the **parsed** object is stored, not the raw string. The write is applied by the `Runner` when it commits the event’s `state_delta`.

Next agent in a `SequentialAgent` reads it two ways:

1. Instruction template: `{netflix_spec}` is replaced from `session.state` **before** the model call. Missing key raises. `{netflix_spec?}` is the documented optional form (no raise).
2. Inside a tool: `tool_context.state["netflix_spec"]`.

There is no other magic interpolation. `{buyer}` only works if something already wrote `state["buyer"]` — `create_session(..., state={...})`, a prior `output_key`, a tool writing `tool_context.state`, or `state_delta` on `run_async`.

Do not use `output_key` as a JSON bus for Parallel payloads if the agent also chatters. Give that agent `output_schema` (Pydantic) so state holds a dict. Docs note tools on the same agent as `output_schema` are a bad mix.

---

## C3. `sub_agents` vs `AgentTool`

**`sub_agents=[...]` on an `LlmAgent`:** the parent gets `transfer_to_agent`. The **model** chooses the child. Control leaves the parent. Siblings cannot transfer to each other. This is LLM routing. Non-deterministic.

**`AgentTool`:**

```python
from google.adk.tools import AgentTool
```

Wraps a child agent as a **tool**. The parent model calls it like a function, gets a result, continues. The child runs in the same invocation; the parent stays in charge of the next token.

**Deterministic control is neither.** Deterministic control is `SequentialAgent` / `ParallelAgent` / `Workflow` / `BaseAgent._run_async_impl` / a Python function you call yourself. Those do not ask Gemini who goes next.

Use `sub_agents` transfer only if you want a receptionist. Use `AgentTool` if a parent LLM must optionally invoke a specialist. For Cuepass, use **neither** on the measure/repair path.

---

## C4. `FunctionTool` / raw functions

Python ADK auto-wraps a plain function in `tools=[fn]`. Explicit wrap:

```python
from google.adk.tools import FunctionTool
FunctionTool(func=search_buyer_spec)
```

What the schema builder actually reads (inspect the function, not folklore):

- **Name** = `fn.__name__`
- **Description** = docstring. Google-style `Args:` descriptions become property descriptions.
- **Parameters** = type-hinted named params. No hint → junk schema. `**kwargs` is historically stripped; do not use it.
- Optional params = default value or `X | None`.
- You may add `tool_context: ToolContext` as a parameter. It is **not** sent to the model; ADK injects it.

Return shape: JSON-serializable. `dict` is what the after-tool callback type and the model loop expect. A `str` gets wrapped. Return a dict with stable keys (`status`, `urls`, `search_id`, `session_id`, `error`). Do not return a Parallel SDK object.

```python
def search_buyer_spec(buyer: str, objective: str) -> dict:
    """Find current official caption-delivery spec URLs for one buyer.

    Args:
        buyer: One of netflix, amazon, bbc, fcc.
        objective: Natural-language search goal including the quantities needed.

    Returns:
        Dict with status, search_id, session_id, and results (url, title, excerpts).
    """
```

Keep Parallel I/O inside the function. The LLM should only see `buyer` / `objective` (or just `buyer` if you own the objective string).

---

## C5. Callbacks and the real topology

On `LlmAgent` (and mirrored on plugins):

- `before_agent_callback` / `after_agent_callback` — `CallbackContext`
- `before_model_callback` / `after_model_callback` — request / `LlmResponse`
- `before_tool_callback` / `after_tool_callback` — `BaseTool`, `args`, `ToolContext`, result
- Also present in current callback docs/plugins: `on_model_error_callback`, `on_tool_error_callback`, `on_event_callback`

**For a UI trace, do not rely on callbacks as the source of truth.** Consume the event stream from `runner.run_async`. Every agent step, tool call, and tool result is already an `Event`. Inspect in your wheel:

```python
getattr(event, "author", None)
getattr(event, "get_function_calls", lambda: None)()
getattr(event, "get_function_responses", lambda: None)()
getattr(event, "is_final_response", lambda: False)()
getattr(event, "actions", None)
```

`after_tool_callback` is useful to **copy** `tool.name`, args, and result into a list you attach to the HTTP response. Pair it with the event stream. `planner=` (`BuiltInPlanner`, `PlanReActPlanner`) is the wrong hook for this pipeline; it adds thought tokens, not topology.

---

## C6. `Runner` in FastAPI

Python 2.8 public surface is `from google.adk import Runner`. `InMemoryRunner` is first-class in TS/Kotlin; in Python the usual pattern is `Runner` + `InMemorySessionService`. Confirm `InMemoryRunner` on `google.adk.runners` before importing it.

Minimal handler:

```python
from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

session_service = InMemorySessionService()  # module singleton, not per request
runner = Runner(agent=root_agent, app_name="cuepass", session_service=session_service)

async def run_once(user_id: str, session_id: str, text: str) -> dict:
    await session_service.create_session(
        app_name="cuepass", user_id=user_id, session_id=session_id
    )
    events = []
    final = None
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=Content(role="user", parts=[Part(text=text)]),
    ):
        events.append(event)
        if event.is_final_response() and event.content and event.content.parts:
            final = event.content.parts[0].text
    session = await session_service.get_session(
        app_name="cuepass", user_id=user_id, session_id=session_id
    )
    return {"final": final, "state": dict(session.state), "events": events}
```

Create one `Runner` at process start. Per-request `InMemorySessionService()` loses the point of a service and still is not durable. For judging, in-memory is fine. `InMemoryRunner` if present is only a shortcut that builds those services for you.

---

## C7. Fake vs real, 10-second tell

**Fake:** `root_agent = LlmAgent(..., tools=[one_fn]);` or `LlmAgent` whose only job is to call `generate_content`. One author in the event log. Zero `SequentialAgent`/`Workflow`/`FunctionNode`. README says “multi-agent.” `planner=PlanReActPlanner` on a linear pipeline.

**Real (what 2.8 samples and the ADK 2 codelab push):** a `Workflow` or `SequentialAgent` whose **nodes include functions that never touch a model**, plus `LlmAgent` only where a model must choose or phrase. Event log shows multiple `author` values and `function_call` / `function_response` pairs in a fixed order that matches the graph, not a chat.

The 10-second grep: open the event list. If the first model call happens **before** Search/Extract/measure have already produced state, it is a chatbot with extra files. If measure/repair appear as tool/function-node results **with no model event between them**, it is an agentic workflow.

---

## C8. Topology for your pipeline

**Root: `SequentialAgent` (or `Workflow` with the same edges).** Not an `LlmAgent`.

```
Sequential:
  1. ParallelAgent  — four buyer profiles
        each branch: Sequential
           Function/tool: search_buyer   # client.search, writes session_id
           Function/tool: extract_buyer  # client.extract(session_id=...)
           Function/tool: parse_thresholds  # clauses + numbers; hard fail
  2. Function: measure          # NOT an agent
  3. Function: repair           # NOT an agent
  4. Function: remeasure        # NOT an agent
  5. LlmAgent: classify_leftovers   # ONLY leftovers → editorial actions
     output_schema + output_key="editorial"
```

**`ParallelAgent` belongs in exactly one place:** the four buyers. Their Search/Extract/Task work does not share intermediate state. Give each branch distinct `output_key`s (`netflix_spec`, `amazon_spec`, …).

**`SequentialAgent` belongs in two places:** (a) inside each buyer: Search → Extract → parse, (b) the outer pipeline after the join: measure → repair → remeasure → classify.

**Must not be agents:** measure, repair, remeasure, URL allowlist, cps arithmetic, overlap checks. Implement as `FunctionTool`s invoked by a thin `BaseAgent`/`FunctionNode`, or call them in `BaseAgent._run_async_impl` and `yield Event`. If an `LlmAgent` is allowed to “decide” to skip remeasure, you are back to theater.

**May be an `LlmAgent`:** leftover classification (split / rewrite / waiver copy). Bind it with `output_schema`. Do not let it call Search.

**Do not:** `LoopAgent` on the happy path; `sub_agents` transfer; `AgentTool` of the whole pipeline; `planner=` on the root; MCPToolset on the measurement path.

If you can wire `Workflow` in time, encode that same graph as edges and put measure/repair/remeasure in `FunctionNode`s. That is the 2.8-shaped screenshot. If `Workflow` costs you two hours, ship `SequentialAgent` + `ParallelAgent` and say in the README they are the 2.8-deprecated workflow agents wrapping deterministic tools. That is still a real ADK multi-agent. One `LlmAgent` with four Parallel tools is the fake.
```


## Turn 4, sent and unanswered

Blocked by the x.com Grok quota. Included so the question is on record.

### Prompt

```text
Turn 4. Two things, and I need concrete answers because I ship in a few hours.

FIRST, YOU WERE RIGHT AND I VERIFIED IT. SequentialAgent, ParallelAgent and LoopAgent all carry @deprecated("in favor of Workflow") in the installed google-adk 2.8.0, and google.adk.workflow does expose Workflow, FunctionNode, JoinNode, START, Edge, RetryConfig. I built the graph on Workflow edges: START fans out to four LlmAgent buyer desks, a JoinNode waits for all four, then five FunctionNodes that never touch a model (bind_cited_specs, measure, repair, remeasure, collect_leftovers), then one LlmAgent that triages leftovers with an output_schema. Search then Extract with a shared session_id is live and working. Thresholds are read from extracted page text in Python and each carries the verbatim sentence; the desks' output schema has no numeric field at all, so a model cannot author a threshold.

SECOND, YOUR B1 WINNING FEATURE HAS PARTIALLY COLLAPSED AND I NEED YOUR CALL. The buyer matrix does not work, for a reason that is about the world and not my code. I verified with live Extract calls:
- Netflix: works perfectly. partnerhelp.netflixstudios.com Timed Text Style Guide General Requirements yields all four rules with quotable sentences: "Adult programs: Up to 20 characters per second", "Subtitles should not be any shorter in duration than 20 frames (or 4/5 sec).", "42 characters per line", "2 lines maximum".
- BBC: bbc.github.io/subtitle-guidelines is client-rendered. Extract returns 285 characters of page shell. No rules.
- Amazon: the Prime Video spec is a PDF behind a help shell. Extract got 2369 chars of navigation. No rules.
- FCC: 10154 chars extracted, but the FCC genuinely publishes no reading-speed number. Its caption rules are about accuracy, synchronicity, completeness and placement.
- I also tried DCMP captioning key, Ofcom, Apple video asset guide and YouTube help. None yielded a numeric rule my reader could take with a defensible sentence.

So right now the product cites ONE buyer, and shows the other three as "no citable spec page" with the reason their research desk gave. Questions:
B1a. Is one cited buyer plus three honestly-reported failures better or worse, to the two Parallel MTS engineers, than four columns where three came from a blog restating a spec? Answer plainly.
B1b. Netflix's own page states BOTH "Adult programs: Up to 20 characters per second" AND a lower limit for children's programmes, on the same page, with two separate quotable sentences. Is "same file, two delivery profiles from one cited page, different verdict" a real substitute for the buyer matrix, or is it a consolation prize a judge will see through?
B1c. Is there a buyer I have not tried whose caption spec is on a static crawlable page with explicit numbers? Name specific URLs. I will Extract each one and keep only what actually yields a rule.
B1d. Given the collapse, what is the single strongest sentence to lead the product with now?

THIRD, THE UI. This is a CINEMA hackathon and I am told my current interface is not premium enough. It is a dark spotting sheet: Anton for display type, Space Mono for timecode and cps, mint #3cffd0 as the only accent on near-black #131313, 2px radius, a huge "89 to 65" pair in Anton, the cited spec URL in the header, and a list of failing cue rows with index, timecode, cue text, measured cps and why the retime could not clear it.
C1. What does a premium, cinema-grade interface for subtitle compliance actually look like, as opposed to a competent spotting sheet? Be concrete about layout and hierarchy, not adjectives.
C2. The artefact here is a cue: a timecode range, a piece of text, and a reading speed that is too high for the time it is on screen. How do I render THAT as the interface, so the thing on screen is the subtitle failing rather than a table row about a subtitle failing?
C3. What single element would make a judge screenshot it?
C4. Name the specific things in what I described that read as generic or templated, and what to replace each with.
```
