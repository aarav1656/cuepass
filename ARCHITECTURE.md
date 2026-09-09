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

One rule has a pinned fallback, `min_duration_s`, because neither Netflix profile's own page states it and the desk does not always land on a page that does. It is `PINNED_FALLBACKS` in `parallel_spec.py`, carries the Netflix page it is published on and that page's exact sentence, and comes back with provenance `fallback`, which the interface prints beside the number.

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
