# Cuepass: partner wiring

Google ADK and Gemini run the desks. Every threshold they measure against comes from Parallel Search and Extract, via the official `parallel-web` SDK, at runtime, on every run.

## Runtime path

```
POST /run
    ->  five ADK spec desks in parallel (cuepass_agents.py)
    ->  parallel_spec.search_spec_candidates
            Parallel.client.search(...)     URLs only
    ->  parallel_spec.extract_spec_page
            Parallel.client.extract(...)    the page as markdown
    ->  read_page_thresholds                Python, not the model
    ->  measure, retime, re-measure         same check, twice
```

Search is not allowed to produce a number. Extract opens the page. Every threshold on the live path is read from that text. If Parallel cannot produce a cited spec, the run raises. There is no hardcoded `MAX_CPS`: reading speed is never pinned, for either Netflix profile.

Two rules have a pinned fallback, `min_duration_s` and `min_gap_s`, because both sit on Netflix timing pages that neither profile's headline article states or links, and the desk does not always land there. They are `PINNED_FALLBACKS` in `parallel_spec.py`, each carries the Netflix page it is published on and that page's exact sentence, and each comes back with provenance `fallback`, which the interface prints beside the number.

`min_gap_s` is the gap the repair has to leave in front of every cue it lengthens: "Subtitles must have a minimum of 2 frames between them." The repair used to close gaps to a hardcoded one frame, so the repaired file failed the page it had been repaired against. `remeasure_every_buyer` now reads the repaired file back and raises if the repair narrowed any gap below the cited minimum.

## Where it is in code

| Piece | File |
|---|---|
| SDK client | `parallel_spec.py` `_client()` -> `parallel_sdk.Parallel` |
| Search | `parallel_spec.py` `search_spec_candidates` `client.search` |
| Extract | `parallel_spec.py` `extract_spec_page` |
| ADK tools | `cuepass_agents.py` `FunctionTool(search_spec_candidates)` and `FunctionTool(extract_spec_page)` |
| Fail closed | `ParallelUnavailableError` |

## Google

Each desk is an ADK `LlmAgent` on `gemini-2.5-flash`. The model picks which candidate URL is the buyer's page. It never invents a threshold.

The graph is exported at module scope as `cuepass_agents.root_agent`, the name ADK's tooling discovers, and it imports with no credential set.

The graph is a `google.adk.workflow.Workflow` named `cuepass_delivery_desk`: 13 nodes, 16 edges, of which 6 are `LlmAgent`, 5 are `FunctionNode` that call no model, and one is the `JoinNode` that waits for every desk.

```bash
python -c "
import collections, cuepass_agents
g = cuepass_agents.graph_shape()
print(g['workflow'], len(g['nodes']), 'nodes', len(g['edges']), 'edges')
print(collections.Counter(n['kind'] for n in g['nodes']))"
#   cuepass_delivery_desk 13 nodes 16 edges
#   Counter({'LlmAgent': 6, 'FunctionNode': 5, 'BaseNode': 1, 'JoinNode': 1})
```

Live: the sheet header is the cited URL from that run, and `149 -> 75` is a second measure of the repaired file.
