/* Sheet filter check for Cuepass.
 *
 * Pulls the real filter functions out of app.py (no second copy of the logic)
 * and runs them against data/sheet_fixture.json, which is generated from real
 * iron_mask cues by make_sheet_fixture.py and contains BOTH cues repair could
 * not clear and cues it did clear.
 *
 * Run: node tests_sheet_filter.js
 */

const fs = require('fs');
const path = require('path');

const root = __dirname;
const appSrc = fs.readFileSync(path.join(root, 'app.py'), 'utf8');

// Take the filter block verbatim from the served page, so this check fails if
// the shipped behaviour changes.
const start = appSrc.indexOf('// ---- leftover filter');
const end = appSrc.indexOf('function setStatus(html)');
if (start < 0 || end < 0 || end < start) {
  throw new Error('could not locate the filter block in app.py');
}
const rowStart = appSrc.indexOf('function rowHtml(r, cls)');
const rowEnd = appSrc.indexOf('</script>', rowStart);
if (rowStart < 0 || rowEnd < 0) throw new Error('could not locate rowHtml in app.py');

const esc = s => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const block = appSrc.slice(start, end) + appSrc.slice(rowStart, rowEnd);
const api = new Function('esc', block +
  '\nreturn { buildRows, rowsForMode, chipCounts, defaultMode, rowHtml, ' +
  'copyLineFor, ' +
  'REASON_NO_FREE_SPACE, REASON_LINE_TOO_LONG, REASON_BOXED_IN };')(esc);

const d = JSON.parse(
  fs.readFileSync(path.join(root, 'data', 'sheet_fixture.json'), 'utf8'));

let failures = 0;
function check(name, cond, detail) {
  if (cond) { console.log('  ok    ' + name); return; }
  failures++;
  console.log('  FAIL  ' + name + (detail ? '\n        ' + detail : ''));
}

const rows = api.buildRows(d.before.findings, d.leftover_reasons);
const clearedIdx = rows.filter(r => r.reason === '').map(r => r.finding.cue_index);
const leftoverIdx = rows.filter(r => r.reason !== '').map(r => r.finding.cue_index);

console.log('fixture: ' + rows.length + ' findings, ' + leftoverIdx.length
  + ' leftover, ' + clearedIdx.length + ' cleared');

// A filter that only ever sees leftovers, or nothing at all, proves nothing.
check('fixture has cues repair cleared', clearedIdx.length > 0);
check('fixture has cues still red', leftoverIdx.length > 0);

// 1. Default view is leftover only.
const mode = api.defaultMode(rows);
const shown = api.rowsForMode(rows, mode);
check('default view is leftover only', mode === 'leftover');
check('default view is not empty', shown.length > 0);
const leaked = shown.filter(r => r.reason === '').map(r => r.finding.cue_index);
check('default view hides every cleared cue', leaked.length === 0,
  'cleared cues visible: ' + leaked.join(', '));
check('default view keeps every still-red cue',
  shown.length === leftoverIdx.length);

// 2. A reason chip shows only its own reason.
[api.REASON_NO_FREE_SPACE, api.REASON_LINE_TOO_LONG, api.REASON_BOXED_IN]
  .forEach(function(reason) {
    const got = api.rowsForMode(rows, reason);
    const wrong = got.filter(r => r.reason !== reason)
      .map(r => r.finding.cue_index + ':' + (r.reason || 'cleared'));
    check('chip "' + reason + '" is not empty', got.length > 0);
    check('chip "' + reason + '" shows only that reason', wrong.length === 0,
      'foreign rows: ' + wrong.join(', '));
  });

// The reason chips must actually partition, otherwise "only that reason" is
// trivially true for a chip that shows nothing meaningful.
const partition = api.rowsForMode(rows, api.REASON_NO_FREE_SPACE).length
  + api.rowsForMode(rows, api.REASON_LINE_TOO_LONG).length
  + api.rowsForMode(rows, api.REASON_BOXED_IN).length;
check('reason chips cover every leftover row', partition === leftoverIdx.length,
  partition + ' vs ' + leftoverIdx.length);

// 3. Counts on the chips match what clicking them renders.
const counts = api.chipCounts(rows);
check('all count matches rendered rows',
  counts.all === api.rowsForMode(rows, 'all').length);
check('still red count matches rendered rows',
  counts.leftover === api.rowsForMode(rows, 'leftover').length);
check('all chip shows the cleared cues again',
  api.rowsForMode(rows, 'all').length > shown.length);

// 4. The rendered HTML of the default view carries no cleared cue index.
const html = shown.map(r => api.rowHtml(r, d.classification)).join('');
const pad = n => String(n).padStart(4, '0');
const inHtml = clearedIdx.filter(i => html.includes('>' + pad(i) + '</div>'));
check('rendered default HTML contains no cleared cue', inHtml.length === 0,
  'found: ' + inHtml.join(', '));
check('rendered default HTML contains the still-red cues',
  leftoverIdx.every(i => html.includes('>' + pad(i) + '</div>')));

// 5. Clicking a still-red cue must yield a pasteable spotting note, and a
// cleared cue must yield nothing at all.
const leftoverRows = rows.filter(r => r.reason !== '');
const clearedRows  = rows.filter(r => r.reason === '');

const emptyNotes = leftoverRows
  .filter(r => !api.copyLineFor(r).trim())
  .map(r => r.finding.cue_index);
check('every still-red cue copies a non-empty note', emptyNotes.length === 0,
  'empty for cues: ' + emptyNotes.join(', '));

const copyableCleared = clearedRows
  .filter(r => api.copyLineFor(r) !== '')
  .map(r => r.finding.cue_index);
check('no cleared cue is copyable', copyableCleared.length === 0,
  'copyable cleared cues: ' + copyableCleared.join(', '));

// The note has to carry every field a spotting editor would retype.
leftoverRows.slice(0, 5).forEach(function(r) {
  const line = api.copyLineFor(r);
  const f = r.finding;
  const idx = pad(f.cue_index);
  const missing = [];
  if (!line.includes('cue ' + idx))       missing.push('index');
  if (!line.includes(f.timecode))         missing.push('timecode');
  if (!line.includes(f.unit))             missing.push('unit');
  if (!line.includes(r.reason))           missing.push('reason');
  if (!line.includes(f.text_preview.trim().slice(0, 20))) missing.push('text');
  if (line.includes('\n'))                missing.push('single line');
  check('note for cue ' + idx + ' carries every field', missing.length === 0,
    'missing: ' + missing.join(', ') + ' | ' + line);
});

// A row the sheet renders as copyable must be exactly a still-red row.
const copyableHtml = api.rowsForMode(rows, 'all')
  .map(r => ({ r, html: api.rowHtml(r, d.classification) }));
const markedCleared = copyableHtml
  .filter(x => x.r.reason === '' && x.html.includes('copyable'))
  .map(x => x.r.finding.cue_index);
check('rendered cleared rows carry no copy handle', markedCleared.length === 0,
  'marked: ' + markedCleared.join(', '));
check('rendered still-red rows carry a copy handle',
  copyableHtml.filter(x => x.r.reason !== '')
    .every(x => x.html.includes('data-copy="')));

console.log(failures === 0 ? '\nPASS' : '\n' + failures + ' FAILED');
process.exit(failures === 0 ? 0 : 1);
