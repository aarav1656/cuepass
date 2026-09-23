# Cuepass

Cuepass checks an SRT subtitle file against a platform's published caption rules, retimes the cues that retiming can fix, measures the repaired file again, and writes out the cues that still need a person. It doesn't keep its own copy of the rules; each run finds the platform's style guide page, reads the limits off it, and keeps the sentence each limit came from.

![Two Netflix profiles measured on one file, with a failing cue shown on its frame](docs/img/live-two-profiles.png)

## Why it reads the page

Netflix publishes two adult reading-speed limits on two current partner help pages, for two delivery scopes:

| Page | Article | Adult | Children's |
|---|---|---|---|
| English (USA) Timed Text Style Guide | `217350977` | 20 cps | 17 cps |
| Timed Text Style Guide: Subtitle Templates | `219375728` | 17 cps | 15 cps |

You can check this yourself:

```bash
for A in 217350977-English-Timed-Text-Style-Guide \
         219375728-Timed-Text-Style-Guide-Subtitle-Templates; do
  echo "== $A"
  curl -sL "https://partnerhelp.netflixstudios.com/hc/en-us/articles/$A" \
    | grep -oE "(Adult|Children.s) programs?: Up to [0-9]+ characters per second" | sort -u
done
```

```
== 217350977-English-Timed-Text-Style-Guide
Adult programs: Up to 20 characters per second
Children’s programs: Up to 17 characters per second
== 219375728-Timed-Text-Style-Guide-Subtitle-Templates
Adult programs: Up to 17 characters per second
Children’s programs: Up to 15 characters per second
```

A checker with one hardcoded limit will pass or fail a file depending on which page its author happened to read. Screenshots of both pages, taken 2026-09-09, are in `docs/problem/evidence/`.

On a real file the difference is large. `data/iron_mask.asr.srt` is the ASR subtitle track for The Iron Mask (1929) from archive.org, 516 cues. Measuring it with only the reading speed changed:

```bash
python - <<'PY'
import measure
srt = open("data/iron_mask.asr.srt").read()
def failing(cps):
    spec = {"max_cps": cps, "min_duration_s": 0.8, "max_line_chars": 42, "max_lines": 2}
    rep = measure.measure_subtitles(srt, spec=spec)
    return rep.summary(), {f["cue_index"] for f in rep.findings_as_dicts()
                           if f["check"] == "reading_speed"}
s20, cues20 = failing(20.0)
s17, cues17 = failing(17.0)
print("20 cps: over reading speed", s20["over_cps_count"], "under min duration", s20["under_duration_count"])
print("17 cps: over reading speed", s17["over_cps_count"], "under min duration", s17["under_duration_count"])
print("pass at 20, fail at 17:", len(cues17 - cues20))
PY
```

```
20 cps: over reading speed 46 under min duration 42
17 cps: over reading speed 107 under min duration 42
pass at 20, fail at 17: 61
```

So 61 cues are fine under one Netflix page and fail under the other. The stored run in `data/runs/iron_mask-69b5d4cf.json` has the full result for both profiles:

| | `217350977` (20 cps) | `219375728` (17 cps) |
|---|---|---|
| All violations, before and after repair | 118 to 68 | 179 to 105 |
| Timing failures, before and after | 88 to 38 | 149 to 75 |
| Cues retimed | 51 | 78 |
| Verdict | HOLD | HOLD |

## How a run works

A run is a `google.adk.workflow.Workflow` built in `cuepass_agents.build_workflow` and exported as `cuepass_agents.root_agent`:

```bash
python -c "
import collections, cuepass_agents as c
print(type(c.root_agent).__name__, c.root_agent.name)
g = c.graph_shape()
print(len(g['nodes']), 'nodes', len(g['edges']), 'edges', collections.Counter(n['kind'] for n in g['nodes']), c.MODEL)"
```

```
Workflow cuepass_delivery_desk
13 nodes 16 edges Counter({'LlmAgent': 6, 'FunctionNode': 5, 'BaseNode': 1, 'JoinNode': 1}) gemini-2.5-flash
```

1. Five spec desks run concurrently, one per delivery profile: `netflix_en_us`, `netflix_templates`, `amazon`, `bbc`, `fcc`. Each is an `LlmAgent` with two tools from `parallel_spec.py`. `search_spec_candidates` calls Parallel Search for candidate URLs, and `extract_spec_page` calls Parallel Extract to fetch a page. The model's only job is to pick which candidate page is the platform's own spec. Its output schema, `SpecChoice`, has no field that can hold a number.
2. `extract_spec_page` only opens URLs that Search returned in the same run, on the hosts listed in `OFFICIAL_HOSTS`. If Search finds nothing on those hosts, it falls back to a URL from `SEARCH_FAILURE_FALLBACK_URLS` and labels the result `seed_fallback`.
3. `read_page_thresholds` pulls the limits out of the extracted text in plain Python: reading speed, line length, lines per subtitle, minimum duration and minimum gap. Each value keeps its verbatim sentence and the URL it came from. A desk may open up to four pages to cover all of them.
4. Minimum duration and minimum gap sit on Netflix timing pages the headline articles don't always link to, so they have pinned values in `PINNED_FALLBACKS`, each with its source page and sentence. They show up as `fallback`, never `live`. Reading speed is never pinned.
5. Five `FunctionNode`s with no model do the rest, all through `measure.py`: bind the cited specs, measure, retime, re-measure the repaired file, and collect what's left. The repair only extends cue out-times into free space and never edits text. `assert_repair_kept_gaps` raises if a repair narrows any gap below the cited minimum.
6. A final `LlmAgent` triages the leftovers into `split_cue`, `rewrite_shorter`, `merge_with_next` or `request_waiver`, with a one-line note for the editor.

If a rule has no threshold, its check reports `None` rather than `0`, and its name goes into `checks_not_verifiable`. For Amazon, the BBC and the FCC the stored run has no citable spec page, and the interface shows the reason each desk gave.

Timing is compared in integer milliseconds, the precision SRT stores, so a cue retimed to exactly 800 ms passes an 800 ms minimum.

`agent.py` drives one invocation and records which nodes and tool calls fired. `runstore.py` stores runs: the seed runs in `data/runs/` ship with the image, and new runs go to `CUEPASS_RUN_DIR`. `app.py` is the FastAPI app. It serves the page, the run API, the repaired SRT downloads, a per-profile exceptions file, and a frame cutter that uses ffmpeg to grab the film frame at a failing cue's in-time.

![The cuepass_delivery_desk graph](docs/img/adk-workflow-graph.png)

## Running it

Python 3.10 or newer (google-adk needs it).

```bash
git clone https://github.com/aarav1656/cuepass
cd cuepass
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --port 8000
```

With no credentials the page still loads the stored Iron Mask run, and these work:

```bash
curl -s localhost:8000/health
# {"status":"ok","service":"cuepass","stored_runs":1,"engine":{"parallel":false,"gemini":false}}
curl -s localhost:8000/api/runs
curl -s localhost:8000/exceptions/iron_mask-69b5d4cf/netflix_templates
curl -s -o cue.jpg localhost:8000/frame/iron_mask-69b5d4cf/netflix_templates/70.jpg   # needs ffmpeg
```

A new run (`POST /run` with an archive.org `identifier`) needs Parallel and Gemini credentials in the environment: `PARALLEL_API_KEY`, plus either `GOOGLE_API_KEY` or `GOOGLE_GENAI_USE_VERTEXAI=true` with `GOOGLE_CLOUD_PROJECT`. Without them it returns a 500 that names the missing credential. Cuepass has no mode that substitutes default thresholds.

`python seed_run.py [archive.org identifier]` regenerates the stored landing run. It exits non-zero if the file it measured has no timing violations.

`scripts/verify_parallel_cli.sh` replays the Search then Extract chain for `netflix_en_us` with `parallel-cli`, if you want to see the Parallel calls outside the app.

## Tests

```bash
pytest tests.py test_spec_integrity.py test_real_data.py -q -rs
node tests_sheet_filter.js
```

Without `PARALLEL_API_KEY`:

```
118 passed, 1 skipped
SKIPPED [1] test_real_data.py:106: PARALLEL_API_KEY not set
```

and the Node script prints 83 `ok` lines followed by `PASS`. The skipped test is the live Search then Extract round trip; everything else runs offline.

Most of `test_spec_integrity.py` guards specific bugs that happened while building this: a check that never ran reporting zero, a metadata row read as a line-length limit, float-second comparisons failing cues that sat exactly at the limit, and a repair that closed gaps to one frame when Netflix asks for two. Each test's docstring describes the bug it covers.

## Layout

```
parallel_spec.py         Parallel Search and Extract, threshold parsing, the evidence ledger
cuepass_agents.py        the ADK Workflow graph and its nodes
agent.py                 runs one invocation and records the executed trace
measure.py               measurement and repair, plain Python
runstore.py              run storage and the read API
archive.py               archive.org fetch
seed_run.py              regenerates the stored landing run
app.py                   FastAPI app, page, frame cutter
data/                    the Iron Mask track and the stored run
docs/                    diagrams, screenshots, evidence captures
scripts/                 parallel-cli verification
```

More on the Parallel and ADK wiring is in [ARCHITECTURE.md](ARCHITECTURE.md), and the page's design tokens are in [DESIGN.md](DESIGN.md).

## License

MIT. See [LICENSE](LICENSE).
