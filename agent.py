"""Driving the Cuepass delivery-desk graph and turning it into a stored run.

`cuepass_agents.py` owns the topology. This module owns everything around one
invocation of it: which film, seeding the graph's state with the real subtitle
text, running it, recording which nodes actually fired, shaping the buyer matrix
the UI renders, and persisting the whole thing so it survives the request.

Nothing here decides a threshold or counts a violation. Those happen inside the
graph, in the deterministic nodes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

import archive as archive_mod
import cuepass_agents
import parallel_spec
import runstore

logger = logging.getLogger(__name__)

# The default title is fixed rather than "whatever archive.org lists first".
# A judge who clicks Run without choosing has to land on a track that actually
# fails, and a demo whose subject changes between runs cannot be checked by
# anyone. `test_default_film_still_fails` guards this.
DEFAULT_FILM = "iron_mask"

APP_NAME = "cuepass"

GeminiUnavailableError = cuepass_agents.GeminiUnavailableError


def _has_model_credentials() -> bool:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("true", "1", "yes"):
        return bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    return bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))


def _jsonable(value: Any) -> Any:
    """Compact anything an ADK event carries into something JSON can hold."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # The trace is provenance a reader inspects, so where it is shortened it has
    # to say so. Dropping items silently would make a truncated tool result
    # indistinguishable from a short one.
    if isinstance(value, dict):
        items = list(value.items())
        out = {k: _jsonable(v) for k, v in items[:12]}
        if len(items) > 12:
            out["..."] = f"{len(items) - 12} more keys"
        return out
    if isinstance(value, (list, tuple)):
        items = list(value)
        out = [_jsonable(v) for v in items[:8]]
        if len(items) > 8:
            out.append(f"... {len(items) - 8} more items")
        return out
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass
    text = str(value)
    return text if len(text) <= 240 else text[:240] + "..."


def _trace_from_events(events: list) -> list[dict]:
    """The nodes and tool calls that actually ran, in the order they ran.

    This is read off the event stream, not written by hand, so a node that was
    declared in the graph and never fired does not appear here. The UI draws
    the declared graph and this list side by side, which is the only way a
    reader can tell the topology apart from a diagram of one.
    """
    trace: list[dict] = []
    for event in events:
        author = getattr(event, "author", "") or ""
        branch = getattr(event, "branch", None)
        node = str(branch).rsplit(".", 1)[-1] if branch else author
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or [] if content else []
        for part in parts:
            call = getattr(part, "function_call", None)
            if call is not None:
                args = dict(call.args or {})
                trace.append(
                    {
                        "node": node,
                        "author": author,
                        "kind": "tool_call",
                        "label": call.name,
                        "detail": _jsonable(
                            {k: v for k, v in args.items() if k != "session_id"}
                        ),
                    }
                )
            response = getattr(part, "function_response", None)
            if response is not None:
                trace.append(
                    {
                        "node": node,
                        "author": author,
                        "kind": "tool_result",
                        "label": response.name,
                        "detail": _jsonable(response.response),
                    }
                )
        output = getattr(event, "output", None)
        if output is not None and not parts:
            trace.append(
                {
                    "node": node,
                    "author": author,
                    "kind": "node_output",
                    "label": node,
                    "detail": _jsonable(output),
                }
            )
    return trace


async def _drive(workflow, initial_state: dict) -> tuple[dict, list[dict]]:
    """Run the graph once. Returns (final session state, trace)."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=workflow, app_name=APP_NAME)
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id="qc", state=initial_state
    )
    message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    "Clear this subtitle track for delivery. Cite each buyer's own "
                    "published caption specification."
                )
            )
        ],
    )
    events = []
    async for event in runner.run_async(
        user_id="qc", session_id=session.id, new_message=message
    ):
        events.append(event)

    final = await runner.session_service.get_session(
        app_name=APP_NAME, user_id="qc", session_id=session.id
    )
    return dict(final.state), _trace_from_events(events)


def _verdict(after: dict) -> str:
    """The ship gate. Not a legal opinion, a delivery decision.

    A caption style guide is a buyer's acceptance criterion, not a statute, so
    the words are DELIVER and HOLD rather than legal or illegal.
    """
    return "DELIVER" if after.get("total_violations", 0) == 0 else "HOLD"


class VacuousContrastError(Exception):
    """Raised when two profiles are compared on a threshold they share.

    A comparison between two cited specs is only worth showing if the specs
    actually differ. Presenting "same file, different rule" when both rules are
    the same number would be theatre.
    """


def _cue_verdicts(entry: dict, check: str) -> set[int]:
    """Cue indices failing one check for one profile, before repair."""
    return {
        f["cue_index"] for f in entry["before"]["findings"] if f["check"] == check
    }


def _contrasts(buyers: dict[str, dict]) -> list[dict]:
    """Where two cited profiles disagree about the same file.

    For every pair of profiles that published a DIFFERENT reading-speed figure,
    count the cues that are acceptable under one and not the other. That count
    is the argument: it exists only because the thresholds were fetched rather
    than hardcoded, and it changes if either page changes.

    A pair whose figures are identical produces no contrast row. Nothing is shown
    that would let a reader infer a difference that is not there.
    """
    out: list[dict] = []
    keys = sorted(buyers)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            spec_a, spec_b = buyers[a]["spec"], buyers[b]["spec"]
            cps_a, cps_b = spec_a.get("max_cps"), spec_b.get("max_cps")
            if cps_a is None or cps_b is None or cps_a == cps_b:
                continue
            fail_a = _cue_verdicts(buyers[a], "reading_speed")
            fail_b = _cue_verdicts(buyers[b], "reading_speed")
            stricter, looser = (a, b) if cps_a < cps_b else (b, a)
            only_stricter = (fail_a - fail_b) if stricter == a else (fail_b - fail_a)
            out.append(
                {
                    "stricter": stricter,
                    "looser": looser,
                    "stricter_platform": buyers[stricter]["spec"]["platform"],
                    "looser_platform": buyers[looser]["spec"]["platform"],
                    "stricter_max_cps": buyers[stricter]["spec"]["max_cps"],
                    "looser_max_cps": buyers[looser]["spec"]["max_cps"],
                    "stricter_clause": buyers[stricter]["spec"]
                    .get("evidence", {})
                    .get("max_cps", {})
                    .get("clause", ""),
                    "looser_clause": buyers[looser]["spec"]
                    .get("evidence", {})
                    .get("max_cps", {})
                    .get("clause", ""),
                    "stricter_url": buyers[stricter]["spec"]["source_url"],
                    "looser_url": buyers[looser]["spec"]["source_url"],
                    "stricter_scope": buyers[stricter]["spec"].get("scope", ""),
                    "looser_scope": buyers[looser]["spec"].get("scope", ""),
                    # The number that only exists because the specs were fetched.
                    "cues_legal_under_looser_only": len(only_stricter),
                    # Every index, uncapped, and it must stay that way. This was
                    # sliced to 200 while the count above stayed exact, so a wider
                    # reading-speed gap would have published a true count next to
                    # a short list, and a consumer marking rows from the list would
                    # have highlighted 200 of them while the headline said more.
                    # A count and the evidence for it must not be able to disagree.
                    "cue_indices": sorted(only_stricter),
                }
            )
    return out


def _pick_film(identifier: str | None) -> dict:
    ident = (identifier or "").strip() or DEFAULT_FILM
    info = archive_mod.pick_files(ident)
    if not info["subtitle"]:
        raise RuntimeError(f"{ident} has no subtitle track on archive.org")
    return info


def run_agent(identifier: str | None = None) -> dict:
    """One full pass: research every delivery profile, measure, repair, prove, triage.

    Returns the stored run record. Raises rather than degrading: without
    Parallel there is no cited spec to measure against, and without Gemini
    there is nobody to choose which page is the buyer's own.
    """
    if not _has_model_credentials():
        raise GeminiUnavailableError(
            "No Gemini credentials. Set GOOGLE_GENAI_USE_VERTEXAI=true with "
            "GOOGLE_CLOUD_PROJECT, or GOOGLE_API_KEY. The buyer desks and the "
            "triage node are model decisions; Cuepass will not substitute a "
            "default for either."
        )
    if not os.environ.get("PARALLEL_API_KEY"):
        raise parallel_spec.ParallelUnavailableError(
            "PARALLEL_API_KEY is not set. Every threshold Cuepass measures "
            "against is read off a page Parallel opened this run."
        )

    info = _pick_film(identifier)
    srt_text = archive_mod.fetch_text(info["identifier"], info["subtitle"])
    if not srt_text.strip():
        raise RuntimeError(f"Empty subtitle file for {info['identifier']}")

    # Both registers are per-run. The ledger: a URL accepted by a desk must have
    # been opened by this run's Extract call, not by a previous one still
    # sitting in memory. The offer register: a URL may only be opened if this
    # run's Search offered it, so a page found by a previous run cannot be
    # reopened without being found again.
    parallel_spec.ledger_clear()
    parallel_spec.discovery_clear()

    workflow = cuepass_agents.build_workflow()
    state, trace = asyncio.run(
        _drive(
            workflow,
            {
                "srt_text": srt_text,
                "film_title": info["title"],
                "film_identifier": info["identifier"],
            },
        )
    )

    specs = state.get("specs") or {}
    before = state.get("before") or {}
    after = state.get("after") or {}
    if not specs or not before or not after:
        raise RuntimeError(
            "The graph did not complete: "
            f"specs={sorted(specs)} before={sorted(before)} after={sorted(after)}. "
            "No verdict is reported from a partial run."
        )

    editorial_raw = state.get("editorial")
    if isinstance(editorial_raw, str):
        try:
            editorial_raw = json.loads(editorial_raw)
        except ValueError:
            editorial_raw = {}
    actions = (editorial_raw or {}).get("actions", []) if isinstance(editorial_raw, dict) else []
    editorial = {str(a["cue_index"]): a for a in actions if isinstance(a, dict) and "cue_index" in a}

    leftover_reasons = state.get("leftover_reasons") or {}
    cues_changed = state.get("cues_changed") or {}
    repaired_srt = state.get("repaired_srt") or {}

    run_id = f"{info['identifier']}-{uuid.uuid4().hex[:8]}"
    buyers: dict[str, dict] = {}
    for buyer, spec in specs.items():
        buyers[buyer] = {
            "spec": {k: v for k, v in spec.items() if k != "desk_rejected"},
            "before": before[buyer],
            "after": after[buyer],
            "leftover_reasons": leftover_reasons.get(buyer, {}),
            "cues_changed": cues_changed.get(buyer, 0),
            "verdict": _verdict(after[buyer]),
        }

    any_cue_count = next(iter(before.values()))["cue_count"]
    contrasts = _contrasts(buyers)
    record = {
        "run_id": run_id,
        "measured_at": runstore.now_iso(),
        "film_title": info["title"],
        "film_identifier": info["identifier"],
        "subtitle_filename": info["subtitle"],
        "subtitle_url": archive_mod.download_url(info["identifier"], info["subtitle"]),
        "cue_count": any_cue_count,
        "buyers": buyers,
        "unavailable": state.get("specs_unavailable") or {},
        "editorial": editorial,
        "editorial_capped_at": len(state.get("triage_input") or []),
        "leftover_cue_total": state.get("triage_total", 0),
        "contrasts": contrasts,
        "graph": cuepass_agents.graph_shape(),
        "trace": trace,
        "model": cuepass_agents.MODEL,
        "framework": "google-adk",
        "parallel_surfaces": ["search", "extract"],
    }
    return runstore.save(record, repaired_srt, source_srt=srt_text)


def exceptions_file(record: dict, buyer: str) -> dict:
    """The artefact a QC lead sends on: every cue still failing one buyer.

    Each row carries the measured value, the limit, the verbatim clause from
    the buyer's page that set that limit, and the editorial action the triage
    node assigned. This is the file, not a screenshot of a table.
    """
    entry = record["buyers"][buyer]
    spec = entry["spec"]
    reasons = entry["leftover_reasons"]
    evidence = spec.get("evidence", {})
    check_to_threshold = {
        "reading_speed": "max_cps",
        "min_duration": "min_duration_s",
        "non_positive_duration": "min_duration_s",
        "line_length": "max_line_chars",
        "line_count": "max_lines",
    }
    rows = []
    for f in entry["after"]["findings"]:
        key = str(f["cue_index"])
        threshold_name = check_to_threshold.get(f["check"], "")
        clause = evidence.get(threshold_name, {}).get("clause", "")
        action = record.get("editorial", {}).get(key, {})
        rows.append(
            {
                "cue_index": f["cue_index"],
                "timecode": f["timecode"],
                "text": f["text_preview"],
                "check": f["check"],
                "measured": f["value"],
                "limit": f["threshold"],
                "unit": f["unit"],
                "blocked_by": reasons.get(key, ""),
                "editorial_action": action.get("action", ""),
                "editorial_note": action.get("note", ""),
                "clause": clause,
            }
        )
    return {
        "film": record["film_title"],
        "source_subtitle": record["subtitle_url"],
        "buyer": spec["platform"],
        "spec_source_url": spec["source_url"],
        "spec_extract_id": spec.get("extract_id", ""),
        "measured_at": record["measured_at"],
        "run_id": record["run_id"],
        "verdict": entry["verdict"],
        "violations_before_repair": entry["before"]["total_violations"],
        "violations_after_repair": entry["after"]["total_violations"],
        "cues_retimed": entry["cues_changed"],
        "exceptions": rows,
    }
