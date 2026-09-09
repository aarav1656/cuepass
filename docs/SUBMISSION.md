# Cuepass: Devpost submission copy

Agentic Cinema (Google Cloud + Devpost). Partner track selected on the form: **Parallel**.

Each heading below maps to one field on the Devpost form. Copy the body, not the heading.

---

## Project name

Cuepass

---

## Elevator pitch (200 characters max)

> Subtitle delivery QC with no thresholds in its own code. Parallel reads the limits off the buyer's published page mid-run. On one film, 61 cues pass one Netflix page and fail another.

(183 characters.)

---

## Inspiration

A distributor delivers a finished restoration to a streaming platform, and four weeks later it comes back rejected on caption spec. Cues that run past the platform's reading-speed limit. Cues that flash for a fifth of a second. Lines longer than the platform accepts. Nobody read those cues wrong; nobody measured them before delivery. The re-deliver cycle costs weeks plus a QC vendor invoice, and the person eating it is a localization and accessibility QC lead who currently exports the .srt into a spreadsheet and spot-checks by eye.

The arithmetic isn't the hard part. Characters divided by seconds is arithmetic. The hard part is *which number*, and that turns out not to be a constant at all.

Netflix publishes 20 characters per second on its English (USA) Timed Text Style Guide, and 17 characters per second on its Timed Text Style Guide page for subtitle templates. Two pages, two scopes, two separately citable figures. A tool with `MAX_CPS = 17` compiled into it will confidently pass a file the buyer rejects, and nothing in its output tells you it's measuring against a number somebody typed in once and never revisited.

So we built the thing where the rules aren't in our code.

---

## What it does

Cuepass takes a subtitle track, measures it against thresholds it read off the buyer's own published page during that run, repairs what retiming can repair, re-measures the repaired file to prove it, and hands a human the list it couldn't fix.

The demonstration file is The Iron Mask (1929) from archive.org, 516 cues on an ASR subtitle track. Real file, real defects, downloadable by anyone who wants to check us.

Five buyer desks run concurrently, one per delivery profile rather than per company. Netflix gets two desks because it publishes two figures on two pages. Every threshold that enters a measurement carries three things: its value, the verbatim sentence on the page that states it, and the URL that sentence was read from. Thresholds also carry a provenance of `live`, `fallback` or `unverified`, plus the Parallel `extract_id` and the count of characters the extract returned.

### The contrast, which is the whole argument

On the seeded run `iron_mask-13ef15ee`:

| Profile | Page cited | Reading speed | Violations before / after | Timing before / after | Cues retimed |
|---|---|---|---|---|---|
| `netflix_en_us` | English (USA) Timed Text Style Guide | 20 cps | 118 / 68 | 88 / 38 | 51 |
| `netflix_templates` | Timed Text Style Guide, Subtitle Templates | 17 cps | 179 / 105 | 149 / 75 | 78 |

Same subtitle file. Same code path. Different cited rule, different verdict.

**61 cues are acceptable under one published Netflix page and unacceptable under the other.** The run payload carries both clauses verbatim, both URLs, both scope descriptions, and the 61 cue indices, so you can click the number on the landing screen and filter the sheet down to exactly those cues.

Those two figures are not Netflix contradicting itself, and we won't sell it that way. They're different scopes: one guide governs an English subtitle file for the US catalogue, the other governs a template-derived delivery. Cuepass prints the scope beside the number, because "which page am I being held to" is the question a QC lead is actually asking. Implying a contradiction would be a cheap shot at a spec that's simply layered, and any judge who works on this stuff would spot it in a second.

What matters is that 61 is a number no tool with a hardcoded constant can produce. It exists only because both thresholds were fetched, at runtime, from two different pages, and neither profile is permitted to pin a reading speed of its own.

We lead with the timing pair, 88 to 38, not 118 to 68. Retiming extends out-times; it can't shorten a 45-character line. Putting the 30 line-length failures in the headline would credit the repair with cues it provably cannot touch, so those go in the breakdown and the editorial queue instead.

The "after" numbers come from measuring the repaired file on disk a second time, not from subtracting what the repair believes it fixed. Both tracks download, so the comparison is reproducible rather than assertable.

### What it does not do

Three of the five desks come back empty, and the page says so with the reason and the URLs that desk tried.

- Amazon's global content guide is a PDF behind a help shell. The BBC's subtitle guidelines are client-rendered, so Extract returns 285 characters of page shell. The FCC publishes caption quality rules about accuracy and synchronicity and states no characters-per-second figure at all. There is no four-buyer matrix here, and we're not going to draw one. A missing column with a reason attached is information; a fabricated column is a lie.
- `min_duration_s` is `fallback` provenance on both Netflix profiles, because neither profile page states it. The value is pinned with the General Requirements page URL and that page's exact sentence, and it's labelled as a fallback everywhere it appears, including on screen.
- Parallel Extract does not return identical content for the same URL on every call. We watched one URL return 80,965 characters on one run and 11,627 on a later one, stating none of the same rules. That's precisely why the design pins nothing and re-reads the page every run, recording what it actually read.
- Repair only extends out-times. It can't rewrite text, split a line, or reflow a cue.
- Nobody has used this in production.

---

## How we built it

**Parallel, as a Search then Extract chain, with the model locked out of the numbers.**

`client.search()` returns candidate URLs and snippets. Search is not allowed to produce a number, because a snippet reading "17 characters per second" could have come from a blog restating a spec that changed two years ago. Search output is a menu of pages and nothing else.

`client.extract(urls=[...], session_id=...)` then opens the chosen page and pulls it as markdown, carrying forward the `session_id` that Search returned so the two calls are one piece of agent work rather than two unrelated API hits. Every threshold is parsed out of that extracted text in Python, by `parallel_spec.read_page_thresholds`, and keeps the sentence it came from.

A model never authors a threshold. `SpecChoice`, the schema the desks are required to return, has exactly three fields: `accepted_urls`, `reason`, `rejected`. Not one of them can hold a number. Thresholds enter a measurement only through an evidence ledger keyed by URL, and only `extract_spec_page` writes to that ledger, so a desk that names a page it never opened gets an error instead of a spec.

What the model does decide is genuinely a judgement call: which of the returned URLs is an official spec page rather than a press release or a partner blog, and which candidate to open next when a page turns out to state no rule. A host allowlist alone picks press releases. First-result picks whatever won SEO that morning.

Remove Parallel and there's no product. No key, no run, `ParallelUnavailableError`. There's no cached-constants fallback mode, because a tool quietly swapping in constants would be citing a page it never opened.

**Google Cloud, via a real ADK workflow graph.**

`cuepass_agents.build_workflow()` returns a `google.adk.workflow.Workflow`. START fans out to five `LlmAgent` buyer desks, each holding the two Parallel tools, running concurrently because they're five independent research jobs. A `JoinNode` holds the deterministic half back until every desk reports. Then five `FunctionNode`s that never touch a model: bind the cited specs, measure every buyer, repair every buyer, re-measure every buyer, collect the leftovers. Then one triage `LlmAgent` turns each unfixable cue into an editorial action a spotting editor can act on (`split_cue`, `rewrite_shorter`, `merge_with_next`, `request_waiver`).

The order is fixed by the graph's edges, not by a prompt asking nicely. `graph_shape()` reads the topology off the built graph and `agent.py` records which nodes and tool calls actually fired, so the page shows the declared graph next to the executed one instead of a drawing of what we meant.

Gemini runs on Vertex AI. The service is a FastAPI app on Cloud Run, with seed runs baked into the image so a cold container is never empty, and live runs written to `CUEPASS_RUN_DIR` and listed alongside them.

---

## Challenges we ran into

**A floating point bug that made the product understate its own work by 40 percent.**

An earlier run reported 89 timing violations before repair and 65 after. That 65 was wrong, and wrong in the direction that made us look worse.

SRT stores milliseconds. Subtracting two float seconds does not: `133.79 - 132.99` evaluates to `0.79999999999998295`. A cue the repair had set to exactly 800ms then re-measured as failing an 800ms minimum, by one part in ten to the fourteenth. The sheet was printing rows that read **"0.800 s, limit 0.8, fail"** and **"20.00 cps, limit 20, fail"**, which is the single objection this product cannot survive: flagging a cue that meets the spec.

On the real track, 16 duration cues and 11 reading-speed cues were arithmetic noise. 27 of the 65 reported leftovers weren't leftovers. Comparisons now happen at the precision SRT actually stores, integer milliseconds, and reading speed at the two decimals the sheet prints. The same residue had also left 13 cues failing with no recorded reason, because the leftover explainer and the re-measure disagreed by exactly that amount. The real result is 88 to 38, and all 68 remaining failures now carry a reason.

**A check that could not fail.**

Parallel doesn't return the same Netflix page every run. One run landed on the Subtitle Templates article, which states reading speed and line length but says nothing about minimum duration. `min_duration_s` came back as `None`, the duration check quietly didn't run, and 42 real violations were reported as zero. A zero in a violation column reads as "clean" to anyone glancing at it.

Three things stop it now. Every threshold carries provenance. A check with no threshold reports `None` and never `0`, and its name lands in `checks_not_verifiable`, so the interface is forced to say "not verifiable against the live spec" rather than render a tick. And each desk opens up to four pages, because buyers split their spec across pages.

A related guard came out of the BBC page, where the metadata row `Translator's Name |TN |[Up to 32 characters]` was being read as a 32-character line-length limit and measured against. A number isn't a rule just because it's the right size; the sentence around it has to be about the thing being measured.

**A two-digit timecode fraction that would have been a tenfold error on every cue.**

The archive.org ASR track writes a non-standard two-digit fraction in its timecodes. `00:00:30,95` means 950 milliseconds, not 95. Reading it the obvious way puts every cue duration off by a factor of ten, which would have made the reading-speed numbers meaningless while looking entirely plausible on screen.

**Most buyers don't publish anything a machine can read.**

We went in expecting a buyer matrix and got two usable profiles, both Netflix. PDF behind a shell, client-rendered page, and a regulator that legislates accuracy without ever naming a number. We shipped what's true instead of what we'd sketched.

---

## Accomplishments we're proud of

The 61, and the guard that stops it from becoming decoration. `test_two_profiles_with_the_same_threshold_produce_no_contrast` fails the build if two profiles resolving to the same number are still allowed to produce a contrast row, and `test_netflix_profiles_do_not_share_a_pinned_reading_speed` fails if either profile is given a pinned reading speed it could borrow. The headline comparison can't quietly go vacuous.

The measurement survived an outside check. The orchestrator wrote a from-scratch SRT parser sharing no code with this project and ran it over the same file: 516 cues, 42 under the minimum duration, 30 cues with a line over 42 characters. Both matched Cuepass exactly, including the timecode fraction handling, which is the part we most expected to have got wrong.

77 tests pass. `test_spec_integrity.py` is the suite worth reading, because every test in it guards a bug that actually happened during the build, and each was checked in both directions: bug put back, test confirmed red, bug removed, test confirmed green. That includes the one asserting the model has no field capable of holding a threshold, and the one asserting a URL nobody opened can never become a spec.

We also resisted the better-looking number. 118 to 68 is a bigger drop than 88 to 38 and we're not allowed to use it, because 30 of those failures are line lengths that retiming physically cannot address.

---

## What we learned

A test that can't fail is worse than no test, and the `min_duration_s` bug is the cleanest example we've hit. Every check was green. Forty-two genuine violations were sitting behind a `None` that got treated as a zero, and nothing in the output distinguished "measured, found nothing" from "never measured".

Floating point isn't an abstract hazard. It cost us a quarter of our own repair credit, silently, in the direction that made the product look weaker rather than stronger, which is the direction you never think to check.

The most useful architectural decision was deciding what the model is not permitted to output. Once `SpecChoice` had no numeric field, an entire category of failure became unrepresentable rather than merely unlikely. Letting a model summarize a spec page would have shipped a day sooner and been worth nothing, because the number it emitted would have been unfalsifiable.

And an Extract API that returns different content for the same URL on different calls isn't a defect to work around, it's the reason provenance has to travel with every value. If we'd cached the first good extract and moved on, we'd have built a tool that cites a page it read last week.

---

## What's next

Support IMSC and TTML, not just SubRip, because that's what a modern delivery package actually contains.

Repair at the text level. Splitting a cue and reflowing a line is what clears the 30 line-length failures that retiming can't reach, and right now those only ever become a row in the exceptions file.

Handle the buyers who publish PDFs, since Amazon's guide exists and is readable by a human, just not by Extract as configured today.

Then get it in front of the QC lead whose spreadsheet workflow started this, on a delivery that has an actual deadline attached, and find out which parts of the exceptions file she throws away.

---

## Built with

`python`, `fastapi`, `uvicorn`, `google-adk`, `google-cloud-aiplatform`, `gemini`, `vertex-ai`, `google-cloud-run`, `docker`, `parallel-web`, `parallel-search-api`, `parallel-extract-api`, `pytest`, `javascript`, `archive.org`, `srt`

---

## Try it yourself

**Live app:** https://sixteen-seventeen-387894104564.us-central1.run.app

Opens on the stored run `iron_mask-13ef15ee` at zero clicks, with its `measured_at` timestamp shown. Click the 61 to filter the sheet to exactly the cues that pass one Netflix page and fail the other. Both subtitle tracks and the exceptions file download.

**Repo:** https://github.com/aarav1656/sixteen-seventeen (MIT licence)

**Demo video:** https://youtube.com/@kamal

> **TODO REPLACE** the demo video URL above before submitting. The link is a placeholder and is not the demo video. Do not submit this form while it is still there.

Run it locally:

```bash
git clone https://github.com/aarav1656/sixteen-seventeen
cd sixteen-seventeen
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export PARALLEL_API_KEY=...
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=...

uvicorn app:app --reload --port 8000
```

Without a Parallel key the run raises rather than falling back to constants. Measurement and repair are pure Python in `measure.py` and are unit-tested with no key at all.

```bash
pytest tests.py test_spec_integrity.py test_real_data.py -q   # 77 passed
python seed_run.py                                            # regenerate the landing measurement
```
