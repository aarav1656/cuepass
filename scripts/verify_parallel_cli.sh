#!/usr/bin/env bash
# Cuepass Parallel CLI verify: one live Search then Extract against Netflix hosts.
# Mirrors parallel_spec.search_spec_candidates + extract_spec_page for netflix_en_us.
#
# Install parallel-cli (pick one):
#   brew install parallel-web/tap/parallel-cli
#   pipx install "parallel-web-tools[cli]" && pipx ensurepath
#   curl -fsSL https://parallel.ai/install.sh | bash
#
# Auth:
#   export PARALLEL_API_KEY=...   # from https://platform.parallel.ai
#
# Usage (from repo root or anywhere):
#   ./scripts/verify_parallel_cli.sh
#
# Exit: 0 ok, 2 bad input / missing CLI, 3 auth, 4 API / empty official hosts.

set -euo pipefail

# Prefer PARALLEL_API_KEY. If unset, accept an active parallel-cli OAuth login
# (parallel-cli auth shows "Active: stored credentials").
if [[ -z "${PARALLEL_API_KEY:-}" ]]; then
  AUTH_OUT="$(parallel-cli auth 2>&1 || true)"
  if ! printf '%s' "$AUTH_OUT" | grep -Eqi 'Active:|stored credentials|Organization:'; then
    if [[ ! -f "$HOME/.config/parallel-web-tools/auth.json" ]]; then
      echo "No PARALLEL_API_KEY and parallel-cli is not authenticated. Export a key or run: parallel-cli login" >&2
      echo "$AUTH_OUT" >&2
      exit 3
    fi
  fi
  echo "PARALLEL_API_KEY unset; using parallel-cli stored OAuth credentials."
  echo "$AUTH_OUT" | head -5
fi

if ! command -v parallel-cli >/dev/null 2>&1; then
  echo "parallel-cli not on PATH. Install with brew / pipx / parallel.ai/install.sh (see script header)." >&2
  exit 2
fi

OBJECTIVE="Find Netflix partner help Timed Text Style Guide pages that state adult characters per second subtitle reading speed limits"
Q1="Netflix Timed Text Style Guide characters per second"
Q2="Netflix partnerhelp English Timed Text Style Guide"
Q3="Netflix subtitle templates reading speed cps"
DOMAINS="partnerhelp.netflixstudios.com,help.netflix.com,netflix.com"
OUT_DIR="${TMPDIR:-/tmp}/cuepass-parallel-cli-$$"
mkdir -p "$OUT_DIR"
SEARCH_JSON="$OUT_DIR/search.json"
EXTRACT_JSON="$OUT_DIR/extract.json"

echo "== parallel-cli auth =="
parallel-cli auth || true

echo "== Search (netflix_en_us hosts) =="
# --session-id groups Search and Extract; CLI may mint or accept one.
SESSION_ID="cuepass-verify-$(date +%s)"
parallel-cli search "$OBJECTIVE" \
  -q "$Q1" -q "$Q2" -q "$Q3" \
  --include-domains "$DOMAINS" \
  --max-results 10 \
  --mode fast \
  --session-id "$SESSION_ID" \
  --client-model "cuepass-verify-cli" \
  --json -o "$SEARCH_JSON"

python3 - "$SEARCH_JSON" "$SESSION_ID" <<'PY'
import json, sys
path, fallback_session = sys.argv[1], sys.argv[2]
data = json.load(open(path))
# CLI JSON shapes vary: top-level results or nested.
results = data.get("results") or data.get("search", {}).get("results") or []
search_id = data.get("search_id") or data.get("search", {}).get("search_id") or ""
session_id = data.get("session_id") or data.get("search", {}).get("session_id") or fallback_session
print(f"search_id: {search_id or '(missing)'}")
print(f"session_id: {session_id or '(missing)'}")
print(f"results: {len(results)}")
official = []
for i, r in enumerate(results, 1):
    url = r.get("url") or ""
    title = r.get("title") or ""
    print(f"  rank {i}: {title[:80]}")
    print(f"           {url}")
    host = url.split("/")[2] if "://" in url else ""
    if any(h in host for h in ("partnerhelp.netflixstudios.com", "help.netflix.com", "netflix.com")):
        official.append((i, url, title))
if not official:
    print("NO official-host URL in Search results", file=sys.stderr)
    sys.exit(4)
rank, url, title = official[0]
open(path + ".pick", "w").write(json.dumps({"rank": rank, "url": url, "title": title, "search_id": search_id, "session_id": session_id}))
print(f"picked official rank {rank}: {url}")
PY

PICK=$(python3 -c 'import json; print(json.load(open("'"$SEARCH_JSON"'.pick"))["url"])')
PICK_SESSION=$(python3 -c 'import json; print(json.load(open("'"$SEARCH_JSON"'.pick"))["session_id"])')
PICK_SEARCH=$(python3 -c 'import json; print(json.load(open("'"$SEARCH_JSON"'.pick")).get("search_id",""))')
PICK_RANK=$(python3 -c 'import json; print(json.load(open("'"$SEARCH_JSON"'.pick"))["rank"])')

echo "== Extract (session-linked) =="
# Prefer session linkage when the CLI accepts it.
set +e
if parallel-cli extract --help 2>&1 | grep -q -- '--session-id'; then
  parallel-cli extract "$PICK" \
    --objective "Extract adult and children characters-per-second subtitle reading speed limits and on-screen duration rules with exact sentences" \
    --session-id "$PICK_SESSION" \
    --full-content \
    --json -o "$EXTRACT_JSON"
  EXTRACT_RC=$?
else
  parallel-cli extract "$PICK" \
    --objective "Extract adult and children characters-per-second subtitle reading speed limits and on-screen duration rules with exact sentences" \
    --full-content \
    --json -o "$EXTRACT_JSON"
  EXTRACT_RC=$?
fi
set -e
if [[ $EXTRACT_RC -ne 0 ]]; then
  echo "Extract failed with exit $EXTRACT_RC" >&2
  exit 4
fi

python3 - "$EXTRACT_JSON" "$PICK" "$PICK_SEARCH" "$PICK_SESSION" "$PICK_RANK" <<'PY'
import json, re, sys
path, url, search_id, session_id, rank = sys.argv[1:6]
data = json.load(open(path))
results = data.get("results") or data.get("extract", {}).get("results") or []
blob = json.dumps(data)
# Prefer excerpts / full_content text.
texts = []
for r in results:
    for ex in r.get("excerpts") or []:
        texts.append(ex if isinstance(ex, str) else str(ex))
    fc = r.get("full_content") or r.get("content") or ""
    if fc:
        texts.append(fc)
text = "\n".join(texts) or blob
cps = sorted(set(re.findall(r"Up to (\d+) characters per second", text, flags=re.I)))
print(f"extract_url: {url}")
print(f"search_id: {search_id or '(missing)'}")
print(f"session_id: {session_id or '(missing)'}")
print(f"search_rank: {rank}")
print(f"chars_in_extract_payload: {len(text)}")
print(f"cps_sentences_found: {cps or '(none matched regex; still extracted page)'}")
if len(text) < 200:
    print("Extract payload too small to count as a real page read", file=sys.stderr)
    sys.exit(4)
print("OK: Parallel CLI Search then Extract mirrored Cuepass netflix_en_us path.")
PY

echo "artifacts: $SEARCH_JSON $EXTRACT_JSON"
