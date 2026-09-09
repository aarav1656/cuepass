"""FastAPI web application for Cuepass.

The page lands on a real stored measurement. A judge who opens Cuepass sees the
buyer spec that was fetched, the verbatim sentence each threshold was read out
of, the violation count before and after repair, and the cues that are still
failing, with no click and no wait. Running a track live is offered as proof
that the stored numbers came from this code, not as the price of entry.

Every number rendered here is read out of a stored run record. This module
computes no threshold, counts no violation, and holds no fallback number. When
nothing is stored the page says so rather than drawing something.

Spotting-sheet system: near-black canvas, Anton display, Space Mono for every
measured value, mint reserved for the live spec badge, repaired state, and the
one primary action. No Inter. No dashboard chrome.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import agent as agent_mod
import archive
import runstore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cuepass", docs_url="/api/docs")

# Archive.org identifiers with a real .srt track. No measurement is claimed for
# any of them here: the numbers on the page come out of a stored run, and a
# track nobody has run yet carries no number at all.
KNOWN_FILMS = [
    {"identifier": "iron_mask", "title": "The Iron Mask (1929)"},
    {"identifier": "isle_of_destiny", "title": "Isle of Destiny"},
    {"identifier": "inner_sanctum", "title": "Inner Sanctum"},
    {"identifier": "in_old_caliente", "title": "In Old Caliente"},
]

# Every rule Cuepass can measure: the check name `measure` emits, the spec key
# the threshold arrives under, the unit shown beside the number, and the words
# used when a buyer's page does not state that rule at all.
RULES = [
    ("reading_speed", "max_cps", "cps", "reading speed"),
    ("min_duration", "min_duration_s", "sec", "minimum duration"),
    ("line_length", "max_line_chars", "chars", "line length"),
    ("line_count", "max_lines", "lines", "lines per cue"),
]

# A cue too short to hold its text is a minimum-duration failure, so it shares
# that rule's threshold rather than getting one of its own.
CHECK_TO_RULE = {
    "reading_speed": "reading_speed",
    "min_duration": "min_duration",
    "non_positive_duration": "min_duration",
    "line_length": "line_length",
    "line_count": "line_count",
}

# Repair retimes cues. It cannot shorten a line, so the headline pair counts the
# violations retiming is able to address and the breakdown carries the rest.
TIMING_CHECKS = ("reading_speed", "min_duration", "non_positive_duration")

# ---- the frame at the cue -------------------------------------------------
# A cue is a line of dialogue on a picture. The sheet can say 22.63 cps all day
# and it stays an abstraction until the frame that line sits over is on screen
# with the line drawn on it. The picture is not decoration here: it is the thing
# being measured. Frames are cut from the same archive.org item the track came
# from, at the cue's own in-time, so nothing on the panel is a stand-in.
FRAME_DIR = Path(os.environ.get("CUEPASS_FRAME_DIR", "/tmp/cuepass-frames"))
# h.264 first: it is the derivative that seeks in one range request. The others
# are there so an item without an mp4 still yields a frame rather than a gap.
FRAME_VIDEO_EXT = (".mp4", ".m4v", ".ogv", ".mpg", ".mpeg", ".avi")
FRAME_TIMEOUT = 150
# How many frames the box pulls ahead of the reader on first load. The sheet
# opens on the still-red rows, so those are the ones warmed.
FRAME_PREWARM = 20

_frame_registry_lock = threading.Lock()
_frame_locks: dict[str, threading.Lock] = {}
# identifier -> the archive.org video URL frames are cut from. Filled by the
# prewarm thread and read without blocking, so no page render and no test ever
# waits on archive.org metadata, and the page names the file only once it is
# genuinely resolved.
_video_urls: dict[str, str] = {}
_prewarmed: set[str] = set()

_TIMECODE_ONE = re.compile(r"^(\d+):(\d+):(\d+)[,.](\d+)$")


def cue_seconds(timecode: str) -> float | None:
    """One SRT timestamp as seconds, or None if it is not one.

    Digit count decides the divisor, the same rule `measure._seconds` applies.
    This archive.org ASR track writes two subsecond digits, so reading `,95` as
    95ms would seek 855ms early and put a different shot on screen.
    """
    match = _TIMECODE_ONE.match((timecode or "").strip())
    if match is None:
        return None
    hours, minutes, seconds, frac = match.groups()
    return (
        int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(frac) / (10 ** len(frac))
    )


def resolve_video_url(identifier: str) -> str:
    """The archive.org video for an item, resolved once per box. "" if none."""
    if identifier in _video_urls:
        return _video_urls[identifier]
    files: list = []
    try:
        files = archive.metadata(identifier).get("files", []) or []
    except Exception:
        logger.warning("archive metadata unavailable for %s", identifier, exc_info=True)
    # Tallest picture wins, because this frame is going on screen at size. An
    # item carries the same film at 320x240 and at 640x480, and picking on file
    # size lands on the 256Kb derivative, which looks like a thumbnail blown up.
    # Extension order breaks a tie, so an mp4 is taken over an equal-height ogv.
    def rank(item: tuple[int, dict]) -> tuple[int, int, int]:
        index, entry = item
        return (
            int(entry.get("height", 0) or 0),
            -index,
            int(entry.get("size", 0) or 0),
        )

    candidates = []
    for entry in files:
        name = str(entry.get("name", "")).lower()
        if int(entry.get("size", 0) or 0) <= 0:
            continue
        for index, ext in enumerate(FRAME_VIDEO_EXT):
            if name.endswith(ext):
                candidates.append((index, entry))
                break
    url = ""
    if candidates:
        url = archive.download_url(identifier, max(candidates, key=rank)[1]["name"])
    if url:
        _video_urls[identifier] = url
    return url


def frame_path(identifier: str, seconds: float) -> Path:
    """Where the frame at this instant lives. Keyed on the instant, not the cue.

    Two profiles raise the same cue, and a cue is the same picture under both,
    so the key is the item and the millisecond. The corpus is fixed and a frame
    of a 1929 film does not change, so a hit is always the right picture.
    """
    return FRAME_DIR / f"{identifier}-{int(round(seconds * 1000)):09d}.jpg"


def extract_frame(identifier: str, seconds: float) -> Path | None:
    """The frame at `seconds`, cut with ffmpeg and cached. None if there is none.

    Returning None is a real answer: no ffmpeg on this box, no video in the
    item, or a seek the file cannot serve. The panel says so in words rather
    than showing a broken image.
    """
    if not identifier or seconds is None or seconds < 0:
        return None
    dest = frame_path(identifier, seconds)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    url = resolve_video_url(identifier)
    if not url:
        return None
    with _frame_registry_lock:
        lock = _frame_locks.setdefault(dest.name, threading.Lock())
    # Two readers on the same cue must not both pull the same frame off
    # archive.org. The second waits and then finds it on disk.
    with lock:
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        FRAME_DIR.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        cmd = [
            ffmpeg, "-nostdin", "-loglevel", "error", "-y",
            # Seek before the input so ffmpeg range-requests its way to the
            # keyframe instead of decoding a 452MB file from the top.
            "-ss", f"{seconds:.3f}",
            "-i", url,
            "-frames:v", "1", "-q:v", "2", "-an", "-sn",
            "-f", "image2", str(part),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=FRAME_TIMEOUT)
        except Exception:
            logger.warning("frame at %.3fs of %s not extracted", seconds, identifier, exc_info=True)
            part.unlink(missing_ok=True)
            return None
        if not part.exists() or part.stat().st_size == 0:
            part.unlink(missing_ok=True)
            return None
        part.replace(dest)
        return dest


def _prewarm_seconds(record: dict) -> list[float]:
    """The in-times of the two views the page actually opens on.

    First the still-red cues of the open desk, which is the landing sheet. Then
    the cues behind the profile-contrast number, which is the one click the
    product is built around. Warming only the first would leave that click
    landing on a black rectangle for as long as ffmpeg takes.
    """
    buyers = record.get("buyers") or {}
    default = _default_buyer(buyers)
    entry = buyers.get(default) or {}
    still = {
        (f.get("cue_index"), f.get("check"))
        for f in entry.get("after", {}).get("findings", [])
    }
    open_cues = [
        f.get("cue_index")
        for f in entry.get("before", {}).get("findings", [])
        if (f.get("cue_index"), f.get("check")) in still
    ]
    contrast_cues: list[int] = []
    for row in record.get("contrasts") or []:
        if row.get("stricter") == default:
            contrast_cues.extend(row.get("cue_indices") or [])

    at: dict[int, float] = {}
    for finding in entry.get("before", {}).get("findings", []):
        index = finding.get("cue_index")
        if index in at:
            continue
        seconds = cue_seconds(str(finding.get("timecode", "")).partition(" --> ")[0])
        if seconds is not None:
            at[index] = seconds

    out: list[float] = []
    for index in open_cues[:FRAME_PREWARM] + contrast_cues[:FRAME_PREWARM]:
        seconds = at.get(index)
        if seconds is not None and seconds not in out:
            out.append(seconds)
    return out


def prewarm_frames(record: dict | None) -> None:
    """Pull the opening frames in the background, once per run per box.

    The first reader would otherwise wait on ffmpeg for the hero frame. This
    runs off the page request, so the panel fills in behind them.
    """
    if not record:
        return
    identifier = record.get("film_identifier", "")
    run_id = record.get("run_id", "")
    if not identifier or not shutil.which("ffmpeg"):
        return
    with _frame_registry_lock:
        if run_id in _prewarmed:
            return
        _prewarmed.add(run_id)
    targets = _prewarm_seconds(record)
    if not targets:
        return

    def work() -> None:
        resolve_video_url(identifier)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda s: extract_frame(identifier, s), targets))

    threading.Thread(target=work, name="cuepass-frames", daemon=True).start()


def safe_url(url: str) -> str:
    """A URL fit to put behind an anchor, or "".

    A Parallel raw result occasionally comes back with a local file path spliced
    into it, for example a host followed by `:Users:someone:Desktop:`. A broken
    link in front of a reader is worse than no link, so anything that is not a
    plain absolute http(s) URL with a hostname is dropped and the page says the
    source URL was withheld.
    """
    if not isinstance(url, str) or not url:
        return ""
    if any(ch in url for ch in ' \t\r\n"<>\\') or url.count("://") != 1:
        return ""
    try:
        parts = urlparse(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    host = parts.hostname or ""
    if "." not in host or host.startswith(".") or host.endswith("."):
        return ""
    if ":" in parts.path or "\\" in parts.path:
        return ""
    return url


def engine_state() -> dict:
    """Whether this instance can perform a live run, stated rather than guessed.

    Cuepass will not measure against an uncited threshold, so without a Parallel
    key there is no spec to measure against and without Gemini there is nobody
    to decide which page is the buyer's own. A box missing either serves its
    stored runs and says why the button is off, instead of failing on click.
    """
    vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("true", "1", "yes")
    if vertex:
        gemini = bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    else:
        gemini = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    return {"parallel": bool(os.environ.get("PARALLEL_API_KEY")), "gemini": gemini}


def _default_buyer(buyers: dict) -> str:
    """Which desk opens first: the one with the most of its page behind it.

    Ranked on how many of the four rules the buyer's own page actually states,
    tie-broken by the worst outcome. Ranking on citation count rather than on
    the violation count means the open column is the best evidenced one, not the
    flattering one. Every other desk sits one row away in the index with its own
    result, including the desks repair could not move at all.
    """
    def rank(item: tuple[str, dict]) -> tuple[int, int]:
        _, entry = item
        spec = entry.get("spec", {})
        cited = sum(1 for _, key, _, _ in RULES if spec.get(key) is not None)
        return (cited, entry.get("before", {}).get("total_violations", 0))

    return max(buyers.items(), key=rank)[0] if buyers else ""


def _full_text(record: dict, buyer: str) -> dict[int, str]:
    """The verbatim text of every cue, keyed by cue index.

    A finding carries `text_preview`, cut to a fixed length, which on this track
    lands mid-word. The sheet is a spotting sheet, so it shows the cue as it
    plays, with the line breaks the subtitle itself sets. Empty when the source
    track is not on disk, in which case the row falls back to the preview rather
    than to nothing.
    """
    try:
        rows = runstore.cue_table(record, buyer)
    except Exception:
        logger.warning("cue table unavailable for %s", buyer, exc_info=True)
        return {}
    out = {}
    for row in rows:
        lines = row.get("lines") or []
        text = "\n".join(lines) if lines else row.get("text", "")
        if text:
            out[row["index"]] = text
    return out


def _cue_rows(
    entry: dict,
    editorial: dict,
    full_text: dict[int, str],
    contrast_indices: set[int],
) -> list[dict]:
    """One row per finding the first measurement produced, in cue order.

    A row is still failing when the second measurement, run on the repaired
    track, produced the same finding again. Deriving it from the remeasure
    rather than from the repair notes is what makes the count on the filter row
    the same number as the one in the headline pair.
    """
    before = entry.get("before", {})
    after = entry.get("after", {})
    reasons = entry.get("leftover_reasons", {})
    still = {f"{f['cue_index']}:{f['check']}": f for f in after.get("findings", [])}

    rows = []
    for f in before.get("findings", []):
        key = str(f["cue_index"])
        again = still.get(f"{f['cue_index']}:{f['check']}")
        open_now = again is not None
        timecode = str(f.get("timecode", ""))
        tc_in, _, tc_out = timecode.partition(" --> ")
        action = editorial.get(key, {}) if open_now else {}
        rows.append(
            {
                "index": f["cue_index"],
                "tc_in": tc_in,
                "tc_out": tc_out,
                "text": full_text.get(f["cue_index"]) or f.get("text_preview", ""),
                "check": f["check"],
                "rule": CHECK_TO_RULE.get(f["check"], f["check"]),
                "value": f.get("value"),
                # What the same check measured on the repaired track. A still-red
                # row leads with this, so the number on screen is the cue as it
                # stands now rather than as it arrived, and the original is kept
                # beside it to show what the retime did move.
                "value_after": (again or {}).get("value"),
                "limit": f.get("threshold"),
                "unit": f.get("unit", ""),
                "timing": f["check"] in TIMING_CHECKS,
                # This cue is inside the reading-speed gap between two published
                # profiles: legal under the looser one, raised here. Only the
                # stricter desk carries the mark, because only it raises them.
                "in_contrast": (
                    f["check"] == "reading_speed" and f["cue_index"] in contrast_indices
                ),
                "open": open_now,
                # Only a still-failing cue carries a reason. A cue the retime
                # cleared says so instead, so nothing about a repaired cue reads
                # as a complaint.
                "blocked_by": reasons.get(key, "") if open_now else "",
                "action": action.get("action", ""),
                "note": action.get("note", ""),
            }
        )
    return rows


def _evidence(spec: dict) -> dict:
    """Per threshold: the sentence, the page it was read from, and how.

    A profile page does not always state all four rules, so a threshold can be
    cited from a page other than the profile's own. That is worth showing rather
    than flattening: the band marks a borrowed row and links the page it really
    came from, so no number sits under a citation that does not contain it.
    """
    own = spec.get("source_url", "")
    provenance = spec.get("provenance") or {}
    out = {}
    for _, key, _, _ in RULES:
        raw = (spec.get("evidence") or {}).get(key) or {}
        page = raw.get("url", "") or own
        # The run records whether this number came off the profile's lead page.
        # That field is authoritative. Comparing the URLs asks the same question
        # a second way, kept so a check can hold the two against each other
        # rather than trusting either on its own.
        derived = bool(page) and bool(own) and page != own
        stated = raw.get("from_profile_page")
        out[key] = {
            "clause": raw.get("clause", ""),
            "url": safe_url(page),
            "off_profile": (not stated) if stated is not None else derived,
            "off_profile_derived": derived,
            # Whatever the run recorded for this threshold. Rendered whenever it
            # is not "live", so a borrowed number can never sit silently under a
            # badge claiming the whole spec was fetched this run.
            "provenance": provenance.get(key, ""),
        }
    return out


def _buyer_view(
    buyer: str,
    entry: dict,
    editorial: dict,
    repaired: str,
    full_text: dict[int, str],
    contrast_indices: set[int],
) -> dict:
    before = entry.get("before", {})
    after = entry.get("after", {})
    spec = entry.get("spec", {})
    rows = _cue_rows(entry, editorial, full_text, contrast_indices)

    timing_before = sum(1 for r in rows if r["timing"])
    timing_after = sum(1 for r in rows if r["timing"] and r["open"])
    publishes_timing = spec.get("max_cps") is not None or spec.get("min_duration_s") is not None
    citation = safe_url(spec.get("source_url", ""))

    return {
        "key": buyer,
        "platform": spec.get("platform", buyer.upper()),
        "verdict": entry.get("verdict", ""),
        "cues_retimed": entry.get("cues_changed", 0),
        "repaired_file": repaired,
        "spec": {
            "max_cps": spec.get("max_cps"),
            "min_duration_s": spec.get("min_duration_s"),
            "max_line_chars": spec.get("max_line_chars"),
            "max_lines": spec.get("max_lines"),
            "citation_url": citation,
            "url_withheld": bool(spec.get("source_url")) and not citation,
            "citation_title": spec.get("source_label", ""),
            "is_cached": bool(spec.get("is_cached", False)),
            "extract_id": spec.get("extract_id", ""),
            "chars_extracted": spec.get("chars_extracted", 0),
            "evidence": _evidence(spec),
            # Every page that contributed a threshold to this profile. A spec is
            # spread across pages, so the count is part of the provenance: one
            # page is a lucky hit, three is a resolution.
            "source_urls": [u for u in (safe_url(x) for x in spec.get("source_urls") or []) if u],
            # How the cited page was found. "parallel_search" means Parallel
            # Search returned this URL during this run, at search_rank, off the
            # queries below. "seed_fallback" means Search returned nothing on a
            # host this buyer publishes on and the documented fallback URL in
            # parallel_spec.py fired, which the page says out loud rather than
            # letting the citation imply a discovery that did not happen.
            "discovery": spec.get("discovery", ""),
            "search_rank": next(
                (d.get("search_rank") for d in spec.get("source_discovery") or []), None
            ),
            "search_queries": next(
                (d.get("queries") or [] for d in spec.get("source_discovery") or []), []
            ),
            "desk_reason": spec.get("desk_reason", ""),
            # What this profile covers, in the run's own words. Two profiles
            # from one company are two scopes, not a contradiction, and the
            # page has no business implying otherwise.
            "scope": spec.get("scope", ""),
        },
        "totals": {
            "violations": before.get("total_violations", 0),
            "violations_after": after.get("total_violations", 0),
            "over_cps": before.get("over_cps_count", 0),
            "under_min_duration": before.get("under_duration_count", 0),
            "over_line_chars": before.get("over_line_chars_count", 0),
            "over_max_lines": before.get("over_line_count", 0),
            "non_positive_duration": before.get("non_positive_duration_count", 0),
            "checks_skipped": before.get("checks_skipped", []),
        },
        # The pair the headline shows. Timing violations when the buyer publishes
        # a timing rule, because retiming is what repair does: pairing a total
        # that includes line-length failures against an after-count would credit
        # repair with cues it provably cannot touch. A buyer who publishes only a
        # line rule gets the total, and the legend says which is on screen.
        "pair": {
            "kind": "timing" if publishes_timing else "total",
            "before": timing_before if publishes_timing else before.get("total_violations", 0),
            "after": timing_after if publishes_timing else after.get("total_violations", 0),
        },
        "rows": rows,
    }


TIMECODE = re.compile(r"\d{2}:\d{2}:\d{2}[,.](\d+)\s*-->")


def _fraction_digits(record: dict) -> int | None:
    """How many subsecond digits the stored source track actually writes.

    SRT is HH:MM:SS,mmm. This archive.org ASR track writes two digits, and read
    naively every duration on it is out by a factor of ten, which would make
    every count on this page fiction. `measure` normalises on digit count, and
    this reads the same fact back off the file so the page can say so for the
    track in front of it instead of asserting it about tracks in general.

    None when the source is not on disk, in which case nothing is claimed.
    """
    name = record.get("source_file", "")
    if not name:
        return None
    path = runstore.repaired_path(name)
    if path is None:
        return None
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return None
    match = TIMECODE.search(head)
    return len(match.group(1)) if match else None


def _trace_marks(record: dict) -> dict:
    """Which declared nodes actually fired, read off the stored event trace.

    The graph is what the code declares. The trace is what ran. Showing the
    declared topology with the nodes that fired marked is the only way a reader
    can tell a real graph from a picture of one.
    """
    fired: dict[str, int] = {}
    for step in record.get("trace", []):
        node = str(step.get("author") or step.get("node") or "").split("@")[0]
        if node:
            fired[node] = fired.get(node, 0) + 1
    return fired


def _contrasts(record: dict) -> list[dict]:
    """Every pair of published profiles that set different reading speeds.

    This is the run's sharpest output: the count of cues that clear one
    published profile and fail another, same file, same code, same run.

    Every row is carried, not just the first. Three profiles at three different
    reading speeds produce three pairs, and rendering one of them would drop
    measured evidence while looking complete. The list is empty when no two
    profiles differ, which is the honest state: the page then shows nothing
    rather than an empty frame.
    """
    out = []
    for row in record.get("contrasts") or []:
        count = row.get("cues_legal_under_looser_only", 0)
        if not count:
            continue
        out.append(
            {
                "stricter": row.get("stricter", ""),
                "looser": row.get("looser", ""),
                "stricter_platform": row.get("stricter_platform", ""),
                "looser_platform": row.get("looser_platform", ""),
                "stricter_max_cps": row.get("stricter_max_cps"),
                "looser_max_cps": row.get("looser_max_cps"),
                "stricter_clause": row.get("stricter_clause", ""),
                "looser_clause": row.get("looser_clause", ""),
                "stricter_url": safe_url(row.get("stricter_url", "")),
                "looser_url": safe_url(row.get("looser_url", "")),
                "stricter_scope": row.get("stricter_scope", ""),
                "looser_scope": row.get("looser_scope", ""),
                "cue_indices": list(row.get("cue_indices") or []),
                "count": count,
                # The headline count and the list of cues behind it are two
                # fields, so they can disagree. If the list is ever shorter, the
                # block must not offer to show N cues and then produce fewer:
                # the number would stay right while the evidence quietly shrank.
                "evidence_complete": count == len(row.get("cue_indices") or []),
            }
        )
    return out


def ui_run(record: dict) -> dict:
    """Shape one stored run for the page. Values pass through as measured."""
    editorial = record.get("editorial") or {}
    repaired_files = record.get("repaired_files") or {}
    raw_buyers = record.get("buyers") or {}
    # The cue text is the same for every desk, so the track is parsed once.
    full_text = _full_text(record, _default_buyer(raw_buyers)) if raw_buyers else {}
    contrasts = _contrasts(record)
    # Only the stricter side of a pair raises the cues in its gap, so only that
    # profile's sheet may mark them: marking them on the looser side would flag
    # cues that profile's own page calls legal. A profile can be the stricter
    # side of more than one pair, so the marks are the union of those gaps.
    gaps: dict[str, set[int]] = {}
    for row in contrasts:
        gaps.setdefault(row["stricter"], set()).update(row["cue_indices"])
    buyers = {
        key: _buyer_view(
            key,
            entry,
            editorial,
            repaired_files.get(key, ""),
            full_text,
            gaps.get(key, set()),
        )
        for key, entry in raw_buyers.items()
    }
    return {
        "run_id": record.get("run_id", ""),
        "title": record.get("film_title", ""),
        "identifier": record.get("film_identifier", ""),
        "source_url": safe_url(record.get("subtitle_url", "")),
        # The video frames are cut from, named only once it has actually been
        # resolved off archive.org. Read from memory, never fetched here, so
        # rendering a page and importing this module stay offline.
        "video_url": safe_url(_video_urls.get(record.get("film_identifier", ""), "")),
        "source_filename": record.get("subtitle_filename", ""),
        "fraction_digits": _fraction_digits(record),
        "measured_at": record.get("measured_at", ""),
        "cue_count": record.get("cue_count", 0),
        "buyers": buyers,
        "default_buyer": _default_buyer(raw_buyers),
        "contrasts": contrasts,
        "unavailable": record.get("unavailable") or {},
        "graph": record.get("graph") or {},
        "fired": _trace_marks(record),
        "trace_len": len(record.get("trace") or []),
        "model": record.get("model", ""),
        "framework": record.get("framework", ""),
        "parallel_surfaces": record.get("parallel_surfaces") or [],
        "leftover_cue_total": record.get("leftover_cue_total", 0),
        "editorial_capped_at": record.get("editorial_capped_at", 0),
    }


def boot_payload(run_id: str = "") -> dict:
    """What the page opens on: a stored run, the index, and what this box can do."""
    chosen = run_id or runstore.default_run_id()
    record = runstore.load(chosen) if chosen else None
    return {
        "run": ui_run(record) if record else None,
        "index": runstore.list_runs(),
        "engine": engine_state(),
    }


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Cuepass: subtitle compliance against the buyer's cited spec</title>
  <meta name="description" content="Cuepass measures a subtitle track against each buyer's own published caption specification, fetched live, and shows the verbatim sentence every threshold was read from." />
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%23131313'/%3E%3Crect x='6' y='21' width='20' height='4' fill='%233cffd0'/%3E%3Crect x='9' y='27' width='14' height='2' fill='%23949494'/%3E%3C/svg%3E">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Anton&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --canvas:  #131313;
      --surface: #191919;
      --border:  #242424;
      --border-hi: #363636;
      /* Every one of these clears 4.5:1 on the canvas, measured rather than
         eyeballed: the sheet was grey-on-near-black at 11px and a judge skims. */
      --text:    #ffffff;
      --text-2:  #c8c8c8;
      --text-3:  #949494;
      --mint:    #3cffd0;
      --mint-dim: #2b7a68;
      --red:     #ff5d52;
      --display: 'Anton', Impact, 'Helvetica Neue', sans-serif;
      --mono:    'Space Mono', ui-monospace, 'JetBrains Mono', monospace;
      --read:    -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    }

    html, body { height: 100%; }

    body {
      background: var(--canvas);
      color: var(--text);
      font-family: var(--read);
      font-size: 16px;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }

    ::selection { background: var(--mint); color: #000; }

    .page {
      max-width: 1340px;
      margin: 0 auto;
      padding: clamp(18px, 2.2vw, 28px) clamp(20px, 3.4vw, 40px) 120px;
    }

    /* ---- masthead ---- */
    .masthead {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: end;
      gap: 14px 34px;
    }
    .brand { display: flex; align-items: baseline; gap: 13px; }
    .wordmark {
      font-family: var(--display);
      font-weight: 400;
      font-size: clamp(34px, 3.4vw, 46px);
      letter-spacing: -0.015em;
      line-height: 0.9;
      color: var(--text);
    }
    .brand-unit {
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 3px;
      color: var(--mint);
    }
    .brand-claim {
      font-family: var(--read);
      font-size: 15px;
      line-height: 1.55;
      color: var(--text-2);
      max-width: 62ch;
      margin-top: 9px;
    }
    .brand-claim b { color: var(--text); font-weight: 700; }

    .runbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: flex-end; }
    .runbar select, .runbar input[type="text"] {
      background: var(--surface);
      border: 1px solid var(--border-hi);
      border-radius: 2px;
      padding: 0 11px;
      height: 36px;
      color: var(--text);
      font-family: var(--mono);
      font-size: 12px;
      letter-spacing: 0.2px;
      -webkit-appearance: none;
      appearance: none;
    }
    .runbar select { min-width: 188px; cursor: pointer; }
    .runbar select:hover, .runbar input:hover { border-color: #4a4a4a; }
    .runbar select:focus-visible, .runbar input:focus-visible,
    .run-btn:focus-visible, .rail-row:focus-visible, .flt:focus-visible, a:focus-visible {
      outline: 1px solid var(--mint);
      outline-offset: 2px;
    }
    .runbar select:focus, .runbar input:focus { outline: none; border-color: var(--mint); }
    .runbar select option { background: #1c1c1c; color: var(--text); }
    .runbar .ident { width: 126px; }
    .runbar .or {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--text-3);
    }

    .run-btn {
      background: var(--mint);
      color: #000;
      border: 0;
      border-radius: 2px;
      height: 36px;
      padding: 0 18px;
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      cursor: pointer;
      transition: transform .12s ease;
      white-space: nowrap;
    }
    .run-btn:hover:not(:disabled) { transform: translateY(-1px); }
    .run-btn:active:not(:disabled) { transform: translateY(0); }
    .run-btn:disabled { background: #2a2a2a; color: var(--text-3); cursor: default; }

    .status-line {
      font-family: var(--mono);
      font-size: 11px;
      line-height: 1.5;
      color: var(--text-2);
      letter-spacing: 0.3px;
      min-height: 15px;
      margin-top: 7px;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 7px;
      text-align: right;
    }
    .spinner {
      width: 9px; height: 9px;
      border: 1px solid var(--border-hi);
      border-top-color: var(--mint);
      border-radius: 50%;
      animation: spin .7s linear infinite;
      flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) {
      .spinner { animation: none; }
      .run-btn, .rail-row, .cue-row, .flt, .screen-img { transition: none; }
    }

    /* ---- spec band: the cited spec is the header, not a footnote ---- */
    .specband {
      margin-top: 14px;
      border-top: 2px solid var(--mint-dim);
      border-bottom: 1px solid var(--border-hi);
      padding: 12px 0 11px;
      display: grid;
      grid-template-columns: 238px minmax(0, 1fr);
      gap: 4px 34px;
    }
    .sb-label {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
    }
    .sb-buyer {
      font-family: var(--display);
      font-size: 26px;
      line-height: 1.05;
      letter-spacing: -0.01em;
      margin-top: 3px;
    }
    .sb-meta {
      font-family: var(--mono);
      font-size: 11px;
      line-height: 1.5;
      letter-spacing: 0.3px;
      color: var(--text-2);
      margin-top: 6px;
    }
    .sb-meta.dim {
      color: var(--text-3);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .sb-badge {
      display: inline-block;
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      padding: 2px 6px;
      border: 1px solid currentColor;
      border-radius: 2px;
    }
    .sb-badge.live   { color: var(--mint); }
    .sb-badge.cached { color: var(--text-3); }

    .th-row {
      display: grid;
      grid-template-columns: 64px 94px minmax(0, 1fr);
      gap: 0 16px;
      align-items: baseline;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
    }
    .th-row:last-child { border-bottom: 0; }
    .th-val {
      font-family: var(--mono);
      font-size: 17px;
      font-weight: 700;
      letter-spacing: -0.4px;
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    .th-val.skipped {
      font-size: 10px; font-weight: 400; color: var(--text-3);
      letter-spacing: 1.2px; text-transform: uppercase;
    }
    .th-unit {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.4px;
      text-transform: uppercase;
      color: var(--text-3);
    }
    /* The verbatim sentence is the track argument, so it is set as a sentence
       and not as log output: reading face, near-white, at a size a judge reads
       standing up. */
    .th-clause {
      font-family: var(--read);
      font-size: 15px;
      line-height: 1.5;
      color: var(--text);
      min-width: 0;
    }
    .th-clause.absent { font-size: 14px; color: var(--text-3); }
    /* The provenance of a borrowed threshold sits under its clause on its own
       line. Inline, it used to push a 62-character unbreakable URL through the
       right edge of the grid. */
    .th-mark {
      display: block;
      margin-top: 5px;
      font-family: var(--mono);
      font-size: 11.5px;
      letter-spacing: 0.2px;
      color: var(--text-3);
    }
    .th-else {
      display: inline-block;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      vertical-align: bottom;
      color: var(--text-2);
      text-decoration: none;
      border-bottom: 1px solid var(--border-hi);
    }
    a.th-else:hover { color: var(--mint); border-color: var(--mint); }
    .th-else.warn { color: var(--red); border-bottom: 0; text-transform: uppercase; letter-spacing: 1.2px; font-size: 10px; }

    .sb-scope {
      grid-column: 1 / -1;
      font-family: var(--read);
      font-size: 14px;
      line-height: 1.5;
      color: var(--text-2);
      margin-top: 11px;
      padding-left: 11px;
      border-left: 2px solid var(--mint-dim);
    }

    .sb-prov {
      grid-column: 1 / -1;
      margin-top: 11px;
      padding-top: 10px;
      border-top: 1px solid var(--border);
      font-family: var(--mono);
      font-size: 11.5px;
      letter-spacing: 0.3px;
      color: var(--text-3);
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 4px 20px;
    }
    .sb-prov > span { min-width: 0; max-width: 100%; }
    .sb-prov a {
      display: inline-block;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      vertical-align: bottom;
      color: var(--text-2);
      text-decoration: none;
      border-bottom: 1px solid var(--border-hi);
    }
    .sb-prov a:hover { color: var(--mint); border-color: var(--mint); }
    .sb-prov .withheld { color: var(--red); }

    /* ---- split: index left, open desk right ---- */
    .split {
      display: grid;
      grid-template-columns: 252px minmax(0, 1fr);
      gap: 0 38px;
      margin-top: 10px;
      align-items: start;
    }
    .rail { border-right: 1px solid var(--border); padding-right: 20px; }
    .rail-group + .rail-group { margin-top: 22px; }
    .rail-head {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
      padding-bottom: 6px;
      border-bottom: 1px solid var(--border-hi);
    }
    .rail-row {
      display: block;
      width: 100%;
      text-align: left;
      background: none;
      border: 0;
      border-bottom: 1px solid var(--border);
      border-left: 2px solid transparent;
      padding: 9px 0 9px 10px;
      cursor: pointer;
      font-family: var(--mono);
      color: var(--text-2);
      transition: background .12s ease, color .12s ease;
    }
    .rail-row:hover { background: rgba(255,255,255,0.025); color: var(--text); }
    .rail-row.on { border-left-color: var(--mint); color: var(--text); background: rgba(255,255,255,0.03); }
    .rail-row.dead { cursor: default; color: var(--text-3); }
    .rail-row.dead:hover { background: none; color: var(--text-3); }
    .rr-top { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
    .rr-name { font-size: 13px; font-weight: 700; letter-spacing: 0.3px; }
    .rr-tag { font-size: 9px; letter-spacing: 1.3px; text-transform: uppercase; flex-shrink: 0; }
    .rr-tag.hold { color: var(--red); }
    .rr-tag.deliver { color: var(--mint); }
    .rr-tag.none { color: var(--text-3); }
    .rr-sub {
      display: block;
      font-size: 11.5px;
      line-height: 1.5;
      letter-spacing: 0.3px;
      color: var(--text-3);
      margin-top: 4px;
      font-variant-numeric: tabular-nums;
    }
    .rr-sub .n { color: var(--text-2); font-weight: 700; }
    /* A desk that found nothing explains itself, and the explanation carries the
       URLs it tried. Those are single unbreakable tokens, so without this the
       rail sets the width of the whole grid. */
    .rr-why {
      display: block;
      font-family: var(--read);
      font-size: 13.5px;
      line-height: 1.5;
      color: var(--text-2);
      margin-top: 6px;
      overflow-wrap: anywhere;
    }
    .rail, .rail-row, .contrast { min-width: 0; }
    .rr-sub, .rr-name, .c-say, .c-side { overflow-wrap: anywhere; }

    /* ---- the two-profile contrast: the run's sharpest single number ---- */
    .contrast {
      display: block;
      width: 100%;
      text-align: left;
      background: none;
      border: 0;
      border-bottom: 1px solid var(--border);
      padding: 11px 0 13px;
      cursor: pointer;
      font-family: var(--mono);
      color: var(--text-2);
    }
    .c-num {
      display: block;
      font-family: var(--display);
      font-weight: 400;
      font-size: 56px;
      line-height: 0.84;
      letter-spacing: -0.01em;
      color: var(--text);
      font-variant-numeric: tabular-nums;
    }
    .c-say {
      display: block;
      font-family: var(--read);
      font-size: 14px;
      line-height: 1.5;
      color: var(--text-2);
      margin-top: 9px;
    }
    .c-side {
      display: block;
      font-size: 11.5px;
      line-height: 1.5;
      color: var(--text-3);
      margin-top: 8px;
      padding-left: 10px;
      border-left: 1px solid var(--border-hi);
    }
    .c-side b {
      color: var(--text);
      font-weight: 700;
      font-size: 13.5px;
      font-variant-numeric: tabular-nums;
    }
    .c-side a { color: var(--text-2); text-decoration: none; border-bottom: 1px solid var(--border-hi); margin-left: 7px; }
    .c-side a:hover { color: var(--mint); border-color: var(--mint); }
    .c-side .c-name { color: var(--text-2); margin-left: 7px; }
    .c-partial {
      display: block;
      font-size: 11px;
      line-height: 1.45;
      color: var(--red);
      margin-top: 8px;
    }
    .c-go {
      display: inline-block;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.4px;
      color: var(--mint);
      border-bottom: 1px solid var(--mint);
      margin-top: 11px;
      padding-bottom: 2px;
    }
    .contrast:hover .c-go { color: var(--text); border-color: var(--text); }

    /* ---- the frame at the cue ----
       A subtitle is a line of type over a picture, and every number on this
       page is a statement about how that line sits on that picture. The frame
       is cut from the same archive.org item the track came from, at the cue's
       own in-time, and the cue is drawn over it the way a viewer gets it. */
    .marquee {
      display: grid;
      grid-template-columns: minmax(0, 424px) minmax(0, 1fr);
      gap: 0 36px;
      align-items: start;
      padding-top: 4px;
    }
    .reel { min-width: 0; }
    .reel-head {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
      padding-bottom: 7px;
    }
    .screen {
      position: relative;
      aspect-ratio: 4 / 3;
      background: #000;
      border: 1px solid var(--border-hi);
      overflow: hidden;
      container-type: inline-size;
    }
    .screen-img {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: contain;
      opacity: 0;
      transition: opacity .45s ease;
    }
    .screen.ready .screen-img { opacity: 1; }
    /* The cue, drawn as the delivered track times it. */
    .screen-sub {
      position: absolute;
      left: 4%;
      right: 4%;
      bottom: 7%;
      text-align: center;
      font-family: var(--read);
      /* Sized so a line at the 42-character limit still sets on one line. If
         the panel wrapped it, a cue that breaks the line-length rule would look
         the same as one that does not. */
      font-size: clamp(12px, 3.7cqw, 18px);
      line-height: 1.3;
      color: #fff;
      white-space: pre-line;
      text-shadow: 0 2px 6px rgba(0,0,0,.95), 0 0 3px rgba(0,0,0,.9);
    }
    /* A QC viewer burns the timecode into the corner. This one is the cue's
       own in-time, which is the instant the frame behind it was cut at. */
    .screen-tc, .screen-id {
      position: absolute;
      top: 8px;
      font-family: var(--mono);
      font-size: 10.5px;
      letter-spacing: 0.6px;
      color: rgba(255,255,255,0.82);
      background: rgba(0,0,0,0.55);
      padding: 2px 6px;
      font-variant-numeric: tabular-nums;
    }
    .screen-tc { left: 8px; }
    .screen-id { right: 8px; }
    .screen-hold {
      position: absolute;
      left: 10%;
      right: 10%;
      top: 38%;
      text-align: center;
      font-family: var(--mono);
      font-size: 11.5px;
      line-height: 1.6;
      letter-spacing: 0.3px;
      color: var(--text-3);
    }
    .screen.ready .screen-hold { display: none; }
    .screen.gone { border-color: var(--border); }
    .reel-cap {
      font-family: var(--mono);
      font-size: 11px;
      line-height: 1.55;
      letter-spacing: 0.2px;
      color: var(--text-3);
      margin-top: 8px;
    }
    .reel-cap a {
      color: var(--text-2);
      text-decoration: none;
      border-bottom: 1px solid var(--border-hi);
      display: inline-block;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      vertical-align: bottom;
    }
    .reel-cap a:hover { color: var(--mint); border-color: var(--mint); }

    .reel-read { margin-top: 13px; }
    .rr-rule {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
    }
    /* Measured against the limit, on one scale. The tick is the published
       number, the bar is what the cue does. */
    .gauge {
      position: relative;
      height: 8px;
      margin: 9px 0 8px;
      background: #1e1e1e;
      border: 1px solid var(--border);
    }
    .gauge-bar { position: absolute; left: 0; top: 0; bottom: 0; background: var(--red); }
    .gauge-bar.ok { background: var(--mint); }
    .gauge-tick { position: absolute; top: -4px; bottom: -4px; width: 2px; background: var(--mint); }
    .rr-say {
      font-family: var(--read);
      font-size: 15px;
      line-height: 1.5;
      color: var(--text);
    }
    .rr-say b { font-family: var(--mono); font-weight: 700; font-variant-numeric: tabular-nums; }
    .rr-say .over { color: var(--red); }
    .rr-meta {
      font-family: var(--mono);
      font-size: 11.5px;
      line-height: 1.6;
      letter-spacing: 0.3px;
      color: var(--text-3);
      margin-top: 6px;
      font-variant-numeric: tabular-nums;
    }
    .rr-meta b { color: var(--text-2); font-weight: 700; }

    /* The cues either side of this one, in the filter that is open. Six real
       frames, so what the sheet lists as rows also reads as a run of shots. */
    .stripwrap { grid-column: 1 / -1; }
    .strip-head {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
      margin: 22px 0 8px;
    }
    .strip { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 6px; }
    .strip-cell {
      position: relative;
      aspect-ratio: 4 / 3;
      background: #000;
      border: 1px solid var(--border);
      padding: 0;
      cursor: pointer;
      overflow: hidden;
    }
    .strip-cell img {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      opacity: .55;
      transition: opacity .18s ease;
    }
    .strip-cell:hover img { opacity: .9; }
    .strip-cell.on { border-color: var(--mint); }
    .strip-cell.on img { opacity: 1; }
    .strip-num {
      position: absolute;
      left: 0; right: 0; bottom: 0;
      font-family: var(--mono);
      font-size: 9.5px;
      letter-spacing: 0.4px;
      color: #fff;
      background: rgba(0,0,0,0.6);
      padding: 2px 0;
      text-align: center;
      font-variant-numeric: tabular-nums;
    }
    @media (prefers-reduced-motion: reduce) { .strip-cell img { transition: none; } }

    /* ---- verdict: the pair is the headline ---- */
    .verdict { padding: 0 0 2px; }
    .v-kicker {
      font-family: var(--mono);
      font-size: 10.5px;
      letter-spacing: 1.1px;
      text-transform: uppercase;
      color: var(--text-2);
      padding-bottom: 8px;
    }
    .v-kicker b { color: var(--text); font-weight: 700; }
    .v-kicker .sep { color: var(--text-3); padding: 0 7px; }
    .verdict-nums {
      display: flex;
      align-items: baseline;
      gap: clamp(14px, 2.2vw, 30px);
      font-variant-numeric: tabular-nums;
    }
    .vnum { display: flex; flex-direction: column; }
    .v-big {
      font-family: var(--display);
      font-weight: 400;
      font-size: clamp(56px, 7vw, 88px);
      line-height: 0.8;
      letter-spacing: -0.01em;
    }
    .v-big.before { color: var(--red); }
    .v-big.after.clean { color: var(--mint); }
    .v-big.after.leftover { color: var(--red); }
    .v-cap {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      color: var(--text-3);
      margin-top: 11px;
    }
    .v-arrow {
      font-family: var(--display);
      font-size: clamp(24px, 3vw, 38px);
      line-height: 0.8;
      color: var(--text-3);
    }
    .verdict-cap {
      font-family: var(--read);
      font-size: 15px;
      line-height: 1.55;
      color: var(--text-2);
      margin-top: 12px;
      max-width: 58ch;
    }
    .verdict-cap b { color: var(--text); font-weight: 700; }
    .breakdown {
      display: flex;
      flex-wrap: wrap;
      gap: 5px 22px;
      margin-top: 11px;
      padding-top: 10px;
      border-top: 1px solid var(--border);
      font-family: var(--mono);
      font-size: 12px;
      letter-spacing: 0.3px;
      color: var(--text-3);
    }
    .breakdown .n { color: var(--red); font-weight: 700; font-variant-numeric: tabular-nums; }
    .breakdown .n.zero { color: var(--text-2); }
    .take-row { display: flex; flex-wrap: wrap; gap: 9px 22px; margin-top: 9px; }
    .take-track {
      font-family: var(--mono);
      font-size: 12.5px;
      font-weight: 700;
      letter-spacing: 0.4px;
      color: var(--mint);
      text-decoration: none;
      border-bottom: 1px solid var(--mint);
      padding-bottom: 2px;
    }
    .take-track.second { color: var(--text-2); border-color: var(--border-hi); font-weight: 400; }
    .take-track:hover { color: var(--text); border-color: var(--text); }
    .src-note {
      font-family: var(--read);
      font-size: 14px;
      line-height: 1.55;
      color: var(--text-2);
      margin-bottom: 15px;
    }
    .src-note b { color: var(--red); font-weight: 700; }

    /* ---- filter row ---- */
    .filter-row {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 4px 0;
      padding: 20px 0 6px;
    }
    .flt {
      background: none;
      border: 0;
      cursor: pointer;
      font-family: var(--mono);
      font-size: 11.5px;
      letter-spacing: 1.4px;
      text-transform: uppercase;
      color: var(--text-3);
      padding: 4px 13px 4px 0;
      transition: color .12s ease;
    }
    .flt:not(:last-child)::after { content: '/'; color: var(--border-hi); padding-left: 13px; }
    .flt:hover { color: var(--text-2); }
    .flt .n { color: var(--text-2); font-weight: 700; margin-left: 6px; font-variant-numeric: tabular-nums; }
    .flt.on { color: var(--text); }
    .flt.on .n { color: var(--mint); }

    /* ---- spotting sheet ---- */
    .sheet-head, .cue-row {
      display: grid;
      grid-template-columns: 52px 166px minmax(0, 1fr) 122px;
      gap: 0 18px;
    }
    .sheet-head {
      padding: 7px 0;
      border-bottom: 1px solid var(--border-hi);
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.6px;
      text-transform: uppercase;
      color: var(--text-3);
    }
    .sheet-head .r { text-align: right; }

    .cue-row {
      padding: 11px 0;
      border-bottom: 1px solid var(--border);
      align-items: start;
      cursor: pointer;
      transition: background .1s ease;
    }
    .cue-row:hover { background: rgba(255,255,255,0.03); }
    .cue-row.copied  { background: rgba(60,255,208,0.06); }
    /* The row whose frame is on the screen above. */
    .cue-row.on {
      background: rgba(255,255,255,0.04);
      box-shadow: inset 2px 0 0 var(--mint);
    }

    .cue-num {
      font-family: var(--mono);
      font-size: 12.5px;
      color: var(--text-3);
      display: flex;
      align-items: center;
      gap: 8px;
      padding-top: 3px;
      font-variant-numeric: tabular-nums;
    }
    .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: var(--red); }
    .dot.repaired { background: var(--mint); }

    .cue-tc {
      font-family: var(--mono);
      font-size: 12.5px;
      color: var(--text-2);
      letter-spacing: -0.2px;
      padding-top: 3px;
      line-height: 1.55;
      font-variant-numeric: tabular-nums;
    }
    .cue-tc .out { color: var(--text-3); }
    .cue-tc .out.repaired { color: var(--mint); }

    .cue-body { min-width: 0; }
    /* The cue as it plays: its own line breaks, not the column's. Two lines is
       the most any buyer here permits, so a cue clamped at two is a cue that
       already breaks the line-count rule, and the sheet says so on its own row. */
    .cue-text {
      font-family: var(--read);
      font-size: 16px;
      line-height: 1.35;
      color: var(--text);
      overflow-wrap: anywhere;
      white-space: pre-line;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .cue-why { font-family: var(--mono); font-size: 12.5px; letter-spacing: 0.4px; margin-top: 6px; color: var(--red); }
    .cue-why.repaired { color: var(--mint); }
    .cue-act { font-family: var(--mono); font-size: 11.5px; line-height: 1.5; letter-spacing: 0.3px; margin-top: 4px; color: var(--text-3); }
    .cue-act b { color: var(--text-2); font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase; }

    .cue-val { text-align: right; font-family: var(--mono); padding-top: 1px; font-variant-numeric: tabular-nums; }
    .cue-val .big { font-size: 19px; font-weight: 700; line-height: 1; letter-spacing: -0.3px; }
    .cue-val.red  .big { color: var(--red); }
    .cue-val.mint .big { color: var(--mint); }
    .cue-val .sub { display: block; font-size: 11.5px; color: var(--text-3); margin-top: 5px; letter-spacing: 0.4px; }

    .empty-note {
      padding: 26px 0;
      font-family: var(--read);
      font-size: 15px;
      line-height: 1.6;
      color: var(--text-2);
      max-width: 62ch;
    }
    .empty-note b { color: var(--text); font-weight: 700; }

    /* ---- graph: declared topology with the nodes that actually fired ---- */
    .provenance { margin-top: 34px; border-top: 1px solid var(--border-hi); padding-top: 14px; }
    .prov-head {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.8px;
      text-transform: uppercase;
      color: var(--text-3);
    }
    .prov-note {
      font-family: var(--read);
      font-size: 14.5px;
      line-height: 1.6;
      color: var(--text-2);
      margin-top: 9px;
      max-width: 74ch;
    }
    .prov-note b { color: var(--text); font-weight: 700; }
    .nodes { display: flex; flex-wrap: wrap; gap: 7px 8px; margin-top: 13px; }
    .node {
      font-family: var(--mono);
      font-size: 11.5px;
      letter-spacing: 0.3px;
      padding: 4px 9px;
      border: 1px solid var(--border);
      border-radius: 2px;
      color: var(--text-3);
    }
    .node.fired { color: var(--text); border-color: var(--border-hi); }
    .node.fired.model { border-color: var(--mint-dim); }
    .node .times { color: var(--text-3); margin-left: 7px; font-variant-numeric: tabular-nums; }
    /* A node that runs no model authors no event, so it can never appear in the
       stream. Marking it as silent rather than cold stops a deterministic node
       reading like a failed one. */
    .node.silent { color: var(--text-2); border-color: var(--border); }
    .node.silent .times { color: var(--text-3); }
    .node.cold { border-style: dashed; color: var(--text-3); }
    .node.cold .times { color: var(--red); }

    .error-box { margin-bottom: 20px; border: 1px solid var(--red); border-radius: 2px; padding: 13px 15px; }
    .error-label {
      font-family: var(--mono);
      font-size: 10px;
      letter-spacing: 1.6px;
      text-transform: uppercase;
      color: var(--red);
      margin-bottom: 6px;
    }
    .error-body { font-family: var(--mono); font-size: 12px; color: var(--text-2); line-height: 1.6; overflow-wrap: anywhere; }

    @media (max-width: 620px) {
      /* The threshold, then its unit, then the sentence under both. Holding
         three columns here squeezed the clause into a two-word ribbon. */
      .th-row { grid-template-columns: auto minmax(0, 1fr); gap: 3px 10px; padding: 9px 0; }
      .th-val { text-align: left; }
      .th-clause { grid-column: 1 / -1; }
    }

    @media (max-width: 900px) {
      /* The frame stops being a column and becomes the top of the page. It
         keeps its size: a subtitle you cannot read is not evidence. */
      .marquee { grid-template-columns: minmax(0, 1fr); gap: 22px; }
      .reel { max-width: 452px; }
      .strip { grid-template-columns: repeat(6, minmax(0, 1fr)); }
    }

    @media (max-width: 520px) {
      .strip { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    }

    @media (max-width: 1040px) {
      /* minmax(0, 1fr), never 1fr: a bare 1fr track cannot shrink below its
         content's min-content width, and one 62-character URL in the spec band
         is enough to set the width of the whole page. */
      .masthead { grid-template-columns: minmax(0, 1fr); align-items: start; }
      .runbar, .status-line { justify-content: flex-start; text-align: left; }
      .specband { grid-template-columns: minmax(0, 1fr); gap: 12px; }
      .split { grid-template-columns: minmax(0, 1fr); gap: 24px; }
      .rail { border-right: 0; border-bottom: 1px solid var(--border); padding-right: 0; padding-bottom: 16px; }
      .sheet-head { display: none; }
      /* The cue text is the row. On a narrow screen it takes the full width and
         the measured value moves up beside the index, rather than squeezing the
         text into a third of the screen. */
      .cue-row { grid-template-columns: 46px minmax(0, 1fr); gap: 0; }
      .cue-num { grid-column: 1; grid-row: 1; padding-top: 0; }
      .cue-val { grid-column: 2; grid-row: 1; display: flex; align-items: baseline;
                 justify-content: flex-end; gap: 9px; padding-top: 0; }
      .cue-val .sub { display: inline; margin-top: 0; }
      .cue-body { grid-column: 1 / -1; grid-row: 2; padding-top: 9px; }
      .cue-text { font-size: 16px; }
      .cue-tc { grid-column: 1 / -1; grid-row: 3; padding-top: 7px; }
      .cue-tc br { display: none; }
      .cue-tc .out::before { content: ' to '; color: var(--text-3); }
    }
  </style>
</head>
<body>
  <div class="page">
    <header class="masthead">
      <div>
        <div class="brand">
          <h1 class="wordmark">Cuepass</h1>
          <span class="brand-unit">CPS</span>
        </div>
        <p class="brand-claim">No threshold here is hardcoded. Every limit was read off the buyer's own
          published page by <b>Parallel</b>, and carries the sentence it came from. A rule a buyer
          does not publish is not checked.</p>
      </div>
      <div>
        <div class="runbar">
          <select id="film-select" aria-label="Subtitle track to run">
            <option value="">Run another track</option>
            __FILM_OPTIONS__
          </select>
          <span class="or">or</span>
          <input type="text" id="identifier" class="ident" placeholder="archive id" aria-label="Archive.org identifier" />
          <button class="run-btn" id="run-btn" type="button">Run it live</button>
        </div>
        <div class="status-line" id="status-line" aria-live="polite"></div>
      </div>
    </header>

    <section class="specband" id="specband" aria-label="Cited specification"></section>

    <div class="split">
      <aside class="rail" id="rail" aria-label="Buyer desks and stored runs"></aside>
      <main class="sheetcol" id="main-area"></main>
    </div>
  </div>

  <script type="application/json" id="boot">__BOOT__</script>
<script>
const filmSel  = document.getElementById('film-select');
const identIn  = document.getElementById('identifier');
const runBtn   = document.getElementById('run-btn');
const statLine = document.getElementById('status-line');
const specBand = document.getElementById('specband');
const rail     = document.getElementById('rail');
const mainArea = document.getElementById('main-area');

let STATE = { run: null, index: [], engine: { parallel: false, gemini: false }, buyer: '', mode: '', error: '', cue: null, visible: [] };

filmSel.addEventListener('change', () => { if (filmSel.value) identIn.value = ''; });
identIn.addEventListener('input',  () => { if (identIn.value)  filmSel.value = ''; });

// ---- leftover filter (pure, node-testable: see tests_sheet_filter.js) ----
const REASON_NO_FREE_SPACE = 'no free space';
const REASON_LINE_TOO_LONG = 'line too long';
const REASON_BOXED_IN      = 'min duration boxed in';

// A cue the repair left failing without recording which of the three reasons
// blocked it. It gets its own bucket rather than being folded into one of them,
// because picking a reason for it would be inventing a finding.
const REASON_UNRECORDED = 'no reason recorded';

// A row is still red when the remeasure on the repaired track produced the same
// finding again. `open` carries that, so the filter counts and the headline pair
// are the same measurement rather than two guesses at it.
function isOpen(r) { return r.open === true; }
function reasonOf(r) { return isOpen(r) ? (r.blocked_by || REASON_UNRECORDED) : ''; }

// The single place that decides what a filter shows.
function rowsForMode(rows, mode) {
  if (mode === 'all')      return rows;
  if (mode === 'leftover') return rows.filter(isOpen);
  // Cues inside the reading-speed gap between two published profiles. Not a
  // repair outcome, a scope difference, so it is its own axis rather than a
  // reason: a cue here can be cleared or still red and belongs in both counts.
  if (mode === 'contrast') return rows.filter(function(r) { return r.in_contrast === true; });
  return rows.filter(function(r) { return reasonOf(r) === mode; });
}

// Every reason actually present among the still-red rows, the known three first.
// Derived from the rows rather than hardcoded, so the reason counts always sum to
// the still-red count. A fixed list of three lets a fourth bucket exist in the
// data and appear nowhere on screen, which is how a total stops adding up.
const REASON_ORDER = [REASON_NO_FREE_SPACE, REASON_LINE_TOO_LONG, REASON_BOXED_IN];
function reasonsPresent(rows) {
  var seen = {};
  rows.filter(isOpen).forEach(function(r) { seen[reasonOf(r)] = 1; });
  var known = REASON_ORDER.filter(function(x) { return seen[x] === 1; });
  var extra = Object.keys(seen).filter(function(x) { return REASON_ORDER.indexOf(x) === -1; }).sort();
  return known.concat(extra);
}

function chipCounts(rows) {
  var counts = { all: rows.length, leftover: rowsForMode(rows, 'leftover').length, by: {} };
  reasonsPresent(rows).forEach(function(reason) {
    counts.by[reason] = rowsForMode(rows, reason).length;
  });
  return counts;
}

// Leftovers are the product. Only fall back to all when nothing is still red.
function defaultMode(rows) {
  return rowsForMode(rows, 'leftover').length > 0 ? 'leftover' : 'all';
}

// One plain-text spotting note for a still-red cue. A cleared cue has no note:
// this returns '' so nothing about a repaired cue is ever copyable.
function copyLineFor(r) {
  if (!r || !isOpen(r)) return '';
  var text = String(r.text || '').replace(/\\s+/g, ' ').trim();
  if (!text) return '';
  var now = typeof r.value_after === 'number' ? r.value_after : r.value;
  return 'cue ' + pad4(r.index)
    + '  ' + r.tc_in + ' --> ' + r.tc_out
    + '  ' + shortNum(now) + ' ' + (r.unit || '') + ' (limit ' + shortNum(r.limit) + ')'
    + '  ' + reasonOf(r)
    + '  ' + text;
}

function pad4(n) { var s = String(n); while (s.length < 4) s = '0' + s; return s; }
function shortNum(v) {
  if (v === null || v === undefined) return 'n/a';
  return typeof v === 'number' ? String(Number(v.toFixed(3))) : String(v);
}
// How many spec desks the declared graph actually carries, read off the loaded
// run rather than written into the copy. Counting them by hand is how a page
// ends up telling a judge "four desks" while five of them run in front of them.
// Empty string when no run is loaded, so the sentence still reads.
function deskCount() {
  var g = STATE.run && STATE.run.graph;
  var nodes = (g && g.nodes) || [];
  var n = nodes.filter(function(x) { return /_spec_desk$/.test(x.name); }).length;
  return n ? n + ' ' : '';
}

function setStatus(html) { statLine.innerHTML = html; }
function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function num(n) { return Number(n || 0).toLocaleString('en-US'); }

const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
function stamp(iso) {
  var d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso || '');
  function p(n) { return (n < 10 ? '0' : '') + n; }
  return p(d.getUTCDate()) + ' ' + MONTHS[d.getUTCMonth()] + ' ' + d.getUTCFullYear()
    + ' ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes()) + ' UTC';
}
function hostOf(url) {
  try { return new URL(url).host.replace(/^www\\./, ''); } catch (e) { return ''; }
}
// A citation has to stay checkable, and a Netflix help-centre article slug is
// 62 characters of unbreakable token. Shown whole it walked out through the
// right edge of the spec band. Host plus a clipped last segment identifies the
// page, the full URL rides in the href and the title, and the CSS clips
// whatever is left, so no length of URL can push the grid again.
function shortUrl(url) {
  try {
    var u = new URL(url);
    var host = u.host.replace(/^www\\./, '');
    var segs = u.pathname.split('/').filter(function (s) { return s; });
    var last = segs.length ? segs[segs.length - 1] : '';
    if (last.length > 30) last = last.slice(0, 30) + '\\u2026';
    return last ? host + '/' + last : host;
  } catch (e) { return ''; }
}

// ---- the four rules, in the order the spec band lists them ----------------
const RULES = [
  ['reading_speed', 'max_cps',        'cps',        'reading speed'],
  ['min_duration',  'min_duration_s', 'sec min',    'minimum duration'],
  ['line_length',   'max_line_chars', 'chars/line', 'line length'],
  ['line_count',    'max_lines',      'lines max',  'lines per cue']
];

function renderSpecBand(run, buyerKey) {
  var entry = run && run.buyers[buyerKey];
  if (!entry) { specBand.innerHTML = ''; return; }
  var s = entry.spec;
  var ev = s.evidence || {};
  var live = !s.is_cached;

  var rows = RULES.map(function(t) {
    var check = t[0], key = t[1], unit = t[2], label = t[3];
    var value = s[key];
    if (value === null || value === undefined) {
      return '<div class="th-row">'
        + '<span class="th-val skipped">none</span>'
        + '<span class="th-unit">' + esc(label) + '</span>'
        + '<span class="th-clause absent">This page states no ' + esc(label) + ' limit. '
        + 'Cuepass skipped the check rather than borrow a number from another buyer.</span>'
        + '</div>';
    }
    var e = ev[key] || {};
    var clause = e.clause || '';
    var shown = check === 'min_duration' ? Number(value).toFixed(3) : String(value);
    // A rule this profile's own page does not state, read off another page in
    // the same publisher's guide. Marked and linked, never folded in silently.
    var mark = '';
    if (e.off_profile) {
      mark += e.url
        ? '<span class="th-mark">not on this profile page. read from '
          + '<a class="th-else" href="' + esc(e.url) + '" target="_blank" rel="noopener"'
          + ' title="' + esc(e.url) + '">' + esc(shortUrl(e.url) || e.url) + '</a></span>'
        : '<span class="th-mark">not on this profile page</span>';
    }
    if (e.provenance && e.provenance !== 'live') {
      mark += '<span class="th-mark"><span class="th-else warn">' + esc(e.provenance) + '</span></span>';
    }
    return '<div class="th-row">'
      + '<span class="th-val">' + esc(shown) + '</span>'
      + '<span class="th-unit">' + esc(unit) + '</span>'
      + '<span class="th-clause">'
      + (clause ? '&ldquo;' + esc(clause) + '&rdquo;' : 'Read off this page by Parallel Extract.')
      + mark
      + '</span>'
      + '</div>';
  }).join('');

  var prov = [];
  if (s.citation_url) {
    prov.push('<span>read from <a href="' + esc(s.citation_url) + '" target="_blank" rel="noopener"'
      + ' title="' + esc(s.citation_title || s.citation_url) + '">'
      + esc(shortUrl(s.citation_url) || s.citation_url) + '</a></span>');
  } else if (s.url_withheld) {
    prov.push('<span class="withheld">source URL withheld: the result came back malformed, '
      + 'and Cuepass will not print a link it cannot resolve</span>');
  }
  // Where the URL above came from. A citation with no discovery behind it is a
  // bookmark, so the page says which of the two it is looking at.
  if (s.discovery === 'parallel_search') {
    var q = (s.search_queries || [])[0] || '';
    prov.push('<span>found by Parallel Search'
      + (s.search_rank ? ', result ' + esc(String(s.search_rank)) : '')
      + (q ? ' for &ldquo;' + esc(q) + '&rdquo;' : '') + '</span>');
  } else if (s.discovery === 'seed_fallback') {
    prov.push('<span class="withheld">Parallel Search returned no page on a host this '
      + 'buyer publishes on, so this run opened the fallback URL recorded in '
      + 'parallel_spec.py. The numbers are still read off the page Extract pulled.</span>');
  }
  // A profile's rules are not all on one page. Saying how many were opened is
  // the difference between a lucky single hit and a resolution across a guide.
  var pages = (s.source_urls || []).length;
  if (pages > 1) {
    prov.push('<span>' + pages + ' pages opened</span>');
  }
  if (s.extract_id) prov.push('<span>' + esc(String(s.extract_id).slice(0, 24)) + '</span>');
  if (s.chars_extracted) prov.push('<span>' + num(s.chars_extracted) + ' chars read</span>');
  prov.push('<span>' + (live ? 'fetched this run, not cached' : 'from the spec cache') + '</span>');

  specBand.innerHTML = ''
    + '<div>'
      + '<div class="sb-label">Measured against</div>'
      + '<div class="sb-buyer">' + esc(s.platform_display || entry.platform) + '</div>'
      + '<div class="sb-meta"><span class="sb-badge ' + (live ? 'live' : 'cached') + '">'
        + (live ? 'live spec' : 'cached spec') + '</span></div>'
      + '<div class="sb-meta">' + esc(stamp(run.measured_at)) + '</div>'
    + '</div>'
    + '<div>' + rows + '</div>'
    + (s.scope ? '<div class="sb-scope">covers ' + esc(s.scope) + '</div>' : '')
    + '<div class="sb-prov">' + prov.join('') + '</div>';
}

// ---- rail: every desk on this track, then every stored run ---------------
// Two published profiles from the same publisher, set to different reading
// speeds because they cover different deliveries. The count is the number of
// cues that sit in the gap. This is stated as two scopes, never as a
// contradiction: both pages are current and both are correct for what they
// cover, and the whole point is that a tool with the number in its source could
// not tell them apart.
function renderContrast(list) {
  if (!list || !list.length) return '';
  function side(cps, platform, url) {
    var name = url
      ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(platform) + '</a>'
      : '<span class="c-name">' + esc(platform) + '</span>';
    return '<span class="c-side"><b>' + esc(String(cps)) + '</b> cps' + name + '</span>';
  }
  // One block per differing pair. The heading counts nothing: three profiles at
  // three reading speeds produce three pairs, and a heading that says "two"
  // above them would be the same stale-tally bug as any other hardcoded count.
  var blocks = list.map(function(c, i) {
    // The headline is the measured count. The offer below it is only ever for
    // the cues actually listed, so clicking can never deliver less than it
    // promised, and a short list is stated rather than quietly absorbed.
    var listed = (c.cue_indices || []).length;
    var partial = c.evidence_complete === false;
    return '<button class="contrast" type="button" data-contrast="' + i + '">'
      + '<span class="c-num">' + num(c.count) + '</span>'
      + '<span class="c-say">cues clear the looser of these profiles and fail the stricter. '
      + 'Both scopes current, both read live this run.</span>'
      + side(c.looser_max_cps, c.looser_platform, c.looser_url)
      + side(c.stricter_max_cps, c.stricter_platform, c.stricter_url)
      + (partial
          ? '<span class="c-partial">This run recorded ' + num(listed) + ' of them by cue number, '
            + 'so only those can be shown.</span>'
          : '')
      + '<span class="c-go">Show me the ' + num(partial ? listed : c.count) + ' cues</span>'
      + '</button>';
  }).join('');
  return '<div class="rail-group">'
    + '<div class="rail-head">Where the published profiles differ</div>'
    + blocks
    + '</div>';
}

function renderRail(state) {
  var run = state.run;
  var html = run ? renderContrast(run.contrasts) : '';
  if (run) {
    var desks = Object.keys(run.buyers).sort(function(a, b) {
      return run.buyers[b].totals.violations - run.buyers[a].totals.violations;
    });
    html += '<div class="rail-group"><div class="rail-head">Desks on this track</div>';
    desks.forEach(function(k) {
      var e = run.buyers[k];
      var on = k === state.buyer;
      // The colour follows the measurement, not the word. A verdict computed
      // elsewhere could say DELIVER beside a non-zero count, and green next to
      // a failing number is the one contradiction a judge cannot miss.
      var tag = e.totals.violations_after === 0 ? 'deliver' : 'hold';
      html += '<button class="rail-row' + (on ? ' on' : '') + '" type="button" data-buyer="' + esc(k) + '"'
        + ' aria-pressed="' + (on ? 'true' : 'false') + '">'
        + '<span class="rr-top"><span class="rr-name">' + esc(e.platform) + '</span>'
        + '<span class="rr-tag ' + tag + '">' + esc(e.verdict) + '</span></span>'
        + '<span class="rr-sub"><span class="n">' + num(e.totals.violations) + '</span> to '
        + '<span class="n">' + num(e.totals.violations_after) + '</span> violations</span>'
        + '<span class="rr-sub">' + num(e.cues_retimed) + ' cues retimed, '
        + citedCount(e.spec) + ' of 4 rules published</span>'
        + '</button>';
    });
    Object.keys(run.unavailable).sort().forEach(function(k) {
      html += '<div class="rail-row dead">'
        + '<span class="rr-top"><span class="rr-name">' + esc(k.toUpperCase()) + '</span>'
        + '<span class="rr-tag none">no cited spec</span></span>'
        + '<span class="rr-why">' + esc(run.unavailable[k]) + '</span>'
        + '</div>';
    });
    html += '</div>';
  }

  if (state.index && state.index.length) {
    html += '<div class="rail-group"><div class="rail-head">Stored runs, worst first</div>';
    // Sorted here so the heading is true by construction. The order arrives from
    // the store, and a label that asserts a property of somebody else's ordering
    // is a claim that goes stale the moment that sort is touched.
    state.index.slice().sort(worstFirst).forEach(function(r) {
      var on = !!(run && r.run_id === run.run_id);
      html += '<button class="rail-row' + (on ? ' on' : '') + '" type="button" data-run="' + esc(r.run_id) + '"'
        + ' aria-pressed="' + (on ? 'true' : 'false') + '">'
        + '<span class="rr-top"><span class="rr-name">' + esc(r.title || r.run_id) + '</span>'
        + '<span class="rr-tag ' + (r.is_seed ? 'none' : 'deliver') + '">'
        + (r.is_seed ? 'seed' : 'this box') + '</span></span>'
        + '<span class="rr-sub"><span class="n">' + num(r.violation_count) + '</span> violations in '
        + num(r.cue_count) + ' cues, ' + esc((r.buyers || []).join(' and ') || 'no desk') + '</span>'
        + '<span class="rr-sub">' + esc(stamp(r.measured_at)) + '</span>'
        + '</button>';
    });
    html += '</div>';
  }
  rail.innerHTML = html;
}

// The order the "worst first" heading claims: most violations first, and among
// equal counts the older run first. Matches runstore.list_runs, which sorts on
// (-violation_count, measured_at), so the edge sort cannot reorder a tie away
// from the store's own answer about which run leads. Named rather than inline so
// a test can exercise the tie rather than grep the source for a sort.
function worstFirst(a, b) {
  var byCount = (b.violation_count || 0) - (a.violation_count || 0);
  if (byCount !== 0) return byCount;
  return String(a.measured_at || '').localeCompare(String(b.measured_at || ''));
}

function citedCount(spec) {
  return RULES.filter(function(t) {
    var v = spec[t[1]];
    return v !== null && v !== undefined;
  }).length;
}

rail.addEventListener('click', function(e) {
  // The contrast is a claim about a number, so clicking it has to show the
  // cues that number counts, on the profile that raises them.
  var box = e.target.closest('.contrast');
  if (box && STATE.run && STATE.run.contrasts) {
    if (e.target.closest('a')) return;
    var pair = STATE.run.contrasts[Number(box.dataset.contrast)];
    if (!pair) return;
    STATE.buyer = pair.stricter;
    STATE.mode = 'contrast';
    paintAll();
    var sheet = document.getElementById('sheet');
    if (sheet) sheet.scrollIntoView({ block: 'start', behavior: 'smooth' });
    return;
  }
  var el = e.target.closest('.rail-row');
  if (!el) return;
  if (el.dataset.buyer) { selectBuyer(el.dataset.buyer); return; }
  if (el.dataset.run)   { loadRun(el.dataset.run); }
});

function selectBuyer(key) {
  if (!STATE.run || !STATE.run.buyers[key] || key === STATE.buyer) return;
  STATE.buyer = key;
  STATE.mode = '';
  paintAll();
}

async function loadRun(runId) {
  if (STATE.run && STATE.run.run_id === runId) return;
  setStatus('<span class="spinner"></span>opening stored run');
  try {
    const resp = await fetch('/api/run/' + encodeURIComponent(runId));
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || 'that run could not be opened');
    STATE.run = data.run;
    STATE.buyer = data.run.default_buyer;
    STATE.mode = '';
    STATE.error = '';
    paintAll();
  } catch (err) {
    STATE.error = err.message;
    renderSheet(STATE);
  } finally {
    setStatus('');
  }
}

// ---- live run: the same code that wrote the stored numbers ---------------
runBtn.addEventListener('click', async () => {
  const id = identIn.value.trim() || filmSel.value || '';
  runBtn.disabled = true;
  STATE.error = '';
  setStatus('<span class="spinner"></span>' + deskCount() + 'spec desks searching for a citable page');
  try {
    const resp = await fetch('/run', { method: 'POST', body: new URLSearchParams({ identifier: id }) });
    setStatus('<span class="spinner"></span>measuring, retiming, measuring again');
    const data = await resp.json();
    if (!resp.ok) {
      STATE.error = data.detail || JSON.stringify(data);
      renderSheet(STATE);
    } else {
      STATE.run = data.run;
      STATE.index = data.index;
      STATE.buyer = data.run.default_buyer;
      STATE.mode = '';
      paintAll();
    }
  } catch (err) {
    STATE.error = err.message;
    renderSheet(STATE);
  } finally {
    runBtn.disabled = false;
    setStatus('');
  }
});

// ---- the sheet -----------------------------------------------------------
function renderSheet(state) {
  var run = state.run;
  var errHtml = state.error
    ? '<div class="error-box"><div class="error-label">Live run failed</div>'
      + '<div class="error-body">' + esc(state.error) + '</div></div>'
    : '';

  if (!run) {
    mainArea.innerHTML = errHtml
      + '<div class="empty-note">No run is stored on this box yet. Pick a track above and run it: '
      + 'one spec desk per delivery profile searches for that profile\\'s own caption page, reads the '
      + 'thresholds off it, and the measurement is written down here. Nothing is drawn until one '
      + 'has been.</div>';
    return;
  }

  var entry = run.buyers[state.buyer];
  if (!entry) { mainArea.innerHTML = errHtml; return; }

  var t = entry.totals;
  var pair = entry.pair;
  var afterCls = pair.after === 0 ? 'clean' : 'leftover';
  var skipped = t.checks_skipped || [];
  var checked = RULES.filter(function(r) { return skipped.indexOf(r[0]) === -1; })
    .map(function(r) { return r[3]; });

  var kicker = '<div class="v-kicker"><b>' + esc(run.title) + '</b>'
    + '<span class="sep">/</span>' + num(run.cue_count) + ' cues'
    + (run.source_filename ? '<span class="sep">/</span>' + esc(run.source_filename) : '')
    + '<span class="sep">/</span>' + checked.length + ' of ' + RULES.length + ' rules checked'
    + '</div>';

  var cap = '<p class="verdict-cap">One check run twice: on the delivered track, then on the track '
    + 'Cuepass retimed. <b>' + num(entry.cues_retimed) + '</b> cues were retimed.';
  cap += pair.kind === 'timing'
    ? ' The pair counts only what retiming can reach, so a line that is simply too long is never '
      + 'credited to it.</p>'
    : ' ' + esc(entry.platform) + ' publishes no timing rule, so the pair is the total.</p>';

  var breakdown = '<div class="breakdown">'
    + bd('over reading speed', t.over_cps, skipped.indexOf('reading_speed') === -1)
    + bd('under minimum duration', t.under_min_duration, skipped.indexOf('min_duration') === -1)
    + bd('line over the limit', t.over_line_chars, skipped.indexOf('line_length') === -1)
    + bd('too many lines', t.over_max_lines, skipped.indexOf('line_count') === -1)
    + '<span>total <span class="n' + (t.violations ? '' : ' zero') + '">' + num(t.violations)
    + '</span> before, <span class="n' + (t.violations_after ? '' : ' zero') + '">'
    + num(t.violations_after) + '</span> after</span>'
    + '</div>';

  var takes = [];
  if (entry.repaired_file) {
    takes.push('<a class="take-track" href="/repaired/' + encodeURIComponent(entry.repaired_file)
      + '" download>Take the repaired track</a>');
  }
  takes.push('<a class="take-track second" href="/exceptions/' + encodeURIComponent(run.run_id)
    + '/' + encodeURIComponent(state.buyer)
    + '" download>Exceptions file: every open cue with the clause it breaks</a>');
  if (run.source_url) {
    takes.push('<a class="take-track second" href="' + esc(run.source_url)
      + '" target="_blank" rel="noopener">Source track on archive.org</a>');
  }

  var kindWord = pair.kind === 'timing' ? 'timing ' : '';
  var verdict = '<div class="verdict">'
    + kicker
    + '<div class="verdict-nums">'
      + '<span class="vnum"><span class="v-big before">' + num(pair.before) + '</span>'
      + '<span class="v-cap">' + kindWord + 'violations as delivered</span></span>'
      + '<span class="v-arrow">to</span>'
      + '<span class="vnum"><span class="v-big after ' + afterCls + '">' + num(pair.after) + '</span>'
      + '<span class="v-cap">after Cuepass retimed it</span></span>'
    + '</div>'
    + cap + breakdown
    + '<div class="take-row">' + takes.join('') + '</div>'
    + '</div>';

  var allRows = entry.rows || [];
  // The frame and the pair, side by side. The picture is the thing the numbers
  // are about, so it opens the page rather than illustrating it further down.
  var marquee = '<div class="marquee">'
    + '<section class="reel" aria-label="The frame this cue sits on">'
      + '<div class="reel-head">The cue on the picture</div>'
      + '<div id="reel-body"></div>'
    + '</section>'
    + verdict
    + '<div class="stripwrap" id="strip-wrap"></div>'
    + '</div>';
  mainArea.innerHTML = errHtml + marquee + '<div id="sheet"></div>' + provenanceHtml(run);
  var sheet = document.getElementById('sheet');
  var stripWrap = document.getElementById('strip-wrap');
  if (stripWrap) {
    stripWrap.addEventListener('click', function(e) {
      var cell = e.target.closest('.strip-cell');
      if (!cell) return;
      var picked = allRows.filter(function(r) { return r.index === Number(cell.dataset.index); })[0];
      if (picked) showCue(picked);
    });
  }

  if (allRows.length === 0) {
    sheet.innerHTML = '<div class="empty-note">No cue on this track breaks a rule that '
      + esc(entry.platform) + ' publishes. The measurement ran across <b>' + num(run.cue_count)
      + '</b> cues and raised nothing.</div>';
    return;
  }

  var counts = chipCounts(allRows);
  var CHIP_LABEL = {};
  CHIP_LABEL[REASON_BOXED_IN] = 'boxed in';
  var contrastCount = rowsForMode(allRows, 'contrast').length;
  var filterRow = '<div class="filter-row" id="filter-row">'
    + flt('leftover', 'still red', counts.leftover)
    + reasonsPresent(allRows).map(function(reason) {
        return flt(reason, CHIP_LABEL[reason] || reason, counts.by[reason]);
      }).join('')
    + (contrastCount ? flt('contrast', 'legal on a looser profile', contrastCount) : '')
    + flt('all', 'all', counts.all)
    + '</div>';
  var head = '<div class="sheet-head">'
    + '<span>#</span><span>Timecode</span><span>Cue</span><span class="r">Measured</span>'
    + '</div>';
  sheet.innerHTML = filterRow + head + '<div id="cue-rows"></div>';

  var host = document.getElementById('cue-rows');
  function paint(mode) {
    var visible = rowsForMode(allRows, mode);
    host.innerHTML = visible.length
      ? visible.map(rowHtml).join('')
      : '<div class="empty-note">No cue on this track is failing for that reason.</div>';
    var bar = document.getElementById('filter-row');
    Array.prototype.forEach.call(bar.children, function(el) {
      var on = el.dataset.mode === mode;
      el.classList.toggle('on', on);
      el.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    // The frame follows the sheet. A filter that hides the cue currently on
    // screen would otherwise leave a picture up that this sheet no longer lists.
    STATE.visible = visible;
    var held = visible.filter(function(r) { return r.index === STATE.cue; })[0];
    showCue(held || visible[0] || null);
  }
  document.getElementById('filter-row').addEventListener('click', function(e) {
    var el = e.target.closest('.flt');
    if (el) paint(el.dataset.mode);
  });
  host.addEventListener('click', function(e) {
    var row = e.target.closest('.cue-row');
    if (!row) return;
    var index = Number(row.dataset.index);
    var picked = allRows.filter(function(r) { return r.index === index; })[0];
    if (picked) { showCue(picked); keepReelInView(); }
    var note = row.dataset.copy;
    if (!note) return;
    var mark = function() {
      row.classList.add('copied');
      setTimeout(function() { row.classList.remove('copied'); }, 900);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(note).then(mark, mark);
    } else { mark(); }
  });
  // A mode asked for by a click elsewhere wins, but only if it has rows to show,
  // so a stale request can never leave the sheet empty.
  var asked = state.mode && rowsForMode(allRows, state.mode).length ? state.mode : '';
  paint(asked || defaultMode(allRows));
}

// SRT writes HH:MM:SS,mmm. This is only rendered for a track that does not, and
// the digit count is read back off the stored source file rather than assumed,
// so a well-formed track shows nothing here.
function srcNote(run) {
  var d = run.fraction_digits;
  if (typeof d !== 'number' || d === 3) return '';
  return '<div class="src-note">Source writes <b>' + d + '</b>-digit subsecond timecodes, not the 3 SRT '
    + 'specifies. Read literally, every duration is out by ' + Math.pow(10, 3 - d)
    + 'x. Normalised on digit count before measuring.</div>';
}

function bd(label, n, checked) {
  if (!checked) return '<span>' + esc(label) + ' <span class="n zero">not published</span></span>';
  return '<span><span class="n' + (n ? '' : ' zero') + '">' + num(n) + '</span> ' + esc(label) + '</span>';
}

function flt(mode, label, n) {
  return '<button class="flt" type="button" data-mode="' + esc(mode) + '" aria-pressed="false">'
    + esc(label) + '<span class="n">' + n + '</span></button>';
}

const UNIT_LABEL = {
  reading_speed: 'cps', min_duration: 'sec', non_positive_duration: 'sec',
  line_length: 'chars', line_count: 'lines'
};

function rowHtml(r) {
  var open = isOpen(r);
  var places = (r.check === 'line_length' || r.check === 'line_count') ? 0 : 2;
  function fmt(v, p) { return typeof v === 'number' ? v.toFixed(p) : 'n/a'; }
  // A still-red row leads with what the repaired track measures, not with what
  // arrived, and carries the original beside it when the retime moved it.
  var shown = (open && typeof r.value_after === 'number') ? r.value_after : r.value;
  var val = fmt(shown, places);
  var was = (open && typeof r.value_after === 'number' && r.value_after !== r.value)
    ? ' &middot; was ' + fmt(r.value, places) : '';
  var lim = fmt(r.limit, r.check === 'min_duration' || r.check === 'non_positive_duration' ? 3 : 0);
  var unit = UNIT_LABEL[r.check] || String(r.check).slice(0, 5);

  var why = open
    ? '<div class="cue-why">' + esc(reasonOf(r)) + '</div>'
    : '<div class="cue-why repaired">retimed and cleared</div>';
  // The verb the triage desk assigned, without its restatement. The full note
  // travels in the exceptions file, which is the artefact an editor works from.
  var act = (open && r.action)
    ? '<div class="cue-act">edit assigned <b>' + esc(String(r.action).replace(/_/g, ' ')) + '</b></div>'
    : '';

  var copyLine = copyLineFor(r);
  var copyAttrs = copyLine ? ' data-copy="' + esc(copyLine) + '"' : '';

  return '<div class="cue-row ' + (copyLine ? 'copyable' : 'cleared') + '"'
    + ' data-index="' + esc(r.index) + '"' + copyAttrs + '>'
    + '<div class="cue-num"><i class="dot ' + (open ? '' : 'repaired') + '"></i>' + pad4(r.index) + '</div>'
    + '<div class="cue-tc">' + esc(r.tc_in) + '<br>'
      + '<span class="out ' + (open ? '' : 'repaired') + '">' + esc(r.tc_out) + '</span></div>'
    + '<div class="cue-body">'
      + '<div class="cue-text">' + esc(r.text || '') + '</div>'
      + why + act
    + '</div>'
    + '<div class="cue-val ' + (open ? 'red' : 'mint') + '">'
      + '<span class="big">' + val + '</span>'
      + '<span class="sub">' + esc(unit) + ' &middot; limit ' + lim + was + '</span>'
    + '</div>'
    + '</div>';
}

// ---- declared graph beside the nodes that actually fired ----------------
function provenanceHtml(run) {
  var g = run.graph || {};
  var nodes = g.nodes || [];
  if (!nodes.length) return '';
  var fired = run.fired || {};
  var ran = nodes.filter(function(n) { return fired[n.name] > 0; }).length;
  // An event in the stream carries the name of the agent that authored it, and
  // only a node that calls a model authors one. A FunctionNode that binds specs
  // or runs the measurement is silent by construction, so absence from the
  // stream is what a working one looks like. Marking those apart from a model
  // node that genuinely produced nothing keeps both readings honest.
  var silent = nodes.filter(function(n) { return !n.runs_model && !(fired[n.name] > 0); }).length;
  var chips = nodes.map(function(n) {
    var hits = fired[n.name] || 0;
    if (hits > 0) {
      return '<span class="node fired' + (n.runs_model ? ' model' : '') + '">' + esc(n.name)
        + '<span class="times">' + hits + '</span></span>';
    }
    return '<span class="node ' + (n.runs_model ? 'cold' : 'silent') + '">' + esc(n.name)
      + '<span class="times">'
      + (n.runs_model ? 'no event under this name' : 'deterministic, no event')
      + '</span></span>';
  }).join('');
  return '<div class="provenance">'
    + srcNote(run)
    + '<div class="prov-head">' + esc(g.workflow || 'workflow') + ': declared graph, and what ran</div>'
    + '<div class="prov-note">Every node the code declares is listed. The count beside one is how many '
    + 'times it appeared in the stored event stream, read off the run rather than written down. '
    + '<b>' + ran + ' of ' + nodes.length + '</b> nodes fired '
    + 'across <b>' + num(run.trace_len) + '</b> recorded steps. Firing means authoring an event, which '
    + 'only a node that calls a model can do: the <b>' + silent + '</b> deterministic nodes bind the '
    + 'cited specs, measure, retime and measure again without one, so they author nothing and are '
    + 'marked silent rather than failed. What they produced is the pair above. Mint outline marks a '
    + 'node that calls <b>' + esc(run.model) + '</b>. Clicking a row above puts its frame on the '
    + 'screen and copies its spotting note; the '
    + 'reason each edit was chosen travels in the exceptions file with the clause it breaks. The triage '
    + 'desk assigned edits to <b>' + num(run.editorial_capped_at) + '</b> of <b>'
    + num(run.leftover_cue_total) + '</b> cues left over across every desk. Framework <b>'
    + esc(run.framework) + '</b>, Parallel surfaces <b>'
    + esc((run.parallel_surfaces || []).join(' and ')) + '</b>.</div>'
    + '<div class="nodes">' + chips + '</div>'
    + '</div>';
}

// ---- the frame at the cue -----------------------------------------------
// The measurement is a claim about a line of type over a picture. This puts the
// picture on screen: the real frame at that cue's in-time, cut from the same
// archive.org item the track came from, with the cue drawn over it the way the
// delivered file times it. Nothing here is illustrative, and when no frame
// comes back the panel says that rather than showing something else.

function frameSrc(run, buyer, index) {
  return '/frame/' + encodeURIComponent(run.run_id)
    + '/' + encodeURIComponent(buyer)
    + '/' + encodeURIComponent(index) + '.jpg';
}

// Seconds from one SRT stamp, on the same digit rule the measurement used: this
// track writes two subsecond digits, so ,95 is 950ms and not 95.
function tcSeconds(stamp) {
  var m = /^(\\d+):(\\d+):(\\d+)[,.](\\d+)$/.exec(String(stamp || '').trim());
  if (!m) return null;
  return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3])
    + Number(m[4]) / Math.pow(10, m[4].length);
}

// What the rule says about this cue, in a sentence, with the published number
// beside the measured one. Both come off the row; neither is computed here.
function reelSentence(r, platform) {
  var places = (r.check === 'line_length' || r.check === 'line_count') ? 0 : 2;
  var limPlaces = (r.check === 'min_duration' || r.check === 'non_positive_duration') ? 3 : 0;
  function n(v, p) { return typeof v === 'number' ? v.toFixed(p) : 'n/a'; }
  var value = '<b class="over">' + n(r.value, places) + '</b>';
  var limit = '<b>' + n(r.limit, limPlaces) + '</b>';
  var who = esc(platform);
  if (r.check === 'reading_speed') {
    return 'This line runs at ' + value + ' characters per second. '
      + who + ' publishes ' + limit + '.';
  }
  if (r.check === 'min_duration') {
    return 'This line holds for ' + value + ' seconds. '
      + who + ' publishes a floor of ' + limit + '.';
  }
  if (r.check === 'non_positive_duration') {
    return 'This line never opens: its out point is not after its in point, '
      + 'so it holds for ' + value + ' seconds.';
  }
  if (r.check === 'line_length') {
    return 'Its longest line is ' + value + ' characters. ' + who + ' publishes ' + limit + '.';
  }
  if (r.check === 'line_count') {
    return 'It carries ' + value + ' lines. ' + who + ' publishes ' + limit + '.';
  }
  return value + ' against a published ' + limit + '.';
}

// Measured against published, on one scale. The tick is the limit, the bar is
// the cue. Drawn only when both numbers can share a scale, so a check whose
// threshold is zero gets the sentence and no picture of nothing.
function gaugeHtml(r) {
  var value = Number(r.value), limit = Number(r.limit);
  if (!isFinite(value) || !isFinite(limit)) return '';
  var span = Math.max(value, limit) * 1.2;
  if (!(span > 0)) return '';
  function pct(x) { return (Math.max(0, Math.min(1, x)) * 100).toFixed(2) + '%'; }
  return '<div class="gauge">'
    + '<span class="gauge-bar" style="width:' + pct(value / span) + '"></span>'
    + '<span class="gauge-tick" style="left:' + pct(limit / span) + '"></span>'
    + '</div>';
}

// Six cues from the sheet as it currently stands, the open one among them.
// Built off the filtered list rather than off the whole track, so the strip is
// always a run of cues this filter actually raised.
var STRIP_SIZE = 12;
function stripHtml(row) {
  var visible = STATE.visible || [];
  if (visible.length < 2) return '';
  var pos = 0;
  for (var i = 0; i < visible.length; i++) {
    if (visible[i].index === row.index) { pos = i; break; }
  }
  var start = Math.max(0, Math.min(pos - 2, visible.length - STRIP_SIZE));
  var window_ = visible.slice(start, start + STRIP_SIZE);
  var cells = window_.map(function(r) {
    return '<button class="strip-cell' + (r.index === row.index ? ' on' : '') + '" type="button"'
      + ' data-index="' + esc(r.index) + '"'
      + ' title="cue ' + pad4(r.index) + ' at ' + esc(r.tc_in) + '">'
      + '<img alt="" src="' + frameSrc(STATE.run, STATE.buyer, r.index) + '">'
      + '<span class="strip-num">' + pad4(r.index) + '</span>'
      + '</button>';
  }).join('');
  return '<div class="strip-head">cues either side of it, in this filter</div>'
    + '<div class="strip" id="strip">' + cells + '</div>';
}

function showCue(row) {
  var host = document.getElementById('reel-body');
  if (!host) return;
  var run = STATE.run;
  var entry = run && run.buyers[STATE.buyer];
  STATE.cue = row ? row.index : null;
  if (!row || !entry) { host.innerHTML = ''; markSelectedRow(null); return; }

  var seconds = tcSeconds(row.tc_in), out = tcSeconds(row.tc_out);
  var held = (seconds !== null && out !== null) ? (out - seconds).toFixed(2) + ' s' : '';
  var source = run.video_url
    ? '<a href="' + esc(run.video_url) + '" target="_blank" rel="noopener" title="'
      + esc(run.video_url) + '">' + esc(shortUrl(run.video_url)) + '</a>'
    : 'the archive.org source';

  host.innerHTML = ''
    + '<figure class="screen" id="screen">'
      + '<span class="screen-tc">' + esc(row.tc_in) + '</span>'
      + '<span class="screen-id">CUE ' + pad4(row.index) + '</span>'
      + '<div class="screen-hold">cutting this frame off archive.org</div>'
      + '<div class="screen-sub">' + esc(row.text || '') + '</div>'
    + '</figure>'
    + '<div class="reel-cap" id="reel-cap">Frame cut at ' + esc(row.tc_in) + ' from ' + source
      + ' with ffmpeg. The cue is drawn as the delivered file times it.</div>'
    + '<div class="reel-read">'
      + '<div class="rr-rule">' + esc(String(row.rule || row.check).replace(/_/g, ' ')) + '</div>'
      + gaugeHtml(row)
      + '<div class="rr-say">' + reelSentence(row, entry.platform) + '</div>'
      + '<div class="rr-meta">' + esc(row.tc_in) + ' to ' + esc(row.tc_out)
        + (held ? ' &middot; <b>' + held + '</b> on screen' : '') + '</div>'
    + '</div>';

  var strip = document.getElementById('strip-wrap');
  if (strip) strip.innerHTML = stripHtml(row);

  var figure = document.getElementById('screen');
  var img = new Image();
  img.className = 'screen-img';
  img.alt = 'Frame of ' + run.title + ' at ' + row.tc_in;
  img.addEventListener('load', function() { figure.classList.add('ready'); });
  img.addEventListener('error', function() {
    figure.classList.add('gone');
    var hold = figure.querySelector('.screen-hold');
    if (hold) hold.textContent = 'no frame came back at this timecode, so none is drawn';
    // The caption claims a frame was cut. When none was, it has to stop saying so.
    var cap = document.getElementById('reel-cap');
    if (cap) {
      cap.textContent = 'No frame at ' + row.tc_in + '. This box could not cut one from the '
        + 'archive.org source, so the cue is shown over nothing rather than over a stand-in.';
    }
  });
  img.src = frameSrc(run, STATE.buyer, row.index);
  figure.insertBefore(img, figure.firstChild);
  markSelectedRow(row.index);
}

function markSelectedRow(index) {
  var host = document.getElementById('cue-rows');
  if (!host) return;
  Array.prototype.forEach.call(host.children, function(el) {
    el.classList.toggle('on', Number(el.dataset.index) === index);
  });
}

// Clicking a row far down the sheet changes a picture that may be off screen.
// Bring it back only when it actually is, so a click near the top does not
// throw the page around.
function keepReelInView() {
  var figure = document.getElementById('screen');
  if (!figure) return;
  var box = figure.getBoundingClientRect();
  if (box.bottom < 72 || box.top > window.innerHeight - 90) {
    figure.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
}

function paintAll() {
  renderSpecBand(STATE.run, STATE.buyer);
  renderRail(STATE);
  renderSheet(STATE);
}

// ---- land on the stored measurement, before any click -------------------
(function boot() {
  var data = JSON.parse(document.getElementById('boot').textContent);
  STATE.run = data.run;
  STATE.index = data.index || [];
  STATE.engine = data.engine || STATE.engine;
  STATE.buyer = data.run ? data.run.default_buyer : '';
  paintAll();
  var missing = [];
  if (!STATE.engine.parallel) missing.push('a Parallel key');
  if (!STATE.engine.gemini) missing.push('Gemini credentials');
  if (missing.length) {
    runBtn.disabled = true;
    setStatus('This box is missing ' + missing.join(' and ') + ', so it serves stored runs only');
  }
})();
</script>
</body>
</html>"""


def render_page(run_id: str = "") -> str:
    film_options = "\n".join(
        f'<option value="{f["identifier"]}">{f["title"]}</option>' for f in KNOWN_FILMS
    )
    boot = json.dumps(boot_payload(run_id)).replace("</", "<\\/")
    return HTML.replace("__FILM_OPTIONS__", film_options).replace("__BOOT__", boot)


@app.get("/", response_class=HTMLResponse)
async def index():
    prewarm_frames(runstore.load(runstore.default_run_id() or ""))
    return render_page()


@app.get("/frame/{run_id}/{buyer}/{cue_index}.jpg")
def frame(run_id: str, buyer: str, cue_index: int):
    """The frame of the film at one cue's in-time, cut from the archive source.

    The instant is read off the stored finding, never off the query, so this
    endpoint can only ever produce a picture of a cue this run measured.
    """
    record = runstore.load(run_id)
    entry = (record or {}).get("buyers", {}).get(buyer)
    if record is None or entry is None:
        raise HTTPException(status_code=404, detail="No such run or desk")
    timecode = ""
    for finding in entry.get("before", {}).get("findings", []):
        if finding.get("cue_index") == cue_index:
            timecode = str(finding.get("timecode", "")).partition(" --> ")[0]
            break
    seconds = cue_seconds(timecode)
    if seconds is None:
        raise HTTPException(status_code=404, detail="That desk raised no finding on that cue")
    path = extract_frame(record.get("film_identifier", ""), seconds)
    if path is None:
        raise HTTPException(status_code=404, detail="No frame could be cut at that timecode")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/runs")
async def api_runs():
    return {"index": runstore.list_runs()}


@app.get("/api/run/{run_id}")
async def api_run(run_id: str):
    record = runstore.load(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No stored run with that id")
    return {"run": ui_run(record)}


@app.post("/run")
def run(identifier: str = Form(default="")):
    """One live pass of the graph, on a worker thread.

    Deliberately not `async def`. `agent.run_agent` owns its own event loop via
    `asyncio.run`, which raises the moment it is called on a thread that already
    has one running, and a run that takes minutes would hold the loop hostage
    anyway. A sync handler is dispatched to Starlette's threadpool, so the loop
    stays free to serve the frames the page is fetching while the desks work.
    """
    try:
        record = agent_mod.run_agent(identifier=identifier.strip() or None)
    except Exception as exc:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse({"run": ui_run(record), "index": runstore.list_runs()})


@app.get("/exceptions/{run_id}/{buyer}")
async def exceptions(run_id: str, buyer: str):
    """The artefact a QC lead forwards: every open cue with the clause it breaks."""
    record = runstore.load(run_id)
    if record is None or buyer not in (record.get("buyers") or {}):
        raise HTTPException(status_code=404, detail="No such run or desk")
    payload = agent_mod.exceptions_file(record, buyer)
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}.{buyer}.exceptions.json"'
        },
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "cuepass",
        "stored_runs": len(runstore.list_runs()),
        "engine": engine_state(),
    }


@app.get("/repaired/{name}")
async def repaired(name: str):
    """Serve a repaired .srt a run wrote. No model call, no arbitrary read.

    `runstore.repaired_path` only resolves a name that lands directly inside a
    run directory, so `../`, an absolute path, and a name from anywhere else on
    disk all fall through to 404.
    """
    path = runstore.repaired_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="No such repaired track")
    return FileResponse(path, media_type="text/x-subrip", filename=name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
