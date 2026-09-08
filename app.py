"""FastAPI web application for SIXTEEN SEVENTEEN.

Single dark HTML page showing before/after subtitle QC results with the
cited spec source. No rainbow gradients. No emoji headers. No AI slop.
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
  <title>SIXTEEN SEVENTEEN — Subtitle Compliance</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0d0d0f;
      --surface: #16181c;
      --border: #2a2d34;
      --accent: #4f8ef7;
      --accent-dim: #2a4a8a;
      --pass: #2ea84f;
      --fail: #d94848;
      --warn: #c8962e;
      --text: #d8dce8;
      --muted: #7a8094;
      --mono: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
    }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
      font-size: 15px;
      line-height: 1.6;
      min-height: 100vh;
    }
    header {
      border-bottom: 1px solid var(--border);
      padding: 24px 32px;
      display: flex;
      align-items: baseline;
      gap: 16px;
    }
    header h1 {
      font-size: 20px;
      font-weight: 600;
      letter-spacing: -0.02em;
      color: #fff;
    }
    header span {
      font-size: 13px;
      color: var(--muted);
    }
    main { max-width: 960px; margin: 0 auto; padding: 32px; }
    section { margin-bottom: 40px; }
    h2 {
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 16px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px 24px;
    }
    .form-row {
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 12px;
      align-items: end;
    }
    label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 6px; }
    input[type=text], select {
      width: 100%;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text);
      padding: 9px 12px;
      font-size: 14px;
      outline: none;
    }
    input[type=text]:focus, select:focus { border-color: var(--accent); }
    button[type=submit] {
      background: var(--accent);
      color: #fff;
      border: none;
      border-radius: 6px;
      padding: 10px 20px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
    }
    button[type=submit]:hover { opacity: 0.88; }
    button[type=submit]:disabled { opacity: 0.4; cursor: default; }
    .badge {
      display: inline-block;
      border-radius: 4px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }
    .pass  { background: #162d1e; color: var(--pass); border: 1px solid #1e4a2a; }
    .fail  { background: #2d1616; color: var(--fail); border: 1px solid #4a1e1e; }
    .warn  { background: #2d2516; color: var(--warn); border: 1px solid #4a3a1e; }
    .cached { background: #252016; color: #c8962e; border: 1px solid #4a3a1e; font-size:10px; }
    .live   { background: #162525; color: #2ea8a8; border: 1px solid #1e4a4a; font-size:10px; }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }
    .stat {
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px 16px;
    }
    .stat .value {
      font-size: 28px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #fff;
      font-family: var(--mono);
    }
    .stat .label { font-size: 11px; color: var(--muted); margin-top: 4px; }
    .before-after {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .panel { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 16px; }
    .panel h3 { font-size: 12px; color: var(--muted); margin-bottom: 12px; letter-spacing: 0.06em; }
    .check-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
      font-size: 13px;
    }
    .check-row:last-child { border-bottom: none; }
    .spec-citation {
      font-size: 12px;
      color: var(--muted);
      margin-top: 12px;
    }
    .spec-citation a { color: var(--accent); text-decoration: none; }
    .spec-citation a:hover { text-decoration: underline; }
    .cue-table { width: 100%; border-collapse: collapse; font-size: 12px; font-family: var(--mono); }
    .cue-table th {
      text-align: left;
      padding: 6px 10px;
      border-bottom: 1px solid var(--border);
      color: var(--muted);
      font-weight: 500;
    }
    .cue-table td {
      padding: 5px 10px;
      border-bottom: 1px solid #1a1c22;
      vertical-align: top;
      max-width: 320px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .error-box {
      background: #2d1616;
      border: 1px solid var(--fail);
      border-radius: 6px;
      padding: 16px;
      color: #f07070;
      font-size: 13px;
    }
    .spinner {
      display: none;
      width: 20px; height: 20px;
      border: 2px solid var(--border);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      margin-left: 12px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    #status-msg { font-size: 13px; color: var(--muted); margin-top: 16px; min-height: 20px; }
    #result { margin-top: 32px; }
    .delta-good { color: var(--pass); font-weight: 700; }
    .delta-neutral { color: var(--muted); }
    .improvement-banner {
      background: #0d2010;
      border: 1px solid #1e5030;
      border-radius: 6px;
      padding: 14px 20px;
      font-size: 13px;
      margin-bottom: 20px;
    }
    .improvement-banner strong { color: var(--pass); }
    a { color: var(--accent); }
  </style>
</head>
<body>
<header>
  <h1>SIXTEEN SEVENTEEN</h1>
  <span>Subtitle compliance, measured and repaired.</span>
</header>
<main>
  <section>
    <h2>Run a compliance pass</h2>
    <div class="card">
      <form id="run-form">
        <div class="form-row">
          <div>
            <label>archive.org identifier (or leave blank to auto-pick)</label>
            <input type="text" name="identifier" id="identifier" placeholder="e.g. vicki_1953" />
          </div>
          <div>
            <label>Target platform</label>
            <select name="platform" id="platform">
              <option value="netflix">Netflix (TTSS)</option>
              <option value="amazon">Amazon Prime Video</option>
              <option value="bbc">BBC</option>
              <option value="fcc">FCC (US broadcast)</option>
            </select>
          </div>
          <div>
            <button type="submit" id="run-btn">Run agent</button>
          </div>
        </div>
      </form>
      <div style="display:flex;align-items:center;margin-top:12px;">
        <div class="spinner" id="spinner"></div>
        <div id="status-msg"></div>
      </div>
    </div>
  </section>

  <div id="result"></div>

  <section>
    <h2>Known films with subtitle tracks</h2>
    <div class="card">
      <table class="cue-table">
        <thead>
          <tr><th>Identifier</th><th>Title</th><th>Note</th></tr>
        </thead>
        <tbody>
          {known_rows}
        </tbody>
      </table>
    </div>
  </section>
</main>

<script>
const form = document.getElementById('run-form');
const btn  = document.getElementById('run-btn');
const spin = document.getElementById('spinner');
const msg  = document.getElementById('status-msg');
const res  = document.getElementById('result');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  btn.disabled = true;
  spin.style.display = 'block';
  msg.textContent = 'Fetching spec from Parallel Search…';
  res.innerHTML = '';

  const fd = new FormData(form);
  const body = new URLSearchParams(fd);

  try {
    msg.textContent = 'Downloading subtitle track from archive.org…';
    const resp = await fetch('/run', { method: 'POST', body });
    msg.textContent = 'Measuring, classifying, repairing…';
    const data = await resp.json();
    if (!resp.ok) {
      res.innerHTML = `<div class="error-box"><b>Error:</b> ${data.detail || JSON.stringify(data)}</div>`;
    } else {
      renderResult(data);
    }
  } catch(err) {
    res.innerHTML = `<div class="error-box"><b>Network error:</b> ${err.message}</div>`;
  } finally {
    btn.disabled = false;
    spin.style.display = 'none';
    msg.textContent = '';
  }
});

function pct(n, total) {
  return total ? (100 * n / total).toFixed(1) + '%' : '0%';
}

function renderResult(d) {
  const b = d.before, a = d.after, s = d.spec;
  const imp = d.improvement;

  const specBadge = s.is_cached
    ? `<span class="badge cached">CACHED SPEC</span>`
    : `<span class="badge live">LIVE SPEC</span>`;

  const overCpsBefore   = b.over_cps_count;
  const overCpsAfter    = a.over_cps_count;
  const underDurBefore  = b.under_duration_count;
  const underDurAfter   = a.under_duration_count;
  const lineCharsBefore = b.over_line_chars_count;
  const lineCharsAfter  = a.over_line_chars_count;

  const deltaRow = (label, before, after, total) => {
    const cls = after < before ? 'delta-good' : 'delta-neutral';
    return `<div class="check-row">
      <span>${label}</span>
      <span>
        <span class="badge ${before > 0 ? 'fail' : 'pass'}">${before} (${pct(before, total)})</span>
        &rarr;
        <span class="badge ${after > 0 ? 'fail' : 'pass'}">${after} (${pct(after, total)})</span>
        <span class="${cls}" style="margin-left:6px">&minus;${before - after}</span>
      </span>
    </div>`;
  };

  const failingSample = (b.findings || []).slice(0, 40);

  const cueRows = failingSample.map(f => `<tr>
    <td>${f.cue_index}</td>
    <td>${f.check}</td>
    <td>${typeof f.value === 'number' ? f.value.toFixed(2) : f.value}</td>
    <td>${f.threshold}</td>
    <td>${f.unit}</td>
    <td>${(d.classification[String(f.cue_index)] || '—')}</td>
    <td title="${f.text_preview}">${f.text_preview.slice(0, 48)}</td>
  </tr>`).join('');

  res.innerHTML = `
    <section>
      <h2>Results: ${d.film_title}</h2>
      <div class="improvement-banner">
        <strong>${d.cues_changed}</strong> cues retimed &bull;
        <strong>${d.auto_fixable_count}</strong> auto-fixable &bull;
        <strong>${d.needs_review_count}</strong> need editorial review &bull;
        Spec: ${s.platform} ${specBadge}
      </div>

      <div class="stats-grid">
        <div class="stat">
          <div class="value">${b.cue_count}</div>
          <div class="label">Total cues</div>
        </div>
        <div class="stat">
          <div class="value">${overCpsBefore}</div>
          <div class="label">Over reading speed (before)</div>
        </div>
        <div class="stat">
          <div class="value">${overCpsAfter}</div>
          <div class="label">Over reading speed (after)</div>
        </div>
        <div class="stat">
          <div class="value">${s.max_cps}</div>
          <div class="label">Max chars/sec (${s.platform})</div>
        </div>
      </div>

      <div class="before-after">
        <div class="panel">
          <h3>BEFORE REPAIR</h3>
          ${deltaRow('Reading speed > ' + s.max_cps + ' cps', overCpsBefore, overCpsAfter, b.cue_count)}
          ${deltaRow('Duration < ' + s.min_duration_s.toFixed(3) + 's', underDurBefore, underDurAfter, b.cue_count)}
          ${deltaRow('Line length > ' + s.max_line_chars + ' chars', lineCharsBefore, lineCharsAfter, b.cue_count)}
        </div>
        <div class="panel">
          <h3>AFTER REPAIR</h3>
          <div class="check-row"><span>Reading speed violations</span>
            <span class="badge ${overCpsAfter > 0 ? 'fail' : 'pass'}">${overCpsAfter > 0 ? overCpsAfter + ' FAIL' : 'PASS'}</span></div>
          <div class="check-row"><span>Duration violations</span>
            <span class="badge ${underDurAfter > 0 ? 'fail' : 'pass'}">${underDurAfter > 0 ? underDurAfter + ' FAIL' : 'PASS'}</span></div>
          <div class="check-row"><span>Line length violations</span>
            <span class="badge ${lineCharsAfter > 0 ? 'warn' : 'pass'}">${lineCharsAfter > 0 ? lineCharsAfter + ' WARN (editorial)' : 'PASS'}</span></div>
        </div>
      </div>

      <div class="spec-citation">
        Spec fetched at runtime from: <a href="${s.source_url}" target="_blank" rel="noopener">${s.source_url}</a><br/>
        ${s.source_label}
      </div>
    </section>

    <section>
      <h2>Failing cues (first 40 of ${b.findings ? b.findings.length : 0})</h2>
      <div class="card" style="padding:0;overflow-x:auto;">
        <table class="cue-table">
          <thead>
            <tr><th>#</th><th>Check</th><th>Value</th><th>Threshold</th><th>Unit</th><th>Classification</th><th>Text preview</th></tr>
          </thead>
          <tbody>${cueRows}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>Film metadata</h2>
      <div class="card">
        <div class="check-row"><span>Title</span><span>${d.film_title}</span></div>
        <div class="check-row"><span>Archive.org identifier</span><span><a href="https://archive.org/details/${d.film_identifier}" target="_blank">${d.film_identifier}</a></span></div>
        <div class="check-row"><span>Subtitle file</span><span><a href="${d.subtitle_url}" target="_blank">${d.subtitle_filename}</a></span></div>
        <div class="check-row"><span>Total cues measured</span><span>${b.cue_count}</span></div>
      </div>
    </section>
  `;
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    known_rows = "\n".join(
        f'<tr><td>{f["identifier"]}</td><td>{f["title"]}</td><td>{f["note"]}</td></tr>'
        for f in KNOWN_FILMS
    )
    return HTML.replace("{known_rows}", known_rows)


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
