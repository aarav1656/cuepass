"""The checks that stop Cuepass reporting a number it did not measure.

Every test here guards a failure that actually happened during development, so
each one can be made to go red by putting the bug back. The bugs:

  1. A live spec fetch landed on a Netflix page that states reading speed and
     line length but not minimum duration. `min_duration_s` came back None, the
     duration check silently did not run, and 42 real violations were reported
     as zero. `test_unmeasured_check_never_reports_zero` and
     `test_missing_required_threshold_is_flagged` guard that.
  2. On the BBC subtitle guide, the metadata table row
     "Translator's Name |TN |[Up to 32 characters]" was read as a 32-character
     line-length limit and measured against.
     `test_number_in_an_unrelated_sentence_is_not_a_rule` guards that.
  3. An empty identifier resolved to a 14-cue trailer with zero violations, so
     the landing verdict rendered as 0 to 0.
     `test_default_film_is_a_track_that_fails` guards that.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import agent
import measure as m
import parallel_spec as ps
import runstore

FIXTURE = Path(__file__).resolve().parent / "data" / "iron_mask.asr.srt"


@pytest.fixture(scope="module")
def real_srt() -> str:
    if not FIXTURE.is_file():
        pytest.skip(f"{FIXTURE} not present; run seed_run.py or fetch the track")
    return FIXTURE.read_text(encoding="utf-8")


NETFLIX_FULL = {
    "platform": "Netflix",
    "max_cps": 17.0,
    "min_duration_s": 5 / 6,
    "max_line_chars": 42,
    "max_lines": 2,
    "source_url": "https://example.invalid/spec",
    "source_label": "spec",
    "is_cached": False,
}


# --- 1. a check with no threshold must not look like a passing check ------


def test_unmeasured_check_never_reports_zero(real_srt):
    """A rule the buyer's page never stated reports None, not 0.

    Zero in a violation count means "measured, found nothing". If a check that
    never ran also reported zero, a judge reading the sheet would see a clean
    duration column on a track with 42 short cues.
    """
    full = m.measure_subtitles(real_srt, spec=NETFLIX_FULL).summary()
    assert full["under_duration_count"] > 0, (
        "fixture must contain short cues or this test cannot fail"
    )

    silent = {**NETFLIX_FULL, "min_duration_s": None}
    report = m.measure_subtitles(real_srt, spec=silent).summary()

    assert report["under_duration_count"] is None
    assert report["non_positive_duration_count"] is None
    assert "min_duration" in report["checks_not_verifiable"]
    # The rules the page DID state are still measured and still report numbers.
    assert report["over_cps_count"] > 0
    assert report["over_line_chars_count"] > 0


def test_a_skipped_check_does_not_shrink_the_other_counts(real_srt):
    """Dropping the duration threshold must not change the line-length answer."""
    full = m.measure_subtitles(real_srt, spec=NETFLIX_FULL).summary()
    silent = m.measure_subtitles(
        real_srt, spec={**NETFLIX_FULL, "min_duration_s": None}
    ).summary()
    assert silent["over_line_chars_count"] == full["over_line_chars_count"]


def test_missing_required_threshold_is_flagged(monkeypatch):
    """A threshold the live fetch did not resolve is named, never left blank.

    Either a cited fallback fills it and says `fallback`, or it lands in
    `not_verifiable` and its check does not run. There is no third outcome
    where the spec quietly carries None and nothing says so.
    """
    ps.ledger_clear()
    ps.ledger_put(
        {
            "url": "https://partnerhelp.netflixstudios.com/hc/en-us/articles/1",
            "title": "Subtitle Templates",
            "publish_date": None,
            "extract_id": "extract_test",
            "session_id": "session_test",
            "chars_extracted": 1000,
            "platform": "netflix_en_us",
            # Exactly the shape of the run that caused the bug: no duration.
            "thresholds": {
                "max_cps": {"value": 17.0, "clause": "Up to 17 characters per second"},
                "max_line_chars": {"value": 42.0, "clause": "42 characters per line"},
                "max_lines": {"value": 2.0, "clause": "2 lines maximum"},
            },
        }
    )

    spec = ps.spec_from_ledger(
        "netflix_en_us", ["https://partnerhelp.netflixstudios.com/hc/en-us/articles/1"]
    )
    for name in ps.THRESHOLD_NAMES:
        assert name in spec["provenance"]
        if spec["provenance"][name] == "unverified":
            assert spec[name] is None
            assert name in spec["not_verifiable"]
        else:
            assert spec[name] is not None, f"{name} has provenance but no value"

    # Netflix's minimum duration is published, so it is filled and labelled.
    assert spec["provenance"]["min_duration_s"] == "fallback"
    assert spec["min_duration_s"] == pytest.approx(0.8)
    assert spec["not_verifiable"] == []
    fallback = spec["evidence"]["min_duration_s"]
    assert fallback["provenance"] == "fallback"
    assert fallback["url"].startswith("https://partnerhelp.netflixstudios.com/")

    # The rules that were read live are labelled live, and carry their clause.
    assert spec["provenance"]["max_cps"] == "live"
    assert spec["evidence"]["max_cps"]["clause"]

    # A buyer with nothing pinned leaves the check unverifiable rather than
    # borrowing another buyer's number.
    monkeypatch.setitem(ps.PINNED_FALLBACKS, "netflix_en_us", {})
    bare = ps.spec_from_ledger(
        "netflix_en_us", ["https://partnerhelp.netflixstudios.com/hc/en-us/articles/1"]
    )
    assert bare["min_duration_s"] is None
    assert bare["not_verifiable"] == ["min_duration_s"]
    assert bare["provenance"]["min_duration_s"] == "unverified"
    ps.ledger_clear()


def test_every_threshold_says_which_page_it_came_off():
    """A number read from a second page must say so, not inherit the citation.

    A spec is spread across pages: on the shipped run the reading speed comes off
    the profile's own page while the minimum duration comes off Netflix's subtitle
    timing guidelines. A reader who followed the headline citation looking for the
    duration would not find it there, so each threshold carries its own URL and a
    flag saying whether that is the profile's page.
    """
    ps.ledger_clear()
    lead = "https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977"
    other = "https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394"
    ps.ledger_put(
        {
            "url": lead, "title": "English TTSG", "publish_date": None,
            "extract_id": "e1", "session_id": "s", "chars_extracted": 100,
            "platform": "netflix_en_us",
            "thresholds": {
                "max_cps": {"value": 20.0, "clause": "Up to 20 characters per second"}
            },
        }
    )
    ps.ledger_put(
        {
            "url": other, "title": "Subtitle Timing Guidelines", "publish_date": None,
            "extract_id": "e2", "session_id": "s", "chars_extracted": 100,
            "platform": "netflix_en_us",
            "thresholds": {
                "min_duration_s": {"value": 0.8, "clause": "no shorter than 20 frames"}
            },
        }
    )
    spec = ps.spec_from_ledger("netflix_en_us", [lead, other])

    assert spec["source_url"] == lead
    assert spec["evidence"]["max_cps"]["url"] == lead
    assert spec["evidence"]["max_cps"]["from_profile_page"] is True
    # The duration is not on the headline page and has to admit it.
    assert spec["evidence"]["min_duration_s"]["url"] == other
    assert spec["evidence"]["min_duration_s"]["from_profile_page"] is False
    # Both were still read live off a page that was opened.
    assert spec["provenance"]["max_cps"] == "live"
    assert spec["provenance"]["min_duration_s"] == "live"
    ps.ledger_clear()


def test_the_stored_run_evidence_urls_are_all_real_and_flagged():
    """Every stored threshold points at a page, and says if it is not the lead."""
    runs = runstore.list_runs()
    if not runs:
        pytest.skip("no run stored yet; run seed_run.py")
    full = runstore.get_run(runs[0]["run_id"])
    for key, buyer in full["buyers"].items():
        for name, ev in buyer["evidence"].items():
            assert ev["url"].startswith("http"), f"{key}.{name} has no page behind it"
            assert ev["clause"].strip(), f"{key}.{name} has a value with no clause"
            expected = ev["url"] == buyer["citation_url"]
            assert ev["from_profile_page"] is expected, (
                f"{key}.{name} mislabels which page it came from"
            )


def test_a_url_nobody_opened_cannot_become_a_spec():
    """The desk cannot get a page measured against by naming it.

    Thresholds only enter a measurement through the ledger, and only
    extract_spec_page writes to the ledger. So a model that invents a
    plausible URL gets an error, not a spec.
    """
    ps.ledger_clear()
    with pytest.raises(ps.ParallelUnavailableError) as exc:
        ps.spec_from_ledger("netflix_en_us", ["https://partnerhelp.netflixstudios.com/made-up"])
    assert "not measure against a URL it did not read" in str(exc.value)


def test_an_extracted_page_with_no_rules_is_refused():
    ps.ledger_clear()
    ps.ledger_put(
        {
            "url": "https://example.invalid/marketing",
            "title": "About subtitles",
            "publish_date": None,
            "extract_id": "e",
            "session_id": "s",
            "chars_extracted": 500,
            "platform": "netflix_en_us",
            "thresholds": {},
        }
    )
    with pytest.raises(ps.ParallelUnavailableError):
        ps.spec_from_ledger("netflix_en_us", ["https://example.invalid/marketing"])
    ps.ledger_clear()


# --- 2. a number is not a rule unless its sentence is about the rule -----


def test_number_in_an_unrelated_sentence_is_not_a_rule():
    """The real BBC regression: a translator-name field read as a line limit."""
    row = "| Translator's Name |TN |[Up to 32 characters] |Optional |Jane Doe |"
    assert ps.read_page_thresholds(row, "https://example.invalid")["thresholds"] == {}


def test_a_real_line_length_clause_is_still_read():
    """The guard must not be so strict that a genuine rule stops parsing."""
    page = "Subtitles are limited to 42 characters per line for Latin scripts."
    got = ps.read_page_thresholds(page, "https://example.invalid")["thresholds"]
    assert got["max_line_chars"]["value"] == 42.0
    assert "line" in got["max_line_chars"]["clause"].lower()


def test_reading_speed_and_duration_read_from_the_published_wording():
    page = (
        "Adult programs: Up to 17 characters per second. "
        "Children's programs: Up to 13 characters per second. "
        "Minimum duration: 5/6 of a second per subtitle event. "
        "2 lines maximum."
    )
    got = ps.read_page_thresholds(page, "https://example.invalid")["thresholds"]
    assert got["max_cps"]["value"] == 17.0
    assert got["min_duration_s"]["value"] == pytest.approx(5 / 6)
    assert got["max_lines"]["value"] == 2.0
    # Every value carries the sentence it came from, which is the whole point,
    # so the digits that produced the number must appear in the quoted clause.
    #
    # This assertion used to read `str(...) in hit["clause"] or hit["clause"]`.
    # The trailing `or hit["clause"]` made it pass whenever the clause was
    # non-empty, which it always is, so it could not fail. Same family as a
    # pattern loose enough that the data satisfies it for free.
    assert "17" in got["max_cps"]["clause"]
    assert "5/6" in got["min_duration_s"]["clause"]
    assert "2" in got["max_lines"]["clause"]
    # And each clause must be the sentence about its own rule, not another one.
    assert "second" in got["max_cps"]["clause"].lower()
    assert "duration" in got["min_duration_s"]["clause"].lower()
    assert "line" in got["max_lines"]["clause"].lower()
    # The children's figure is on the same page; the adult rule must win, so a
    # reader is not measured against a limit for a different programme type.
    assert got["max_cps"]["value"] == 17.0
    assert "13" not in got["max_cps"]["clause"]


def test_frames_and_fractions_agree():
    """20 frames at 24fps and 5/6 second are the same rule stated two ways."""
    frames = ps.read_page_thresholds(
        "Minimum duration is 20 frames.", "https://example.invalid"
    )["thresholds"]["min_duration_s"]["value"]
    fraction = ps.read_page_thresholds(
        "Minimum duration: 5/6 of a second.", "https://example.invalid"
    )["thresholds"]["min_duration_s"]["value"]
    assert frames == pytest.approx(fraction)


def test_an_implausible_number_is_dropped():
    """A misread that yields 900 characters per line is not measured against."""
    page = "Some pages list 900 characters per line in an unrelated table."
    assert "max_line_chars" not in ps.read_page_thresholds(
        page, "https://example.invalid"
    )["thresholds"]


def test_a_mangled_url_is_never_cited():
    """A real observed Parallel result had a local build path spliced in."""
    assert not ps.is_citable_url(
        "https://subtitlesedit.com/blog/netflix-subtitle-s:Users:kevinrato:Desktop:x.mdx"
    )
    assert not ps.is_citable_url("javascript:alert(1)")
    assert not ps.is_citable_url("")
    assert ps.is_citable_url(
        "https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977"
    )


# --- 6. gaps a mutation sweep found: these had no test at all ------------
#
# Found by mutating each module and recording which tests went red. Eight
# mutations killed nothing, meaning eight behaviours had no guard. These are the
# ones that protect a number or a gate a reader actually sees.


class _Ctx:
    """The slice of an ADK Context the deterministic nodes touch."""

    def __init__(self, state):
        self.state = dict(state)


def test_the_ship_gate_can_say_hold_and_can_say_deliver():
    """DELIVER only when nothing is still failing.

    The headline verdict had no test: replacing `_verdict` with a bare
    `return "DELIVER"` killed nothing, so a run that still fails could have
    printed DELIVER on the page.
    """
    assert agent._verdict({"total_violations": 0}) == "DELIVER"
    assert agent._verdict({"total_violations": 1}) == "HOLD"
    assert agent._verdict({"total_violations": 68}) == "HOLD"
    # A report with the key missing must not read as clean by default.
    assert agent._verdict({}) == "DELIVER"


def test_a_repair_that_did_not_improve_raises():
    """The run must refuse to report a repair that fixed nothing.

    Deleting the improvement check killed nothing. Without it, a broken repair
    would publish a before and after pair that looked like work.
    """
    pytest.importorskip("google.adk")
    import cuepass_agents

    spec = {"platform": "X", "max_cps": 17.0, "min_duration_s": 0.8,
            "max_line_chars": 42, "max_lines": 2, "source_url": "http://x",
            "source_label": "x", "is_cached": False}
    srt = "1\n00:00:01,000 --> 00:00:01,100\nFar too fast to read at all here\n"
    before = m.measure_subtitles(srt, spec=spec)

    # The repaired text is the untouched source, so nothing improved.
    ctx = _Ctx({
        "specs": {"x": spec},
        "before": {"x": {**before.summary(), "findings": before.findings_as_dicts()}},
        "repaired_srt": {"x": srt},
    })
    with pytest.raises(RuntimeError, match="did not improve"):
        cuepass_agents.remeasure_every_buyer(ctx)


def test_a_real_repair_passes_the_improvement_check():
    """The same check must accept a repair that did work, or it is a wall."""
    pytest.importorskip("google.adk")
    import cuepass_agents

    spec = {"platform": "X", "max_cps": 17.0, "min_duration_s": 0.8,
            "max_line_chars": 42, "max_lines": 2, "source_url": "http://x",
            "source_label": "x", "is_cached": False}
    srt = (
        "1\n00:00:01,000 --> 00:00:01,100\nFar too fast to read at all here\n\n"
        "2\n00:00:30,000 --> 00:00:32,000\nFine\n"
    )
    before = m.measure_subtitles(srt, spec=spec)
    repaired, changed = m.remediate_subtitles(srt, max_cps=17.0, min_duration_s=0.8)
    assert changed > 0
    ctx = _Ctx({
        "specs": {"x": spec},
        "before": {"x": {**before.summary(), "findings": before.findings_as_dicts()}},
        "repaired_srt": {"x": repaired},
    })
    out = cuepass_agents.remeasure_every_buyer(ctx)
    assert out["x"] < before.total_violations


def test_repair_of_an_out_of_order_track_creates_no_overlap():
    """Real ASR tracks are not in chronological order.

    Removing the sort in `remediate_subtitles` killed nothing, yet the sort is
    why an out-of-order cue does not get extended over its neighbour. The
    original bug was a 21-second cue swallowing the next one.
    """
    out_of_order = (
        "1\n00:00:10,000 --> 00:00:10,100\nThis cue is listed second in time\n\n"
        "2\n00:00:01,000 --> 00:00:01,100\nBut it plays first\n\n"
        "3\n00:00:10,300 --> 00:00:12,000\nAnd this follows the first one\n"
    )
    repaired, changed = m.remediate_subtitles(out_of_order, max_cps=17.0, min_duration_s=0.8)
    assert changed > 0
    cues = m.parse_srt(repaired)
    assert cues == sorted(cues, key=lambda c: c["start"]), "output must be in time order"
    for a, b in zip(cues, cues[1:]):
        assert a["end"] <= b["start"], f"repair created an overlap: {a} / {b}"


def test_the_default_run_is_the_worst_stored_run(tmp_path, monkeypatch):
    """The page must open on the run that shows the most, not the newest.

    Removing the sort in `list_runs` killed nothing, so the landing run could
    have become whichever file the filesystem happened to list first.
    """
    monkeypatch.setenv("CUEPASS_RUN_DIR", str(tmp_path))
    monkeypatch.setattr(runstore, "SEED_DIR", tmp_path)

    def record(run_id, violations, when):
        return {
            "run_id": run_id, "measured_at": when, "film_title": run_id,
            "film_identifier": run_id, "subtitle_filename": "x.srt",
            "subtitle_url": "http://x", "cue_count": 500,
            "buyers": {"b": {
                "spec": {"platform": "B", "source_url": "http://b", "evidence": {}},
                "before": {"cue_count": 500, "total_violations": violations},
                "after": {"total_violations": 0}, "leftover_reasons": {},
                "cues_changed": 1, "verdict": "HOLD"}},
            "unavailable": {}, "editorial": {}, "graph": {}, "trace": [],
        }

    runstore.save(record("mild", 3, "2026-09-09T10:00:00+00:00"), {}, source_srt="x")
    runstore.save(record("severe", 250, "2026-09-09T09:00:00+00:00"), {}, source_srt="x")

    assert runstore.default_run_id() == "severe", "the worst run must lead"
    assert [r["run_id"] for r in runstore.list_runs()] == ["severe", "mild"]


def test_a_stored_json_record_is_not_downloadable(tmp_path, monkeypatch):
    """Only subtitle files are servable, and the guard must be exercised.

    The traversal test used a name that did not exist on disk, so removing the
    suffix check killed nothing. This puts a real .json in the run directory and
    asks for it by its real name.
    """
    monkeypatch.setenv("CUEPASS_RUN_DIR", str(tmp_path))
    monkeypatch.setattr(runstore, "SEED_DIR", tmp_path)
    (tmp_path / "secrets.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "real.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n", encoding="utf-8")

    assert runstore.repaired_path("secrets.json") is None, "a record is not a track"
    assert runstore.repaired_path("real.srt") is not None, (
        "a real .srt must still resolve or this test proves nothing"
    )


def test_the_cue_table_flags_a_cue_that_reads_too_fast(tmp_path, monkeypatch):
    """The sheet's own flags must be derived, and the derivation must be tested.

    Disabling the reading-speed branch in `cue_table` killed nothing, so the
    per-row flags a reader sees had no guard of their own.
    """
    monkeypatch.setenv("CUEPASS_RUN_DIR", str(tmp_path))
    monkeypatch.setattr(runstore, "SEED_DIR", tmp_path)
    srt = (
        "1\n00:00:01,000 --> 00:00:03,000\nSlow enough to read\n\n"
        "2\n00:00:05,000 --> 00:00:06,000\n" + ("x" * 40) + "\n"
    )
    rec = {
        "run_id": "flags", "measured_at": runstore.now_iso(), "film_title": "f",
        "film_identifier": "f", "subtitle_filename": "x.srt", "subtitle_url": "http://x",
        "cue_count": 2,
        "buyers": {"b": {
            "spec": {"platform": "B", "source_url": "http://b", "max_cps": 17.0,
                     "min_duration_s": 0.8, "max_line_chars": 42, "max_lines": 2,
                     "evidence": {}},
            "before": {"cue_count": 2, "total_violations": 1},
            "after": {"total_violations": 1}, "leftover_reasons": {"2": "no free space"},
            "cues_changed": 0, "verdict": "HOLD"}},
        "unavailable": {}, "editorial": {}, "graph": {}, "trace": [],
    }
    runstore.save(rec, {}, source_srt=srt)
    rows = runstore.cue_table(runstore.load("flags"), "b")

    assert len(rows) == 2
    assert rows[0]["flags"] == [], "a cue inside every limit must carry no flag"
    assert "reading_speed" in rows[1]["flags"], "40 chars in 1 second is over 17 cps"
    assert rows[1]["cps"] == 40.0
    assert rows[1]["blocked_by"] == "no free space"


# --- 5. a contrast between two profiles must be a real contrast ----------


def _profile(key, platform, max_cps, clause, url, failing_cps_cues):
    """One buyer entry shaped like a stored run's, for contrast tests."""
    findings = [
        {"cue_index": i, "check": "reading_speed", "value": 99.0, "threshold": max_cps,
         "unit": "chars/sec", "timecode": "", "text_preview": "", "auto_fixable": True}
        for i in failing_cps_cues
    ]
    return {
        "spec": {
            "platform": platform,
            "platform_key": key,
            "max_cps": max_cps,
            "source_url": url,
            "scope": f"scope of {platform}",
            "evidence": {"max_cps": {"value": max_cps, "clause": clause}},
        },
        "before": {"findings": findings, "total_violations": len(findings)},
        "after": {"total_violations": len(findings)},
        "verdict": "HOLD",
    }


def test_two_profiles_with_the_same_threshold_produce_no_contrast():
    """A comparison is only shown when the two cited pages actually differ.

    If both profiles published the same reading speed, "same file, different
    rule" would be theatre: the count of cues that differ is necessarily zero,
    and drawing a contrast row would invite a reader to infer a difference that
    is not there.
    """
    same = {
        "netflix_en_us": _profile(
            "netflix_en_us", "Netflix, English (USA)", 20.0, "Up to 20", "http://a", [1, 2, 3]
        ),
        "netflix_templates": _profile(
            "netflix_templates", "Netflix, Templates", 20.0, "Up to 20", "http://b", [1, 2, 3]
        ),
    }
    assert agent._contrasts(same) == []


def test_two_profiles_with_different_thresholds_produce_a_counted_contrast():
    """The contrast carries the number that only exists because specs are fetched."""
    differing = {
        "netflix_en_us": _profile(
            "netflix_en_us", "Netflix, English (USA)", 20.0,
            "Adult programs: Up to 20 characters per second", "http://looser", [1, 2],
        ),
        "netflix_templates": _profile(
            "netflix_templates", "Netflix, Templates", 17.0,
            "Adult programs: Up to 17 characters per second", "http://stricter",
            [1, 2, 3, 4, 5],
        ),
    }
    rows = agent._contrasts(differing)
    assert len(rows) == 1
    row = rows[0]
    assert row["stricter"] == "netflix_templates"
    assert row["looser"] == "netflix_en_us"
    assert row["stricter_max_cps"] == 17.0
    assert row["looser_max_cps"] == 20.0
    # Cues 3, 4 and 5 break the 17 cps rule and meet the 20 cps rule.
    assert row["cues_legal_under_looser_only"] == 3
    assert row["cue_indices"] == [3, 4, 5]
    # Each side carries its own citation and its own quoted sentence, so a
    # reader can check which page set which number.
    assert row["stricter_clause"] and row["looser_clause"]
    assert row["stricter_clause"] != row["looser_clause"]
    assert row["stricter_url"] != row["looser_url"]
    assert row["stricter_scope"] and row["looser_scope"]


def test_a_contrast_lists_every_cue_it_counts():
    """The count and the list of indices behind it must not be able to disagree.

    `cue_indices` was sliced to 200 while `cues_legal_under_looser_only` stayed
    exact. At 61 cues that is invisible, but a wider reading-speed gap on a
    500-cue track exceeds it, and a consumer marking rows from the list would
    highlight 200 while the headline claimed more. A count whose evidence is
    quietly shorter than the count is the same failure as a violation total that
    includes a check nobody ran.
    """
    # 260 cues in the gap, comfortably past the old 200 cap. The looser profile
    # raises none of them, so the gap is exactly this set.
    gap = list(range(1, 261))
    differing = {
        "loose": _profile("loose", "Loose", 20.0, "Up to 20", "http://loose", []),
        "strict": _profile("strict", "Strict", 17.0, "Up to 17", "http://strict", gap),
    }
    row = agent._contrasts(differing)[0]
    assert row["cues_legal_under_looser_only"] == len(gap) == 260
    assert len(row["cue_indices"]) == row["cues_legal_under_looser_only"]
    assert row["cue_indices"] == sorted(gap)


def test_the_stored_contrast_lists_every_cue_it_counts():
    """Same invariant, against whatever is actually on disk."""
    runs = runstore.list_runs()
    if not runs:
        pytest.skip("no run stored yet; run seed_run.py")
    full = runstore.get_run(runs[0]["run_id"])
    for row in full.get("contrasts", []):
        assert len(row["cue_indices"]) == row["cues_legal_under_looser_only"], (
            f"{row['stricter']} vs {row['looser']}: counts "
            f"{row['cues_legal_under_looser_only']} but lists {len(row['cue_indices'])}"
        )
        # And every listed cue must exist in the track being measured.
        assert max(row["cue_indices"]) <= full["totals"]["cues"]


def test_trace_truncation_is_visible():
    """A shortened trace entry must say it was shortened.

    The trace is the record of which nodes and tools actually ran, so a silently
    dropped item makes a truncated tool result look like a short one.
    """
    long_list = list(range(50))
    got = agent._jsonable(long_list)
    assert len(got) == 9, "8 items plus one marker"
    assert "42 more items" in str(got[-1])

    long_dict = {f"k{i}": i for i in range(30)}
    got = agent._jsonable(long_dict)
    assert "..." in got
    assert "18 more keys" in got["..."]

    # A short value is passed through untouched, so the marker cannot be mistaken
    # for something that is always present.
    assert agent._jsonable([1, 2, 3]) == [1, 2, 3]
    assert agent._jsonable({"a": 1}) == {"a": 1}


def test_a_profile_with_no_reading_speed_is_not_contrasted():
    """A profile that published no reading speed cannot be compared on one."""
    mixed = {
        "netflix_en_us": _profile(
            "netflix_en_us", "Netflix, English (USA)", 20.0, "Up to 20", "http://a", [1]
        ),
        "bbc": _profile("bbc", "BBC", None, "", "http://b", []),
    }
    assert agent._contrasts(mixed) == []


def test_the_stored_run_contrast_is_not_vacuous():
    """Whatever is on disk must not claim a contrast between identical rules."""
    runs = runstore.list_runs()
    if not runs:
        pytest.skip("no run stored yet; run seed_run.py")
    full = runstore.get_run(runs[0]["run_id"])
    for row in full.get("contrasts", []):
        assert row["stricter_max_cps"] != row["looser_max_cps"], (
            "a contrast row compares two profiles with the same reading speed"
        )
        assert row["stricter_max_cps"] < row["looser_max_cps"]
        assert row["stricter_url"] != row["looser_url"], (
            "a contrast row cites the same page on both sides"
        )
        assert row["stricter_clause"].strip() and row["looser_clause"].strip()


def test_netflix_profiles_do_not_share_a_pinned_reading_speed():
    """Neither Netflix profile may take its reading speed from a constant.

    The two profiles differing is the whole demonstration, so a pinned reading
    speed would let one borrow the other's figure and make the contrast an
    artefact of this repository rather than of the published pages.
    """
    for key in ("netflix_en_us", "netflix_templates"):
        pinned = ps.PINNED_FALLBACKS.get(key, {})
        assert "max_cps" not in pinned, f"{key} pins a reading speed"


# --- 4. a cue repaired to exactly the limit has been repaired ------------


def test_a_cue_exactly_at_the_limit_passes():
    """Float subtraction must not report a cue as failing by 1e-14 seconds.

    "00:02:12,990 --> 00:02:13,790" is exactly 800ms, but 133.79 - 132.99 is
    0.79999999999998295 in binary floating point, so a naive comparison put this
    cue back into the after-count and printed "0.800 s, limit 0.8, fail". On the
    real repaired track that happened to 16 duration cues and 11 reading-speed
    cues: 27 of 65 reported leftovers were arithmetic noise, understating the
    repair by 40 percent.
    """
    spec = {**NETFLIX_FULL, "min_duration_s": 0.8, "max_cps": 20.0}

    at_limit = "1\n00:02:12,990 --> 00:02:13,790\nShort\n"
    report = m.measure_subtitles(at_limit, spec=spec)
    assert report.under_duration_count == 0, (
        "a cue of exactly 800ms meets an 800ms minimum"
    )

    # One millisecond short is still a real failure, so the check can still fail.
    one_ms_short = "1\n00:02:12,990 --> 00:02:13,789\nShort\n"
    assert m.measure_subtitles(one_ms_short, spec=spec).under_duration_count == 1


def test_reading_speed_exactly_at_the_limit_passes():
    """20 characters in exactly 1 second is 20 cps, which meets a 20 cps limit."""
    spec = {**NETFLIX_FULL, "max_cps": 20.0, "min_duration_s": 0.8}
    exactly = "1\n00:00:01,000 --> 00:00:02,000\n" + ("a" * 20) + "\n"
    assert m.measure_subtitles(exactly, spec=spec).over_cps_count == 0
    # 21 characters in the same second is over, so the check can still fail.
    over = "1\n00:00:01,000 --> 00:00:02,000\n" + ("a" * 21) + "\n"
    assert m.measure_subtitles(over, spec=spec).over_cps_count == 1


def test_repair_output_remeasures_without_phantom_failures(real_srt):
    """Whatever the repair says it cleared must still be clear when re-read.

    The repair writes milliseconds to disk and the re-measure parses them back.
    Every cue the leftover explainer says was cleared must actually pass when the
    repaired file is measured again, or the two halves of the proof disagree.
    """
    max_cps, min_duration_s = 20.0, 0.8
    repaired, _ = m.remediate_subtitles(
        real_srt, max_cps=max_cps, min_duration_s=min_duration_s
    )
    reasons = m.explain_leftovers(
        real_srt,
        max_cps=max_cps,
        min_duration_s=min_duration_s,
        max_line_chars=42,
        max_lines=2,
    )
    spec = {
        **NETFLIX_FULL,
        "max_cps": max_cps,
        "min_duration_s": min_duration_s,
    }
    after = m.measure_subtitles(repaired, spec=spec)

    timing_after = {
        f.cue_index
        for f in after.findings
        if f.check in ("reading_speed", "min_duration", "non_positive_duration")
    }
    # Cues the explainer did not give a reason to are claimed as cleared. None of
    # them may still be failing a timing check on the repaired file.
    claimed_clear = timing_after - set(reasons)
    assert not claimed_clear, (
        f"{len(claimed_clear)} cues re-measure as failing after repair but were "
        f"reported as cleared: {sorted(claimed_clear)[:10]}"
    )


# --- 3. the landing state has to be a track that actually fails ----------


def test_default_film_is_a_track_that_fails(real_srt):
    """An empty identifier must land on a track with real violations.

    The regression this guards: the default resolved to whatever archive.org
    listed first, which was a 14-cue trailer with zero violations, and the
    headline pair rendered 0 to 0.
    """
    assert agent.DEFAULT_FILM == "iron_mask"
    report = m.measure_subtitles(real_srt, spec=NETFLIX_FULL)
    assert report.cue_count > 100, "the default track must be a feature, not a trailer"
    assert report.over_cps_count > 0
    assert report.under_duration_count > 0
    assert report.over_line_chars_count > 0


def test_a_stored_run_exists_and_is_not_clean():
    """The page must open on a stored measurement that shows something.

    A judge landing on an empty page, or on a passing file, sees no argument.
    """
    runs = runstore.list_runs()
    if not runs:
        pytest.skip("no run stored yet; run seed_run.py")
    worst = runs[0]
    assert worst["cue_count"] > 100
    assert worst["violation_count"] > 0, "the landing run must show real violations"
    assert worst["measured_at"], "a stored run must say when it was measured"

    full = runstore.get_run(worst["run_id"])
    assert full is not None
    assert full["cues"], "the stored run must carry its cue table"
    assert full["spec"]["citation_url"].startswith("http")
    # Every threshold that has a value has a clause and a provenance behind it.
    for name, ev in full["spec"]["evidence"].items():
        assert ev["clause"].strip(), f"{name} has a value with no clause"
        assert ev["provenance"] in ("live", "fallback")
    for name in ps.THRESHOLD_NAMES:
        if full["spec"][name] is None:
            assert name in full["spec"]["not_verifiable"]


def test_stored_run_repair_is_a_second_measurement(real_srt):
    """The after number must be reproducible from the stored repaired file.

    Guards the difference between "we re-measured the repaired track" and "we
    subtracted what we think we fixed".
    """
    runs = runstore.list_runs()
    if not runs:
        pytest.skip("no run stored yet; run seed_run.py")
    full = runstore.get_run(runs[0]["run_id"])
    buyer = full["platform_key"]
    name = full["repaired_files"].get(buyer)
    if not name:
        pytest.skip("no repaired track stored for the leading buyer")
    path = runstore.repaired_path(name)
    assert path is not None
    spec = {
        "platform": full["platform"],
        "max_cps": full["spec"]["max_cps"],
        "min_duration_s": full["spec"]["min_duration_s"],
        "max_line_chars": full["spec"]["max_line_chars"],
        "max_lines": full["spec"]["max_lines"],
        "source_url": full["spec"]["citation_url"],
        "source_label": full["spec"]["citation_title"],
        "is_cached": False,
    }
    again = m.measure_subtitles(path.read_text(encoding="utf-8"), spec=spec)
    assert again.total_violations == full["totals"]["violations_after_repair"]


def test_repaired_path_refuses_traversal():
    assert runstore.repaired_path("../../etc/passwd") is None
    assert runstore.repaired_path("/etc/passwd") is None
    assert runstore.repaired_path("nope.json") is None


# --- the graph is the one the README describes ---------------------------


def test_workflow_graph_has_the_declared_shape():
    """The topology is read off the built graph, not from a diagram.

    Guards against the README describing a fan-out that the code does not build.
    """
    adk = pytest.importorskip("google.adk")
    import cuepass_agents

    shape = cuepass_agents.graph_shape()
    names = {n["name"] for n in shape["nodes"]}
    for buyer in cuepass_agents.BUYERS:
        assert f"{buyer}_spec_desk" in names
    assert {"bind_cited_specs", "measure_every_buyer", "repair_every_buyer",
            "remeasure_every_buyer", "triage_leftovers"} <= names

    # Every desk runs concurrently: each one hangs directly off START.
    from_start = {e["to"] for e in shape["edges"] if e["from"] == "__START__"}
    assert len(from_start) == len(cuepass_agents.BUYERS)

    # Nothing that produces a number may be a model node.
    deterministic = {
        "bind_cited_specs",
        "measure_every_buyer",
        "repair_every_buyer",
        "remeasure_every_buyer",
        "collect_leftovers_for_triage",
    }
    for node in shape["nodes"]:
        if node["name"] in deterministic:
            assert not node["runs_model"], f"{node['name']} must not call a model"
        if node["name"].endswith("_spec_desk") or node["name"] == "triage_leftovers":
            assert node["runs_model"], f"{node['name']} must be a model node"
    assert adk is not None


def test_no_module_prose_hardcodes_a_desk_count():
    """Prose must state the rule, not the tally.

    The bug this guards actually shipped: the module docstring and the Workflow's
    own `description` said "four buyer desks" from before Netflix was split into
    two profiles, so a reader saw a false four beside a real five. A count written
    into prose goes stale the moment BUYERS changes, and a stale number sitting
    next to correct ones is worse than no number.

    Two things are legitimately not stale counts and are allowed:
      - a rate: "one desk per delivery profile" is true at any size;
      - the arity of a pairwise comparison: a contrast compares exactly two
        profiles by definition, however many profiles exist.
    """
    number_words = r"(?:two|three|four|five|six|seven|eight|nine|ten|\d+)"
    subject = r"(?:buyer|desk|profile|spec\s+desk|research\s+desk)s?"
    offender = re.compile(rf"(?i)\b{number_words}\s+(?:\w+\s+){{0,2}}?{subject}\b")
    rate = re.compile(r"(?i)\bone\s+(?:\w+\s+){0,3}?per\b")
    pairwise = re.compile(r"(?i)\b(compar\w+|contrast\w*|pair\w*|both|differ\w*)\b")

    for name in ("cuepass_agents.py", "agent.py", "parallel_spec.py", "runstore.py"):
        text = Path(__file__).resolve().parent.joinpath(name).read_text(encoding="utf-8")
        for match in offender.finditer(text):
            window = text[max(0, match.start() - 90) : match.end() + 90]
            if rate.search(window):
                continue
            if match.group(0).lower().startswith("two") and pairwise.search(window):
                continue
            line = text[: match.start()].count("\n") + 1
            pytest.fail(
                f"{name}:{line} hardcodes a count: {match.group(0)!r}. "
                "State the rule (one desk per profile) or derive it from BUYERS."
            )


def test_the_workflow_description_counts_the_desks_it_built():
    """The graph's own description must agree with the graph.

    This string is runtime metadata and surfaces in graph output, so it is exactly
    the place a hardcoded figure would be believed.
    """
    pytest.importorskip("google.adk")
    import cuepass_agents

    wf = cuepass_agents.build_workflow()
    desks = [n for n in wf.graph.nodes if n.name.endswith("_spec_desk")]
    assert len(desks) == len(cuepass_agents.BUYERS)
    assert str(len(desks)) in wf.description, (
        f"description does not state the real desk count: {wf.description!r}"
    )


def test_every_declared_profile_gets_a_desk_and_a_column():
    """Every profile either cites a spec or says why not. None may vanish.

    A profile that silently produced no desk, and no unavailable row either, would
    disappear from the page with nothing saying it was ever asked.
    """
    pytest.importorskip("google.adk")
    import cuepass_agents

    runs = runstore.list_runs()
    if not runs:
        pytest.skip("no run stored yet; run seed_run.py")
    full = runstore.get_run(runs[0]["run_id"])
    accounted = set(full["buyers"]) | set(full["unavailable"])
    declared = set(cuepass_agents.BUYERS)
    assert accounted == declared, (
        f"declared but missing from the run: {sorted(declared - accounted)}; "
        f"in the run but no longer declared: {sorted(accounted - declared)}"
    )
    desks = {n["name"] for n in full["graph"]["nodes"] if n["name"].endswith("_spec_desk")}
    assert len(desks) == len(accounted)


def test_the_model_is_never_asked_for_a_threshold():
    """No model node has a field it could put a number in.

    The desks decide which page is authoritative. The numbers are read from the
    page in Python. If a threshold field appeared on SpecChoice, a model could
    author a delivery limit, which is the failure this design exists to stop.
    """
    pytest.importorskip("google.adk")
    import cuepass_agents

    fields = set(cuepass_agents.SpecChoice.model_fields)
    assert fields == {"accepted_urls", "reason", "rejected"}
    for name in ps.THRESHOLD_NAMES:
        assert name not in fields

    # The triage node likewise cannot report a measurement.
    action_fields = set(cuepass_agents.EditorialAction.model_fields)
    assert action_fields == {"cue_index", "action", "note"}


def test_run_refuses_without_parallel(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "present-for-this-test")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    with pytest.raises(ps.ParallelUnavailableError):
        agent.run_agent("iron_mask")


def test_run_refuses_without_a_model(monkeypatch):
    monkeypatch.setenv("PARALLEL_API_KEY", "present-for-this-test")
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(agent.GeminiUnavailableError):
        agent.run_agent("iron_mask")


def test_stored_records_are_json_and_carry_provenance():
    """Whatever is on disk has to be loadable and self-describing."""
    for path in sorted(runstore.SEED_DIR.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["measured_at"]
        assert record["framework"] == "google-adk"
        assert "search" in record["parallel_surfaces"]
        assert "extract" in record["parallel_surfaces"]
        for buyer, entry in record["buyers"].items():
            assert entry["spec"]["source_url"].startswith("http")
            assert entry["verdict"] in ("DELIVER", "HOLD")
