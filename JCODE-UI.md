# WORK ORDER: rebuild Cuepass so the cue list is the product

You are Claude Opus. Effort high. Visual judgment is the job. Do not add a copy-on-click or another chip. Rebuild the first viewport.

Wordmark **Cuepass**. You are in `projects/sixteen-seventeen`. The UI lives in the `HTML = """..."""` string in `app.py`. Rewrite that HTML/CSS/JS. Keep `/run` and `/health` and `/repaired/{name}`. Do not introduce Next.js or Inter.

## Why the current page is slop

It is a 48px header plus a 252px sidebar form. Anton is 22px. Verge's display face runs 60-107px. A spotting editor does not fill in a form. They read cues.

## Design Read (already locked)

`.uicraft-read.json` exists. Tokens from `DESIGN.md` (The Verge 2024):
- Type: Anton for display (Manuka substitute). Space Mono for labels, cps, timecode. Body is the cue text, system sans is allowed only for cue dialogue, not for chrome.
- Surface: `#131313`.
- Accent: mint `#3cffd0` only for repaired state and the one run control. Ultraviolet stays unused unless a leftover reason needs a second hazard. Do not mint-wash the page.
- Radius: 2px. Verge's 40px pills are for story tiles, not this tool. A spotting sheet is sharp.
- Showpiece: none.

Obey uicraft contract. `uicraft gate --cwd .` then `uicraft look --url http://127.0.0.1:8082`.

## First viewport (this is the product)

No sidebar. No app chrome bar.

- Anton wordmark at 64-90px, letter-spacing tight, top of the sheet. Tagline is not a sentence. If anything, `CPS` in Space Mono.
- Film select + Run this track on one line under the wordmark. Not a stacked form.
- Empty state before a run: the sheet is already a column of cue-row ghosts? No. Empty is the wordmark and the run control. Do not fake cues.
- After `/run`: the page is the leftover cues. Default view is still-red only. Each row: index, timecode, cue text at a size you can read from 60cm, measured cps in Space Mono, leftover reason in mint-or-red as a short clause not a badge.
- The `N → M` pair is Anton, huge, above the list. That pair is the verdict. Do not add a second summary strip that repeats it.
- **Take repaired track** stays, as a text link in Space Mono, not a pill.

Mint is the repaired out-time and the run button fill. Red is leftover. White is readable cue text. Nothing else is colored.

## Keep

`POST /run` JSON shape, leftover_reasons, spec citation URL as a real `<a>` in the sheet header (live vs cached). `/repaired/{name}` download. Tests that extract JS from the HTML string must still be able to find filter/reason functions, or you update those tests.

## Hard bans

Inter. Sidebar. 48px global header. Pill buttons. Anton under 48px for the wordmark. Emoji. Em dash. En dash. "subtitle compliance" hero sentence. Three feature cards. Gradient.

## Done when

1. `uicraft gate --cwd .` exits 0.
2. `uicraft look --url http://127.0.0.1:8082` at 1440. Name remaining tells. Fix them.
3. A judge at 8 seconds is reading illegal cues, not a form.
4. Commit.

Note: uvicorn caches `app.py`. After commit, the look URL must be a restarted process. Restart `127.0.0.1:8082` yourself if the HTML you just wrote is not what curl returns.
