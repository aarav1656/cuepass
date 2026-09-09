## Parallel CLI verify (deepener)

Cuepass uses the `parallel-web` SDK at runtime. The same Search then Extract chain can be replayed from the shell with `parallel-cli`:

```bash
# install (one of)
brew install parallel-web/tap/parallel-cli
# or: pipx install "parallel-web-tools[cli]" && pipx ensurepath
# or: curl -fsSL https://parallel.ai/install.sh | bash

export PARALLEL_API_KEY=...   # https://platform.parallel.ai
./scripts/verify_parallel_cli.sh
```

The script searches Netflix partner-help hosts with the same objective family as `netflix_en_us`, prints `search_id` / `session_id` / ranks, then Extracts the first official-host URL. Exit non-zero if Search returns no official host or Extract is empty.

## Live Parallel pytest

```bash
export PARALLEL_API_KEY=...
pytest test_real_data.py -k parallel_search_then_extract -q
```

Without the key that test is skipped. With the key it must pass: Search returns a `session_id`, Extract opens a citable page, and at least one threshold is read from the page text.
