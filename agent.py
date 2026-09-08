"""Gemini-powered subtitle compliance agent.

The agent orchestrates the deterministic measure→classify→repair→re-measure loop.
Gemini's role is step 3 only: given a list of failing cues, decide which are
auto-repairable vs. which require human editorial review.

Why Gemini here:
- Classifying "auto-fixable" vs "needs human" requires semantic understanding:
  a 20 cps cue from a rapid-fire exchange might be perfectly fine to extend,
  but a 20 cps cue that is already 3 lines long cannot be fixed by retiming.
- The deterministic repair step (measure.py:remediate_subtitles) does the actual
  work; Gemini only sets the strategy.

Steps:
  1. fetch_film       — pick a real archive.org film with .srt
  2. fetch_spec       — Parallel Search fetches the live platform spec
  3. measure_before   — deterministic measure
  4. classify         — Gemini reviews failures, classifies each
  5. repair           — deterministic retime
  6. measure_after    — re-measure; raises if not improved
  7. build_report     — return structured results for the UI
"""

from __future__ import annotations

import json
import logging
import os
import textwrap
from pathlib import Path

import archive as archive_mod
import measure as measure_mod
import parallel_spec

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")


def _gemini_classify(
    failures: list[dict],
    spec: dict,
    film_title: str,
) -> dict[int, str]:
    """Ask Gemini to classify each failing cue.

    Returns a dict mapping cue_index -> "auto_fixable" | "needs_review".
    Falls back to pure deterministic logic if Gemini is unavailable.
    """
    try:
        from google import genai  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("google-genai not installed; using deterministic fallback")
        return _deterministic_classify(failures)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set; using deterministic fallback")
        return _deterministic_classify(failures)

    client = genai.Client(api_key=api_key)

    # Compact failure summary to save tokens
    failure_summary = json.dumps(
        [
            {
                "cue": f["cue_index"],
                "check": f["check"],
                "value": f["value"],
                "threshold": f["threshold"],
                "unit": f["unit"],
                "text_preview": f["text_preview"][:60],
            }
            for f in failures[:100]  # cap to avoid token limits
        ],
        indent=2,
    )

    prompt = textwrap.dedent(f"""
        You are a subtitle QC agent for the film "{film_title}".
        Target platform: {spec['platform']} (max {spec['max_cps']} chars/sec, max line length {spec['max_line_chars']} chars).

        The following subtitle cues fail delivery spec. For each cue, decide whether it is:
        - "auto_fixable": the out-time can be extended to fix reading speed or minimum duration.
          Only auto_fixable if check is "reading_speed" or "min_duration".
        - "needs_review": the fix requires editorial judgment (e.g., line_length, line_count,
          or a reading_speed failure where the next cue is too close to allow extension).

        Respond with ONLY valid JSON: a dict mapping cue index (as string) to either
        "auto_fixable" or "needs_review". Nothing else.

        Failing cues:
        {failure_summary}
    """).strip()

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        # strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        raw = json.loads(text)
        return {int(k): v for k, v in raw.items()}
    except Exception as exc:
        logger.warning("Gemini classification failed: %s; using deterministic fallback", exc)
        return _deterministic_classify(failures)


def _deterministic_classify(failures: list[dict]) -> dict[int, str]:
    """Fallback: auto_fixable iff the check is reading_speed or min_duration."""
    return {
        f["cue_index"]: (
            "auto_fixable" if f["check"] in ("reading_speed", "min_duration") else "needs_review"
        )
        for f in failures
    }


def run_agent(
    identifier: str | None = None,
    platform: str = "netflix",
    max_video_mb: int = 15,
) -> dict:
    """Full agent pipeline. Returns a structured result dict for the UI.

    identifier: archive.org item identifier; if None, picks automatically.
    platform:   spec target ("netflix", "amazon", "bbc", "fcc").
    max_video_mb: cap on video download (we only need the .srt, but log the size).
    """
    DATA_DIR.mkdir(exist_ok=True)

    # ── Step 1: pick film ──────────────────────────────────────────────────
    if identifier is None:
        results = archive_mod.search(rows=10)
        info = None
        for r in results:
            candidate = archive_mod.pick_files(r["identifier"])
            if candidate["subtitle"]:
                info = candidate
                break
        if info is None:
            raise RuntimeError("No archive.org film with subtitles found in first 10 results")
    else:
        info = archive_mod.pick_files(identifier)
        if not info["subtitle"]:
            raise RuntimeError(f"{identifier} has no subtitle track")

    film_title = info["title"]
    film_identifier = info["identifier"]
    subtitle_filename = info["subtitle"]

    logger.info("Film: %s (%s), subtitle: %s", film_title, film_identifier, subtitle_filename)

    # ── Step 2: fetch spec via Parallel Search ─────────────────────────────
    spec = parallel_spec.fetch_spec(platform)
    logger.info(
        "Spec: %s — %s cps, source: %s (cached=%s)",
        spec["platform"], spec["max_cps"], spec["source_url"], spec["is_cached"],
    )

    # ── Step 3: fetch subtitle and measure before ──────────────────────────
    srt_text = archive_mod.fetch_text(film_identifier, subtitle_filename)
    if not srt_text.strip():
        raise RuntimeError(f"Empty subtitle file for {film_identifier}/{subtitle_filename}")

    report_before = measure_mod.measure_subtitles(srt_text, spec=spec)
    logger.info(
        "Before: %d cues, %d violations (%d over-cps, %d under-duration, %d line-chars, %d line-count)",
        report_before.cue_count,
        report_before.total_violations,
        report_before.over_cps_count,
        report_before.under_duration_count,
        report_before.over_line_chars_count,
        report_before.over_line_count,
    )

    # ── Step 4: Gemini classifies failures ────────────────────────────────
    failures_dicts = report_before.findings_as_dicts()
    classification = _gemini_classify(failures_dicts, spec, film_title)

    auto_count = sum(1 for v in classification.values() if v == "auto_fixable")
    review_count = sum(1 for v in classification.values() if v == "needs_review")

    # ── Step 5: deterministic repair ──────────────────────────────────────
    srt_repaired, n_changed = measure_mod.remediate_subtitles(
        srt_text,
        max_cps=spec["max_cps"],
        min_duration_s=spec["min_duration_s"],
    )

    # Save repaired SRT
    repaired_path = DATA_DIR / f"{film_identifier}_repaired.srt"
    repaired_path.write_text(srt_repaired, encoding="utf-8")
    logger.info("Repaired SRT written to %s (%d cues changed)", repaired_path, n_changed)

    # ── Step 6: re-measure and verify improvement ─────────────────────────
    report_after = measure_mod.measure_subtitles(srt_repaired, spec=spec)
    logger.info(
        "After: %d cues, %d violations (%d over-cps, %d under-duration)",
        report_after.cue_count,
        report_after.total_violations,
        report_after.over_cps_count,
        report_after.under_duration_count,
    )

    # Hard check: repair must have reduced at least speed/duration violations
    fixable_before = report_before.over_cps_count + report_before.under_duration_count
    fixable_after = report_after.over_cps_count + report_after.under_duration_count
    if fixable_before > 0 and fixable_after >= fixable_before:
        raise RuntimeError(
            f"Repair did NOT improve: fixable violations before={fixable_before}, after={fixable_after}"
        )

    # ── Step 7: build report ──────────────────────────────────────────────
    return {
        "film_title": film_title,
        "film_identifier": film_identifier,
        "subtitle_filename": subtitle_filename,
        "subtitle_url": archive_mod.download_url(film_identifier, subtitle_filename),
        "spec": spec,
        "before": {
            **report_before.summary(),
            "findings": failures_dicts,
        },
        "after": {
            **report_after.summary(),
            "findings": report_after.findings_as_dicts(),
        },
        "classification": {str(k): v for k, v in classification.items()},
        "auto_fixable_count": auto_count,
        "needs_review_count": review_count,
        "cues_changed": n_changed,
        "repaired_srt_path": str(repaired_path),
        "improvement": {
            "over_cps": report_before.over_cps_count - report_after.over_cps_count,
            "under_duration": report_before.under_duration_count - report_after.under_duration_count,
            "over_line_chars": report_before.over_line_chars_count - report_after.over_line_chars_count,
        },
    }
