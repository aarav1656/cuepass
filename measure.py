"""Deterministic subtitle QC measurement and repair.

Every function here is pure Python or regex: no model involved.
The numbers a judge reproduces must come from the same logic they can read.

Adapted from the reference measure.py in the deliverable project, stripped to
subtitle-only checks for SIXTEEN SEVENTEEN.

Key quirk: archive.org ASR .srt files emit TWO-DIGIT milliseconds
  (e.g. 00:02:00,70). A naive parser dividing by 1000 reads that as 70ms
  instead of 700ms, mangling every duration. _seconds() normalises on digit
  count exactly as the reference code does.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field

# Unit-test defaults only. Every live call passes `spec=` from parallel_spec.py,
# which always carries all four keys, so none of these four numbers is reachable
# on the path a run takes. They exist so measurement and repair can be tested
# with no Parallel key at all, and `measure_subtitles` labels the report
# "Netflix (default)" / "... (default constants)" when they are used, so a report
# built on them cannot be mistaken for a cited one.
DEFAULT_MAX_CPS = 17.0
DEFAULT_MIN_CUE_SECONDS = 5 / 6
DEFAULT_MAX_LINE_CHARS = 42
DEFAULT_MAX_LINES = 2

# SRT timestamp pattern; accepts 2- or 3-digit milliseconds
_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _seconds(h: str, m: str, s: str, ms: str) -> float:
    """Convert SRT timestamp components to seconds.

    Handles both 2-digit (archive.org ASR) and 3-digit milliseconds.
    """
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / (10 ** len(ms))


def parse_srt(text: str) -> list[dict]:
    """Parse an SRT string into a list of cue dicts."""
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        if len(lines) < 2:
            continue
        ts_line = next((ln for ln in lines if _TS.search(ln)), None)
        if not ts_line:
            continue
        m = _TS.search(ts_line)
        start = _seconds(*m.groups()[:4])
        end = _seconds(*m.groups()[4:])
        body = [ln for ln in lines[lines.index(ts_line) + 1 :]]
        if not body:
            continue
        cues.append(
            {
                "start": start,
                "end": end,
                "duration": max(end - start, 0.0),
                "lines": body,
                "text": " ".join(body),
            }
        )
    return cues


@dataclass
class CueFinding:
    """One violation on one cue."""

    cue_index: int  # 1-based
    check: str
    value: float
    threshold: float
    unit: str
    timecode: str  # cue in/out, "HH:MM:SS,mmm --> HH:MM:SS,mmm"
    text_preview: str
    auto_fixable: bool


@dataclass
class SubtitleReport:
    """Full QC report for one subtitle file."""

    cue_count: int
    spec_platform: str
    spec_source_url: str
    spec_source_label: str
    spec_is_cached: bool
    max_cps: float
    min_duration_s: float
    max_line_chars: int
    max_lines: int
    findings: list[CueFinding] = field(default_factory=list)

    # Aggregate counts filled in after findings list is built
    over_cps_count: int = 0
    under_duration_count: int = 0
    over_line_chars_count: int = 0
    over_line_count: int = 0
    non_positive_duration_count: int = 0

    # Checks the buyer's own page never states, so nothing was measured for
    # them. Carried through to the UI: a silent spec is not a passing spec.
    checks_skipped: list[str] = field(default_factory=list)

    @property
    def total_violations(self) -> int:
        return len(self.findings)

    @property
    def passed(self) -> bool:
        return self.total_violations == 0

    def summary(self) -> dict:
        """Counts, with a check that was never run reported as None, not zero.

        A check with no threshold behind it finds nothing, and a zero in a
        violation count reads as "clean". So a check listed in `checks_skipped`
        reports None instead: the caller has to decide what to say about a rule
        the buyer's page did not state, and cannot accidentally render it as a
        pass. `total_violations` still counts only real findings, so the arrow
        pair on screen is never inflated by an unmeasured rule.

        THE COUNTERS ARE NOT ALL DISJOINT. `non_positive_duration_count` is a
        SUBSET of `under_duration_count`, not a fifth category beside it: a cue
        whose out-time is not after its in-time is also a cue under the minimum,
        and it increments both. So the reconciliation is four terms, not five:

            over_cps + under_duration + over_line_chars + over_line_count
                == total_violations

        Adding `non_positive_duration_count` to that sum double-counts those
        cues. On the shipped run it turns 179 into 181. Use `total_violations`,
        which is `len(findings)` and needs no addition at all, whenever a total
        is what you want.
        """
        skipped = set(self.checks_skipped)

        def count(check: str, value: int) -> int | None:
            return None if check in skipped else value

        return {
            "cue_count": self.cue_count,
            "total_violations": self.total_violations,
            "over_cps_count": count("reading_speed", self.over_cps_count),
            "under_duration_count": count("min_duration", self.under_duration_count),
            "over_line_chars_count": count("line_length", self.over_line_chars_count),
            "over_line_count": count("line_count", self.over_line_count),
            "non_positive_duration_count": count(
                "min_duration", self.non_positive_duration_count
            ),
            "checks_skipped": list(self.checks_skipped),
            "checks_not_verifiable": list(self.checks_skipped),
            "passed": self.passed,
            "spec_platform": self.spec_platform,
            "spec_source_url": self.spec_source_url,
            "spec_source_label": self.spec_source_label,
            "spec_is_cached": self.spec_is_cached,
            "max_cps": self.max_cps,
            "min_duration_s": self.min_duration_s,
            "max_line_chars": self.max_line_chars,
            "max_lines": self.max_lines,
        }

    def findings_as_dicts(self) -> list[dict]:
        return [asdict(f) for f in self.findings]


def measure_subtitles(
    text: str,
    max_cps: float = DEFAULT_MAX_CPS,
    min_duration_s: float = DEFAULT_MIN_CUE_SECONDS,
    max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
    max_lines: int = DEFAULT_MAX_LINES,
    spec: dict | None = None,
) -> SubtitleReport:
    """Measure all QC checks against the given spec thresholds.

    `spec` is a dict built from a page Parallel Extract opened this run. Its
    thresholds override the defaults.

    A threshold present in the spec dict with the value None means the buyer's
    own page never states that rule. That check is then SKIPPED rather than
    measured against a borrowed number, and the check name is recorded in
    `checks_skipped`. Silence in a spec is not permission, and it is not a
    reason to quietly apply another buyer's limit.

    If spec is None, the module defaults apply, which is the unit-test path.
    """
    skipped: list[str] = []
    if spec:
        if "max_cps" in spec:
            max_cps = spec["max_cps"]
        if "min_duration_s" in spec:
            min_duration_s = spec["min_duration_s"]
        if "max_line_chars" in spec:
            max_line_chars = spec["max_line_chars"]
        if "max_lines" in spec:
            max_lines = spec["max_lines"]
        platform = spec.get("platform", "Netflix")
        source_url = spec.get("source_url", "")
        source_label = spec.get("source_label", "")
        is_cached = spec.get("is_cached", True)
        for name, value in (
            ("reading_speed", max_cps),
            ("min_duration", min_duration_s),
            ("line_length", max_line_chars),
            ("line_count", max_lines),
        ):
            if value is None:
                skipped.append(name)
    else:
        platform = "Netflix (default)"
        source_url = "https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617"
        source_label = "Netflix Timed Text Style Guide (default constants)"
        is_cached = True

    cues = parse_srt(text)
    report = SubtitleReport(
        cue_count=len(cues),
        spec_platform=platform,
        spec_source_url=source_url,
        spec_source_label=source_label,
        spec_is_cached=is_cached,
        max_cps=max_cps,
        min_duration_s=min_duration_s,
        max_line_chars=max_line_chars,
        max_lines=max_lines,
        checks_skipped=skipped,
    )

    for idx, c in enumerate(cues, start=1):
        chars = len(c["text"].strip())
        preview = c["text"][:60]
        timecode = f"{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}"

        # SRT stores milliseconds, so the comparison happens at millisecond
        # resolution. Subtracting two float seconds does not: 133.79 - 132.99 is
        # 0.79999999999998295, and a cue the repair set to exactly 800ms then
        # re-measured as failing an 800ms minimum by one part in 10^14. On the
        # real track that put 27 cues back into the after-count and printed rows
        # reading "0.800 s, limit 0.8, fail" and "20.00 cps, limit 20, fail",
        # which understated the repair by 40 percent and looked like a lie.
        duration_ms = int(round(c["duration"] * 1000))
        min_duration_ms = (
            None if min_duration_s is None else int(math.ceil(min_duration_s * 1000 - 1e-6))
        )
        under_minimum = min_duration_ms is not None and duration_ms < min_duration_ms

        # reading speed check
        if max_cps is not None and duration_ms > 0 and not under_minimum:
            cps = chars / (duration_ms / 1000)
            # Compared at the precision the sheet prints, for the same reason.
            if round(cps, 2) > max_cps:
                report.findings.append(
                    CueFinding(
                        cue_index=idx,
                        check="reading_speed",
                        value=round(cps, 2),
                        threshold=max_cps,
                        unit="chars/sec",
                        timecode=timecode,
                        text_preview=preview,
                        auto_fixable=True,
                    )
                )
                report.over_cps_count += 1

        # minimum duration. A cue whose out-time is not after its in-time is a
        # different defect from a cue that is merely short: it never displays at
        # all, and it is the row that would divide by zero if the reading-speed
        # check did not already require a positive duration. It is named as
        # itself rather than reported as "0.0 seconds, limit 0.833".
        if min_duration_s is not None and duration_ms <= 0:
            report.findings.append(
                CueFinding(
                    cue_index=idx,
                    check="non_positive_duration",
                    value=round(c["duration"], 3),
                    threshold=0.0,
                    unit="seconds",
                    timecode=timecode,
                    text_preview=preview,
                    auto_fixable=True,
                )
            )
            report.under_duration_count += 1
            report.non_positive_duration_count += 1
        elif under_minimum:
            report.findings.append(
                CueFinding(
                    cue_index=idx,
                    check="min_duration",
                    value=round(c["duration"], 3),
                    threshold=min_duration_s,
                    unit="seconds",
                    timecode=timecode,
                    text_preview=preview,
                    auto_fixable=True,
                )
            )
            report.under_duration_count += 1

        # line length
        longest = max((len(ln) for ln in c["lines"]), default=0)
        if max_line_chars is not None and longest > max_line_chars:
            report.findings.append(
                CueFinding(
                    cue_index=idx,
                    check="line_length",
                    value=float(longest),
                    threshold=float(max_line_chars),
                    unit="chars",
                    timecode=timecode,
                    text_preview=preview,
                    auto_fixable=False,
                )
            )
            report.over_line_chars_count += 1

        # line count
        if max_lines is not None and len(c["lines"]) > max_lines:
            report.findings.append(
                CueFinding(
                    cue_index=idx,
                    check="line_count",
                    value=float(len(c["lines"])),
                    threshold=float(max_lines),
                    unit="lines",
                    timecode=timecode,
                    text_preview=preview,
                    auto_fixable=False,
                )
            )
            report.over_line_count += 1

    return report


# --- remediation ----------------------------------------------------------


def remediate_subtitles(
    text: str,
    max_cps: float = DEFAULT_MAX_CPS,
    min_duration_s: float = DEFAULT_MIN_CUE_SECONDS,
) -> tuple[str, int]:
    """Extend cue out-times so reading speed and minimum duration are met.

    Repair strategy: extend the end-time of each cue into free space.
    Never shorten a cue, never create overlaps, leave a 1-frame gap (~42ms at 24fps).

    Returns: (corrected_srt_text, number_of_cues_changed)
    """
    cues = parse_srt(text)
    changed = 0

    # Real ASR subtitle tracks are not always in chronological order, and the
    # "do not run into the NEXT cue" rule is only sound if "next" means the next
    # cue in TIME. On a real archive.org track an out-of-order cue produced a
    # 21-second cue overlapping its neighbour. Sort before repairing.
    cues.sort(key=lambda c: (c["start"], c["end"]))

    for i, c in enumerate(cues):
        chars = len(c["text"].strip())
        needed = max(chars / max_cps if max_cps else 0.0, min_duration_s)
        # SRT only stores milliseconds; round the requirement up to avoid floating
        # comparisons that land back under the threshold.
        needed = math.ceil(needed * 1000) / 1000
        if c["duration"] >= needed:
            continue
        # Do not run into the next cue; leave ~42ms gap (1 frame at 24fps).
        # Clamp to the cue's own end so an already-overlapping source cue is never
        # extended further.
        ceiling = (
            cues[i + 1]["start"] - 0.042 if i + 1 < len(cues) else c["start"] + needed
        )
        new_end = min(c["start"] + needed, ceiling)
        if new_end > c["end"]:
            c["end"] = new_end
            c["duration"] = new_end - c["start"]
            changed += 1

    return _render_srt(cues), changed


def _fmt_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _render_srt(cues: list[dict]) -> str:
    parts = []
    for i, c in enumerate(cues, start=1):
        parts.append(
            f"{i}\n{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}\n"
            + "\n".join(c["lines"])
        )
    return "\n\n".join(parts) + "\n"


# --- why a leftover cue is still red -------------------------------------

REASON_NO_FREE_SPACE = "no free space"
REASON_LINE_TOO_LONG = "line too long"
REASON_BOXED_IN = "min duration boxed in"


def explain_leftovers(
    text: str,
    max_cps: float = DEFAULT_MAX_CPS,
    min_duration_s: float = DEFAULT_MIN_CUE_SECONDS,
    max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
    max_lines: int = DEFAULT_MAX_LINES,
) -> dict[int, str]:
    """Say why each cue that repair could not clear is still failing.

    Runs the same sort/ceiling arithmetic as remediate_subtitles, so the reason
    is derived from the repair that actually ran, not from a second guess.

    Keys are 1-based cue indices in the ORIGINAL parse order, matching the
    cue_index carried on findings from the source file, so a reason drops
    straight onto its row on the sheet.
    """
    cues = parse_srt(text)
    for n, c in enumerate(cues, start=1):
        c["_orig_index"] = n
    cues.sort(key=lambda c: (c["start"], c["end"]))
    reasons: dict[int, str] = {}

    for i, c in enumerate(cues):
        idx = c["_orig_index"]
        chars = len(c["text"].strip())
        needed = max(chars / max_cps if max_cps else 0.0, min_duration_s)
        needed = math.ceil(needed * 1000) / 1000

        ceiling = (
            cues[i + 1]["start"] - 0.042 if i + 1 < len(cues) else c["start"] + needed
        )
        reachable = max(min(c["start"] + needed, ceiling), c["end"]) - c["start"]

        # Text problems retiming can never touch come first: no amount of
        # extra screen time shortens a 60-character line.
        if max((len(ln) for ln in c["lines"]), default=0) > max_line_chars or (
            len(c["lines"]) > max_lines
        ):
            reasons[idx] = REASON_LINE_TOO_LONG
            continue

        # Millisecond comparison, matching measure_subtitles: a cue the repair
        # can bring to exactly the needed duration is cleared, and must not be
        # given a leftover reason by a float residue of 1e-14 seconds.
        if int(round(reachable * 1000)) >= int(round(needed * 1000)):
            continue  # repair cleared this cue

        # Still short after extending as far as the next cue allows.
        if reachable < min_duration_s:
            reasons[idx] = REASON_BOXED_IN
        else:
            reasons[idx] = REASON_NO_FREE_SPACE

    return reasons
