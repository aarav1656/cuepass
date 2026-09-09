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

# Default thresholds; overridden at runtime by the spec from parallel_spec.py
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

    @property
    def total_violations(self) -> int:
        return len(self.findings)

    @property
    def passed(self) -> bool:
        return self.total_violations == 0

    def summary(self) -> dict:
        return {
            "cue_count": self.cue_count,
            "total_violations": self.total_violations,
            "over_cps_count": self.over_cps_count,
            "under_duration_count": self.under_duration_count,
            "over_line_chars_count": self.over_line_chars_count,
            "over_line_count": self.over_line_count,
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

    `spec` is a dict from parallel_spec.fetch_spec(); its thresholds override
    the defaults. If spec is None, the default Netflix constants apply.
    """
    if spec:
        max_cps = spec.get("max_cps", max_cps)
        min_duration_s = spec.get("min_duration_s", min_duration_s)
        max_line_chars = spec.get("max_line_chars", max_line_chars)
        max_lines = spec.get("max_lines", max_lines)
        platform = spec.get("platform", "Netflix")
        source_url = spec.get("source_url", "")
        source_label = spec.get("source_label", "")
        is_cached = spec.get("is_cached", True)
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
    )

    for idx, c in enumerate(cues, start=1):
        chars = len(c["text"].strip())
        preview = c["text"][:60]
        timecode = f"{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}"

        # reading speed check
        if c["duration"] > 0 and c["duration"] >= min_duration_s:
            cps = chars / c["duration"]
            if cps > max_cps:
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

        # minimum duration
        if c["duration"] < min_duration_s:
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
        if longest > max_line_chars:
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
        if len(c["lines"]) > max_lines:
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
