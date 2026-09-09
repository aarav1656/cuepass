"""Caption delivery specs, read off the buyer's own published page at runtime.

Two exceptions, both stated up front and both labelled in every result they
touch:

  * `PINNED_FALLBACKS` at the bottom of this file: a published VALUE, with its
    page and its sentence, filling a rule the pages this run opened did not
    state. Never reading speed. See the comment above it.
  * `SEARCH_FAILURE_FALLBACK_URLS`: a published URL, no value, offered to the
    desk on exactly one condition, that Parallel Search returned no candidate on
    a host the buyer publishes on. See the comment above it.

Two Parallel surfaces, in a chain, both load-bearing:

  1. `client.search(...)`  finds candidate spec pages. Search is allowed to
     return URLs. Search is NOT allowed to produce a number: a snippet that
     says "17 characters per second" could have come from a 2019 blog post.
     Search is where the URL comes from: `extract_spec_page` refuses any URL
     that was not offered by a `search_spec_candidates` call in this same run,
     so neither a constant in this file nor a URL the model remembered can be
     opened, let alone measured against.
  2. `client.extract(urls=[...], session_id=...)`  pulls the actual page and
     returns it as markdown. Every threshold on the live path is read out of
     that extracted page text, and every threshold Cuepass measures against,
     live or pinned, carries the verbatim sentence that states it plus the URL
     that sentence lives on.

The `session_id` returned by Search is passed into Extract, which is how the
Parallel SDK links the two calls as one piece of agent work.

If Extract cannot produce a page that states a reading-speed rule, this module
raises. Reading speed is never pinned. The only rule with a pinned fallback is
the minimum on-screen duration, which neither Netflix profile's own page states:
see `PINNED_FALLBACKS`, where the value carries the buyer page it is published on
and that page's exact sentence, and comes back labelled `fallback` so every
consumer can say so. A number with no clause behind it is never returned, because
Cuepass would then be citing a spec it never read.

No language model is ever asked what a threshold is. The model (see
`cuepass_agents.py`) decides WHICH page is authoritative and when to try
another candidate. `read_page_thresholds` does the reading, in Python, and
records the result in a per-process ledger keyed by URL. The agent can only
accept a URL that is already in that ledger, so a hallucinated number cannot
reach a measurement.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ParallelUnavailableError(Exception):
    """Raised when the Parallel chain cannot produce a cited spec.

    Hard failure, never a downgrade. The Parallel track requires runtime use of
    the Search API, and a tool that silently swapped in hardcoded constants
    would be citing a page it never opened.
    """


# Where each buyer publishes its own spec. Used to rank candidates and to
# reject a third-party summary standing in for the buyer's own page. These are
# hosts, not thresholds: nothing in this dict is ever measured against.
OFFICIAL_HOSTS: dict[str, tuple[str, ...]] = {
    "netflix_en_us": ("partnerhelp.netflixstudios.com", "help.netflix.com", "netflix.com"),
    "netflix_templates": (
        "partnerhelp.netflixstudios.com",
        "help.netflix.com",
        "netflix.com",
    ),
    "amazon": ("videodirect.amazon.com", "amazon.com", "aws.amazon.com"),
    "bbc": ("bbc.co.uk", "bbc.com", "bbc.github.io"),
    "fcc": ("fcc.gov",),
}

PLATFORM_LABELS: dict[str, str] = {
    "netflix_en_us": "Netflix, English (USA)",
    "netflix_templates": "Netflix, Subtitle Templates",
    "amazon": "Amazon Prime Video",
    "bbc": "BBC",
    "fcc": "FCC (US broadcast)",
}

# What each profile is the spec FOR. Shown wherever its number is shown, because
# two Netflix profiles stating different reading speeds is not Netflix
# contradicting itself: they are different scopes, and saying which one applies
# is the difference between a finding and a cheap shot.
PROFILE_SCOPE: dict[str, str] = {
    "netflix_en_us": (
        "Netflix's English (USA) Timed Text Style Guide, the guide an English "
        "language subtitle file for the US catalogue is held to."
    ),
    "netflix_templates": (
        "Netflix's Timed Text Style Guide page on subtitle templates, which is "
        "the guide a template-derived delivery is held to."
    ),
    "amazon": "Amazon Prime Video's published subtitle delivery specification.",
    "bbc": "The BBC's published subtitle guidelines.",
    "fcc": "The FCC's published closed-captioning quality rules for US broadcast.",
}

# SEARCH-FAILURE FALLBACK. Not a seed, not a starting candidate, and not part of
# the normal path.
#
# It fires under exactly one condition, asserted in `search_spec_candidates` and
# reported in that call's result as `seed_fallback_fired`: Parallel Search
# returned zero candidates on any host in `OFFICIAL_HOSTS` for this profile. If
# Search returns even one official-host URL, nothing in this dict is offered to
# the desk, nothing in it can be extracted, and the URL Cuepass cites is a URL
# Search found this run.
#
# When it does fire the candidate is labelled `discovery: "seed_fallback"`, that
# label rides through Extract into the evidence ledger, into the spec, into the
# stored run and onto the page, so a run standing on this dict says so wherever
# its numbers are shown.
#
# No threshold is written down here. Even in the fallback case the page is still
# opened by Parallel Extract and every number still comes off the extracted page
# text with the sentence that states it.
SEARCH_FAILURE_FALLBACK_URLS: dict[str, str] = {
    "netflix_en_us": (
        "https://partnerhelp.netflixstudios.com/hc/en-us/articles/"
        "217350977-English-Timed-Text-Style-Guide"
    ),
    "netflix_templates": (
        "https://partnerhelp.netflixstudios.com/hc/en-us/articles/"
        "219375728-Timed-Text-Style-Guide-Subtitle-Templates"
    ),
}

# Parallel's Search guidance: concise keyword queries, 3-6 words, two or three
# of them, with the intent carried by `objective` rather than by operators.
PLATFORM_QUERIES: dict[str, list[str]] = {
    "netflix_en_us": [
        "Netflix English timed text style guide",
        "Netflix subtitle reading speed limit",
        "Netflix subtitle character limit line",
    ],
    "netflix_templates": [
        "Netflix timed text style guide subtitle templates",
        "Netflix subtitle template reading speed",
        "Netflix subtitle template character limit",
    ],
    "amazon": [
        "Amazon Prime Video subtitle specification",
        "Amazon video direct timed text guide",
        "Prime Video caption reading speed",
    ],
    "bbc": [
        "BBC subtitle guidelines reading speed",
        "BBC subtitle line length guidance",
        "BBC subtitle guidelines characters second",
    ],
    "fcc": [
        "FCC closed captioning quality rules",
        "FCC caption standards accuracy synchronicity",
        "FCC captioning requirements broadcasters",
    ],
}

PLATFORM_OBJECTIVES: dict[str, str] = {
    p: (
        f"Find the page where {PLATFORM_LABELS[p]} publishes its own subtitle or "
        "closed-caption delivery specification, stating the maximum reading speed "
        "in characters per second, the maximum characters per subtitle line, the "
        "maximum number of lines per subtitle, and the minimum duration a "
        "subtitle stays on screen."
    )
    for p in PLATFORM_LABELS
}


# --- deterministic reading of an extracted page --------------------------
#
# Every pattern below captures the number AND enough surrounding text that the
# sentence it came from can be quoted back. A threshold whose sentence cannot
# be located is not returned.

_CPS_PATTERNS = [
    re.compile(
        r"(\d{1,2}(?:\.\d)?)\s*(?:characters?|chars?)\s*(?:per\s*|/\s*|a\s+)second", re.I
    ),
    re.compile(r"(\d{1,2}(?:\.\d)?)\s*cps\b", re.I),
    re.compile(r"reading\s+speed[^.\n]{0,80}?(\d{1,2}(?:\.\d)?)\s*(?:characters?|chars?|cps)", re.I),
]
_LINE_CHARS_PATTERNS = [
    re.compile(r"(\d{2,3})\s*(?:characters?|chars?)\s*(?:per\s*|a\s+|/\s*)?line", re.I),
    re.compile(r"line\s+length[^.\n]{0,60}?(\d{2,3})\s*(?:characters?|chars?)", re.I),
    re.compile(
        r"(?:maximum|max\.?|no more than|up to)[^.\n]{0,30}?(\d{2,3})\s*(?:characters?|chars?)",
        re.I,
    ),
    re.compile(r"(\d{2,3})\s*(?:characters?|chars?)[^.\n]{0,20}?(?:per|a)\s+(?:subtitle\s+)?line", re.I),
]
_MAX_LINES_PATTERNS = [
    re.compile(r"(?:maximum|max\.?|no more than|up to)\s*(?:of\s*)?(\d)\s*lines?\b", re.I),
    re.compile(r"(\d)\s*lines?\s*(?:per\s+(?:subtitle|caption|cue)|maximum|max\b)", re.I),
    re.compile(r"(?:limit(?:ed)?\s+to|restrict(?:ed)?\s+to)\s*(\d)\s*lines?", re.I),
]
# Minimum on-screen duration is published three ways: in seconds, as a vulgar
# fraction of a second ("5/6 of a second", which is how the Netflix guide states
# it), or in frames. All three are read; frames convert at 24fps, the rate the
# repair step already assumes for its one-frame gap.
_MIN_DURATION_FRACTION = re.compile(
    r"(\d)\s*/\s*(\d)\s*(?:of\s+a\s+)?(?:second|sec)\b", re.I
)
# The minimum gap between one subtitle's out-time and the next one's in-time.
# It is published in frames rather than seconds, and it is a delivery rule the
# repair itself has to obey: retiming a cue longer closes the gap in front of
# it, so a repair that ignores this rule hands back a file that fails the page
# it was repaired against.
_MIN_GAP_PATTERNS = [
    re.compile(
        r"minimum\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(frames?|seconds?|ms)\b[^.\n]{0,60}?between",
        re.I,
    ),
    re.compile(
        r"(?:gaps?\s+between|between)[^.\n]{0,60}?minimum\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(frames?|seconds?|ms)\b",
        re.I,
    ),
]
# There is deliberately no looser third pattern. A `(?:gap|space) ... (\d+)
# frames` catch-all matches the sentence right beside the rule on the page
# Cuepass actually cites: "any gaps between subtitles of 3-11 frames inclusive
# must be closed to 2 frames" yields 3, which is inside the band and whose
# clause contains "gap", so it would be accepted and silently measured against.
# Both patterns above require "minimum" adjacent to "between", which is what
# the rule itself says.

_MIN_DURATION_PATTERNS = [
    re.compile(
        r"minimum[^.\n]{0,40}?duration[^.\n]{0,60}?(\d+(?:\.\d+)?)\s*(seconds?|secs?|frames?|ms)",
        re.I,
    ),
    re.compile(
        r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|frames?)[^.\n]{0,30}?minimum\s+duration", re.I
    ),
    re.compile(r"minimum[^.\n]{0,50}?(\d+)\s*(frames?)\b", re.I),
    re.compile(r"(?:on\s*screen|display(?:ed)?)[^.\n]{0,40}?at\s+least\s+(\d+(?:\.\d+)?)\s*(seconds?|frames?)", re.I),
]

# Plausibility bands. A page that yields a number outside its band was misread,
# so the threshold is dropped rather than measured against.
_BANDS = {
    "max_cps": (5.0, 40.0),
    "max_line_chars": (20.0, 100.0),
    "max_lines": (1.0, 6.0),
    "min_duration_s": (0.2, 5.0),
    # Two frames at 24fps is 0.083s. A gap rule wider than a second is not a
    # gap rule, it is a shot-change or a maximum-duration sentence misread.
    "min_gap_s": (0.02, 1.0),
}

# A number is not a rule just because it is the right size. The sentence it was
# read from has to be about the thing being measured. This caught a real
# regression: on the BBC subtitle guide, "Translator's Name |TN |[Up to 32
# characters] |Optional |Jane Doe" is a metadata table row about a name field,
# and it was being accepted as a 32-character line-length limit and measured
# against. A clause that does not mention lines is not a line-length rule.
_CLAUSE_MUST_MENTION = {
    "max_cps": ("second", "cps", "reading speed"),
    "max_line_chars": ("line",),
    "max_lines": ("line",),
    "min_duration_s": ("duration", "frame", "second", "on screen", "on-screen"),
    # The sentence has to be about the space BETWEEN subtitles. "20 frames
    # minimum duration" is the right shape and the wrong rule, and measuring a
    # gap against it would be the BBC "Translator's Name |TN |[Up to 32
    # characters]" mistake again in a different column.
    "min_gap_s": ("between", "gap"),
}

# Words that mean the sentence is about something other than the subtitle text
# itself, however well the numbers fit.
_CLAUSE_MUST_NOT_MENTION = ("translator", "filename", "file name", "email", "url")


def _clause_is_about(name: str, clause: str) -> bool:
    lowered = clause.lower()
    if any(bad in lowered for bad in _CLAUSE_MUST_NOT_MENTION):
        return False
    required = _CLAUSE_MUST_MENTION.get(name, ())
    return any(word in lowered for word in required)


def _sentence_around(text: str, match_start: int, match_end: int) -> str:
    """The sentence a match sits in, trimmed for display in a citation."""
    left = max(
        text.rfind(". ", 0, match_start),
        text.rfind("\n", 0, match_start),
        text.rfind("| ", 0, match_start),
    )
    start = 0 if left < 0 else left + 1
    right_candidates = [
        i for i in (text.find(". ", match_end), text.find("\n", match_end)) if i != -1
    ]
    end = min(right_candidates) + 1 if right_candidates else min(len(text), match_end + 160)
    clause = " ".join(text[start:end].split())
    clause = clause.strip(" |*#-")
    if len(clause) > 240:
        # Keep the number visible when a table row is long.
        rel = match_start - start
        lo = max(0, rel - 110)
        clause = clause[lo : lo + 240].strip()
    return clause


def _first_hit(text: str, patterns: list[re.Pattern], name: str) -> tuple[float, str] | None:
    """The first match on this page whose sentence is actually about `name`.

    Every match of every pattern is considered, not just the first, because the
    first number of the right shape on a long page is often in an unrelated
    table. A match is only taken when its own sentence passes the topic check.
    """
    for pat in patterns:
        for m in pat.finditer(text):
            clause = _sentence_around(text, m.start(), m.end())
            if _clause_is_about(name, clause):
                return float(m.group(1)), clause
    return None


def _read_min_duration(text: str) -> tuple[float, str] | None:
    """Minimum on-screen duration, normalised to seconds."""
    for m in _MIN_DURATION_FRACTION.finditer(text):
        numerator, denominator = float(m.group(1)), float(m.group(2))
        clause = _sentence_around(text, m.start(), m.end())
        if denominator > 0 and _clause_is_about("min_duration_s", clause):
            return numerator / denominator, clause
    for pat in _MIN_DURATION_PATTERNS:
        for m in pat.finditer(text):
            clause = _sentence_around(text, m.start(), m.end())
            if not _clause_is_about("min_duration_s", clause):
                continue
            value = float(m.group(1))
            unit = (m.group(2) if m.lastindex and m.lastindex >= 2 else "seconds").lower()
            if unit.startswith("frame"):
                value = value / 24.0
            elif unit == "ms":
                value = value / 1000.0
            return value, clause
    return None


def _read_min_gap(text: str) -> tuple[float, str] | None:
    """Minimum gap between consecutive subtitles, normalised to seconds.

    Published in frames on every guide that publishes it at all, so frames are
    the common case. 24fps, the rate the rest of this module already converts
    at and the rate the guides are written for.
    """
    for pat in _MIN_GAP_PATTERNS:
        for m in pat.finditer(text):
            clause = _sentence_around(text, m.start(), m.end())
            if not _clause_is_about("min_gap_s", clause):
                continue
            value = float(m.group(1))
            unit = (m.group(2) if m.lastindex and m.lastindex >= 2 else "frames").lower()
            if unit.startswith("frame"):
                value = value / 24.0
            elif unit == "ms":
                value = value / 1000.0
            return value, clause
    return None


def read_page_thresholds(page_text: str, url: str) -> dict:
    """Read caption thresholds out of one extracted page. Pure Python.

    Returns a dict of threshold name -> {"value", "clause", "url"} for every
    threshold this page actually states, plus "found" listing them. A threshold
    the page does not state is absent, not guessed.
    """
    text = page_text or ""
    readers = {
        "max_cps": lambda: _first_hit(text, _CPS_PATTERNS, "max_cps"),
        "max_line_chars": lambda: _first_hit(text, _LINE_CHARS_PATTERNS, "max_line_chars"),
        "max_lines": lambda: _first_hit(text, _MAX_LINES_PATTERNS, "max_lines"),
        "min_duration_s": lambda: _read_min_duration(text),
        "min_gap_s": lambda: _read_min_gap(text),
    }
    out: dict[str, dict] = {}
    for name, reader in readers.items():
        hit = reader()
        if not hit:
            continue
        value, clause = hit
        lo, hi = _BANDS[name]
        if not (lo <= value <= hi):
            logger.info("dropping %s=%s from %s: outside band %s", name, value, url, _BANDS[name])
            continue
        out[name] = {"value": value, "clause": clause, "url": url}
    return {"url": url, "thresholds": out, "found": sorted(out)}


# --- the per-run evidence ledger -----------------------------------------
#
# Thresholds only ever enter a measurement through this ledger. The model is
# given the URL, never the number, so the number it would have to invent is one
# it is never shown and can never write into the result.

_LEDGER: dict[str, dict] = {}
_LEDGER_LOCK = threading.Lock()


def ledger_put(entry: dict) -> None:
    with _LEDGER_LOCK:
        _LEDGER[entry["url"]] = entry


def ledger_get(url: str) -> dict | None:
    with _LEDGER_LOCK:
        return _LEDGER.get(url)


def ledger_urls() -> list[str]:
    with _LEDGER_LOCK:
        return list(_LEDGER)


def ledger_clear() -> None:
    with _LEDGER_LOCK:
        _LEDGER.clear()


# --- where a URL came from ------------------------------------------------
#
# The offer register. `search_spec_candidates` writes one row per URL it hands
# to the desk, saying how that URL was discovered: `parallel_search` with the
# query that surfaced it and its rank in the result, or `seed_fallback` when
# Search found nothing on an official host.
#
# `extract_spec_page` will only open a URL that has a row here, so a URL the
# model wrote from memory, and a URL a future edit of this file hardcodes
# without offering it through Search, both fail before any page is fetched. The
# register is per process and per run: `discovery_clear` empties it alongside
# the ledger at the top of every run.

_DISCOVERY: dict[str, dict] = {}


def discovery_put(url: str, row: dict) -> None:
    with _LEDGER_LOCK:
        _DISCOVERY.setdefault(url, row)


def discovery_get(url: str) -> dict | None:
    with _LEDGER_LOCK:
        return _DISCOVERY.get(url)


def discovery_clear() -> None:
    with _LEDGER_LOCK:
        _DISCOVERY.clear()


# --- the two Parallel calls ----------------------------------------------


def _client():
    try:
        import parallel as parallel_sdk  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ParallelUnavailableError(
            "parallel-web is not installed. pip install parallel-web"
        ) from exc

    api_key = os.environ.get("PARALLEL_API_KEY", "")
    if not api_key:
        raise ParallelUnavailableError(
            "PARALLEL_API_KEY is not set. Cuepass measures against a spec page it "
            "fetched this run, so without Parallel there is no spec to measure against."
        )
    return parallel_sdk.Parallel(api_key=api_key)


def is_citable_url(url: str) -> bool:
    """True only for a URL a reviewer can click and land on the cited page.

    Rejects non-http schemes, missing hosts, and the mangled case where an
    upstream index spliced a local build path into the URL. A real observed
    result was `https://subtitlesedit.com/blog/netflix-subtitle-s:Users:kevin
    rato:Desktop:...mdxtyle-guide-explained`. Cuepass never renders that.
    """
    if not url:
        return False
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    if ":" in parts.path or " " in url:
        return False
    return True


def search_spec_candidates(platform: str) -> dict:
    """Parallel Search: candidate spec pages for one buyer. Returns URLs only.

    Search discovers the pages. Nothing in this repository names the page a
    profile ends up cited against, except in the one failure case documented at
    `SEARCH_FAILURE_FALLBACK_URLS`, which is reported in the return value as
    `seed_fallback_fired` and labelled on the candidate itself.

    Args:
        platform: buyer key, one of netflix, amazon, bbc, fcc.

    Returns:
        A dict with `candidates` (url, title, snippet, is_official, discovery,
        search_rank, found_by_query), the `session_id` to carry into extract,
        the queries that were sent, `official_from_search`, and
        `seed_fallback_fired`.
    """
    platform = platform.lower()
    queries = PLATFORM_QUERIES.get(platform, [f"{platform} subtitle specification"])
    objective = PLATFORM_OBJECTIVES.get(
        platform, f"Find {platform}'s published subtitle delivery specification."
    )
    client = _client()
    try:
        result = client.search(
            search_queries=queries,
            objective=objective,
            mode="fast",
            client_model="gemini-2.5-flash",
        )
    except Exception as exc:
        raise ParallelUnavailableError(f"Parallel Search failed for {platform}: {exc}") from exc

    hosts = OFFICIAL_HOSTS.get(platform, ())
    candidates = []
    for rank, r in enumerate(result.results, start=1):
        url = r.url or ""
        if not is_citable_url(url):
            continue
        host = urlparse(url).netloc.lower()
        candidates.append(
            {
                "url": url,
                "title": r.title or url,
                "snippet": " ".join(r.excerpts or [])[:300],
                "is_official": any(host == h or host.endswith("." + h) for h in hosts),
                "discovery": "parallel_search",
                "search_rank": rank,
            }
        )

    official_from_search = sum(1 for c in candidates if c["is_official"])

    # The one documented failure case, and the only branch on which a URL
    # written in this file reaches the desk: Search came back with nothing on a
    # host this buyer publishes on, so there is no discovered page to open and
    # the alternative is a run with no spec at all. See the comment above
    # SEARCH_FAILURE_FALLBACK_URLS. The candidate is labelled here and stays
    # labelled through Extract, the ledger, the spec and the stored run.
    fallback = SEARCH_FAILURE_FALLBACK_URLS.get(platform, "")
    seed_fallback_fired = bool(fallback) and official_from_search == 0
    if seed_fallback_fired:
        logger.warning(
            "Parallel Search returned no %s page on an official host for %s; "
            "falling back to the documented URL, which will be labelled as such",
            platform,
            platform,
        )
        candidates.insert(
            0,
            {
                "url": fallback,
                "title": f"{PLATFORM_LABELS.get(platform, platform)} (search-failure fallback)",
                "snippet": PROFILE_SCOPE.get(platform, ""),
                "is_official": True,
                "discovery": "seed_fallback",
                "search_rank": 0,
            },
        )

    if not candidates:
        raise ParallelUnavailableError(
            f"Parallel Search returned no usable spec page for {platform}."
        )
    # Official hosts first, and within them Search's own ranking. The desk still
    # chooses; this only orders the menu it is choosing from.
    candidates.sort(key=lambda c: (not c["is_official"], c["search_rank"]))
    candidates = candidates[:6]

    # Only these URLs can be extracted this run.
    for c in candidates:
        discovery_put(
            c["url"],
            {
                "how": c["discovery"],
                "search_rank": c["search_rank"],
                "search_id": result.search_id,
                "queries": queries,
                "platform": platform,
            },
        )

    return {
        "platform": platform,
        "candidates": candidates,
        "session_id": result.session_id,
        "search_id": result.search_id,
        "queries": queries,
        "official_from_search": official_from_search,
        "seed_fallback_fired": seed_fallback_fired,
    }


def extract_spec_page(platform: str, url: str, session_id: str = "") -> dict:
    """Parallel Extract: pull one candidate page and read its thresholds.

    Search snippets are not evidence; this opens the page. Every threshold that
    comes back carries the verbatim sentence it was read from. The result is
    written to the evidence ledger under this URL, and only a ledger entry can
    become a measurement.

    Args:
        platform: buyer key, one of netflix, amazon, bbc, fcc.
        url: the candidate page to open, from search_spec_candidates.
        session_id: session id from the search call, linking the two calls.

    Returns:
        A dict with the thresholds this page states, each with its clause, plus
        `found` (threshold names read) and `states_reading_speed`.
    """
    platform = platform.lower()
    if not is_citable_url(url):
        return {"url": url, "error": "not a citable url", "found": [], "thresholds": {}}
    # No key is a hard stop for the whole integration, so it is raised before
    # anything else is judged.
    client = _client()
    # A URL only becomes openable by being offered in a search result this run.
    # Refused before the fetch, so nothing about the page enters the process and
    # no ledger row is written, which is what stops it becoming a measurement.
    discovery = discovery_get(url)
    if discovery is None:
        return {
            "url": url,
            "error": (
                "this URL was not offered by search_spec_candidates in this run. "
                "Call search first and pass back a url from its candidates."
            ),
            "found": [],
            "thresholds": {},
        }
    try:
        response = client.extract(
            urls=[url],
            objective=PLATFORM_OBJECTIVES.get(platform, ""),
            search_queries=PLATFORM_QUERIES.get(platform, [])[:2],
            session_id=session_id or None,
            advanced_settings={"full_content": {"max_chars_per_result": 120000}},
        )
    except Exception as exc:
        raise ParallelUnavailableError(f"Parallel Extract failed for {url}: {exc}") from exc

    if not response.results:
        detail = response.errors[0].error_type if response.errors else "no result"
        return {
            "url": url,
            "error": f"extract returned nothing ({detail})",
            "found": [],
            "thresholds": {},
        }

    r = response.results[0]
    page_text = r.full_content or " ".join(r.excerpts or [])
    read = read_page_thresholds(page_text, r.url or url)
    entry = {
        "url": r.url or url,
        "title": r.title or url,
        "publish_date": r.publish_date,
        "thresholds": read["thresholds"],
        "found": read["found"],
        "extract_id": response.extract_id,
        "session_id": response.session_id,
        "chars_extracted": len(page_text),
        "platform": platform,
        # How this URL reached the desk. Rides through to the spec and the
        # stored run so a number can always be traced back to the search that
        # found the page it was read off.
        "discovery": discovery,
    }
    ledger_put(entry)
    # Extract can resolve a redirect, so the page that came back is not always
    # the URL that was asked for. Register the resolved one under the same
    # provenance, or the desk's own accepted URL would have no row.
    discovery_put(entry["url"], discovery)
    return {
        "url": entry["url"],
        "title": entry["title"],
        "found": entry["found"],
        "discovery": discovery["how"],
        "states_a_measurable_rule": bool(entry["thresholds"]),
        "states_reading_speed": "max_cps" in entry["thresholds"],
        "chars_extracted": entry["chars_extracted"],
        "extract_id": entry["extract_id"],
        # The clauses go to the model as evidence it can judge. The numbers do
        # not: the model is never asked to repeat one.
        "clauses": {k: v["clause"] for k, v in entry["thresholds"].items()},
    }


THRESHOLD_NAMES = (
    "max_cps",
    "min_duration_s",
    "max_line_chars",
    "max_lines",
    # The gap between subtitles. It is here because it constrains the repair
    # rather than only the source: extending a cue's out-time closes the gap in
    # front of it, so a repair working to an uncited gap can hand back a file
    # that fails the same page it was repaired against.
    "min_gap_s",
)

# A published value, with the page it is published on, used ONLY to fill a gap
# the live fetch left, and always labelled `fallback` in the result so the UI
# can say so. This exists because a buyer's spec is spread across several pages
# and Parallel does not return the same one every run: one run landed on the
# Netflix "Subtitle Templates" article, which states reading speed and line
# length but not minimum duration, and the duration check then had no threshold.
#
# Silently having no threshold is the dangerous outcome, because a check with no
# threshold reports zero violations, and zero reads as "clean" in exactly the
# field where it means "never looked". So: fill it, label it, and cite it.
# Nothing here is invented, and nothing here is used when the live fetch worked.
_NETFLIX_MIN_DURATION_FALLBACK = {
    # Wording and value taken from the page itself, read back through Parallel
    # Extract on 2026-09-09, not from memory. The page states the frame count and
    # the fraction together, and 4/5 sec is 20 frames at 25fps, which is the rate
    # that phrasing implies.
    #
    # Only the minimum duration is pinned, and deliberately only that. Reading
    # speed is never pinned for any Netflix profile: the point of running a desk
    # per profile is that each publishes its own figure, so a pinned reading speed
    # would let one profile borrow another's number and turn the comparison into
    # an artefact of this repository rather than of the published pages.
    "min_duration_s": {
        "value": 0.8,
        "clause": (
            "Subtitles should not be any shorter in duration than 20 frames "
            "(or 4/5 sec)."
        ),
        "url": (
            "https://partnerhelp.netflixstudios.com/hc/en-us/articles/"
            "215758617-Timed-Text-Style-Guide-General-Requirements"
        ),
    }
}

# The second and last pinned rule, and pinned for the same reason as the first:
# neither Netflix profile's headline page states it, it lives on the timing
# guidelines page, and the desk does not always land there. Read back through
# Parallel Extract on 2026-09-09 from article 360051554394, which states it
# three times: "Subtitles must have a minimum of 2 frames between them", "The
# minimum frame gap remains as 2 frames for all frame rates", and "In 24fps
# content, any gaps between subtitles of 3-11 frames inclusive must be closed to
# 2 frames." Two frames at 24fps is 1/12 of a second.
_NETFLIX_MIN_GAP_FALLBACK = {
    "min_gap_s": {
        "value": 2 / 24,
        "clause": "Subtitles must have a minimum of 2 frames between them.",
        "url": (
            "https://partnerhelp.netflixstudios.com/hc/en-us/articles/"
            "360051554394-Timed-Text-Style-Guide-Subtitle-Timing-Guidelines"
        ),
    }
}

_NETFLIX_PINNED = {**_NETFLIX_MIN_DURATION_FALLBACK, **_NETFLIX_MIN_GAP_FALLBACK}

PINNED_FALLBACKS: dict[str, dict[str, dict]] = {
    "netflix_en_us": _NETFLIX_PINNED,
    "netflix_templates": _NETFLIX_PINNED,
}


def spec_from_ledger(platform: str, urls: list[str] | str) -> dict:
    """Build the spec Cuepass measures against, from the pages a desk accepted.

    A buyer's spec is not always on one page, so several accepted URLs are
    merged and each threshold keeps the URL and the verbatim clause it was
    actually read from. First page to state a rule wins it, which is why the
    desk is told to open its best candidate first.

    Every one of the four thresholds ends up with a provenance:
        live         read this run from a page Extract opened
        fallback     the buyer's published value, pinned and cited, because the
                     live fetch did not land on a page stating it
        unverified   no live value and nothing pinned. The check is NOT run and
                     is listed in `not_verifiable`. It is never reported as
                     zero violations, because zero would mean "clean" when the
                     truth is "never measured".
    """
    if isinstance(urls, str):
        urls = [urls]
    urls = [u for u in urls if u]
    if not urls:
        raise ParallelUnavailableError("the desk accepted no page")

    entries = []
    for url in urls:
        entry = ledger_get(url)
        if entry is None:
            continue
        entries.append(entry)
    if not entries:
        raise ParallelUnavailableError(
            f"None of {urls} was opened by Parallel Extract this run, so there is "
            "no page text behind any of them. Cuepass will not measure against a "
            "URL it did not read."
        )

    merged: dict[str, dict] = {}
    for entry in entries:
        for name, value in entry["thresholds"].items():
            # Default the citation to the page this threshold was read from, not
            # to the profile's lead page. Getting that backwards points a reader
            # at a page that does not contain the number they are checking.
            merged.setdefault(
                name,
                {**value, "url": value.get("url") or entry["url"], "provenance": "live"},
            )
    if not merged:
        raise ParallelUnavailableError(
            f"{', '.join(u for u in urls)} were extracted but state none of the "
            "four rules Cuepass can measure."
        )

    pinned = PINNED_FALLBACKS.get(platform, {})
    not_verifiable: list[str] = []
    for name in THRESHOLD_NAMES:
        if name in merged:
            continue
        if name in pinned:
            merged[name] = {**pinned[name], "provenance": "fallback"}
        else:
            not_verifiable.append(name)

    lead = entries[0]
    spec = {
        "platform": PLATFORM_LABELS.get(platform, platform),
        "platform_key": platform,
        "scope": PROFILE_SCOPE.get(platform, ""),
        "source_url": lead["url"],
        "source_label": lead["title"],
        "source_urls": [e["url"] for e in entries],
        # How each cited page was found. `parallel_search` means Parallel Search
        # returned that URL this run at that rank, off those queries.
        # `seed_fallback` means Search returned nothing on an official host and
        # the documented fallback URL fired; see SEARCH_FAILURE_FALLBACK_URLS.
        "source_discovery": [
            {
                "url": e["url"],
                "how": (e.get("discovery") or {}).get("how", "unrecorded"),
                "search_rank": (e.get("discovery") or {}).get("search_rank"),
                "search_id": (e.get("discovery") or {}).get("search_id", ""),
                "queries": (e.get("discovery") or {}).get("queries", []),
            }
            for e in entries
        ],
        "discovery": (lead.get("discovery") or {}).get("how", "unrecorded"),
        "publish_date": lead["publish_date"],
        "extract_id": lead["extract_id"],
        "session_id": lead["session_id"],
        "chars_extracted": sum(e["chars_extracted"] for e in entries),
        "is_cached": False,
        "evidence": {
            name: {
                "value": v["value"],
                "clause": v["clause"],
                "url": v.get("url", lead["url"]),
                "provenance": v["provenance"],
                # Whether this number came off the profile's headline page or off
                # another page the desk had to open to find it. A spec is spread
                # across pages, so this is common and not a fault, but a reader
                # following the headline citation to check a number that is not on
                # that page would be right to lose trust. Stated here rather than
                # left for each consumer to work out by comparing URLs.
                "from_profile_page": v.get("url", lead["url"]) == lead["url"],
            }
            for name, v in merged.items()
        },
        "provenance": {
            name: merged[name]["provenance"] if name in merged else "unverified"
            for name in THRESHOLD_NAMES
        },
        # The checks that were not run at all. The UI must render these as
        # "not verifiable against the live spec", never as a passing check.
        "not_verifiable": not_verifiable,
    }
    for name in THRESHOLD_NAMES:
        spec[name] = merged[name]["value"] if name in merged else None
    if spec["max_lines"] is not None:
        spec["max_lines"] = int(spec["max_lines"])
    if spec["max_line_chars"] is not None:
        spec["max_line_chars"] = int(spec["max_line_chars"])
    return spec
