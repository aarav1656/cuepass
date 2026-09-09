#!/usr/bin/env bash
# Apply Cuepass Parallel deepeners 1/2/5 on projects/sixteen-seventeen.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
# If invoked from repo after copy:
if [[ -f ./app.py && -d ./docs ]]; then
  REPO="$(pwd)"
elif [[ -f /Users/kamal/Desktop/win/projects/sixteen-seventeen/app.py ]]; then
  REPO=/Users/kamal/Desktop/win/projects/sixteen-seventeen
else
  echo "Run from Cuepass repo root" >&2
  exit 2
fi
cd "$REPO"
mkdir -p scripts

# Copy verify script if missing next to this apply script's sibling
if [[ ! -f scripts/verify_parallel_cli.sh ]]; then
  if [[ -f "$ROOT/scripts/verify_parallel_cli.sh" ]]; then
    cp "$ROOT/scripts/verify_parallel_cli.sh" scripts/
  fi
fi
chmod +x scripts/verify_parallel_cli.sh 2>/dev/null || true

python3 << 'PY'
from pathlib import Path
app = Path('app.py')
text = app.read_text()
orig = text
if 'sb-parallel-loud' in text:
    print('app.py already has loud Parallel provenance')
else:
    old = '''            "search_queries": next(
                (d.get("queries") or [] for d in spec.get("source_discovery") or []), []
            ),
            "desk_reason": spec.get("desk_reason", ""),'''
    new = '''            "search_queries": next(
                (d.get("queries") or [] for d in spec.get("source_discovery") or []), []
            ),
            # Parallel Search id for the call that offered this URL, and the
            # Extract session_id that linked Search to Extract on this desk.
            # Both are already on the stored spec / source_discovery; the page
            # prints them so a judge can see the chain without opening JSON.
            "search_id": next(
                (d.get("search_id") for d in spec.get("source_discovery") or [] if d.get("search_id")),
                "",
            ),
            "session_id": spec.get("session_id", ""),
            "desk_reason": spec.get("desk_reason", ""),'''
    assert old in text, '_buyer_view anchor missing'
    text = text.replace(old, new, 1)

    old_js = '''  if (s.discovery === 'parallel_search') {
    var q = (s.search_queries || [])[0] || '';
    prov.push('<span>found by Parallel Search'
      + (s.search_rank ? ', result ' + esc(String(s.search_rank)) : '')
      + (q ? ' for &ldquo;' + esc(q) + '&rdquo;' : '') + '</span>');
  } else if (s.discovery === 'seed_fallback') {
    prov.push('<span class="withheld">Parallel Search returned no page on a host this '
      + 'buyer publishes on, so this run opened the fallback URL recorded in '
      + 'parallel_spec.py. The numbers are still read off the page Extract pulled.</span>');
  }'''
    new_js = '''  if (s.discovery === 'parallel_search') {
    var qs = (s.search_queries || []).filter(Boolean);
    prov.push('<span class="sb-parallel-loud">Parallel Search'
      + (s.search_rank ? ' rank ' + esc(String(s.search_rank)) : '')
      + (s.search_id ? ' · search_id ' + esc(String(s.search_id)) : '')
      + (s.session_id ? ' · extract session_id ' + esc(String(s.session_id)) : '')
      + '</span>');
    if (qs.length) {
      prov.push('<span>queries: ' + qs.map(function(q){ return '&ldquo;' + esc(q) + '&rdquo;'; }).join(' · ') + '</span>');
    }
  } else if (s.discovery === 'seed_fallback') {
    prov.push('<span class="withheld">Parallel Search returned no page on a host this '
      + 'buyer publishes on, so this run opened the fallback URL recorded in '
      + 'parallel_spec.py. The numbers are still read off the page Extract pulled.</span>');
    if (s.session_id) {
      prov.push('<span class="sb-parallel-loud">extract session_id ' + esc(String(s.session_id)) + '</span>');
    }
  }'''
    assert old_js in text, 'discovery JS anchor missing'
    text = text.replace(old_js, new_js, 1)

    old_css = '    .provenance { margin-top: 34px; border-top: 1px solid var(--border-hi); padding-top: 14px; }'
    new_css = '''    .sb-parallel-loud {
      display: block;
      margin-top: 6px;
      padding: 8px 10px;
      border: 1px solid var(--border-hi);
      background: color-mix(in srgb, var(--mint, #7dffc1) 12%, transparent);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      letter-spacing: 0.01em;
      word-break: break-all;
    }
    .provenance { margin-top: 34px; border-top: 1px solid var(--border-hi); padding-top: 14px; }'''
    assert old_css in text, 'css anchor missing'
    text = text.replace(old_css, new_css, 1)

    old_prov = '''  return '<div class="provenance">'
    + srcNote(run)
    + '<div class="prov-head">' + esc(g.workflow || 'workflow') + ': declared graph, and what ran</div>'
    + '<div class="prov-note">Every node the code declares is listed. The count beside one is how many '''
    new_prov = '''  return '<div class="provenance">'
    + srcNote(run)
    + '<div class="prov-head">Parallel this run</div>'
    + '<div class="prov-note">Surfaces <b>' + esc((run.parallel_surfaces || []).join(' and ') || 'none')
    + '</b>. Open any buyer above: the Measured against band prints <b>search_id</b>, '
    + '<b>search rank</b>, the <b>queries</b>, and the Extract <b>session_id</b> that linked '
    + 'Search to Extract for the cited page. Thresholds still come only from Extract page text.</div>'
    + '<div class="prov-head">' + esc(g.workflow || 'workflow') + ': declared graph, and what ran</div>'
    + '<div class="prov-note">Every node the code declares is listed. The count beside one is how many '''
    assert old_prov in text, 'provenanceHtml anchor missing'
    text = text.replace(old_prov, new_prov, 1)
    app.write_text(text)
    print('app.py patched', len(text)-len(orig), 'bytes delta')

# Docs: append insert if not present
insert = Path('docs/_parallel_cli_insert.md')
body = insert.read_text() if insert.exists() else '''## Parallel CLI verify

```bash
export PARALLEL_API_KEY=...
./scripts/verify_parallel_cli.sh
pytest test_real_data.py -k parallel_search_then_extract -q
```
'''
for doc in [Path('README.md'), Path('docs/STORY.md')]:
    t = doc.read_text()
    if 'verify_parallel_cli.sh' in t:
        print(doc, 'already documents verify script')
        continue
    marker = '\n## Parallel is two surfaces' if doc.name=='README.md' else None
    block = '\n\n## Parallel CLI verify (deepener)\n\n' + body.strip() + '\n'
    if marker and marker in t:
        t = t.replace(marker, block + marker, 1)
    else:
        t = t.rstrip() + block
    doc.write_text(t)
    print('updated', doc)
PY

echo "== verify CLI =="
export PATH="$HOME/.local/bin:$PATH"
./scripts/verify_parallel_cli.sh

echo "== live pytest =="
pytest test_real_data.py -k parallel_search_then_extract -q
