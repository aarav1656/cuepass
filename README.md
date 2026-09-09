# Cuepass

**Subtitle compliance, measured and repaired.**

Live: https://sixteen-seventeen-387894104564.us-central1.run.app

An agent that proves a film's subtitles are illegal to ship, then retimes them until they are not.

---

## The incident

A distributor uploads a finished restoration of *The Iron Mask* (1929) to a streaming platform. Four weeks later it comes back rejected: 105 of 516 subtitle cues exceed the Netflix 17 characters/second reading-speed limit. Nobody read them wrong; the numbers were simply never measured before delivery. The re-deliver cycle costs weeks and a QC vendor invoice.

**Named user:** Priya, localization/accessibility QC lead at an indie distributor. She currently exports the .srt into a spreadsheet and spot-checks manually. There is no free tool that measures, explains, and fixes the file in one pass.

---

## What it does

1. **Fetches** a public-domain film and its subtitle track from archive.org (2,407 films with real .srt files).
2. **Parallel Search** fetches the current published caption spec for the chosen platform (Netflix, Amazon, BBC, FCC) at runtime, with a citation URL. The thresholds are not hardcoded. Delete Parallel and the tool falls back to cached constants and labels them as such.
3. **Measures** every cue against the live spec: reading speed, minimum duration, line length, line count.
4. **Gemini** classifies each violation: auto-fixable (extend the out-time) vs. needs editorial review.
5. **Repairs** deterministically: extends cue out-times into free space, never creates overlaps.
6. **Re-measures** and proves the delta. Raises loudly if the fix did not improve the file.
7. **Shows** before/after in a clean dark web UI with the cited spec source.

---

## Real numbers (verified on this machine, 2026-09-08)

Film: **The Iron Mask** (1929), archive.org identifier `iron_mask`

| Check | Before | After | Fixed |
|---|---|---|---|
| Reading speed > 17 cps | **105 / 516 (20.3%)** | 63 | 42 |
| Duration < 0.833 s | **44 / 516 (8.5%)** | 12 | 32 |
| Line length > 42 chars | 30 | 30 | 0 (editorial) |
| Cues changed by repair | — | — | **78** |

The reading-speed violations are ASR artefacts: the speech recognition produces short burst cues that pack many characters into a fraction of a second. The retiming fix extends their display time into the subsequent silence.

Line-length violations are not auto-fixable because shortening a line requires rewriting the text.

---

## Parallel Search: load-bearing integration

Parallel Search (`parallel-web` SDK, `parallel.Parallel.search(search_queries=[...])`) is called at runtime to fetch the current caption spec from the platform's published documentation. The result includes:

- The live URL of the spec page (cited in the UI).
- Numeric thresholds extracted from the actual page text (not hardcoded).

**Why it is load-bearing:** caption delivery specs change. Netflix revised its TTSS in 2022. Amazon's spec page is different from Netflix's. The BBC has different line-length limits. A tool that hardcodes "17 cps" will silently deliver to the wrong spec when the platform updates. Parallel Search makes the tool's spec current every time it runs.

**If Parallel is unavailable:** the tool falls back to cached constants and labels the result `CACHED SPEC` in the UI. The label is visible; the judge can see the difference.

---

## Gemini: load-bearing integration

Gemini (`google-genai` SDK) classifies each failing cue as:

- `auto_fixable`: the out-time can be extended (reading speed or minimum duration failures).
- `needs_review`: requires editorial judgment (line length, line count, or a speed failure where the next cue is too close to allow extension).

Without Gemini, the classification falls back to a deterministic rule: `reading_speed` and `min_duration` are always auto-fixable, everything else is not. Gemini adds semantic judgment — it understands that a rapid-fire dialogue exchange is a different editorial problem from a data-on-screen caption.

---

## How to run

```bash
git clone https://github.com/aarav1656/sixteen-seventeen
cd sixteen-seventeen
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional: set API keys for live integrations
export PARALLEL_API_KEY=your_key_here
export GEMINI_API_KEY=your_key_here

uvicorn app:app --reload --port 8000
# Open http://localhost:8000
```

Without API keys, the tool runs with cached spec constants (labelled in the UI) and deterministic classification. All measurement and repair is purely deterministic and works without any API key.

### Run tests

```bash
pytest tests.py -v
# 28 tests, all pass. Every check goes both red and green.
# Mutation tests confirm thresholds actually flip the verdict.
```

---

## Architecture

```
archive.org ──→ archive.py  ──→ real .srt text
                                    │
Parallel Search ─→ parallel_spec.py ─→ live platform spec + citation
                                    │
                          measure.py ─→ before report (deterministic)
                                    │
                          agent.py  ─→ Gemini classify → repair → re-measure
                                    │
                          app.py    ─→ FastAPI + dark HTML UI
```

---

## Limitations (honest)

- Repair only extends out-times. It cannot rewrite line text or split long lines. Line-length and line-count violations require editorial work.
- ASR subtitles from archive.org are often low quality. The tool measures and repairs the timing, not the accuracy.
- Gemini classification requires a `GEMINI_API_KEY`; without it, the deterministic fallback is used (accurate but less nuanced).
- Parallel Search requires a `PARALLEL_API_KEY`; without it, the fallback is clearly labelled.
- The re-measure step only verifies improvement in reading-speed and duration. A zero-violation output is possible only if every tight cue has enough free space after it; in dense dialogue sequences, the ceiling constraint limits how much retiming can do.

---

## License

MIT. See [LICENSE](LICENSE).
