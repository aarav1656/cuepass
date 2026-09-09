"""FastAPI web application for Cuepass.

Spotting-sheet UI: near-black Verge 2024 system, Anton display,
Space Mono labels, mint #3cffd0 for repaired state and primary action only.
No Inter. No sidebar. No app chrome bar. The cue list is the product.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import agent as agent_mod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cuepass", docs_url="/api/docs")

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
  <title>Cuepass</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Anton&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --canvas:  #131313;
      --surface: #191919;
      --border:  #242424;
      --border-hi: #363636;
      --text:    #ffffff;
      --text-2:  #9a9a9a;
      --text-3:  #5c5c5c;
      --mint:    #3cffd0;
      --red:     #ff3b3b;
      --display: 'Anton', Impact, 'Helvetica Neue', sans-serif;
      --mono:    'Space Mono', ui-monospace, 'JetBrains Mono', monospace;
      --read:    -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    }

    html, body { height: 100%; }

    body {
      background: var(--canvas);
      color: var(--text);
      font-family: var(--read);
      font-size: 15px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }

    ::selection { background: var(--mint); color: #000; }

    .page {
      max-width: 1180px;
      margin: 0 auto;
      padding: clamp(28px, 5vw, 60px) clamp(20px, 5vw, 60px) 120px;
    }

    /* ---- masthead: wordmark + one run line. no sidebar, no chrome bar. ---- */
    .masthead {
      border-bottom: 1px solid var(--border-hi);
      padding-bottom: 22px;
    }

    .brand {
      display: flex;
      align-items: flex-end;
      gap: 16px;
      line-height: 0.9;
    }
    .wordmark {
      font-family: var(--display);
      font-weight: 400;
      font-size: clamp(64px, 7.5vw, 70px);
      letter-spacing: -0.02em;
      line-height: 0.86;
      color: var(--text);
    }
    .brand-unit {
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 3px;
      color: var(--mint);
      padding-bottom: 10px;
    }

    .runbar {
      display: flex;
      flex-wrap: wrap;
      align-items: stretch;
      gap: 10px;
      margin-top: 26px;
    }
    .runbar select, .runbar input[type="text"] {
      background: var(--surface);
      border: 1px solid var(--border-hi);
      border-radius: 2px;
      padding: 0 12px;
      height: 40px;
      color: var(--text);
      font-family: var(--mono);
      font-size: 13px;
      letter-spacing: 0.2px;
      -webkit-appearance: none;
      appearance: none;
    }
    .runbar select { min-width: 220px; cursor: pointer; }
    .runbar select:hover, .runbar input:hover { border-color: #4a4a4a; }
    .runbar select:focus, .runbar input:focus {
      outline: none;
      border-color: var(--mint);
    }
    .runbar select option { background: #1c1c1c; color: var(--text); }
    .runbar .ident { width: 168px; }
    .runbar .or {
      font-family: var(--mono);
      font-size: 11px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--text-3);
      display: flex;
      align-items: center;
      padding: 0 2px;
    }

    /* the single run control, mint fill, sharp corners, not a pill */
    .run-btn {
      background: var(--mint);
      color: #000;
      border: 0;
      border-radius: 2px;
      height: 40px;
      padding: 0 22px;
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 2px;
      text-transform: uppercase;
      cursor: pointer;
      transition: transform .12s ease, opacity .12s ease;
      white-space: nowrap;
    }
    .run-btn:hover:not(:disabled) { transform: translateY(-1px); }
    .run-btn:active:not(:disabled) { transform: translateY(0); }
    .run-btn:disabled { background: #2a2a2a; color: var(--text-3); cursor: default; }

    .status-line {
      font-family: var(--mono);
      font-size: 12px;
      color: var(--text-2);
      letter-spacing: 0.4px;
      margin-top: 16px;
      min-height: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
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

    /* ---- verdict: the N -> M pair is the headline. Anton, huge. ---- */
    .verdict { padding: 40px 0 8px; }
    .verdict-nums {
      display: flex;
      align-items: baseline;
      gap: clamp(20px, 4vw, 44px);
      font-family: var(--display);
      font-weight: 400;
      line-height: 0.82;
    }
    .v-before { font-size: clamp(96px, 17vw, 172px); color: var(--red); letter-spacing: -0.01em; }
    .v-arrow  { font-size: clamp(40px, 7vw, 72px); color: var(--text-3); }
    .v-after  { font-size: clamp(96px, 17vw, 172px); letter-spacing: -0.01em; }
    .v-after.clean    { color: var(--mint); }
    .v-after.leftover { color: var(--red); }
    .verdict-cap {
      font-family: var(--mono);
      font-size: 12px;
      letter-spacing: 0.6px;
      color: var(--text-2);
      margin-top: 20px;
      max-width: 640px;
    }
    .verdict-cap b { color: var(--text); font-weight: 700; }
    .take-track {
      display: inline-block;
      margin-top: 14px;
      font-family: var(--mono);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.5px;
      color: var(--mint);
      text-decoration: none;
      border-bottom: 1px solid var(--mint);
      padding-bottom: 2px;
    }
    .take-track:hover { color: var(--text); border-color: var(--text); }
    .take-track::after { content: ' \\2193'; }

    /* ---- spec citation: sheet header, real anchor, live vs cached ---- */
    .spec-line {
      margin-top: 40px;
      padding: 14px 0;
      border-top: 1px solid var(--border-hi);
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 8px 16px;
      font-family: var(--mono);
      font-size: 12px;
      letter-spacing: 0.3px;
      color: var(--text-2);
    }
    .spec-plat { color: var(--text); font-weight: 700; letter-spacing: 0.5px; }
    .spec-line b { color: var(--text); font-weight: 700; }
    .spec-tag {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1.6px;
      text-transform: uppercase;
    }
    .spec-tag.live   { color: var(--mint); }
    .spec-tag.cached { color: var(--text-3); }
    .spec-src { flex-basis: 100%; color: var(--text-3); word-break: break-all; }
    .spec-src a { color: var(--text-2); text-decoration: none; border-bottom: 1px solid var(--border-hi); }
    .spec-src a:hover { color: var(--mint); border-color: var(--mint); }

    /* ---- filter row: plain mono toggles, default still-red. not chips. ---- */
    .filter-row {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 4px 0;
      padding: 16px 0 6px;
    }
    .flt {
      background: none;
      border: 0;
      cursor: pointer;
      font-family: var(--mono);
      font-size: 11px;
      letter-spacing: 1.4px;
      text-transform: uppercase;
      color: var(--text-3);
      padding: 4px 14px 4px 0;
      transition: color .12s ease;
    }
    .flt:not(:last-child)::after {
      content: '/';
      color: var(--border-hi);
      padding-left: 14px;
    }
    .flt:hover { color: var(--text-2); }
    .flt .n { color: var(--text-2); font-weight: 700; margin-left: 6px; }
    .flt.on { color: var(--text); }
    .flt.on .n { color: var(--mint); }

    /* ---- spotting sheet ---- */
    .sheet-head {
      display: grid;
      grid-template-columns: 58px 188px 1fr 138px;
      gap: 0 20px;
      padding: 10px 0;
      border-bottom: 1px solid var(--border-hi);
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.6px;
      text-transform: uppercase;
      color: var(--text-3);
    }
    .sheet-head .r { text-align: right; }

    .cue-row {
      display: grid;
      grid-template-columns: 58px 188px 1fr 138px;
      gap: 0 20px;
      padding: 16px 0;
      border-bottom: 1px solid var(--border);
      align-items: start;
    }
    .cue-row.copyable { cursor: pointer; }
    .cue-row.copyable:hover { background: rgba(255,255,255,0.02); }
    .cue-row.copied  { background: rgba(60,255,208,0.06); }

    .cue-num {
      font-family: var(--mono);
      font-size: 12px;
      color: var(--text-3);
      display: flex;
      align-items: center;
      gap: 8px;
      padding-top: 4px;
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: var(--red); }
    .dot.repaired { background: var(--mint); }

    .cue-tc {
      font-family: var(--mono);
      font-size: 12px;
      color: var(--text-2);
      letter-spacing: -0.2px;
      padding-top: 4px;
      line-height: 1.55;
    }
    .cue-tc .out { color: var(--text-3); }
    .cue-tc .out.repaired { color: var(--mint); }

    .cue-body { min-width: 0; }
    .cue-text {
      font-family: var(--read);
      font-size: 18px;
      line-height: 1.42;
      color: var(--text);
    }
    .cue-why {
      font-family: var(--mono);
      font-size: 12px;
      letter-spacing: 0.4px;
      margin-top: 8px;
      color: var(--red);
    }
    .cue-why.repaired { color: var(--mint); }

    .cue-val {
      text-align: right;
      font-family: var(--mono);
      padding-top: 2px;
    }
    .cue-val .big { font-size: 20px; font-weight: 700; line-height: 1; letter-spacing: -0.3px; }
    .cue-val.red  .big { color: var(--red); }
    .cue-val.mint .big { color: var(--mint); }
    .cue-val .sub { display: block; font-size: 11px; color: var(--text-3); margin-top: 5px; letter-spacing: 0.4px; }

    .empty-note {
      padding: 40px 0;
      font-family: var(--mono);
      font-size: 12px;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: var(--text-3);
    }

    /* ---- error ---- */
    .error-box { margin-top: 32px; border: 1px solid var(--red); border-radius: 2px; padding: 16px 18px; }
    .error-label {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.6px;
      text-transform: uppercase;
      color: var(--red);
      margin-bottom: 8px;
    }
    .error-body { font-family: var(--mono); font-size: 12px; color: var(--text-2); line-height: 1.6; }
  </style>
</head>
<body>
  <div class="page">
    <div class="masthead">
      <div class="brand">
        <h1 class="wordmark">Cuepass</h1>
        <span class="brand-unit">CPS</span>
      </div>
      <div class="runbar">
        <select id="film-select" aria-label="Film">
          <option value="">Select a track</option>
          {film_options}
        </select>
        <span class="or">or</span>
        <input type="text" id="identifier" class="ident" placeholder="identifier" aria-label="Archive identifier" />
        <select id="platform" aria-label="Platform spec">
          <option value="netflix">Netflix</option>
          <option value="amazon">Amazon</option>
          <option value="bbc">BBC</option>
          <option value="fcc">FCC</option>
        </select>
        <button class="run-btn" id="run-btn" type="button">Run this track</button>
      </div>
      <div class="status-line" id="status-line"></div>
    </div>

    <main id="main-area"></main>
  </div>

<script>
const filmSel  = document.getElementById('film-select');
const identIn  = document.getElementById('identifier');
const platSel  = document.getElementById('platform');
const runBtn   = document.getElementById('run-btn');
const statLine = document.getElementById('status-line');
const mainArea = document.getElementById('main-area');

filmSel.addEventListener('change', () => { if (filmSel.value) identIn.value = ''; });
identIn.addEventListener('input',  () => { if (identIn.value)  filmSel.value = ''; });

// ---- leftover filter (pure, node-testable: see tests_sheet_filter.js) ----
const REASON_NO_FREE_SPACE = 'no free space';
const REASON_LINE_TOO_LONG = 'line too long';
const REASON_BOXED_IN      = 'min duration boxed in';

// One row per before-finding, tagged with the leftover reason repair left on it.
// A row with no reason is a cue repair cleared.
function buildRows(findings, reasons) {
  return (findings || []).map(function(f) {
    return { finding: f, reason: (reasons || {})[String(f.cue_index)] || '' };
  });
}

// The single place that decides what a filter shows.
function rowsForMode(rows, mode) {
  if (mode === 'all')       return rows;
  if (mode === 'leftover')  return rows.filter(function(r) { return r.reason !== ''; });
  return rows.filter(function(r) { return r.reason === mode; });
}

function chipCounts(rows) {
  return {
    all:      rows.length,
    leftover: rowsForMode(rows, 'leftover').length,
    space:    rowsForMode(rows, REASON_NO_FREE_SPACE).length,
    line:     rowsForMode(rows, REASON_LINE_TOO_LONG).length,
    boxed:    rowsForMode(rows, REASON_BOXED_IN).length
  };
}

// Leftovers are the product. Only fall back to all when nothing is still red.
function defaultMode(rows) {
  return rowsForMode(rows, 'leftover').length > 0 ? 'leftover' : 'all';
}

// One plain-text spotting note for a still-red cue. A cleared cue has no note:
// this returns '' so nothing about a repaired cue is ever copyable.
function copyLineFor(r) {
  if (!r || r.reason === '' || !r.finding) return '';
  var f = r.finding;
  var idx = String(f.cue_index);
  while (idx.length < 4) idx = '0' + idx;
  var val = typeof f.value === 'number'
    ? String(Number(f.value.toFixed(2))) : String(f.value);
  var lim = typeof f.threshold === 'number'
    ? String(Number(f.threshold.toFixed(f.check === 'min_duration' ? 3 : 0)))
    : String(f.threshold);
  var unit = f.unit || '';
  var text = String(f.text_preview || '').replace(/\\s+/g, ' ').trim();
  if (!text) return '';
  return 'cue ' + idx
    + '  ' + (f.timecode || '')
    + '  ' + val + ' ' + unit + ' (limit ' + lim + ')'
    + '  ' + r.reason
    + '  ' + text;
}

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
        + '<div class="error-label">Run failed</div>'
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
  const why = d.leftover_reasons || {};

  var total   = b.cue_count;
  var vBefore = b.total_violations;
  var vAfter  = a.total_violations;
  var afterCls = vAfter === 0 ? 'clean' : 'leftover';

  // headline: the same spec check run twice, before repair and after.
  var verdict = '<div class="verdict">'
    + '<div class="verdict-nums">'
    + '<span class="v-before">' + vBefore + '</span>'
    + '<span class="v-arrow">&rarr;</span>'
    + '<span class="v-after ' + afterCls + '">' + vAfter + '</span>'
    + '</div>'
    + '<p class="verdict-cap">Spec violations across <b>' + total
    + '</b> cues, before repair and after, from a second run of the same check '
    + 'on the repaired track.</p>'
    + (d.repaired_srt_name
        ? '<a class="take-track" href="/repaired/'
          + encodeURIComponent(d.repaired_srt_name) + '" download>Take repaired track</a>'
        : '')
    + '</div>';

  // spec citation, real anchor, live vs cached
  var tagCls = s.is_cached ? 'cached' : 'live';
  var tagTxt = s.is_cached ? 'Cached spec' : 'Live spec';
  var spec = '<div class="spec-line">'
    + '<span class="spec-plat">' + esc(s.platform) + '</span>'
    + '<span class="spec-tag ' + tagCls + '">' + tagTxt + '</span>'
    + '<span>max <b>' + s.max_cps + '</b> cps</span>'
    + '<span>min <b>' + Number(s.min_duration_s).toFixed(3) + '</b> s</span>'
    + '<span>max <b>' + s.max_line_chars + '</b> chars/line</span>'
    + '<span>max <b>' + s.max_lines + '</b> lines</span>'
    + '<span class="spec-src">Measured against '
    + '<a href="' + esc(s.source_url) + '" target="_blank" rel="noopener">'
    + esc(s.source_label) + '</a></span>'
    + '</div>';

  var allRows = buildRows(b.findings, why);
  mainArea.innerHTML = verdict + spec + '<div id="sheet"></div>';
  var sheet = document.getElementById('sheet');

  if (allRows.length === 0) {
    sheet.innerHTML = '<div class="empty-note">No spec violations in this track</div>';
    return;
  }

  var counts = chipCounts(allRows);
  var filterRow = '<div class="filter-row" id="filter-row">'
    + flt('leftover', 'still red', counts.leftover)
    + flt(REASON_NO_FREE_SPACE, 'no free space', counts.space)
    + flt(REASON_LINE_TOO_LONG, 'line too long', counts.line)
    + flt(REASON_BOXED_IN, 'boxed in', counts.boxed)
    + flt('all', 'all', counts.all)
    + '</div>';
  var head = '<div class="sheet-head">'
    + '<span>#</span><span>Timecode</span><span>Cue</span><span class="r">Measured</span>'
    + '</div>';
  sheet.innerHTML = filterRow + head + '<div id="cue-rows"></div>';

  var host = document.getElementById('cue-rows');
  function paint(mode) {
    var visible = rowsForMode(allRows, mode);
    host.innerHTML = visible.length
      ? visible.map(function(r) { return rowHtml(r, cls); }).join('')
      : '<div class="empty-note">No cues in this category</div>';
    var bar = document.getElementById('filter-row');
    Array.prototype.forEach.call(bar.children, function(el) {
      el.classList.toggle('on', el.dataset.mode === mode);
    });
  }
  document.getElementById('filter-row').addEventListener('click', function(e) {
    var el = e.target.closest('.flt');
    if (el) paint(el.dataset.mode);
  });
  // click a still-red row to lift its spotting note to the clipboard
  host.addEventListener('click', function(e) {
    var row = e.target.closest('.cue-row.copyable');
    if (!row || !row.dataset.copy) return;
    var note = row.dataset.copy;
    var mark = function() {
      row.classList.add('copied');
      setTimeout(function() { row.classList.remove('copied'); }, 900);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(note).then(mark, mark);
    } else { mark(); }
  });
  paint(defaultMode(allRows));
}

function flt(mode, label, n) {
  return '<button class="flt" type="button" data-mode="' + esc(mode) + '">'
    + esc(label) + '<span class="n">' + n + '</span></button>';
}

function rowHtml(r, cls) {
  var f = r.finding;
  var leftover = r.reason !== '';
  var dotCls   = leftover ? '' : 'repaired';
  var valCls   = leftover ? 'red' : 'mint';
  var val      = typeof f.value === 'number' ? f.value.toFixed(2) : String(f.value);
  var thresh   = typeof f.threshold === 'number'
    ? f.threshold.toFixed(f.check === 'min_duration' ? 3 : 0)
    : String(f.threshold);
  var checkLbl = f.check === 'reading_speed' ? 'cps'
               : f.check === 'min_duration'  ? 's'
               : f.check === 'line_length'   ? 'ch'
               : String(f.check).slice(0, 4);
  var idx = String(f.cue_index);
  while (idx.length < 4) idx = '0' + idx;

  var tc = String(f.timecode || '').split(' --> ');
  var tcIn  = esc(tc[0] || '');
  var tcOut = esc(tc[1] || '');
  var outCls = leftover ? '' : 'repaired';

  var why = leftover
    ? '<div class="cue-why">' + esc(r.reason) + '</div>'
    : '<div class="cue-why repaired">retimed and cleared</div>';

  var copyLine = copyLineFor(r);
  var copyAttrs = copyLine ? ' data-copy="' + esc(copyLine) + '"' : '';

  return '<div class="cue-row ' + (copyLine ? 'copyable' : 'cleared') + '"' + copyAttrs + '>'
    + '<div class="cue-num"><i class="dot ' + dotCls + '"></i>' + idx + '</div>'
    + '<div class="cue-tc">' + tcIn + '<br><span class="out ' + outCls + '">' + tcOut + '</span></div>'
    + '<div class="cue-body">'
      + '<div class="cue-text">' + esc(f.text_preview || '') + '</div>'
      + why
    + '</div>'
    + '<div class="cue-val ' + valCls + '">'
      + '<span class="big">' + val + '</span>'
      + '<span class="sub">' + checkLbl + ' &middot; limit ' + thresh + '</span>'
    + '</div>'
    + '</div>';
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
    return HTML.replace("{film_options}", film_options)


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
    return {"status": "ok", "service": "cuepass"}


@app.get("/repaired/{name}")
async def repaired(name: str):
    """Serve a repaired .srt this process wrote. No model call, no arbitrary read.

    The name must be a key in agent.REPAIRED_FILES, which only run_agent writes,
    so traversal (../, absolute paths, a name from another directory) never
    matches and falls through to 404 along with any file since deleted.
    """
    download_name = agent_mod.REPAIRED_FILES.get(name)
    if download_name is None:
        raise HTTPException(status_code=404, detail="No such repaired track")
    path = agent_mod.DATA_DIR / name
    # Second gate: the resolved path must still sit inside the repair output dir.
    out_dir = agent_mod.DATA_DIR.resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(out_dir)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="No such repaired track") from None
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="No such repaired track")
    return FileResponse(
        resolved,
        media_type="text/x-subrip",
        filename=download_name,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
