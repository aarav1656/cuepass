"""Tests that touch REAL data: a real film's subtitle track and the live Parallel API.

The existing suite runs in 0.02s, which means it exercises no network and no real
file, so it cannot catch an integration that has silently stopped working. These
tests are slower on purpose. Each asserts BOTH directions where a threshold is
involved: clean input passes, dirty input fails.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import archive
import measure
import parallel_spec

HAS_KEY = bool(os.environ.get("PARALLEL_API_KEY"))
needs_key = pytest.mark.skipif(not HAS_KEY, reason="PARALLEL_API_KEY not set")

# A real archive.org public-domain feature with a real ASR subtitle track.
REAL_TITLE = "iron_mask"


@pytest.fixture(scope="module")
def real_srt() -> str:
    picked = archive.pick_files(REAL_TITLE)
    assert picked.get("subtitle"), f"{REAL_TITLE} no longer ships a subtitle track"
    text = archive.fetch_text(REAL_TITLE, picked["subtitle"])
    assert len(text) > 5000, f"subtitle download looks truncated: {len(text)} chars"
    return text


def test_real_subtitle_track_parses(real_srt):
    cues = measure.parse_srt(real_srt)
    # A parser that silently returns [] would make every downstream check vacuous.
    assert len(cues) > 100, f"only parsed {len(cues)} cues from a feature-length film"
    assert all(c["end"] >= c["start"] for c in cues)


def test_real_film_has_real_defects(real_srt):
    """The headline claim. If this film is clean, the demo proves nothing."""
    result = measure.measure_subtitles(real_srt)
    assert result.over_cps_count > 0, (
        "expected real reading-speed violations in an ASR subtitle track"
    )
    # Report the real ratio so a parsing regression shows up as a changed count.
    assert result.over_cps_count / max(result.cue_count, 1) > 0.05


def test_a_clean_track_passes_the_same_check():
    """The counter-case: the checker must not flag everything it is shown."""
    clean = "\n\n".join(
        f"{i}\n00:00:{i*5:02d},000 --> 00:00:{i*5+4:02d},000\nShort tidy line."
        for i in range(1, 6)
    )
    result = measure.measure_subtitles(clean)
    assert result.over_cps_count == 0
    assert result.under_duration_count == 0
    assert result.passed


def test_repair_improves_a_real_track_and_never_overlaps(real_srt):
    before = measure.measure_subtitles(real_srt)
    fixed, changed = measure.remediate_subtitles(real_srt)
    after = measure.measure_subtitles(fixed)

    assert changed > 0
    assert after.over_cps_count < before.over_cps_count, (
        f"repair did not reduce violations: {before.over_cps_count} -> "
        f"{after.over_cps_count}"
    )

    # The right property is "repair INTRODUCES no overlap", not "the output has
    # none": this real ASR track already ships one overlapping cue (a cue running
    # 21s over its neighbour), and a repair tool must not be blamed for a defect
    # it inherited. Compare counts before and after instead.
    def _overlaps(text: str) -> int:
        cs = sorted(measure.parse_srt(text), key=lambda c: (c["start"], c["end"]))
        return sum(1 for a, b in zip(cs, cs[1:]) if a["end"] > b["start"])

    assert _overlaps(fixed) <= _overlaps(real_srt), (
        f"repair introduced overlaps: {_overlaps(real_srt)} -> {_overlaps(fixed)}"
    )


def test_repair_never_introduces_an_overlap_in_a_clean_track():
    """The synthetic counter-case, where the source is known to be overlap-free."""
    packed = "\n\n".join(
        f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},200\n"
        "A very long line that cannot possibly be read in two hundred milliseconds."
        for i in range(1, 8)
    )
    fixed, changed = measure.remediate_subtitles(packed)
    assert changed > 0
    cs = measure.parse_srt(fixed)
    for a, b in zip(cs, cs[1:]):
        assert a["end"] <= b["start"], f"repair created an overlap: {a} / {b}"


@needs_key
def test_parallel_search_then_extract_reaches_a_real_spec_page():
    """The whole Parallel chain, against the live API, end to end.

    Search must return candidate URLs, and Extract must open one of them and
    yield at least one threshold with the verbatim sentence it came from. This
    is the test that proves the integration is reachable rather than described.
    """
    found = parallel_spec.search_spec_candidates("netflix_en_us")
    assert found["candidates"], "Search returned no candidate spec page"
    assert found["session_id"], "Search must return a session id to carry into Extract"
    for candidate in found["candidates"]:
        assert parallel_spec.is_citable_url(candidate["url"])

    # Open candidates until one states a rule, which is what the desk does.
    for candidate in found["candidates"][:3]:
        read = parallel_spec.extract_spec_page(
            "netflix_en_us", candidate["url"], found["session_id"]
        )
        if read.get("found"):
            break
    else:
        pytest.fail("Extract opened three candidates and none stated a caption rule")

    assert read["chars_extracted"] > 0, "Extract returned a page with no text"
    assert read["extract_id"], "Extract must return an id the run can be traced by"
    for name, clause in read["clauses"].items():
        assert clause.strip(), f"{name} was read with no clause behind it"

    spec = parallel_spec.spec_from_ledger("netflix_en_us", [read["url"]])
    assert spec["source_url"].startswith("http")
    assert not spec["is_cached"], "expected a live fetch, got a cached value"
    # At least one threshold, and every threshold present is either read live
    # off the page or a labelled fallback. Never an unlabelled constant.
    assert any(spec[n] is not None for n in parallel_spec.THRESHOLD_NAMES)
    for name in parallel_spec.THRESHOLD_NAMES:
        provenance = spec["provenance"][name]
        assert provenance in ("live", "fallback", "unverified")
        if provenance == "unverified":
            assert spec[name] is None
        else:
            assert spec[name] is not None
    parallel_spec.ledger_clear()


def test_parallel_raises_without_a_key(monkeypatch):
    """No key must be a hard stop, never a silent fallback to hardcoded constants."""
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    with pytest.raises(parallel_spec.ParallelUnavailableError):
        parallel_spec.search_spec_candidates("netflix_en_us")
    with pytest.raises(parallel_spec.ParallelUnavailableError):
        parallel_spec.extract_spec_page(
            "netflix_en_us", "https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617"
        )
