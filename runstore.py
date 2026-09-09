"""Where a finished Cuepass run is kept so it outlives the request.

A judge who opens Cuepass for the first time must land on a real measurement,
not on an empty form, and a run somebody triggered must still be there after
the container recycles. Two layers do that:

  Seed runs  `data/runs/*.json`, committed to the repo and baked into the
             image. These are real runs: produced by `python seed_run.py`,
             which drives the same graph against the same archive.org file and
             writes down whatever the code produced. They carry the timestamp
             they were measured at, and the UI shows it. They are the landing
             state, so the landing state can never be empty and can never be
             invented.

  Live runs  written to the run directory as they finish. On Cloud Run the
             image is read-only outside /tmp, so the directory falls back to
             /tmp and a live run survives for the life of the container. It is
             listed alongside the seeds, newest first.

The repaired .srt files are written next to the record, so a download link from
a run listed in the index still resolves after the process that made it is
gone.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import parallel_spec

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent / "data" / "runs"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("1", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def run_dir() -> Path:
    """The directory finished runs are written to.

    Explicit env first, then the repo's own data/runs when it is writable
    (local development), then a temp directory (Cloud Run, where everything
    outside /tmp is read-only).
    """
    override = os.environ.get("CUEPASS_RUN_DIR")
    if override:
        path = Path(override)
        if _writable(path):
            return path
        logger.warning("CUEPASS_RUN_DIR=%s is not writable", override)
    if _writable(SEED_DIR):
        return SEED_DIR
    fallback = Path(tempfile.gettempdir()) / "cuepass-runs"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _record_paths() -> list[Path]:
    """Every run record on disk, deduplicated by file name.

    The live directory wins over the seed directory for the same name, so a
    re-run of a seeded title replaces it in the index rather than appearing
    twice.
    """
    seen: dict[str, Path] = {}
    for directory in (SEED_DIR, run_dir()):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            seen[path.name] = path
    return sorted(seen.values())


def save(record: dict, repaired_tracks: dict[str, str], source_srt: str = "") -> dict:
    """Persist one finished run plus its repaired tracks. Returns the record.

    The record gains `repaired_files`, mapping buyer to the file name the
    download route will serve, and `source_file`, the original track as
    fetched. The source is kept because the per-cue table the UI renders needs
    every cue's in and out point, not only the failing ones, and because a
    reviewer comparing before with after should be able to download both halves
    of the comparison rather than take the delta on trust.
    """
    directory = run_dir()
    run_id = record["run_id"]
    if source_srt:
        source_name = f"{run_id}.source.srt"
        try:
            (directory / source_name).write_text(source_srt, encoding="utf-8")
            record["source_file"] = source_name
        except OSError as exc:
            logger.warning("could not write source track: %s", exc)
    files: dict[str, str] = {}
    for buyer, srt_text in repaired_tracks.items():
        name = f"{run_id}.{buyer}.srt"
        try:
            (directory / name).write_text(srt_text, encoding="utf-8")
            files[buyer] = name
        except OSError as exc:
            logger.warning("could not write repaired track %s: %s", name, exc)
    record["repaired_files"] = files
    record["stored_in"] = str(directory)
    try:
        (directory / f"{run_id}.json").write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("could not persist run %s: %s", run_id, exc)
        record["stored_in"] = ""
    return record


def load(run_id: str) -> dict | None:
    for path in _record_paths():
        if path.stem == run_id:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return None


# There is deliberately only ONE way to list stored runs: `list_runs()`, ordered
# worst first, with `default_run_id()` taking its first row.
#
# An earlier `index()` and `latest()` lived here and ordered by `measured_at`
# instead, newest first. Nothing called either of them, which is exactly what made
# them dangerous: two functions answering "which run leads" with different
# answers, and the next reader picking whichever they found first. The page's rail
# says "worst first", so a caller who reached for the newest-first version would
# have made that heading a lie without touching the heading. Deleted rather than
# kept as a convenience, because the convenience was a second source of truth.


def repaired_path(name: str) -> Path | None:
    """Resolve a repaired-track file name to a path inside a run directory.

    The name has to sit directly inside one of the run directories after
    resolution, so `../`, an absolute path, or a name from anywhere else on
    disk never resolves.
    """
    if not name.endswith(".srt"):
        return None
    for directory in (SEED_DIR, run_dir()):
        if not directory.is_dir():
            continue
        candidate = directory / name
        try:
            resolved = candidate.resolve()
            resolved.relative_to(directory.resolve())
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            return resolved
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- the read API the web layer calls ------------------------------------
#
# Named as the UI asked for them so the page does not have to adapt. Every
# value below is read out of a stored record. Nothing here computes a verdict
# or invents a threshold; if no run has been stored, these return empty and the
# caller must say the page has no measurement yet rather than draw one.


def _primary_buyer(record: dict) -> str:
    """The buyer whose column leads the page.

    The one with the most violations before repair, because that is the column
    that carries the argument. Ties break towards Netflix only because it is
    the buyer the incident in the README is about.
    """
    buyers = record.get("buyers", {})
    if not buyers:
        return ""
    return max(
        buyers,
        key=lambda b: (
            buyers[b].get("before", {}).get("total_violations", 0),
            b == "netflix",
        ),
    )


def _source_srt(record: dict) -> str:
    name = record.get("source_file", "")
    if not name:
        return ""
    path = repaired_path(name)
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def cue_table(record: dict, buyer: str) -> list[dict]:
    """Every cue in the track, with what one buyer's spec makes of it.

    The whole track, not only the failures, so the sheet can show a passing cue
    next to a failing one. `flags` is empty for a cue that meets every rule
    that buyer publishes. A rule the buyer does not publish never produces a
    flag, so a cue is never marked for a limit nobody set.

    The flags come from `measure.measure_subtitles`, the same function that
    produced the counts on screen. They are NOT recomputed here.

    They used to be. This function had its own copy of all four threshold
    comparisons, which made it a second answer to "does this cue violate?".
    The two agreed on the day it was written and then `measure_subtitles` moved
    to millisecond comparisons while this copy stayed on float seconds, so a cue
    sitting exactly on a limit would have been flagged red on the sheet while the
    total beside it counted the cue as clean. No cue in the current track sits on
    a boundary, so nothing was visibly wrong; it was one repair away from being
    a page that contradicted itself.
    """
    import measure as measure_mod

    srt = _source_srt(record)
    if not srt:
        return []
    entry = record.get("buyers", {}).get(buyer, {})
    spec = entry.get("spec", {})
    reasons = entry.get("leftover_reasons", {})
    editorial = record.get("editorial", {})

    # One source of truth for what counts as a violation.
    report = measure_mod.measure_subtitles(srt, spec=spec)
    flags_by_cue: dict[int, list[str]] = {}
    for finding in report.findings:
        flags_by_cue.setdefault(finding.cue_index, []).append(finding.check)

    rows = []
    for idx, c in enumerate(measure_mod.parse_srt(srt), start=1):
        chars = len(c["text"].strip())
        duration = c["duration"]
        # Displayed at the same precision the comparison uses, so the number a
        # reader sees is the number that was actually tested.
        duration_ms = int(round(duration * 1000))
        cps = round(chars / (duration_ms / 1000), 2) if duration_ms > 0 else None
        longest = max((len(ln) for ln in c["lines"]), default=0)
        flags = flags_by_cue.get(idx, [])
        key = str(idx)
        rows.append(
            {
                "index": idx,
                "start": measure_mod._fmt_ts(c["start"]),
                "end": measure_mod._fmt_ts(c["end"]),
                "duration_s": round(duration, 3),
                "chars": chars,
                "cps": cps,
                "longest_line": longest,
                "lines": c["lines"],
                "text": c["text"],
                "flags": flags,
                # Present only when the retime could not clear this cue, which
                # is the difference between "was failing" and "is still failing
                # after the repair ran".
                "blocked_by": reasons.get(key, ""),
                "editorial_action": editorial.get(key, {}).get("action", ""),
                "editorial_note": editorial.get(key, {}).get("note", ""),
            }
        )
    return rows


def list_runs() -> list[dict]:
    """Stored runs, worst first. Safe to call before any run has happened."""
    rows = []
    for path in _record_paths():
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        buyer = _primary_buyer(rec)
        entry = rec.get("buyers", {}).get(buyer, {})
        before = entry.get("before", {})
        cue_count = rec.get("cue_count", 0) or before.get("cue_count", 0)
        violations = before.get("total_violations", 0)
        rows.append(
            {
                "run_id": rec.get("run_id", path.stem),
                "title": rec.get("film_title", ""),
                "source_url": rec.get("subtitle_url", ""),
                "platform": entry.get("spec", {}).get("platform", ""),
                "cue_count": cue_count,
                "violation_count": violations,
                "violation_rate": round(violations / cue_count, 4) if cue_count else 0.0,
                "violations_after_repair": entry.get("after", {}).get("total_violations", 0),
                "measured_at": rec.get("measured_at", ""),
                "buyers": sorted(rec.get("buyers", {})),
                "verdicts": {b: e.get("verdict", "") for b, e in rec.get("buyers", {}).items()},
                "is_seed": path.parent == SEED_DIR,
            }
        )
    rows.sort(key=lambda r: (-r["violation_count"], r["measured_at"]))
    return rows


def default_run_id() -> str:
    """The run the page opens on: the worst failing one that is stored."""
    rows = list_runs()
    return rows[0]["run_id"] if rows else ""


def get_run(run_id: str) -> dict | None:
    """One stored run, with a flat single-buyer view alongside the matrix.

    `primary` is the buyer column that leads the page. `buyers` is the whole
    matrix: the same file against every buyer whose own published spec was
    cited this run, which is the thing that could not exist if the reading speed
    were a constant in this repository.
    """
    record = load(run_id)
    if record is None:
        return None
    buyer = _primary_buyer(record)
    entry = record.get("buyers", {}).get(buyer, {})
    spec = entry.get("spec", {})
    before = entry.get("before", {})
    after = entry.get("after", {})
    return {
        "run_id": record.get("run_id", run_id),
        "title": record.get("film_title", ""),
        "source_url": record.get("subtitle_url", ""),
        "measured_at": record.get("measured_at", ""),
        "platform": spec.get("platform", ""),
        "platform_key": buyer,
        "spec": {
            "max_cps": spec.get("max_cps"),
            "min_duration_s": spec.get("min_duration_s"),
            "max_line_chars": spec.get("max_line_chars"),
            "max_lines": spec.get("max_lines"),
            # A run stored before a rule existed did not measure that rule. It
            # reads back as None and joins `not_verifiable` below, never as a
            # value and never as a clean check, which is the same discipline a
            # live run applies to a page that stays silent.
            "min_gap_s": spec.get("min_gap_s"),
            "citation_url": spec.get("source_url", ""),
            "citation_title": spec.get("source_label", ""),
            "scope": spec.get("scope", ""),
            "is_cached": spec.get("is_cached", False),
            "fetched_at": record.get("measured_at", ""),
            "source_label": spec.get("source_label", ""),
            "extract_id": spec.get("extract_id", ""),
            # The verbatim sentence on the cited page behind each number. This
            # is the part that makes the threshold checkable rather than
            # assertable, so it belongs on screen next to the number.
            "evidence": spec.get("evidence", {}),
            "desk_reason": spec.get("desk_reason", ""),
            # Per threshold: "live" read off a page this run, "fallback" the
            # buyer's published value pinned and cited because the live fetch
            # did not land on a page stating it, "unverified" no value at all.
            # A threshold whose provenance is not "live" must be labelled on
            # screen; an unverified one means its check did not run.
            "provenance": spec.get("provenance", {}),
            "not_verifiable": sorted(
                set(spec.get("not_verifiable", []))
                | {
                    name
                    for name in parallel_spec.THRESHOLD_NAMES
                    if spec.get(name) is None
                }
            ),
            "source_urls": spec.get("source_urls", []),
        },
        "totals": {
            "cues": record.get("cue_count", 0),
            "over_cps": before.get("over_cps_count", 0),
            "under_min_duration": before.get("under_duration_count", 0),
            "over_line_chars": before.get("over_line_chars_count", 0),
            "over_max_lines": before.get("over_line_count", 0),
            # A SUBSET of under_min_duration, not a fifth category beside it: a
            # cue whose out-time is not after its in-time is also under the
            # minimum and is counted in both. Never add this to the others.
            # `violations` below is the authoritative total and needs no sum.
            "non_positive_duration": before.get("non_positive_duration_count", 0),
            "violations": before.get("total_violations", 0),
            "violations_after_repair": after.get("total_violations", 0),
            "timing_violations": (before.get("over_cps_count") or 0)
            + (before.get("under_duration_count") or 0),
            "timing_violations_after_repair": (after.get("over_cps_count") or 0)
            + (after.get("under_duration_count") or 0),
            "cues_retimed": entry.get("cues_changed", 0),
            "checks_skipped": before.get("checks_skipped", []),
            "checks_not_verifiable": before.get("checks_not_verifiable", []),
        },
        "verdict": entry.get("verdict", ""),
        "cues": cue_table(record, buyer),
        # The buyer matrix: one row per buyer whose own page was cited.
        "buyers": {
            b: {
                "platform": e.get("spec", {}).get("platform", ""),
                "citation_url": e.get("spec", {}).get("source_url", ""),
                "max_cps": e.get("spec", {}).get("max_cps"),
                "min_duration_s": e.get("spec", {}).get("min_duration_s"),
                "max_line_chars": e.get("spec", {}).get("max_line_chars"),
                "max_lines": e.get("spec", {}).get("max_lines"),
                "evidence": e.get("spec", {}).get("evidence", {}),
                "provenance": e.get("spec", {}).get("provenance", {}),
                "not_verifiable": e.get("spec", {}).get("not_verifiable", []),
                # Every page this profile's desk opened and took a rule from. A
                # spec is spread across pages, so the count is part of the
                # evidence: one lucky page is a weaker claim than a desk that
                # kept looking until it had all four rules.
                "source_urls": e.get("spec", {}).get("source_urls", []),
                "violations_before": e.get("before", {}).get("total_violations", 0),
                "violations_after": e.get("after", {}).get("total_violations", 0),
                "cues_retimed": e.get("cues_changed", 0),
                "checks_skipped": e.get("before", {}).get("checks_skipped", []),
                "verdict": e.get("verdict", ""),
                "scope": e.get("spec", {}).get("scope", ""),
                "repaired_file": record.get("repaired_files", {}).get(b, ""),
            }
            for b, e in record.get("buyers", {}).items()
        },
        # Buyers whose desk could not find a page stating a measurable rule,
        # with the reason. Shown, not hidden: a missing column is information.
        "unavailable": record.get("unavailable", {}),
        # Pairs of cited profiles that published different reading speeds, with
        # the count of cues acceptable under one and not the other. Empty when no
        # two profiles differ, which is the honest state, not a missing feature.
        "contrasts": record.get("contrasts", []),
        "graph": record.get("graph", {}),
        "trace": record.get("trace", []),
        "model": record.get("model", ""),
        "framework": record.get("framework", ""),
        "parallel_surfaces": record.get("parallel_surfaces", []),
        "source_file": record.get("source_file", ""),
        "repaired_files": record.get("repaired_files", {}),
        "editorial": record.get("editorial", {}),
        "leftover_cue_total": record.get("leftover_cue_total", 0),
        "editorial_capped_at": record.get("editorial_capped_at", 0),
    }


def default_run() -> dict | None:
    """The full run the page opens on. None only when nothing is stored."""
    run_id = default_run_id()
    return get_run(run_id) if run_id else None
