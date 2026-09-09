/* Sheet filter check for Cuepass.
 *
 * Runs the shipped code, both halves of it, against a real stored run.
 *
 *   Rows come from `app.ui_run()` in Python, which is the function the served
 *   page actually calls. Nothing here rebuilds a row, so the shape contract
 *   between the two halves is under test rather than assumed.
 *
 *   Filtering, counting and row rendering are lifted out of the page template
 *   after Python has evaluated it, so this runs the same source the browser
 *   receives and fails if the shipped behaviour changes.
 *
 * The run it reads is whatever `runstore.default_run_id()` returns, which is the
 * one the page opens on, so this check exercises the landing state a judge sees.
 * It refuses to pass on a run that has no cleared cues or no still-red cues:
 * a filter that only ever sees one kind of row proves nothing.
 *
 * Run: node tests_sheet_filter.js
 */

const path = require('path');
const { execFileSync } = require('child_process');

const root = __dirname;

// --- both halves of the shipped path, from Python -------------------------

function python() {
  const candidates = [
    process.env.CUEPASS_PYTHON,
    path.join(root, '.venv312', 'bin', 'python'),
    path.join(root, '.venv', 'bin', 'python'),
    'python3',
  ].filter(Boolean);
  for (const exe of candidates) {
    try {
      execFileSync(exe, ['-c', 'import app'], { cwd: root, stdio: 'ignore' });
      return exe;
    } catch (e) { /* try the next one */ }
  }
  throw new Error('no python that can import app.py; set CUEPASS_PYTHON');
}

// `app.HTML` is the evaluated template, so the script it carries is the script
// the browser receives. Reading app.py as text instead would hand this check
// Python's own backslash escapes, and a regex like /\s+/ would arrive as a
// literal backslash and quietly stop matching. That mismatch hid a real bug.
const READ = `
import json, app, runstore
run_id = runstore.default_run_id()
record = runstore.load(run_id) if run_id else None
if record is None:
    raise SystemExit("no stored run: nothing to check, and an empty check is not a pass")
run = app.ui_run(record)
buyer = run["default_buyer"]
contrast = (run["contrasts"] or [None])[0]
looser = contrast["looser"] if contrast else ""
specs = {k: v["spec"] for k, v in run["buyers"].items()}
print(json.dumps({
    "run_id": run["run_id"],
    "buyer": buyer,
    "rows": run["buyers"][buyer]["rows"],
    "violations_after": run["buyers"][buyer]["totals"]["violations_after"],
    "contrasts": run["contrasts"],
    "contrast_desk_is_open": bool(contrast) and contrast["stricter"] == buyer,
    "looser_rows": run["buyers"][looser]["rows"] if looser else [],
    "specs": specs,
    "cue_count": run["cue_count"],
    "graph_nodes": [n["name"] for n in (run["graph"].get("nodes") or [])],
    "desk_total": len(run["buyers"]) + len(run["unavailable"]),
    "script": app.HTML,
}))
`;

const payload = JSON.parse(
  execFileSync(python(), ['-c', READ], { cwd: root, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }));
const rows = payload.rows;
const served = payload.script;

function slice(from, to, what) {
  const a = served.indexOf(from);
  const b = served.indexOf(to, a);
  if (a < 0 || b < 0 || b < a) throw new Error('could not locate ' + what + ' in the served page');
  return served.slice(a, b);
}

const block = slice('// ---- leftover filter', 'function setStatus(html)', 'the filter block')
  + slice('const UNIT_LABEL = {', '// ---- declared graph', 'rowHtml');

const esc = s => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const api = new Function('esc', block +
  '\nreturn { rowsForMode, chipCounts, defaultMode, reasonsPresent, rowHtml, ' +
  'copyLineFor, isOpen, reasonOf, ' +
  'REASON_NO_FREE_SPACE, REASON_LINE_TOO_LONG, REASON_BOXED_IN, REASON_UNRECORDED };')(esc);

let failures = 0;
function check(name, cond, detail) {
  if (cond) { console.log('  ok    ' + name); return; }
  failures++;
  console.log('  FAIL  ' + name + (detail ? '\n        ' + detail : ''));
}

const openRows    = rows.filter(api.isOpen);
const clearedRows = rows.filter(r => !api.isOpen(r));
const pad = n => String(n).padStart(4, '0');

console.log('run ' + payload.run_id + ' / ' + payload.buyer + ': '
  + rows.length + ' findings, ' + openRows.length + ' still red, '
  + clearedRows.length + ' cleared');

// A check that cannot see both kinds of row cannot fail for the right reason.
check('run has cues repair cleared', clearedRows.length > 0);
check('run has cues still red', openRows.length > 0);

// 0. The still-red count is the number the headline pair is built from, not a
// second opinion about it.
check('still-red rows equal the remeasured violation count',
  openRows.length === payload.violations_after,
  openRows.length + ' rows vs totals.violations_after ' + payload.violations_after);

// 1. Default view is still-red only.
const mode = api.defaultMode(rows);
const shown = api.rowsForMode(rows, mode);
check('default view is still red', mode === 'leftover');
check('default view is not empty', shown.length > 0);
check('default view hides every cleared cue',
  shown.filter(r => !api.isOpen(r)).length === 0);
check('default view keeps every still-red cue', shown.length === openRows.length);

// 2. Every reason chip shows only its own reason, and they partition exactly.
const reasons = api.reasonsPresent(rows);
check('at least one reason chip exists', reasons.length > 0);
let partition = 0;
reasons.forEach(function(reason) {
  const got = api.rowsForMode(rows, reason);
  partition += got.length;
  const wrong = got.filter(r => api.reasonOf(r) !== reason)
    .map(r => r.index + ':' + (api.reasonOf(r) || 'cleared'));
  check('chip "' + reason + '" is not empty', got.length > 0);
  check('chip "' + reason + '" shows only that reason', wrong.length === 0,
    'foreign rows: ' + wrong.join(', '));
});
check('reason chips cover every still-red row exactly once',
  partition === openRows.length, partition + ' vs ' + openRows.length);

// 3. The counts printed on the chips match what clicking them renders.
const counts = api.chipCounts(rows);
check('all count matches rendered rows',
  counts.all === api.rowsForMode(rows, 'all').length);
check('still-red count matches rendered rows',
  counts.leftover === api.rowsForMode(rows, 'leftover').length);
reasons.forEach(function(reason) {
  check('count on chip "' + reason + '" matches its rows',
    counts.by[reason] === api.rowsForMode(rows, reason).length);
});
check('the all chip shows the cleared cues again',
  api.rowsForMode(rows, 'all').length > shown.length);

// 4. The rendered default view carries no cleared cue index.
const html = shown.map(api.rowHtml).join('');
const clearedIdx = clearedRows.map(r => r.index);
const openIdx = openRows.map(r => r.index);
const leaked = clearedIdx.filter(i => !openIdx.includes(i) && html.includes('>' + pad(i) + '</div>'));
check('rendered default HTML contains no cleared-only cue', leaked.length === 0,
  'found: ' + leaked.join(', '));
check('rendered default HTML contains every still-red cue',
  openIdx.every(i => html.includes('>' + pad(i) + '</div>')));

// 5. A still-red row leads with what the repaired track measures, not with what
// arrived. A row whose value moved has to say so.
const moved = openRows.filter(r => typeof r.value_after === 'number' && r.value_after !== r.value);
if (moved.length) {
  const r = moved[0];
  const cell = api.rowHtml(r);
  check('a row the retime moved shows the current value',
    cell.includes('>' + r.value_after.toFixed(2) + '<')
    || cell.includes('>' + r.value_after.toFixed(0) + '<'),
    'cue ' + r.index + ' after=' + r.value_after + ' before=' + r.value);
  // Matched against the marker the template emits, not against the bare word:
  // a cue's own dialogue can contain "was", so grepping the whole row made this
  // pass for the wrong reason and survive the value being dropped.
  check('a row the retime moved keeps the original beside it',
    /&middot; was \d/.test(cell), 'cue ' + r.index + ': ' + cell.slice(-120));
}

// 6. Clicking a still-red cue yields a pasteable note. A cleared cue yields none.
const emptyNotes = openRows.filter(r => !api.copyLineFor(r).trim()).map(r => r.index);
check('every still-red cue copies a non-empty note', emptyNotes.length === 0,
  'empty for cues: ' + emptyNotes.join(', '));
const copyableCleared = clearedRows.filter(r => api.copyLineFor(r) !== '').map(r => r.index);
check('no cleared cue is copyable', copyableCleared.length === 0,
  'copyable cleared cues: ' + copyableCleared.join(', '));

// The note carries every field a spotting editor would otherwise retype.
openRows.slice(0, 5).forEach(function(r) {
  const line = api.copyLineFor(r);
  const missing = [];
  if (!line.includes('cue ' + pad(r.index)))       missing.push('index');
  if (!line.includes(r.tc_in))                     missing.push('in point');
  if (!line.includes(r.tc_out))                    missing.push('out point');
  if (r.unit && !line.includes(r.unit))            missing.push('unit');
  if (!line.includes(api.reasonOf(r)))             missing.push('reason');
  if (!line.includes(String(r.text).replace(/\s+/g, ' ').trim().slice(0, 20))) missing.push('text');
  if (line.includes('\n'))                         missing.push('single line');
  check('note for cue ' + pad(r.index) + ' carries every field', missing.length === 0,
    'missing: ' + missing.join(', ') + ' | ' + line);
});

// A row the sheet renders as copyable is exactly a still-red row.
const rendered = api.rowsForMode(rows, 'all').map(r => ({ r, html: api.rowHtml(r) }));
const markedCleared = rendered
  .filter(x => !api.isOpen(x.r) && x.html.includes('copyable')).map(x => x.r.index);
check('rendered cleared rows carry no copy handle', markedCleared.length === 0,
  'marked: ' + markedCleared.join(', '));
check('rendered still-red rows carry a copy handle',
  rendered.filter(x => api.isOpen(x.r)).every(x => x.html.includes('data-copy="')));

// 7. The profile contrast is the loudest number on the page, so it has to mean
// exactly what the page says: cues this profile raises on reading speed that the
// other published profile's own threshold would let through. Anything else and
// the headline figure is decoration.
const c = (payload.contrasts || [])[0];
if (c) {
  const gap = api.rowsForMode(rows, 'contrast');
  check('the contrast desk is the one that opens', payload.contrast_desk_is_open);
  check('marked rows equal the count the page prints', gap.length === c.count,
    gap.length + ' marked vs ' + c.count + ' printed');
  check('the two profiles genuinely differ', c.stricter_max_cps < c.looser_max_cps,
    c.stricter_max_cps + ' vs ' + c.looser_max_cps);

  const wrongCheck = gap.filter(r => r.check !== 'reading_speed').map(r => r.index);
  check('every marked cue is a reading-speed finding', wrongCheck.length === 0,
    'other checks: ' + wrongCheck.join(', '));

  // The definition of the gap, asserted rather than trusted.
  const outside = gap
    .filter(r => !(r.value > c.stricter_max_cps && r.value <= c.looser_max_cps))
    .map(r => r.index + '@' + r.value);
  check('every marked cue sits between the two published thresholds',
    outside.length === 0, 'outside ' + c.stricter_max_cps + ' to ' + c.looser_max_cps
    + ': ' + outside.slice(0, 6).join(', '));

  // If the looser profile raised them too, they would not be in the gap at all.
  const marked = new Set(gap.map(r => r.index));
  const alsoRaised = payload.looser_rows
    .filter(r => marked.has(r.index) && r.check === 'reading_speed').map(r => r.index);
  check('the looser profile raises none of them', alsoRaised.length === 0,
    'also raised: ' + alsoRaised.slice(0, 6).join(', '));

  // Only the profile that raises these cues may mark them. Note this cannot
  // currently fail: the looser profile has no reading-speed finding for any cue
  // in the gap, by construction, so both the guarded and unguarded code produce
  // an empty list here. It guards the invariant for a future run where a gap
  // cue also breaks a rule the looser profile does publish.
  check('only the stricter profile marks the gap',
    payload.looser_rows.filter(r => r.in_contrast).length === 0);

  // Every differing pair has to reach the page. This run produces one, so the
  // multi-pair case is exercised on synthetic input: three profiles at three
  // reading speeds produce three pairs, and rendering only the first would drop
  // measured evidence while looking complete. Synthetic here is legitimate,
  // nothing invented reaches a screen; it only proves the renderer loops.
  const contrastFn = new Function('esc', 'num',
    slice('function renderContrast', 'function renderRail', 'renderContrast')
    + '\nreturn renderContrast;')(esc, function (n) { return String(n); });
  const threePairs = [
    { count: 11, stricter: 'a', looser: 'b', stricter_platform: 'A', looser_platform: 'B',
      stricter_max_cps: 15, looser_max_cps: 17, stricter_url: '', looser_url: '' },
    { count: 22, stricter: 'a', looser: 'c', stricter_platform: 'A', looser_platform: 'C',
      stricter_max_cps: 15, looser_max_cps: 20, stricter_url: '', looser_url: '' },
    { count: 33, stricter: 'b', looser: 'c', stricter_platform: 'B', looser_platform: 'C',
      stricter_max_cps: 17, looser_max_cps: 20, stricter_url: '', looser_url: '' }
  ];
  const many = contrastFn(threePairs);
  check('every differing pair is rendered, not just the first',
    ['11', '22', '33'].every(n => many.indexOf('>' + n + '<') > -1),
    'missing from output: ' + ['11', '22', '33'].filter(n => many.indexOf('>' + n + '<') < 0));
  check('each pair carries its own click target',
    ['data-contrast="0"', 'data-contrast="1"', 'data-contrast="2"']
      .every(a => many.indexOf(a) > -1));
  check('a run with no differing pair renders nothing', contrastFn([]) === ''
    && contrastFn(null) === '');

  // The headline count and the cue list behind it are separate fields, so they
  // can drift. On the stored run they must agree, otherwise the block offers to
  // show more cues than it holds.
  payload.contrasts.forEach(function(row, i) {
    check('pair ' + i + ': the cue list is as long as the count it prints',
      row.evidence_complete === true
      && row.cue_indices.length === row.count,
      row.cue_indices.length + ' listed vs ' + row.count + ' printed');
    const over = row.cue_indices.filter(n => n < 1 || n > payload.cue_count);
    check('pair ' + i + ': every listed cue index is inside the track',
      over.length === 0, 'out of range: ' + over.slice(0, 6).join(', '));
  });

  // And if a run ever does hand over a short list, the offer has to shrink to
  // match it and say so, rather than promising cues it cannot show.
  const short = contrastFn([{
    count: 260, cue_indices: [1, 2, 3], evidence_complete: false,
    stricter: 'a', looser: 'b', stricter_platform: 'A', looser_platform: 'B',
    stricter_max_cps: 12, looser_max_cps: 20, stricter_url: '', looser_url: ''
  }]);
  check('a short cue list shrinks the offer instead of overpromising',
    short.indexOf('Show me the 3 cues') > -1 && short.indexOf('Show me the 260 cues') < 0);
  check('a short cue list says so on the block', /c-partial/.test(short)
    && short.indexOf('recorded 3 of them') > -1);
  check('a short cue list still shows the measured count as the headline',
    short.indexOf('>260<') > -1);

  // The contrast is a scope difference between two of one publisher's guides.
  // Framing it as a contradiction would be a claim the data does not support.
  const railCopy = slice('function renderContrast', 'function renderRail', 'renderContrast');
  const loaded = /contradict|disagree|conflict|caught|gotcha|wrong|inconsisten/i.exec(railCopy);
  check('the contrast is not framed as a contradiction', loaded === null,
    loaded ? 'found "' + loaded[0] + '"' : '');
  check('both scopes are carried into the page', !!c.stricter_scope && !!c.looser_scope);
}

// 8. Every threshold on screen has to point at a page that actually contains it.
// The run states whether a number came off the profile's lead page; comparing the
// citation URLs asks the same question independently. If those two ever disagree,
// the band is about to send a reader to a page the number is not on, which is the
// one failure this whole surface exists to prevent.
Object.keys(payload.specs).forEach(function(key) {
  const spec = payload.specs[key];
  const rules = ['max_cps', 'min_duration_s', 'max_line_chars', 'max_lines'];
  rules.forEach(function(rule) {
    const e = spec.evidence[rule];
    if (!e) return;
    check(key + '/' + rule + ': stated and derived citation agree',
      e.off_profile === e.off_profile_derived,
      'stated off_profile=' + e.off_profile + ' derived=' + e.off_profile_derived);
    if (spec.max_cps !== null && rule === 'max_cps') {
      check(key + '/' + rule + ': carries a clause and a resolvable page',
        !!e.clause && !!e.url, 'clause=' + JSON.stringify(e.clause) + ' url=' + e.url);
    }
  });
  // A borrowed threshold must cite a page, otherwise the row says the number is
  // not on this profile's page while offering nowhere to check it.
  const borrowedBlind = rules.filter(function(r) {
    var e = spec.evidence[r];
    return e && e.off_profile && !e.url;
  });
  check(key + ': every borrowed threshold links the page it came from',
    borrowedBlind.length === 0, 'blind: ' + borrowedBlind.join(', '));
  // Every page a threshold cites has to be one the run says it opened.
  const opened = new Set(spec.source_urls || []);
  const unlisted = rules
    .map(function(r) { return spec.evidence[r]; })
    .filter(function(e) { return e && e.url && opened.size && !opened.has(e.url); });
  check(key + ': every cited page is one the run opened', unlisted.length === 0,
    'unlisted: ' + unlisted.map(function(e) { return e.url; }).join(', '));
});

// 9. No user-facing sentence may state a count of desks, profiles or rules in
// words. Those change with the run: the page said "four desks" for a week after
// a fifth was added, which is a false claim printed next to true numbers. Counts
// on screen have to be read off the record.
const COUNT_WORDS = /\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:[a-z]+\s+){0,2}?(desks?|profiles?|rules?|buyers?|pages?)\b/gi;
// Comments are not user-facing, and one of them has to be able to name the bug
// it is preventing, so they are stripped before the copy is scanned.
const script = slice('<script>\nconst filmSel', '</script>', 'the inline script')
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/^\s*\/\/.*$/gm, ' ');
const copyClaims = [];
let hit;
while ((hit = COUNT_WORDS.exec(script)) !== null) {
  const after = script.slice(hit.index + hit[0].length, hit.index + hit[0].length + 5);
  // "one spec desk per delivery profile" is a rate, true at any desk count.
  if (/^\s+per\b/.test(after)) continue;
  copyClaims.push(hit[0]);
}
check('no user-facing sentence hardcodes a count that the run decides',
  copyClaims.length === 0, 'hardcoded: ' + copyClaims.join(', '));

// The desk count the status line prints has to match the declared graph.
const deskNodes = (payload.graph_nodes || []).filter(n => /_spec_desk$/.test(n));
check('the graph carries one spec desk per profile plus the unavailable ones',
  deskNodes.length === payload.desk_total,
  deskNodes.length + ' desk nodes vs ' + payload.desk_total + ' profiles plus unavailable');

// 10. Cue text reaches the page escaped. A track is third-party input.
const injected = api.rowHtml({
  index: 1, tc_in: '00:00:01,000', tc_out: '00:00:02,000',
  text: '<img src=x onerror=alert(1)>', check: 'line_length',
  value: 99, value_after: null, limit: 42, unit: 'chars',
  timing: false, open: true, blocked_by: 'line too long', action: '', note: ''
});
check('cue text is escaped before it reaches the page',
  !injected.includes('<img src=x') && injected.includes('&lt;img src=x'));

console.log(failures === 0 ? '\nPASS' : '\n' + failures + ' FAILED');
process.exit(failures === 0 ? 0 : 1);
