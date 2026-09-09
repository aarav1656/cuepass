# Cuepass

**Subtitle delivery QC that reads the buyer's spec off the buyer's own page, then proves the repair.**

Live: https://sixteen-seventeen-387894104564.us-central1.run.app

An agent that measures a film's subtitle track against the caption spec a platform
published, repairs what retiming can repair, re-measures to prove it, and hands a
human the list it could not fix.

Built for the Agentic Cinema hackathon, Parallel track. Google Cloud via Gemini on
Vertex AI and `google-adk`. Partner via the `parallel-web` SDK, Search and Extract.
Partner wiring: `ARCHITECTURE.md`.

---

## The incident

A distributor delivers a finished restoration to a streaming platform. Four weeks
later it comes back rejected on caption spec: cues that exceed the platform's
reading-speed limit, cues that flash on screen for a fifth of a second, lines
longer than the platform accepts. Nobody read them wrong. The numbers were never
measured before delivery.

The re-deliver cycle costs weeks plus a QC vendor invoice. The named user is a
localization and accessibility QC lead at an indie distributor, who today exports
the .srt into a spreadsheet and spot-checks by eye. Nobody has used this in
production yet; that is stated plainly rather than dressed up.

## The part that is actually hard

Not the arithmetic. Characters divided by seconds is arithmetic.

The hard part is **which number**. A caption spec is not a constant. Netflix
publishes two different adult reading-speed limits on two different pages for two
different delivery scopes, 20 and 17 characters per second, both verified live
below. Amazon, the BBC and the FCC publish different rules again, in different
units, and some publish no machine-readable rule at all. A tool with
`MAX_CPS = 17` hardcoded in it will confidently pass a file the buyer rejects, and
nothing in its output tells you it is measuring against a number somebody typed in
2019.

So Cuepass goes and reads the figure instead of carrying one. Every threshold on
the live path is read out of a page Parallel Extract opened during that run, and
every threshold travels with the verbatim sentence that states it and the URL
that sentence lives on. Where a rule is not published on the profile's own page,
the value is pinned to the buyer's page that does state it, labelled `fallback`
everywhere it appears and linked to that page.

Exactly one rule has a pinned fallback, the minimum on-screen duration, and
reading speed is never pinned for either Netflix profile. That is why the
contrast below is a live-fetch result rather than an artefact of this repository,
and `test_netflix_profiles_do_not_share_a_pinned_reading_speed` fails the build
if anyone changes it.

---

## What one run does

```
                     Parallel Search            Parallel Extract
                     candidate URLs             the page itself
                            |                          |
   START                    v                          v
     |-- netflix_en_us_spec_desk     (LlmAgent, two Parallel tools) --+
     |-- netflix_templates_spec_desk (LlmAgent, two Parallel tools) --+
     |-- amazon_spec_desk            (LlmAgent, two Parallel tools) --+--> spec_desk_join
     |-- bbc_spec_desk               (LlmAgent, two Parallel tools) --+          |
     |-- fcc_spec_desk               (LlmAgent, two Parallel tools) --+          v
                                               bind_cited_specs   (no model)
                                                       v
                                               measure_every_buyer     (no model)
                                                       v
                                               repair_every_buyer      (no model)
                                                       v
                                               remeasure_every_buyer   (no model)
                                                       v
                                               collect_leftovers       (no model)
                                                       v
                                               triage_leftovers   (LlmAgent)
```

That is a real `google.adk.workflow.Workflow`, built in `cuepass_agents.py:build_workflow`.
The desks run concurrently, one per delivery profile, because each is an
independent research job; a
`JoinNode` holds the deterministic half back until every desk reports. `graph_shape()`
reads the topology off the built graph, and `agent.py` records which nodes and tool
calls actually fired, so the page can show the declared graph beside the executed
one rather than a drawing.

One desk per delivery **profile**, not per company: Netflix gets two because it
publishes two figures for two scopes, and measuring against both is the point.

---

## Parallel is two surfaces, and it is load-bearing

**Search finds candidate pages. Search is not allowed to produce a number.**
`client.search()` returns URLs and snippets. A snippet saying "17 characters per
second" could have come from a blog restating a spec that changed. Cuepass treats
Search output as a menu of pages, nothing more.

**Extract opens the page.** `client.extract(urls=[...], session_id=...)` pulls the
actual page as markdown, carrying the `session_id` Search returned so the two calls
are one piece of agent work. Every threshold on the live path is read from that
extracted text by `parallel_spec.read_page_thresholds`, in Python, and keeps the
sentence it was read from.

**A model never authors a threshold.** The desks decide which page is authoritative
and which candidate to open next when a page turns out not to state a rule. That is
a genuine judgement: a host allowlist alone picks press releases, and first-result
picks whatever won SEO that day. But `SpecChoice`, the desks' output schema, has
exactly three fields, `accepted_urls`, `reason`, `rejected`, and not one of them can
hold a number. Thresholds enter a measurement only through an evidence ledger keyed
by URL, which only `extract_spec_page` writes to, so a desk that names a page it
never opened gets an error rather than a spec. `test_the_model_is_never_asked_for_a_threshold`
and `test_a_url_nobody_opened_cannot_become_a_spec` hold that line.

**Remove Parallel and there is no product.** No key, no run: `ParallelUnavailableError`.
There is no cached-constants mode, because a tool that silently swaps in constants
would be citing a page it never read.

### The demonstration: 61 cues that are legal on one Netflix page and not on another

Netflix publishes more than one reading-speed figure, on more than one page, for
different scopes. Cuepass runs a separate desk for each, and each desk cites the
page it read:

| Profile | Cited page | Reading speed | The sentence on that page |
|---|---|---|---|
| Netflix, English (USA) | `articles/217350977` | **20 cps** | "Adult programs: Up to 20 characters per second" |
| Netflix, Subtitle Templates | `articles/219375728` | **17 cps** | "Adult programs: Up to 17 characters per second" |

Same film, same code, same run. **118 violations under the first, 179 under the
second. 61 cues are acceptable under one published Netflix page and unacceptable
under the other.**

That number cannot exist in a tool with `MAX_CPS = 17` compiled into it. It is
the whole argument for fetching the spec at runtime, and it is the reason the
clause and the URL travel with every threshold.

**These two figures are not Netflix contradicting itself.** They are different
scopes: one is the English (USA) style guide, the other is the guide for
template-derived delivery. Cuepass prints the scope beside the number, because
which page you are held to is the actual question a QC lead is asking, and
implying a contradiction would be a cheap shot at a spec that is simply layered.

A comparison is only drawn when the two cited pages genuinely differ. Two
profiles resolving to the same number produce no contrast row at all, guarded by
`test_two_profiles_with_the_same_threshold_produce_no_contrast`. Neither profile
is allowed to pin a reading speed, so neither can borrow the other's figure and
manufacture the difference, guarded by
`test_netflix_profiles_do_not_share_a_pinned_reading_speed`.

### What one run cited, 2026-09-09

Every value below was read live off the page named, and is stored in
`data/runs/*.json` with its `extract_id`.

Netflix, English (USA) Timed Text Style Guide
(`partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-Timed-Text-Style-Guide`):

| Rule | Value | The sentence it was read from | Read from |
|---|---|---|---|
| Reading speed | 20 chars/sec | "Adult programs: Up to 20 characters per second" | `articles/217350977` |
| Line length | 42 chars | "42 characters per line" | `articles/217350977` |
| Lines per subtitle | 2 | "2 lines maximum" | `articles/215758617` |
| Minimum duration | 0.8 s | "Subtitles should not be any shorter in duration than 20 frames (or 4/5 sec)." | `articles/360051554394` |

All four are `live`: read this run, off a page Parallel Extract opened this run.
None of them is a pinned constant.

**A spec is spread across pages, and the last two rows are that happening.** The
English (USA) style guide states the reading speed and the line length but not the
line count or the minimum duration, so the desk kept opening pages until it had
all four, and each threshold kept the page it was actually read from. That is why
every value carries its own URL rather than inheriting the profile's headline
citation, and why the interface links each number to the page behind it rather
than to one page for the whole spec.

The pinned-fallback mechanism exists for when that does not work, and it did not
fire on this run. It covers one rule, `min_duration_s`, because neither Netflix
profile's own page states it and the desk does not always land on a page that
does. When it fires the value is labelled `fallback` everywhere it appears,
carries the URL and exact sentence of the page it is published on, and is never
silently a constant. Reading speed is never pinned for either profile. The pinned
values are `PINNED_FALLBACKS` in `parallel_spec.py`; there is nothing else.

Amazon, BBC and the FCC are shown as **no citable spec page**, with the reason
their desk gave, including the URLs it tried. That is not a bug being hidden. The
BBC's subtitle guidelines are client-rendered, so Extract returns 285 characters
of shell; Amazon's global content guide is a PDF behind a help shell; the FCC
publishes caption quality rules about accuracy and synchronicity and states no
reading-speed number at all. A missing column with a reason is information. A
fabricated column would be a lie, and the reason it is not there is that nobody
published a number to put in it.

### The same answer three times, off partly different pages

Parallel Extract does not return identical content for the same URL on every
call. One run pulled 80,965 characters from the General Requirements page and
read all four rules off it; a later extract of that same URL returned 11,627
characters and stated none of them. That is the honest operating condition, and
it is why every stored run carries its own `extract_id`, character count and
clauses rather than a standing claim about what a page says.

The interesting part is what happened anyway. Three consecutive live runs during
this build resolved to **the same four thresholds and produced identical counts**,
having reached them through partly different pages: one run took the reading
speed off `articles/215758617`, the next two off `articles/217350977`, and all
three arrived at 20 cps and 118 violations before repair, 68 after.

Convergence through different routes is a stronger signal than a stable fetch
would have been, because it means the desks are finding the rule rather than
finding one page. Only the most recent run is kept in `data/runs/`; the counts
above are reproducible by running `python seed_run.py` again.

The desks also open more than one page each: three for the English (USA) profile,
two for Subtitle Templates, because neither profile's own page carries all four
rules. `source_urls` records every page that contributed, and each threshold's
`from_profile_page` flag says whether it came off the profile's headline citation
or off one of the others.

---

## Real numbers

Film: **The Iron Mask** (1929), archive.org `iron_mask`, 516 cues, subtitle track
`iron_mask.asr.srt`. One run, the same file, measured against both cited profiles.

The page opens on **Subtitle Templates**, because it is the stricter of the two and
the run that shows the most is the one worth leading with. So these are the numbers
on screen at zero clicks:

| Check | Limit read off the page | Before repair | After repair |
|---|---|---|---|
| Reading speed | 17 chars/sec | **107** | 63 |
| Minimum duration | 0.8 s | **42** | 12 |
| of which out-time not after in-time | | 2 | 0 |
| Line length | 42 chars | 30 | 30 |
| Lines per subtitle | 2 | 0 | 0 |
| **Timing total** | | **149** | **75** |
| All violations | | 179 | 105 |

78 cues retimed. Verdict: **HOLD**.

And the same file against **English (USA)**, whose page states 20 chars/sec:

| Check | Limit read off the page | Before repair | After repair |
|---|---|---|---|
| Reading speed | 20 chars/sec | **46** | 26 |
| Minimum duration | 0.8 s | **42** | 12 |
| Line length | 42 chars | 30 | 30 |
| **Timing total** | | **88** | **38** |
| All violations | | 118 | 68 |

51 cues retimed. Verdict: **HOLD**.

98 cues fail at least one profile, every one carrying the reason retiming could
not clear it, and the first 40 carrying an editorial action from the triage agent.

The "after" numbers come from running the same check a second time against the
repaired file on disk, not from subtracting what the repair thinks it fixed. Each
profile gets its own repaired track, and both those and the source are
downloadable, so the comparison can be reproduced rather than believed.

**The headline pair is the timing total, 149 to 75 on the leading profile.** Not
179 to 105. Retiming extends out-times; it cannot shorten a 45-character line.
Putting the 30 line-length failures in the headline would credit the repair with
cues it provably cannot touch. They are carried in the breakdown and in the
editorial queue instead.

Note that the reading-speed row is the only one that differs between the two
tables. Minimum duration, line length and line count are identical, because both
pages state the same limits for those. A four-column matrix where every column
said the same thing would be decoration; this one earns its second column on one
rule, and says so rather than implying more.

### The bug that made this number worse than it is

An earlier run of the English (USA) profile reported 89 to 65 where it now reports
88 to 38. That 65 was wrong, and wrong in the direction that made the product look
weaker.

SRT stores milliseconds. Subtracting two float seconds does not: `133.79 - 132.99`
is `0.79999999999998295`. A cue the repair had retimed to exactly 800ms then
re-measured as failing an 800ms minimum, by one part in ten to the fourteenth. The
sheet printed rows reading **"0.800 s, limit 0.8, fail"** and **"20.00 cps, limit
20, fail"**. On the real track that put 16 duration cues and 11 reading-speed cues
back into the after-count: **27 of the 65 reported leftovers were arithmetic noise**,
understating the repair by 40 percent, and inviting the one objection this product
cannot survive, that it flags a cue which meets the spec.

Comparisons now happen at the precision SRT actually stores, integer milliseconds,
and reading speed at the two decimal places the sheet prints. The same fault had
also left 13 cues failing with no recorded reason, because the leftover explainer
and the re-measure disagreed by the same residue. Both are gone: on that profile
68 cues still fail, 105 on the stricter one, and every one of them carries a
reason.

### How the counting works, because two honest parsers disagree

A cue shorter than the minimum duration is reported **once**, as a minimum-duration
failure. Its reading speed is not also reported, because extending it to the
minimum is the same single repair, and reporting both would count 20 cues twice.

This matters when comparing against an independent parser. Counting every
positive-duration cue over the limit gives a higher reading-speed number than
counting only those long enough to be measured for reading speed. Both are
defensible; Cuepass does the second, and says so, because the total it feeds is a
count of repairs needed rather than a count of rule breaches.

Two cues in this file have an out-time at or before their in-time. They are a real
defect in the source, reported as `non_positive_duration` rather than as "0.0
seconds", and nothing divides by them.

---

## A check that never ran is not a passing check

This is the bug that mattered most during the build, and the guard against it is
the thing worth reading in the code.

Parallel does not return the same Netflix page every run. One run landed on the
"Subtitle Templates" article, which states reading speed and line length but not
minimum duration. `min_duration_s` came back as None, the duration check quietly
did not run, and **42 real violations were reported as zero**. A zero in a
violation column reads as "clean" to anyone looking at it.

Three things now stop that:

1. Every threshold carries a **provenance**: `live` (read off a page this run),
   `fallback` (the buyer's published value, pinned in code *with the page and the
   sentence it appears on*, used only to fill a gap), or `unverified` (no value at
   all).
2. A check with no threshold reports **`None`, never `0`**, and its name lands in
   `checks_not_verifiable`. The interface has to say "not verifiable against the
   live spec". It cannot render a tick.
3. Each desk now opens up to four pages to cover all four rules, because buyers
   split their spec across pages. Every threshold keeps the URL it came from.

A related guard came out of the BBC page. The metadata row
`Translator's Name |TN |[Up to 32 characters]` was being read as a 32-character
line-length limit and measured against. A number is not a rule because it is the
right size: the sentence it sits in has to be about the thing being measured.

---

## What the page shows without being asked

Cuepass opens on a real prior measurement, at zero clicks. `data/runs/` holds a run
produced by `python seed_run.py`, which drives the same graph against the same file
and writes down whatever came out. It carries `measured_at` and the page shows it.
Nothing on the landing screen is typed by hand, and when no run is stored the page
says so rather than drawing one.

Persistence is two layers, in `runstore.py`. Seed runs are baked into the image, so
a cold container is never empty. Runs finished by a live container are written to
`CUEPASS_RUN_DIR` (`/tmp` on Cloud Run, whose filesystem is read-only elsewhere)
and listed alongside the seeds. The source and repaired tracks are stored next to
the record, so a download link still resolves after the process that made it is gone.

## Where a human takes over

Retiming clears what free space allows. Everything left gets a reason from the same
arithmetic the repair ran (`no free space`, `min duration boxed in`, `line too
long`) and then an action from the triage agent: `split_cue`, `rewrite_shorter`,
`merge_with_next`, `request_waiver`, with one clause a spotting editor can act on.

That is the exceptions file, and it is a download, not a screenshot. Each row
carries the cue, the measured value, the limit, **the sentence from the buyer's own
page that set that limit**, and the action. It is the artefact the QC lead sends on.

Verdicts are `DELIVER` and `HOLD`, not legal or illegal. A caption style guide is a
buyer's acceptance criterion, not a statute.

---

## How to run

```bash
git clone https://github.com/aarav1656/sixteen-seventeen
cd sixteen-seventeen
python3 -m venv .venv && source .venv/bin/activate   # Python 3.10+, ADK needs it
pip install -r requirements.txt

export PARALLEL_API_KEY=...
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=...          # or export GOOGLE_API_KEY=...

uvicorn app:app --reload --port 8000
```

Without either credential the run raises. Measurement and repair themselves are
pure Python in `measure.py` and are unit-tested with no key at all.

Regenerate the landing measurement:

```bash
python seed_run.py            # or: python seed_run.py <archive.org identifier>
```

It exits non-zero if the run it produced has no timing violations, because a
landing page that opens on a clean file demonstrates nothing.

### Tests

```bash
pytest tests.py test_spec_integrity.py test_real_data.py -q     # 97 passed, 1 skipped
node tests_sheet_filter.js
```

The one skip is the live Parallel round trip in `test_real_data.py`, which needs
`PARALLEL_API_KEY`. Everything else runs with no credential.

`test_spec_integrity.py` is the suite worth reading. Every test in it guards a bug
that actually happened, and every one has been checked in both directions: the bug
put back, the test confirmed red, the bug removed, the test confirmed green.

| Guard | Break it by | Goes red |
|---|---|---|
| A check that never ran reports None, not 0 | making `summary()` return the count anyway | `test_unmeasured_check_never_reports_zero` |
| A number needs a sentence about the rule | making `_clause_is_about` return True | `test_number_in_an_unrelated_sentence_is_not_a_rule` |
| The default title must fail | pointing `DEFAULT_FILM` at the 14-cue trailer | `test_default_film_is_a_track_that_fails` |
| A contrast needs two genuinely different specs | letting `_contrasts` compare equal thresholds | `test_two_profiles_with_the_same_threshold_produce_no_contrast` |
| Neither profile may pin a reading speed | adding `max_cps` to the pinned fallbacks | `test_netflix_profiles_do_not_share_a_pinned_reading_speed` |
| Minimum duration is the only pinned rule, and every pin is citable | pinning a second rule, or emptying a pin's clause | `test_min_duration_is_the_only_pinned_rule_and_every_pin_is_cited` |
| A pinned value reaches the page as `fallback`, never as `live` | making `spec_from_ledger` label the pin `live` | `test_a_pinned_threshold_is_never_labelled_live` |
| Only a page Extract opened becomes a spec | letting `spec_from_ledger` accept any URL | `test_a_url_nobody_opened_cannot_become_a_spec` |
| The model has no field for a threshold | adding `max_cps` to `SpecChoice` | `test_the_model_is_never_asked_for_a_threshold` |
| A cue repaired to exactly the limit passes | comparing float seconds again | `test_a_cue_exactly_at_the_limit_passes` |
| The repair and the re-measure agree | comparing float seconds again | `test_repair_output_remeasures_without_phantom_failures` |

---

## Files

```
parallel_spec.py    Parallel Search then Extract; reads thresholds with their
                    verbatim clause; the evidence ledger
cuepass_agents.py   the ADK Workflow graph, its nodes and their output schemas
agent.py            drives one invocation, records the executed trace, shapes the run
measure.py          all measurement and repair; pure Python, no model
runstore.py         durable runs, the read API the web layer calls
archive.py          archive.org fetch
seed_run.py         regenerates the landing measurement
app.py              FastAPI and the interface
```

## Honest limits

- Repair only extends out-times. It cannot rewrite text, split a line or reflow a
  cue. Line-length and line-count failures are reported and queued, never "fixed".
- Only Netflix currently yields a citable machine-readable spec, across two of its
  published pages. Amazon, the BBC and the FCC are shown as unavailable with the
  reason and the URLs their desk tried. Their pages are client-rendered, are PDFs
  behind a help shell, or state no numeric rule. So the comparison is between two
  Netflix profiles, not between two companies, and it is labelled as such.
- Parallel Extract does not return identical content for the same URL on every
  call. A profile can therefore resolve a rule on one run and report it missing on
  the next. Each run records what it actually read.
- The demonstration file is a 1929 public-domain feature with an ASR subtitle track,
  because it is a real file with real defects that anyone can download and check. It
  is not a modern delivery package, and Cuepass measures SubRip, not IMSC or TTML.
- Nobody has used this in production.
- `min_duration_s` is derived at 24fps when a page states frames without a rate.
  Netflix states both the frame count and the fraction, and the fraction wins.
- `min_duration_s` is also the one rule with a pinned fallback, because neither
  Netflix profile's own page states it. When the fallback fires the number is not
  live: it is pinned in `parallel_spec.PINNED_FALLBACKS` with the Netflix page
  that publishes it and that page's exact sentence, and labelled `fallback` in the
  payload and on screen. Every other threshold, on every run, is live or is not
  measured at all.

## License

MIT. See [LICENSE](LICENSE).
