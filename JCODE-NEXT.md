# WORK ORDER: Cuepass, copy a leftover cue as a spotting note

You are in `projects/sixteen-seventeen`. Wordmark is **Cuepass**.

The sheet now defaults to leftover cues and can download the repaired track. A spotting editor still has to retype the illegal cue to send it. Redslip already copies a packet. Each leftover row already has timecode, text, measured value, and leftover reason.

## Do this

1. Keep the spotting sheet. Do not restyle. The huge `N → M` pair stays.
2. Clicking a leftover cue row copies one plain-text line: cue index, timecode, check, measured vs limit, reason, cue text. Use `execCommand('copy')` first (same pattern as Redslip). If clipboard is blocked, show the line in a selectable fallback under that row. Do not copy cleared rows. Do not call Gemini. Do not re-run `/run`.
3. A check that would fail if a leftover row copies empty text, and would fail if a cleared row is copyable. Use the sheet fixture (leftover + cleared) already in the repo.
4. No Inter, no em dash, no emoji.

## Done when

A spotting editor can click a still-red cue and paste `cue 0005  00:01:02,000 --> 00:01:03,200  24 cps  no free space  <text>` into a note without leaving the sheet.
