# WORK ORDER: rebuild SIXTEEN SEVENTEEN as a spotting sheet, not an editorial landing page

The UI lives inside the `HTML = """..."""` string in `app.py`. Rewrite that HTML/CSS/JS. Do not change `/run` or `/health` contract. Do not add frameworks.

## Why it loses

ElevenLabs off-white + EB Garamond + Inter + pill buttons + `.card` stack is a blog about subtitles. The product is **illegal subtitle cues**: a cue that flashes too fast to read. A judge should see the cue list, the illegal ones, and the same cues after retiming.

## Visual system

`DESIGN.md` is The Verge 2024: near-black `#131313`, brutal heavy display, mint `#3cffd0` as the single voltage (use it only for the repaired state and the primary action). System font stack the file names (`-apple-system` etc) plus a Google font that can carry display (choose one heavy sans: `Anton` or `Schibsted Grotesk`, not Inter, not Garamond). Cue text is the reading face.

## First viewport

Not a lede and a form. A **spotting sheet**:

LEFT: film title + "run this track" (the existing known-films select + submit to `POST /run`). Keep the Parallel spec citation URL visible as a small source line after a run (`CACHED SPEC` vs live, the current payload already labels this).

MAIN: two columns of cues, or one list that toggles.
- Each cue is a row: in-time, out-time, cps, the cue text itself.
- Illegal cues (reading speed or min duration or line length, whatever the payload flags) have the cps number in red and a mark on the row.
- After a run, repaired cues show the new out-time and the new cps. The text does not change (retiming only). Make that obvious: times move, words do not.
- A summary strip: `105 / 516 over 17 cps → 63` (use the real numbers from the response, do not hardcode).

If the `/run` JSON does not already include per-cue rows, render whatever it does include honestly (totals, before/after counts, sample cues if present). Read `agent.py` / the `/run` handler before inventing fields. Never fake cue text.

## Hard bans

No Inter. No off-white blog. No pill buttons. No emoji. No "subtitle compliance, measured and repaired" as a hero sentence above the fold. No em dash. No three feature cards.

## Done

The first screen is a list of cues. Print 10 lines describing it.
