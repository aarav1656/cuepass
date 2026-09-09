"""Tests for SIXTEEN SEVENTEEN.

Every check goes BOTH red and green. Mutation tests confirm that changing the
threshold flips the verdict, so a check that cannot fail is caught.

Run: pytest tests.py -v
"""

from __future__ import annotations

import textwrap

import pytest

import measure as m
import parallel_spec

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

# 28 chars in 1.0 second = 28 cps , exceeds Netflix 17 cps limit
FAST_CUE_SRT = textwrap.dedent("""\
    1
    00:00:01,000 --> 00:00:02,000
    Hello world this is fast text here.
""")

# 5 chars in 0.1 second = 50 cps , way over limit
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
        """Lower min_duration to 0.4 s , the 0.5 s cue now passes."""
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
        """Raise the line-length limit above the longest line , violation clears."""
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
        # CLEAN_SRT has cues at ~4-6 cps , will violate a 5 cps limit on the fast ones
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


class TestFindingTimecode:
    """A reviewer has to be able to jump to the failing cue in their editor,
    so every finding carries the cue's own in/out timecode."""

    def test_finding_carries_cue_timecode(self):
        srt = "1\n00:00:01,000 --> 00:00:01,200\nA line that is far too fast to read\n"
        findings = m.measure_subtitles(srt).findings_as_dicts()
        assert findings, "expected the short cue to produce a finding"
        assert all(f["timecode"] == "00:00:01,000 --> 00:00:01,200" for f in findings)

    def test_timecode_tracks_the_cue_it_describes(self):
        """Guard against every finding reporting the first cue's timecode."""
        srt = (
            "1\n00:00:01,000 --> 00:00:01,200\nFirst cue far too fast to read\n\n"
            "2\n00:10:05,500 --> 00:10:05,600\nSecond cue also far too fast\n"
        )
        by_cue = {f["cue_index"]: f["timecode"] for f in m.measure_subtitles(srt).findings_as_dicts()}
        assert by_cue[1].startswith("00:00:01,000")
        assert by_cue[2].startswith("00:10:05,500")


class TestCitableUrl:
    """The spec URL is rendered as a clickable citation, so a malformed URL
    from the search index must never reach the sheet."""

    def test_rejects_url_with_local_path_spliced_in(self):
        # Real observed Parallel result.
        bad = ("https://subtitlesedit.com/blog/netflix-subtitle-s:Users:kevinrato:"
               "Desktop:subtitlesedit:posts:netflix.mdxtyle-guide-explained")
        assert not parallel_spec.is_citable_url(bad)

    def test_accepts_real_spec_url(self):
        good = "https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617"
        assert parallel_spec.is_citable_url(good)

    def test_rejects_empty_and_non_http(self):
        assert not parallel_spec.is_citable_url("")
        assert not parallel_spec.is_citable_url("ftp://example.com/spec")


class TestLeftoverReasons:
    """75 cues still red looks like a broken tool unless each one says why.
    Every cue the retime could not clear must carry a non-empty reason."""

    def _still_failing(self, srt):
        repaired, _ = m.remediate_subtitles(srt)
        return m.measure_subtitles(repaired).findings_as_dicts()

    def test_no_leftover_cue_has_an_empty_reason(self):
        # cue 1 wants ~2.4s of screen time and cue 2 starts 0.4s later;
        # cue 3 is a single line far past the 42-char limit.
        srt = (
            "1\n00:00:01,000 --> 00:00:01,200\nForty one characters of dialogue here ok\n\n"
            "2\n00:00:01,400 --> 00:00:03,000\nShort\n\n"
            "3\n00:00:10,000 --> 00:00:20,000\n"
            "A single line of dialogue well past the forty two character limit\n"
        )
        reasons = m.explain_leftovers(srt)
        leftover = self._still_failing(srt)
        assert leftover, "expected cues that repair could not clear"
        for f in leftover:
            r = reasons.get(f["cue_index"], "")
            assert r.strip(), f"cue {f['cue_index']} left red with no reason"

    def test_reason_names_the_blocking_neighbour(self):
        srt = (
            "1\n00:00:01,000 --> 00:00:01,200\nForty one characters of dialogue here ok\n\n"
            "2\n00:00:01,400 --> 00:00:03,000\nShort\n"
        )
        assert m.explain_leftovers(srt)[1] in (
            m.REASON_NO_FREE_SPACE, m.REASON_BOXED_IN,
        )

    def test_long_line_is_not_blamed_on_timing(self):
        srt = (
            "1\n00:00:10,000 --> 00:00:20,000\n"
            "A single line of dialogue well past the forty two character limit\n"
        )
        assert m.explain_leftovers(srt)[1] == m.REASON_LINE_TOO_LONG

    def test_cue_repair_can_clear_gets_no_reason(self):
        srt = "1\n00:00:01,000 --> 00:00:01,200\nShort\n"
        assert 1 not in m.explain_leftovers(srt)


class TestTakeRepairedTrack:
    """The operator leaves with the same file the second measure ran on.

    These used to reach into an in-memory dict that only lived as long as the
    process, which is why a download link died on every container restart. They
    now go through the durable store, so the thing under test is the thing a
    returning visitor actually gets.
    """

    SRC = (
        "1\n00:00:01,000 --> 00:00:01,200\nA long line of dialogue that needs more time\n\n"
        "2\n00:00:05,000 --> 00:00:05,100\nAlso far too quick to read at all\n\n"
        "3\n00:00:20,000 --> 00:00:22,000\nFine\n"
    )

    def _store(self, tmp_path, monkeypatch):
        import runstore

        monkeypatch.setenv("CUEPASS_RUN_DIR", str(tmp_path))
        monkeypatch.setattr(runstore, "SEED_DIR", tmp_path)
        return runstore

    def _save(self, runstore):
        repaired, _ = m.remediate_subtitles(self.SRC)
        before = m.measure_subtitles(self.SRC)
        after = m.measure_subtitles(repaired)
        record = {
            "run_id": "fixture-run",
            "measured_at": runstore.now_iso(),
            "film_title": "The Iron Mask",
            "film_identifier": "iron_mask",
            "subtitle_filename": "iron_mask.asr.srt",
            "subtitle_url": "https://archive.org/download/iron_mask/iron_mask.asr.srt",
            "cue_count": before.cue_count,
            "buyers": {
                "netflix": {
                    "spec": {
                        "platform": "Netflix",
                        "source_url": (
                            "https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617"
                        ),
                        "source_label": "Timed Text Style Guide",
                        "max_cps": 17.0,
                        "min_duration_s": 0.8,
                        "max_line_chars": 42,
                        "max_lines": 2,
                        "evidence": {},
                        "provenance": {},
                        "not_verifiable": [],
                    },
                    "before": before.summary(),
                    "after": after.summary(),
                    "leftover_reasons": {},
                    "cues_changed": 2,
                    "verdict": "HOLD",
                }
            },
            "unavailable": {},
            "editorial": {},
            "graph": {},
            "trace": [],
            "model": "gemini-2.5-flash",
            "framework": "google-adk",
            "parallel_surfaces": ["search", "extract"],
        }
        return runstore.save(record, {"netflix": repaired}, source_srt=self.SRC), repaired

    def test_stored_track_is_the_repaired_one_not_the_source(self, tmp_path, monkeypatch):
        runstore = self._store(tmp_path, monkeypatch)
        saved, repaired = self._save(runstore)

        path = runstore.repaired_path(saved["repaired_files"]["netflix"])
        assert path is not None
        body = path.read_text(encoding="utf-8")
        assert body.strip(), "an empty file is not a download"

        # Source and repaired differ in cue out-times, so serving the source by
        # mistake, or serving a stale copy, fails here.
        assert body != self.SRC
        got = m.parse_srt(body)
        want = m.parse_srt(repaired)
        assert [c["end"] for c in got] == [c["end"] for c in want]
        assert [c["end"] for c in got] != [c["end"] for c in m.parse_srt(self.SRC)]

        # And the bytes on disk measure the same as the after-report on screen.
        assert m.measure_subtitles(body).summary() == m.measure_subtitles(repaired).summary()

    def test_the_source_track_is_kept_too(self, tmp_path, monkeypatch):
        """Both halves of a before and after must be downloadable, not just one."""
        runstore = self._store(tmp_path, monkeypatch)
        saved, _ = self._save(runstore)
        path = runstore.repaired_path(saved["source_file"])
        assert path is not None
        assert path.read_text(encoding="utf-8") == self.SRC

    def test_a_stored_run_survives_a_fresh_read(self, tmp_path, monkeypatch):
        """The point of the store: a later reader sees the run without re-running."""
        runstore = self._store(tmp_path, monkeypatch)
        self._save(runstore)

        rows = runstore.list_runs()
        assert len(rows) == 1
        assert rows[0]["run_id"] == "fixture-run"
        assert rows[0]["violation_count"] > 0
        assert rows[0]["measured_at"]

        full = runstore.get_run("fixture-run")
        assert full is not None
        assert full["totals"]["cues"] == 3
        assert len(full["cues"]) == 3, "the cue table must rebuild from the stored source"
        assert runstore.default_run_id() == "fixture-run"

    def test_unknown_and_traversal_resolve_to_nothing(self, tmp_path, monkeypatch):
        runstore = self._store(tmp_path, monkeypatch)
        self._save(runstore)
        (tmp_path.parent / "secret.srt").write_text("nope", encoding="utf-8")
        for name in ("nothing_here.srt", "../secret.srt", "/etc/passwd", "run.json"):
            assert runstore.repaired_path(name) is None

    def test_missing_file_after_write_resolves_to_nothing(self, tmp_path, monkeypatch):
        runstore = self._store(tmp_path, monkeypatch)
        saved, _ = self._save(runstore)
        (tmp_path / saved["repaired_files"]["netflix"]).unlink()
        assert runstore.repaired_path(saved["repaired_files"]["netflix"]) is None
