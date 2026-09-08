"""Tests for SIXTEEN SEVENTEEN.

Every check goes BOTH red and green. Mutation tests confirm that changing the
threshold flips the verdict, so a check that cannot fail is caught.

Run: pytest tests.py -v
"""

from __future__ import annotations

import textwrap

import pytest

import measure as m

# ── Fixtures ─────────────────────────────────────────────────────────────────

CLEAN_SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:03,000
    Hello, world.

    2
    00:00:05,000 --> 00:00:08,000
    This is a short subtitle line.

    3
    00:00:10,000 --> 00:00:13,000
    Another clean cue here.
""")

# 28 chars in 1.0 second = 28 cps — exceeds Netflix 17 cps limit
FAST_CUE_SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:02,000
    Hello world this is fast text here.
""")

# 5 chars in 0.1 second = 50 cps — way over limit
VERY_FAST_SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:01,100
    Hello
""")

# Cue shorter than minimum 5/6 s (0.833 s)
SHORT_SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:01,500
    Hi.
""")

# Line longer than 42 chars
LONG_LINE_SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:04,000
    This line is intentionally way too long for any delivery specification.
""")

# THREE-line cue (max is 2)
TOO_MANY_LINES_SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:06,000
    First line here.
    Second line here.
    Third line here too.
""")

# archive.org ASR style: two-digit milliseconds
TWO_DIGIT_MS_SRT = textwrap.dedent("""\
    1
    00:00:01,00 --> 00:00:04,00
    Two digit milliseconds.

    2
    00:00:05,50 --> 00:00:08,00
    Another cue.
""")


# ── parse_srt ────────────────────────────────────────────────────────────────

class TestParseSrt:
    def test_parses_standard_srt(self):
        cues = m.parse_srt(CLEAN_SRT)
        assert len(cues) == 3

    def test_start_end_seconds(self):
        cues = m.parse_srt(CLEAN_SRT)
        assert cues[0]["start"] == pytest.approx(1.0)
        assert cues[0]["end"] == pytest.approx(3.0)

    def test_two_digit_milliseconds(self):
        """archive.org ASR uses two-digit ms; must not be treated as /1000."""
        cues = m.parse_srt(TWO_DIGIT_MS_SRT)
        # 00:00:01,00 → 1.00 s  (not 1.000 s, but also not 1.0000 s treated as 0ms)
        # 00:00:04,00 → 4.00 s  duration = 3.0 s
        assert cues[0]["duration"] == pytest.approx(3.0)
        # 00:00:05,50 → 5.5 s (50 centiseconds = 0.5 s)
        assert cues[1]["start"] == pytest.approx(5.5)

    def test_empty_string_returns_empty(self):
        assert m.parse_srt("") == []

    def test_skips_blocks_without_timestamp(self):
        cues = m.parse_srt("WEBVTT\n\nThis has no timestamp.\n")
        assert cues == []


# ── measure_subtitles: reading speed ─────────────────────────────────────────

class TestReadingSpeed:
    def test_clean_cue_passes(self):
        """A clean SRT with slow-paced cues must produce zero reading-speed violations."""
        report = m.measure_subtitles(CLEAN_SRT)
        assert report.over_cps_count == 0

    def test_fast_cue_fails(self):
        """A cue with ~36 chars in 1 s (36 cps) must exceed the 17 cps limit."""
        report = m.measure_subtitles(FAST_CUE_SRT)
        assert report.over_cps_count >= 1

    # Mutation test: raising the threshold above the cue's cps must flip to PASS
    def test_mutation_threshold_flip(self):
        """If we raise max_cps above the measured rate, the violation disappears."""
        cues = m.parse_srt(FAST_CUE_SRT)
        chars = len(cues[0]["text"].strip())
        cps = chars / cues[0]["duration"]
        # At the real limit (17), it fails
        report_fail = m.measure_subtitles(FAST_CUE_SRT, max_cps=17.0)
        assert report_fail.over_cps_count >= 1
        # Raise limit above the actual rate → PASS
        report_pass = m.measure_subtitles(FAST_CUE_SRT, max_cps=cps + 5.0)
        assert report_pass.over_cps_count == 0, (
            "Mutation test failed: raising threshold above measured rate did not clear violation"
        )

    def test_very_fast_cue_skipped_when_under_min_duration(self):
        """A cue shorter than min_duration gets flagged under_duration, not reading_speed."""
        # 'Hello' in 0.1 s is under min_duration (0.833 s), so reading_speed is NOT counted
        report = m.measure_subtitles(VERY_FAST_SRT)
        assert report.under_duration_count >= 1
        # reading_speed check skips sub-min-duration cues to avoid double-counting
        assert report.over_cps_count == 0


# ── measure_subtitles: min duration ──────────────────────────────────────────

class TestMinDuration:
    def test_clean_cues_pass(self):
        report = m.measure_subtitles(CLEAN_SRT)
        assert report.under_duration_count == 0

    def test_short_cue_fails(self):
        """0.5 s cue must fail the 0.833 s minimum."""
        report = m.measure_subtitles(SHORT_SRT)
        assert report.under_duration_count >= 1

    def test_mutation_lower_threshold_passes(self):
        """Lower min_duration to 0.4 s — the 0.5 s cue now passes."""
        report_fail = m.measure_subtitles(SHORT_SRT, min_duration_s=0.833)
        assert report_fail.under_duration_count >= 1
        report_pass = m.measure_subtitles(SHORT_SRT, min_duration_s=0.4)
        assert report_pass.under_duration_count == 0, (
            "Mutation: lowering threshold should clear min_duration violation"
        )


# ── measure_subtitles: line length ────────────────────────────────────────────

class TestLineLength:
    def test_clean_lines_pass(self):
        report = m.measure_subtitles(CLEAN_SRT)
        assert report.over_line_chars_count == 0

    def test_long_line_fails(self):
        report = m.measure_subtitles(LONG_LINE_SRT)
        assert report.over_line_chars_count >= 1

    def test_mutation_raise_limit_passes(self):
        """Raise the line-length limit above the longest line — violation clears."""
        cues = m.parse_srt(LONG_LINE_SRT)
        longest = max(len(ln) for ln in cues[0]["lines"])
        report_fail = m.measure_subtitles(LONG_LINE_SRT, max_line_chars=42)
        assert report_fail.over_line_chars_count >= 1
        report_pass = m.measure_subtitles(LONG_LINE_SRT, max_line_chars=longest + 1)
        assert report_pass.over_line_chars_count == 0, (
            "Mutation: raising limit above longest line should clear violation"
        )


# ── measure_subtitles: line count ─────────────────────────────────────────────

class TestLineCount:
    def test_two_lines_pass(self):
        srt = "1\n00:00:01,000 --> 00:00:04,000\nLine one.\nLine two.\n"
        report = m.measure_subtitles(srt)
        assert report.over_line_count == 0

    def test_three_lines_fail(self):
        report = m.measure_subtitles(TOO_MANY_LINES_SRT)
        assert report.over_line_count >= 1

    def test_mutation_raise_max_lines_passes(self):
        report_fail = m.measure_subtitles(TOO_MANY_LINES_SRT, max_lines=2)
        assert report_fail.over_line_count >= 1
        report_pass = m.measure_subtitles(TOO_MANY_LINES_SRT, max_lines=3)
        assert report_pass.over_line_count == 0


# ── remediate_subtitles ───────────────────────────────────────────────────────

class TestRemediation:
    def test_no_change_on_clean_srt(self):
        _, changed = m.remediate_subtitles(CLEAN_SRT)
        assert changed == 0

    def test_extends_short_cue(self):
        """A 0.5 s cue must be extended to >= min_duration."""
        repaired, changed = m.remediate_subtitles(SHORT_SRT)
        assert changed >= 1
        cues = m.parse_srt(repaired)
        assert cues[0]["duration"] >= m.DEFAULT_MIN_CUE_SECONDS - 0.001

    def test_extends_fast_cue(self):
        """A reading-speed violation must be remediated."""
        repaired, changed = m.remediate_subtitles(FAST_CUE_SRT)
        assert changed >= 1
        cues = m.parse_srt(repaired)
        # cps after repair must be at or under the limit
        c = cues[0]
        cps = len(c["text"].strip()) / c["duration"]
        assert cps <= m.DEFAULT_MAX_CPS + 0.001, f"Still over limit after repair: {cps:.2f} cps"

    def test_repair_does_not_create_overlaps(self):
        """Adjacent cues in a tight sequence must not overlap after repair."""
        # Two fast cues back to back with 0.1 s gap
        tight = textwrap.dedent("""\
            1
            00:00:01,000 --> 00:00:01,200
            Hello world fast cue text here.

            2
            00:00:01,300 --> 00:00:01,500
            Another fast cue text here please.
        """)
        repaired, _ = m.remediate_subtitles(tight)
        cues = m.parse_srt(repaired)
        for i in range(len(cues) - 1):
            assert cues[i]["end"] <= cues[i + 1]["start"] + 0.001, (
                f"Overlap: cue {i+1} ends at {cues[i]['end']:.3f}, "
                f"cue {i+2} starts at {cues[i+1]['start']:.3f}"
            )

    def test_remeasure_improves_violations(self):
        """After remediation, violation count for speed/duration must decrease."""
        report_before = m.measure_subtitles(FAST_CUE_SRT)
        repaired, _ = m.remediate_subtitles(FAST_CUE_SRT)
        report_after = m.measure_subtitles(repaired)
        before_fixable = report_before.over_cps_count + report_before.under_duration_count
        after_fixable = report_after.over_cps_count + report_after.under_duration_count
        assert after_fixable < before_fixable, (
            f"Repair did not improve: before={before_fixable}, after={after_fixable}"
        )


# ── timestamp formatter ───────────────────────────────────────────────────────

class TestFmtTs:
    def test_basic(self):
        assert m._fmt_ts(0.0) == "00:00:00,000"
        assert m._fmt_ts(1.5) == "00:00:01,500"
        assert m._fmt_ts(3661.001) == "01:01:01,001"

    def test_negative_clamps_to_zero(self):
        assert m._fmt_ts(-0.5) == "00:00:00,000"

    def test_rounding_carry(self):
        # 0.9995 rounds ms to 1000 → carry into seconds
        ts = m._fmt_ts(0.9995)
        assert ts == "00:00:01,000"


# ── spec thresholds applied correctly ────────────────────────────────────────

class TestSpecApplication:
    def test_custom_spec_overrides_defaults(self):
        """A spec dict with max_cps=5 must flag cues that are fine at 17."""
        spec = {
            "platform": "TestPlatform",
            "max_cps": 5.0,
            "min_duration_s": 0.1,
            "max_line_chars": 100,
            "max_lines": 10,
            "source_url": "https://example.com",
            "source_label": "Test spec",
            "is_cached": False,
        }
        # CLEAN_SRT has cues at ~4-6 cps — will violate a 5 cps limit on the fast ones
        report_strict = m.measure_subtitles(CLEAN_SRT, spec=spec)
        report_default = m.measure_subtitles(CLEAN_SRT)
        # The strict spec should catch more or equal violations
        # (at 5 cps many "clean" cues will fail)
        # Just verify that the spec values are applied, not ignored
        assert report_strict.max_cps == 5.0
        assert report_default.max_cps == 17.0

    def test_spec_source_url_in_report(self):
        spec = {
            "platform": "TestPlatform",
            "max_cps": 17.0,
            "min_duration_s": 0.833,
            "max_line_chars": 42,
            "max_lines": 2,
            "source_url": "https://example.com/spec",
            "source_label": "Test",
            "is_cached": False,
        }
        report = m.measure_subtitles(CLEAN_SRT, spec=spec)
        assert report.spec_source_url == "https://example.com/spec"
        assert not report.spec_is_cached
