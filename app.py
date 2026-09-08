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
  <title>SIXTEEN SEVENTEEN: subtitle compliance, measured and repaired</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    /* Tokens from DESIGN.md (ElevenLabs design system), used verbatim.
       Chosen deliberately: this product is about subtitles, which are typography
       under a legal reading-speed limit. Judging cue text on a near-black
       dashboard is the wrong surface. An off-white editorial page renders the
       thing being measured the way a reader actually meets it. Waldenburg is
       licensed, so the display face is EB Garamond, the substitute the design
       file itself names. Tokens live here once, never inline on elements. */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --primary: #292524; --primary-active: #0c0a09;
      --ink: #0c0a09; --body: #4e4e4e; --body-strong: #292524;
      --muted: #777169; --muted-soft: #a8a29e;
      --hairline: #e7e5e4; --hairline-soft: #f0efed; --hairline-strong: #d6d3d1;
      --canvas: #f5f5f5; --canvas-soft: #fafafa; --canvas-deep: #0c0a09;
      --surface-card: #ffffff; --surface-strong: #f0efed;
      --surface-dark: #0c0a09; --surface-dark-elevated: #1c1917;
      --on-primary: #ffffff; --on-dark: #ffffff; --on-dark-soft: #a8a29e;
      --error: #dc2626; --success: #16a34a; --warn: #b45309;

      --r-sm: 6px; --r-md: 8px; --r-lg: 12px; --r-pill: 9999px;
      --s-xs: 8px; --s-sm: 12px; --s-base: 16px; --s-md: 20px;
      --s-lg: 24px; --s-xl: 32px; --s-xxl: 48px; --s-section: 96px;

      --display: 'EB Garamond', 'Times New Roman', serif;
      --sans: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
      --mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace;
    }

    body {
      background: var(--canvas); color: var(--body);
      font: 400 16px/1.5 var(--sans); letter-spacing: 0.16px;
      -webkit-font-smoothing: antialiased;
    }

    /* Display type is the licensed-serif tier: light weight, negative tracking,
       never bold. This system whispers; it does not shout. */
    h1 {
      font-family: var(--display); font-size: 48px; font-weight: 300;
      line-height: 1.08; letter-spacing: -0.96px; color: var(--ink);
    }
    h2 {
      font-family: var(--display); font-size: 32px; font-weight: 300;
      line-height: 1.13; letter-spacing: -0.32px; color: var(--ink);
    }
    .eyebrow {
      font: 600 12px/1.4 var(--sans); letter-spacing: 0.96px;
      text-transform: uppercase; color: var(--muted);
    }
    .lede { font-size: 18px; line-height: 1.55; color: var(--body); max-width: 64ch; }

    header {
      border-bottom: 1px solid var(--hairline);
      padding: var(--s-xl) var(--s-xl) var(--s-lg);
      background: var(--canvas-soft);
    }
    main { max-width: 1120px; margin: 0 auto; padding: var(--s-xl); }

    /* Cards are white on the off-white canvas, separated by a hairline rather
       than a shadow. Print-page logic, not dashboard-panel logic. */
    .card, .panel {
      background: var(--surface-card); border: 1px solid var(--hairline);
      border-radius: var(--r-lg); padding: var(--s-lg);
    }
    .card + .card, .panel + .panel { margin-top: var(--s-lg); }

    button {
      background: var(--primary); color: var(--on-primary); border: 0;
      border-radius: var(--r-pill); padding: 12px 24px; height: 44px;
      font: 500 15px/1 var(--sans); cursor: pointer;
      transition: background .15s ease;
    }
    button:hover:not(:disabled) { background: var(--primary-active); }
    button:disabled { background: var(--hairline-strong); color: var(--muted); cursor: default; }

    input, select {
      background: var(--surface-card); border: 1px solid var(--hairline-strong);
      border-radius: var(--r-md); padding: 11px 14px;
      font: 400 15px/1 var(--sans); color: var(--ink);
    }
    input:focus, select:focus { outline: 2px solid var(--ink); outline-offset: 1px; }

    /* Numbers stay monospaced so cue timings and character counts align. */
    .stat {
      font-family: var(--display); font-size: 48px; font-weight: 300;
      line-height: 1.08; letter-spacing: -0.96px; color: var(--ink);
    }
    .num, .mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
    .pass, .delta-good { color: var(--success); font-weight: 500; }
    .fail { color: var(--error); font-weight: 500; }
    .warn { color: var(--warn); font-weight: 500; }
    .delta-neutral { color: var(--muted); }

    table, .cue-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th {
      text-align: left; font: 600 12px/1.4 var(--sans); letter-spacing: 0.96px;
      text-transform: uppercase; color: var(--muted);
      padding: 10px 8px; border-bottom: 1px solid var(--hairline-strong);
    }
    td {
      padding: 11px 8px; border-bottom: 1px solid var(--hairline);
      vertical-align: top; color: var(--body);
    }
    tr:last-child td { border-bottom: 0; }

    /* Cue text is the subject of the product, so it is set as reading text at a
       readable size, not squeezed into a data cell. */
    .cue-text { font-family: var(--display); font-size: 17px; line-height: 1.45; color: var(--ink); }

    .badge {
      display: inline-block; font: 600 12px/1 var(--sans); letter-spacing: 0.96px;
      text-transform: uppercase; padding: 6px 10px; border-radius: var(--r-pill);
      background: var(--surface-strong); color: var(--body-strong);
    }
    .badge.live { background: var(--ink); color: var(--on-dark); }
    .badge.cached { background: var(--surface-strong); color: var(--muted); }

    .spec-citation {
      font-size: 14px; color: var(--muted); border-left: 2px solid var(--hairline-strong);
      padding-left: var(--s-sm); margin-top: var(--s-xs);
    }
    .error-box {
      background: #fef2f2; border: 1px solid #fecaca; color: #991b1b;
      border-radius: var(--r-md); padding: var(--s-base); font-size: 14px;
    }
    .improvement-banner {
      background: var(--surface-dark); color: var(--on-dark);
      border-radius: var(--r-lg); padding: var(--s-lg); margin-top: var(--s-lg);
    }
    .improvement-banner .stat { color: var(--on-dark); }

    .stats-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: var(--s-lg); align-items: start;
    }
    .form-row { display: flex; gap: var(--s-sm); flex-wrap: wrap; align-items: center; }
    .before-after { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-lg); }
    @media (max-width: 720px) { .before-after { grid-template-columns: 1fr; } }

    .check-row {
      display: flex; justify-content: space-between; gap: var(--s-base);
      padding: 12px 0; border-bottom: 1px solid var(--hairline);
    }
    .check-row:last-child { border-bottom: 0; }

    .spinner {
      width: 16px; height: 16px; border: 2px solid var(--hairline-strong);
      border-top-color: var(--ink); border-radius: var(--r-pill);
      display: inline-block; animation: spin .7s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }

    a { color: var(--ink); text-decoration: underline; text-underline-offset: 2px; }
    a:hover { color: var(--muted); }
    code { font-family: var(--mono); font-size: 13px; color: var(--body-strong); }
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
      <div style="display:flex;align-items:center;gap:10px;margin-top:16px;">
        <div class="spinner" id="spinner" style="display:none"></div>
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
