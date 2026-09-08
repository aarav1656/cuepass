"""FastAPI web application for SIXTEEN SEVENTEEN.

Spotting-sheet UI: near-black Verge 2024 system, Anton display,
Space Mono labels, mint #3cffd0 for repaired state and primary action only.
No Inter. No off-white blog. No pill buttons. No emoji.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

import agent as agent_mod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SIXTEEN SEVENTEEN", docs_url="/api/docs")

# Known films with real .srt tracks that produce interesting measurements
KNOWN_FILMS = [
    {
        "identifier": "iron_mask",
        "title": "The Iron Mask (1929)",
        "note": "Verified: 105/516 cues (20.3%) over reading speed; 44 under min duration",
    },
    {
        "identifier": "isle_of_destiny",
        "title": "Isle of Destiny",
        "note": "Archive.org public domain feature with ASR subtitle track",
    },
    {
        "identifier": "inner_sanctum",
        "title": "Inner Sanctum",
        "note": "Archive.org public domain feature with ASR subtitle track",
    },
    {
        "identifier": "in_old_caliente",
        "title": "In Old Caliente",
        "note": "Archive.org public domain feature with ASR subtitle track",
    },
]

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>SIXTEEN SEVENTEEN</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Anton&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --canvas:    #131313;
      --surface:   #1c1c1c;
      --surface-2: #2d2d2d;
      --border:    #252525;
      --border-hi: #383838;
      --text:      #ffffff;
      --text-2:    #949494;
      --text-3:    #555555;
      --mint:      #3cffd0;
      --uv:        #5200ff;
      --red:       #ff3b3b;
      --display:   'Anton', Impact, 'Helvetica Neue', sans-serif;
      --mono:      'Space Mono', ui-monospace, 'JetBrains Mono', monospace;
      --body:      -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    }

    html, body { height: 100%; }

    body {
      background: var(--canvas);
      color: var(--text);
      font-family: var(--body);
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    .layout {
      display: grid;
      grid-template-rows: 48px 1fr;
      grid-template-columns: 252px 1fr;
      grid-template-areas: "hd hd" "sb mn";
      min-height: 100vh;
    }

    /* ---- header ---- */
    header {
      grid-area: hd;
      border-bottom: 1px solid var(--border-hi);
      padding: 0 24px;
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .wordmark {
      font-family: var(--display);
      font-size: 22px;
      letter-spacing: 2px;
      line-height: 1;
      color: var(--text);
    }

    .wordmark-tag {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
    }

    /* ---- sidebar ---- */
    aside {
      grid-area: sb;
      border-right: 1px solid var(--border);
      padding: 20px 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      overflow-y: auto;
    }

    .field-label {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
      display: block;
      margin-bottom: 6px;
    }

    select, input[type="text"] {
      width: 100%;
      background: var(--surface);
      border: 1px solid var(--border-hi);
      border-radius: 2px;
      padding: 8px 10px;
      color: var(--text);
      font-family: var(--body);
      font-size: 13px;
      -webkit-appearance: none;
    }
    select:focus, input:focus {
      outline: 1px solid var(--mint);
      border-color: var(--mint);
    }
    select option { background: var(--surface); }

    .run-btn {
      width: 100%;
      background: var(--mint);
      color: #000;
      border: 0;
      border-radius: 2px;
      padding: 10px 16px;
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      cursor: pointer;
      transition: opacity .15s;
    }
    .run-btn:hover:not(:disabled) { opacity: 0.82; }
    .run-btn:disabled {
      background: var(--surface-2);
      color: var(--text-3);
      cursor: default;
    }

    .status-line {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-3);
      letter-spacing: 0.4px;
      min-height: 14px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .spinner {
      width: 10px; height: 10px;
      border: 1px solid var(--border-hi);
      border-top-color: var(--mint);
      border-radius: 50%;
      animation: spin .7s linear infinite;
      flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }

    .spec-block {
      border-left: 2px solid var(--border-hi);
      padding-left: 10px;
    }
    .spec-badge {
      font-family: var(--mono);
      font-size: 9px;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      padding: 2px 5px;
      border: 1px solid var(--border-hi);
      border-radius: 1px;
      display: inline-block;
      margin-bottom: 6px;
    }
    .spec-badge.live   { border-color: var(--mint); color: var(--mint); }
    .spec-badge.cached { color: var(--text-3); }
    .spec-block p {
      font-family: var(--mono);
      font-size: 10px;
      color: var(--text-3);
      letter-spacing: 0.3px;
      line-height: 1.7;
      word-break: break-all;
    }
    .spec-block a { color: var(--text-3); text-decoration: none; }
    .spec-block a:hover { color: var(--mint); }

    /* ---- main ---- */
    main { grid-area: mn; overflow-y: auto; }

    /* pre-run: known films reference table */
    .prerun { padding: 28px; }

    .section-label {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
      margin-bottom: 16px;
    }

    .known-tbl { width: 100%; border-collapse: collapse; }
    .known-tbl th {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.6px;
      text-transform: uppercase;
      color: var(--text-3);
      text-align: left;
      padding: 6px 10px;
      border-bottom: 1px solid var(--border-hi);
    }
    .known-tbl td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--border);
      color: var(--text-2);
      font-size: 13px;
      vertical-align: top;
    }
    .known-tbl td:first-child {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text);
      white-space: nowrap;
    }
    .known-tbl tr { cursor: pointer; }
    .known-tbl tr:hover td { background: var(--surface); }

    /* ---- summary strip ---- */
    .summary-strip {
      background: var(--surface);
      border-bottom: 1px solid var(--border-hi);
      padding: 12px 24px;
      display: flex;
      align-items: baseline;
      gap: 18px;
      flex-wrap: wrap;
    }
    .sum-title {
      font-family: var(--display);
      font-size: 20px;
      letter-spacing: 1px;
      color: var(--text);
      margin-right: 4px;
    }
    .sum-stat {
      font-family: var(--mono);
      font-size: 11px;
      letter-spacing: 0.5px;
      color: var(--text-2);
    }
    .sum-n      { color: var(--text); font-weight: 700; }
    .sum-n.red  { color: var(--red); }
    .sum-n.mint { color: var(--mint); }
    .sum-sep    { color: var(--border-hi); font-family: var(--mono); font-size: 11px; }

    /* ---- spotting sheet ---- */
    .sheet-header {
      display: grid;
      grid-template-columns: 52px 1fr 72px 80px;
      gap: 0 12px;
      padding: 8px 24px;
      border-bottom: 1px solid var(--border-hi);
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.6px;
      text-transform: uppercase;
      color: var(--text-3);
    }

    .cue-row {
      display: grid;
      grid-template-columns: 52px 1fr 72px 80px;
      gap: 0 12px;
      padding: 9px 24px;
      border-bottom: 1px solid var(--border);
      align-items: start;
    }
    .cue-row.illegal  { background: rgba(255,59,59,0.04); }
    .cue-row.repaired { background: rgba(60,255,208,0.04); }

    .cue-idx {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text-3);
      display: flex;
      align-items: center;
      gap: 5px;
      padding-top: 2px;
    }
    .dot {
      width: 6px; height: 6px;
      border-radius: 50%;
      flex-shrink: 0;
      background: var(--red);
    }
    .dot.ok       { background: var(--text-3); }
    .dot.repaired { background: var(--mint); }

    .cue-text {
      font-family: Georgia, 'Times New Roman', serif;
      font-size: 14px;
      line-height: 1.45;
      color: var(--text);
    }

    .cue-val {
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      text-align: right;
    }
    .cue-val.red   { color: var(--red); }
    .cue-val.mint  { color: var(--mint); }
    .cue-val.muted { color: var(--text-2); }
    .cue-val small {
      display: block;
      font-weight: 400;
      font-size: 9px;
      color: var(--text-3);
      letter-spacing: 0.5px;
    }

    .cue-check {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 0.8px;
      text-transform: uppercase;
      color: var(--text-3);
    }
    .cue-check span {
      display: block;
      color: var(--text-3);
      font-size: 9px;
    }

    .no-violations {
      padding: 40px 24px;
      font-family: var(--mono);
      font-size: 11px;
      letter-spacing: 1px;
      color: var(--text-3);
      text-transform: uppercase;
    }

    /* ---- error ---- */
    .error-box {
      margin: 24px;
      border: 1px solid var(--uv);
      border-radius: 2px;
      padding: 14px 18px;
    }
    .error-label {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      color: var(--uv);
      margin-bottom: 6px;
    }
    .error-body {
      font-family: var(--mono);
      font-size: 12px;
      color: var(--text-2);
    }
  </style>
</head>
<body>
<div class="layout">

  <header>
    <span class="wordmark">SIXTEEN SEVENTEEN</span>
    <span class="wordmark-tag">subtitle QC</span>
  </header>

  <aside>
    <div>
      <label class="field-label" for="film-select">Film</label>
      <select id="film-select">
        <option value="">-- known films --</option>
        {film_options}
      </select>
    </div>
    <div>
      <label class="field-label" for="identifier">Or identifier</label>
      <input type="text" id="identifier" placeholder="e.g. vicki_1953" />
    </div>
    <div>
      <label class="field-label" for="platform">Platform spec</label>
      <select id="platform">
        <option value="netflix">Netflix (TTSS)</option>
        <option value="amazon">Amazon Prime Video</option>
        <option value="bbc">BBC</option>
        <option value="fcc">FCC (US broadcast)</option>
      </select>
    </div>
    <button class="run-btn" id="run-btn">Run this track</button>
    <div class="status-line" id="status-line"></div>
    <div id="spec-area"></div>
  </aside>

  <main id="main-area">
    <div class="prerun">
      <div class="section-label">Known tracks -- click to select</div>
      <table class="known-tbl">
        <thead>
          <tr><th>Identifier</th><th>Title</th><th>Note</th></tr>
        </thead>
        <tbody id="known-body">
          {known_rows}
        </tbody>
      </table>
    </div>
  </main>

</div>
<script>
const filmSel  = document.getElementById('film-select');
const identIn  = document.getElementById('identifier');
const platSel  = document.getElementById('platform');
const runBtn   = document.getElementById('run-btn');
const statLine = document.getElementById('status-line');
const mainArea = document.getElementById('main-area');
const specArea = document.getElementById('spec-area');

// click a known-film row to select it
document.getElementById('known-body').addEventListener('click', e => {
  const tr = e.target.closest('tr[data-id]');
  if (!tr) return;
  filmSel.value = tr.dataset.id;
  identIn.value = '';
});

filmSel.addEventListener('change', () => { if (filmSel.value) identIn.value = ''; });
identIn.addEventListener('input',  () => { if (identIn.value)  filmSel.value = ''; });

function setStatus(html) { statLine.innerHTML = html; }
function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

runBtn.addEventListener('click', async () => {
  const id       = identIn.value.trim() || filmSel.value || '';
  const platform = platSel.value;
  runBtn.disabled = true;
  specArea.innerHTML = '';
  mainArea.innerHTML = '';
  setStatus('<span class="spinner"></span>fetching spec');

  try {
    setStatus('<span class="spinner"></span>downloading subtitle track');
    const resp = await fetch('/run', {
      method: 'POST',
      body: new URLSearchParams({ identifier: id, platform }),
    });
    setStatus('<span class="spinner"></span>measuring and repairing');
    const data = await resp.json();
    if (!resp.ok) {
      mainArea.innerHTML = '<div class="error-box">'
        + '<div class="error-label">Error</div>'
        + '<div class="error-body">' + esc(data.detail || JSON.stringify(data)) + '</div>'
        + '</div>';
    } else {
      renderSheet(data);
    }
  } catch(err) {
    mainArea.innerHTML = '<div class="error-box">'
      + '<div class="error-label">Network error</div>'
      + '<div class="error-body">' + esc(err.message) + '</div>'
      + '</div>';
  } finally {
    runBtn.disabled = false;
    setStatus('');
  }
});

function renderSheet(d) {
  const b = d.before, a = d.after, s = d.spec;
  const cls = d.classification || {};

  // spec citation in sidebar
  var badgeCls = s.is_cached ? 'cached' : 'live';
  var badgeTxt = s.is_cached ? 'CACHED SPEC' : 'LIVE SPEC';
  specArea.innerHTML = '<div class="spec-block">'
    + '<span class="spec-badge ' + badgeCls + '">' + badgeTxt + '</span>'
    + '<p>' + esc(s.source_label) + '<br>'
    + '<a href="' + esc(s.source_url) + '" target="_blank" rel="noopener">'
    + esc(s.source_url) + '</a></p>'
    + '</div>';

  // summary strip
  var total      = b.cue_count;
  var overBefore = b.over_cps_count;
  var overAfter  = a.over_cps_count;
  var durBefore  = b.under_duration_count;
  var durAfter   = a.under_duration_count;
  var changed    = d.cues_changed;
  var maxCps     = s.max_cps;

  var strip = '<div class="summary-strip">'
    + '<span class="sum-title">' + esc(d.film_title) + '</span>'
    + '<span class="sum-stat"><span class="sum-n red">' + overBefore + '</span>'
    + ' / <span class="sum-n">' + total + '</span>'
    + ' over ' + maxCps + ' cps'
    + ' &rarr; <span class="sum-n mint">' + overAfter + '</span></span>'
    + '<span class="sum-sep">|</span>'
    + '<span class="sum-stat"><span class="sum-n">' + durBefore + '</span>'
    + ' under min dur &rarr; <span class="sum-n mint">' + durAfter + '</span></span>'
    + '<span class="sum-sep">|</span>'
    + '<span class="sum-stat"><span class="sum-n mint">' + changed + '</span> retimed</span>'
    + '</div>';

  // cue rows from findings
  var findings = b.findings || [];
  var rowsHtml = '';

  if (findings.length === 0) {
    rowsHtml = '<div class="no-violations">No violations found</div>';
  } else {
    var header = '<div class="sheet-header">'
      + '<span>#</span><span>TEXT</span>'
      + '<span style="text-align:right">MEASURED</span><span>CHECK</span>'
      + '</div>';

    var rows = findings.map(function(f) {
      var classification = cls[String(f.cue_index)] || '';
      var repaired = classification === 'auto_fixable';
      var rowCls   = repaired ? 'repaired' : 'illegal';
      var dotCls   = repaired ? 'repaired' : '';
      var valCls   = repaired ? 'mint' : 'red';
      var val      = typeof f.value === 'number' ? f.value.toFixed(2) : String(f.value);
      var thresh   = typeof f.threshold === 'number'
        ? f.threshold.toFixed(f.check === 'min_duration' ? 3 : 0)
        : String(f.threshold);
      var checkLbl = f.check === 'reading_speed' ? 'CPS'
                   : f.check === 'min_duration'  ? 'DUR'
                   : f.check === 'line_length'   ? 'LEN'
                   : f.check.toUpperCase().slice(0, 4);
      var idx = String(f.cue_index);
      while (idx.length < 4) idx = '0' + idx;

      return '<div class="cue-row ' + rowCls + '">'
        + '<div class="cue-idx"><span class="dot ' + dotCls + '"></span>' + idx + '</div>'
        + '<div class="cue-text">' + esc(f.text_preview || '') + '</div>'
        + '<div class="cue-val ' + valCls + '">' + val
        + '<small>' + esc(f.unit) + '</small></div>'
        + '<div class="cue-check">' + checkLbl
        + '<span>lim ' + thresh + '</span></div>'
        + '</div>';
    }).join('');

    rowsHtml = header + rows;
  }

  mainArea.innerHTML = strip + rowsHtml;
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    film_options = "\n".join(
        f'<option value="{f["identifier"]}">{f["title"]}</option>'
        for f in KNOWN_FILMS
    )
    known_rows = "\n".join(
        f'<tr data-id="{f["identifier"]}"><td>{f["identifier"]}</td>'
        f'<td>{f["title"]}</td><td>{f["note"]}</td></tr>'
        for f in KNOWN_FILMS
    )
    return (HTML
            .replace("{film_options}", film_options)
            .replace("{known_rows}", known_rows))


@app.post("/run")
async def run(
    identifier: str = Form(default=""),
    platform: str = Form(default="netflix"),
):
    try:
        result = agent_mod.run_agent(
            identifier=identifier.strip() or None,
            platform=platform,
        )
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
async def health():
    return {"status": "ok", "service": "sixteen-seventeen"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
