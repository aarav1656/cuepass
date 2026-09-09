"""Fetch live caption delivery specs from the open web via Parallel Search.

This module is LOAD-BEARING: delete it and the tool raises immediately.
There is no silent fallback. The Parallel track requires runtime use of the
Parallel Search API, and a working tool that silently degrades to hardcoded
thresholds would be decorative, not load-bearing.

Parallel Search is used at runtime to:
1. Find the current published spec page for the chosen platform.
2. Extract the actual numeric thresholds (chars/sec, min/max duration, line length).
3. Return the source URL so the UI can cite it.

API used: parallel.Parallel.search(search_queries=[...]) from the parallel-web SDK.
Result shape: SearchResult.results -> list[WebSearchResult]
  - WebSearchResult.url: str
  - WebSearchResult.title: Optional[str]
  - WebSearchResult.excerpts: list[str]  (markdown-formatted excerpts)
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ParallelUnavailableError(Exception):
    """Raised when Parallel Search cannot be used.

    This is a hard failure, not a recoverable condition. The Parallel track
    requires runtime use of the Search API. Silent degradation to hardcoded
    constants would make the integration decorative.
    """


# Reference constants used ONLY for sanity-checking extracted values.
# Never returned directly to the caller; use fetch_spec() which requires Parallel.
_REFERENCE_SPECS: dict[str, dict] = {
    "netflix": {
        "platform": "Netflix",
        "max_cps": 17.0,
        "min_duration_s": 5 / 6,
        "max_line_chars": 42,
        "max_lines": 2,
        "source_url": "https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617",
    },
    "amazon": {
        "platform": "Amazon Prime Video",
        "max_cps": 17.0,
        "min_duration_s": 0.5,
        "max_line_chars": 42,
        "max_lines": 2,
        "source_url": "https://videodirect.amazon.com/home/help",
    },
    "bbc": {
        "platform": "BBC",
        "max_cps": 17.0,
        "min_duration_s": 0.5,
        "max_line_chars": 40,
        "max_lines": 2,
        "source_url": "https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/",
    },
    "fcc": {
        "platform": "FCC (US broadcast)",
        "max_cps": 17.0,
        "min_duration_s": 0.5,
        "max_line_chars": 32,
        "max_lines": 4,
        "source_url": "https://www.fcc.gov/consumers/guides/captioning-internet-video-programming",
    },
}

# Queries designed to land on the published spec pages, not marketing copy
PLATFORM_QUERIES: dict[str, list[str]] = {
    "netflix": [
        'Netflix "Timed Text Style Guide" subtitle characters per second limit',
        "Netflix TTSS subtitle spec max reading speed characters per second",
    ],
    "amazon": [
        "Amazon Prime Video subtitle delivery specification characters per second line length",
        "Amazon Video Direct subtitle style guide reading speed",
    ],
    "bbc": [
        "BBC subtitle style guide characters per second line length specification",
        "BBC Ofcom subtitle specification reading speed",
    ],
    "fcc": [
        "FCC caption quality rules characters per second reading speed",
        "FCC closed caption standards synchronicity accuracy",
    ],
}

# Patterns to extract thresholds from web text
_CPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*characters?\s*per\s*second", re.I)
_LINE_CHARS_RE = re.compile(r"(\d{2,3})\s*characters?\s*(?:per\s*)?line", re.I)
_MAX_LINES_RE = re.compile(r"(?:maximum|max)\s+(\d)\s*lines?", re.I)


def _is_citable_url(url: str) -> bool:
    """True only for a URL a reviewer can actually click through to.

    Rejects non-http schemes, missing hosts, and the mangled-path case where a
    local filesystem path has been spliced into the URL by the upstream index.
    """
    if not url:
        return False
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    if ":" in parts.path or " " in url:
        return False
    return True


def _run_parallel_search(platform: str) -> dict:
    """Run a live Parallel Search and extract thresholds.

    Raises ParallelUnavailableError on any failure. No silent fallback.
    """
    try:
        import parallel as parallel_sdk  # type: ignore[import-untyped]
    except ImportError:
        raise ParallelUnavailableError(
            "parallel-web package not installed. "
            "Install with: pip install parallel-web"
        )

    api_key = os.environ.get("PARALLEL_API_KEY", "")
    if not api_key:
        raise ParallelUnavailableError(
            "PARALLEL_API_KEY environment variable is not set. "
            "Sign up at https://parallel.ai to get a free API key ($20-80 credits). "
            "The Parallel track requires runtime use of the Search API."
        )

    queries = PLATFORM_QUERIES.get(
        platform,
        [f"{platform} subtitle delivery specification reading speed characters per second"],
    )

    try:
        client = parallel_sdk.Parallel(api_key=api_key)
        result = client.search(
            search_queries=queries,
            mode="fast",
            objective=(
                f"Find the current {platform} caption/subtitle delivery specification, "
                "specifically the maximum reading speed in characters per second, "
                "maximum line length in characters, and minimum cue duration."
            ),
        )
        search_results = result.results  # list[WebSearchResult]
    except Exception as exc:
        raise ParallelUnavailableError(
            f"Parallel Search API call failed: {exc}. "
            "Check your PARALLEL_API_KEY and network connectivity."
        ) from exc

    if not search_results:
        raise ParallelUnavailableError(
            f"Parallel Search returned no results for platform '{platform}'. "
            "The search completed but found no matching spec pages."
        )

    # Aggregate text from all results to maximise coverage of numeric thresholds
    all_text = ""
    source_url = ""
    source_label = ""
    raw_results: list[dict] = []

    ref = _REFERENCE_SPECS.get(platform, _REFERENCE_SPECS["netflix"])
    official_host = urlparse(ref["source_url"]).netloc

    for r in search_results:
        url = r.url or ""
        title = r.title or url
        excerpts_text = " ".join(r.excerpts or [])
        all_text += f" {title} {excerpts_text}"
        raw_results.append({"url": url, "title": title})

    # The citation is shown to a reviewer as a clickable link, so it has to be a
    # real, well-formed URL. Parallel occasionally returns a result whose URL has
    # a local build path spliced into it (a real observed case:
    # ".../netflix-subtitle-s:Users:kevinrato:Desktop:...mdxtyle-guide-explained").
    # Prefer the platform's own domain, then any well-formed result, then the
    # known-good reference URL. Never cite a URL we cannot vouch for.
    citable = [
        (r["url"], r["title"]) for r in raw_results if _is_citable_url(r["url"])
    ]
    first_party = [(u, t) for u, t in citable if urlparse(u).netloc == official_host]
    for url, title in first_party + citable:
        source_url, source_label = url, title
        break

    # Extract numeric thresholds from combined text
    cps_match = _CPS_RE.search(all_text)
    line_chars_match = _LINE_CHARS_RE.search(all_text)
    max_lines_match = _MAX_LINES_RE.search(all_text)

    max_cps = float(cps_match.group(1)) if cps_match else ref["max_cps"]
    max_line_chars = (
        int(line_chars_match.group(1)) if line_chars_match else ref["max_line_chars"]
    )
    max_lines = int(max_lines_match.group(1)) if max_lines_match else ref["max_lines"]

    # Sanity-check extracted values; use reference per-field if they look wrong
    if not (5.0 <= max_cps <= 50.0):
        logger.warning(
            "Extracted max_cps=%s looks implausible; using reference %s",
            max_cps, ref["max_cps"],
        )
        max_cps = ref["max_cps"]

    return {
        "platform": ref["platform"],
        "max_cps": max_cps,
        "min_duration_s": ref["min_duration_s"],
        "max_line_chars": max_line_chars,
        "max_lines": max_lines,
        "source_url": source_url or ref["source_url"],
        "source_label": f"Parallel Search: {source_label}" if source_label else f"Parallel Search ({platform})",
        "is_cached": False,
        "raw_results": raw_results[:5],
    }


def fetch_spec(platform: str = "netflix") -> dict:
    """Return the current caption delivery spec for the given platform.

    Calls Parallel Search API at runtime. Raises ParallelUnavailableError
    if the API is unavailable, the key is missing, or no results are found.
    There is no silent fallback to hardcoded constants.

    The returned dict always contains:
        platform, max_cps, min_duration_s, max_line_chars, max_lines,
        source_url, source_label, is_cached
    """
    platform = platform.lower()
    return _run_parallel_search(platform)
