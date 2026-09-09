# WORK ORDER: Cuepass, let the operator take the repaired track

You are in `projects/sixteen-seventeen`. Wordmark is **Cuepass**.

DeadZone's honesty is that the repaired file is the product. Cuepass re-measures it (`N → M`) and now shows leftover reasons, but the operator cannot take the file. `/run` already returns `repaired_srt_path`. There is no download.

## Do this

1. Keep the spotting sheet. Do not restyle. The huge `N → M` pair stays.
2. After a run, add one control **Take repaired track** that downloads the repaired `.srt` as an attachment (`text/x-subrip` or `text/plain`, filename from the title). Wire a GET that only serves a file this process just wrote under the existing repair output dir. Reject path traversal and missing files with 404. Do not call Gemini.
3. A test that would fail if the downloaded bytes are the source SRT instead of the repaired one (cue count or a leftover cue's out-time must match the after-measure). Empty 200 is not a pass.
4. No Inter, no em dash, no emoji.

## Done when

A QC lead who runs a track can leave with the repaired `.srt`, the same file the second measure ran on.
