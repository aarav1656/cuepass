"""Build the sheet fixture for tests_sheet_filter.js from real iron_mask cues.

The numbers are not hand written: cues are lifted verbatim out of
data/iron_mask_repaired.srt and then run through the same measure_subtitles and
explain_leftovers the server calls, so the fixture carries the same shape as a
real /run payload. Cues repair CAN clear are included on purpose, because a
filter that only ever sees leftovers proves nothing.

Run: python make_sheet_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path

import measure as m

SRC = Path("data/iron_mask_repaired.srt")
OUT = Path("data/sheet_fixture.json")


def main() -> None:
    cues = m.parse_srt(SRC.read_text(encoding="utf-8"))
    reasons_all = m.explain_leftovers(SRC.read_text(encoding="utf-8"))

    # Pick real cues, one batch per leftover reason.
    picked: list[dict] = []
    seen: dict[str, int] = {}
    for n, c in enumerate(cues, start=1):
        r = reasons_all.get(n)
        if r and seen.get(r, 0) < 3:
            seen[r] = seen.get(r, 0) + 1
            picked.append(c)

    # Cues repair clears: real dialogue from the same file, given room to breathe
    # and a short enough line, so the retime reaches the needed duration.
    clearable = [c for c in cues if len(c["text"].strip()) <= 30][:3]

    parts, t = [], 0.0
    for c in picked:
        parts.append((t, t + (c["end"] - c["start"]), c["lines"]))
        t = parts[-1][1] + 0.1  # tight neighbour: leftovers stay leftover
    for c in clearable:
        parts.append((t, t + 0.3, c["lines"]))
        t = parts[-1][1] + 30.0  # wide open: repair can extend freely

    srt = "\n\n".join(
        f"{i}\n{m._fmt_ts(s)} --> {m._fmt_ts(e)}\n" + "\n".join(lines)
        for i, (s, e, lines) in enumerate(parts, start=1)
    ) + "\n"

    before = m.measure_subtitles(srt)
    reasons = m.explain_leftovers(srt)
    findings = before.findings_as_dicts()

    payload = {
        "before": {**before.summary(), "findings": findings},
        "leftover_reasons": {str(k): v for k, v in reasons.items()},
        "classification": {
            str(f["cue_index"]): (
                "auto_fixable" if f["cue_index"] not in reasons else "needs_review"
            )
            for f in findings
        },
    }

    leftover = [f for f in findings if f["cue_index"] in reasons]
    cleared = [f for f in findings if f["cue_index"] not in reasons]
    assert leftover, "fixture must contain cues repair could not clear"
    assert cleared, "fixture must contain cues repair cleared"
    assert len({reasons[f["cue_index"]] for f in leftover}) >= 2, (
        "fixture must contain more than one leftover reason"
    )

    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"{OUT}: {len(findings)} findings, {len(leftover)} leftover, "
          f"{len(cleared)} cleared")


if __name__ == "__main__":
    main()
