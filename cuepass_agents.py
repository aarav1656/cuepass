"""The Cuepass delivery desk, as a google-adk Workflow.

Topology (this is the real graph, not a drawing of one). One spec desk per entry
in `BUYERS`, so the fan-out is however many profiles that tuple holds:

    START
      |-- <profile>_spec_desk  --+
      |-- <profile>_spec_desk  --+--> spec_desk_join
      |-- ...                  --+          |
                                            v
                                  bind_cited_specs      (deterministic)
                                            v
                                  measure_every_buyer   (deterministic)
                                            v
                                  repair_every_buyer    (deterministic)
                                            v
                                  remeasure_every_buyer (deterministic)
                                            v
                                  collect_leftovers     (deterministic)
                                            v
                                  triage_leftovers      (model)

`graph_shape()` reads the built graph, so the desk names and the count printed
anywhere in the product come from `BUYERS` rather than from this comment. Nothing
in this file states how many desks there are: a count written in prose goes stale
the moment a profile is added, and a stale count sitting next to correct numbers
is worse than no count.

Who does what, and why it could not be done by the node before it:

`*_spec_desk` (one LlmAgent per delivery profile, run concurrently by the graph)
    Each one researches one buyer's published caption spec with two Parallel
    tools. The judgement it makes is which of the candidate pages Search
    returned is the buyer's OWN published specification rather than a blog
    restating it, and, when the page it opened turns out not to state a
    reading-speed rule, which candidate to open next. That is a real decision:
    an allowlist alone picks netflix.com press releases, and a first-result
    rule picks whichever SEO page won that day. The desk never states a
    number. `extract_spec_page` reads the numbers out of the page in Python
    and files them in an evidence ledger keyed by URL. The desk returns only
    the URL it accepts.

`bind_cited_specs`, `measure_every_buyer`, `repair_every_buyer`,
`remeasure_every_buyer` (FunctionNodes, no model)
    Arithmetic and file surgery. A model must not be able to decide that a cue
    is compliant, to skip the re-measure, or to author a cps value. These are
    ordinary Python functions in the graph so the event log shows them running
    between the model nodes.

`triage_leftovers` (LlmAgent)
    Only sees the cues that repair could not clear, and only after the numbers
    exist. It assigns each one the editorial action a human would take next.
    Its output is what lands in the downloadable exceptions file, so this node
    changes an artefact, not the prose.

ADK 2.8 note: SequentialAgent, ParallelAgent and LoopAgent all carry
`@deprecated('... in favor of Workflow ...')` in this version, so the graph is
built with `google.adk.workflow.Workflow` edges. The fan-out across the profiles
is a tuple in the edge list and a `JoinNode` waits for every branch.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

import measure as measure_mod
import parallel_spec

logger = logging.getLogger(__name__)

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# One desk per delivery profile, not per company. Netflix publishes more than one
# reading-speed figure on more than one page, for different scopes, and a
# distributor asking "are we compliant with Netflix" gets a different answer
# depending on which published page it is held to. That is the thing worth
# showing, so each profile gets its own desk, its own cited page and its own
# clause, and none of them is ever allowed to borrow another's reading speed:
# `parallel_spec.PINNED_FALLBACKS` holds no `max_cps` for any profile, so the
# contrast on screen is what the pages said rather than what this file arranged.
# The one pinned value, `min_duration_s`, is deliberately shared by both Netflix
# profiles, because it is one published Netflix rule that neither profile page
# restates, and it is labelled `fallback` wherever it appears.
BUYERS: tuple[str, ...] = (
    "netflix_en_us",
    "netflix_templates",
    "amazon",
    "bbc",
    "fcc",
)


class GeminiUnavailableError(Exception):
    """Raised when the graph cannot reach Gemini.

    Hard failure. The spec desks and the triage node are the two places where a
    decision, not a calculation, happens. Substituting a default for either
    would leave the model decorative.
    """


# --- what each model node is required to return --------------------------


class SpecChoice(BaseModel):
    """The pages one buyer desk accepted as that buyer's published spec.

    A list, not a single URL, because buyers split their spec across pages: the
    reading speed and line length can be on the style guide while the minimum
    cue duration is on a general requirements page. Each threshold keeps the
    page it was actually read from.
    """

    accepted_urls: list[str] = Field(
        default_factory=list,
        description=(
            "Exact URLs, copied from extract_spec_page results, whose pages state "
            "this buyer's caption rules. Best page first. Empty if no candidate "
            "page stated any measurable rule."
        )
    )
    reason: str = Field(
        description="One sentence on why these are the buyer's own published spec pages."
    )
    rejected: list[str] = Field(
        default_factory=list,
        description="URLs opened or considered and not accepted.",
    )


class EditorialAction(BaseModel):
    """What a human should do with one cue the retime could not clear."""

    cue_index: int
    action: Literal["split_cue", "rewrite_shorter", "merge_with_next", "request_waiver"]
    note: str = Field(description="One short clause a spotting editor can act on.")


class EditorialQueue(BaseModel):
    actions: list[EditorialAction] = Field(default_factory=list)


# --- one research desk per delivery profile ------------------------------

_DESK_INSTRUCTION = """You are the delivery desk for {label}.

This profile covers: {scope}

Your job is to find the page that publishes the subtitle or closed-caption
delivery specification for THIS profile, and to accept that page as the source
this run measures against.

If a candidate is marked is_profile_page, it is the page this profile is defined
by. Open it first. It is still only a URL and you still have to open it: if it
turns out to state no measurable rule, treat it like any other failed candidate
and move on.

Other profiles in this run cover other scopes and other pages. Do not accept a
page that belongs to a different profile, and never carry a number across from
one. If this profile's page states a figure that differs from another profile's,
that is the correct outcome and not a mistake to reconcile.

Method:
1. Call search_spec_candidates with platform="{buyer}". It returns candidate
   pages only. A search snippet is not evidence and you must not treat a number
   in a snippet as a threshold.
2. Look at the candidates. Prefer the buyer's own published page over a
   third-party blog, a reseller, a subtitle software vendor, or a news article
   restating the rule. is_official tells you the host matches a domain the
   buyer publishes on, but it is a hint, not the answer: a marketing page on
   the right domain is still the wrong page.
3. Call extract_spec_page with platform="{buyer}", the url you chose, and the
   session_id from the search result. That call opens the page and reads its
   thresholds in Python. It returns which thresholds the page states and the
   verbatim clause each was read from.
4. Look at `found` in the result. It lists which of the four rules that page
   states: max_cps (reading speed), min_duration_s (minimum time a subtitle
   stays on screen), max_line_chars, max_lines.
5. You are trying to cover all four. Buyers routinely split them across pages:
   a style guide page often gives reading speed and line length while the
   minimum duration sits on a general requirements page. So if `found` is
   missing any of the four, open ANOTHER candidate to try to cover the gap.
   Open up to four pages in total.
6. Return every URL that contributed at least one rule, best page first, in
   accepted_urls. Do not include a page whose `found` was empty.

Hard rules:
- You must never state, guess, round or repeat a threshold value. The numbers
  are read from the page text by the tool, not by you. Your output schema has
  no field for a number, and inventing one elsewhere would put a rumour into a
  delivery decision.
- Every URL in accepted_urls must be one you actually passed to
  extract_spec_page and which came back with a non-empty `found`. Do not return
  a URL you did not open.
- Prefer the buyer's general or main style guide over a narrow sub-page when
  both state the same rule, because the general page is the one the buyer holds
  a delivery to.
- If every attempt comes back with nothing, return an empty accepted_urls list
  and say why. That is a correct answer. A guessed page is not.
"""


def spec_desk(buyer: str):
    """One buyer's research desk: an LlmAgent holding the two Parallel tools."""
    from google.adk.agents import LlmAgent
    from google.adk.tools import FunctionTool

    label = parallel_spec.PLATFORM_LABELS.get(buyer, buyer)
    scope = parallel_spec.PROFILE_SCOPE.get(buyer, label)
    return LlmAgent(
        name=f"{buyer}_spec_desk",
        model=MODEL,
        description=f"Finds and opens the published caption spec for {label}.",
        instruction=_DESK_INSTRUCTION.format(buyer=buyer, label=label, scope=scope),
        tools=[
            FunctionTool(parallel_spec.search_spec_candidates),
            FunctionTool(parallel_spec.extract_spec_page),
        ],
        output_schema=SpecChoice,
        output_key=f"spec_choice_{buyer}",
    )


# --- the deterministic nodes ---------------------------------------------


def _state_get(ctx, key: str, default: Any = None) -> Any:
    try:
        return ctx.state[key]
    except (KeyError, TypeError):
        return default


def _as_choice(raw: Any) -> dict:
    """Normalise whatever the desk left in state into a plain dict."""
    if isinstance(raw, SpecChoice):
        return raw.model_dump()
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def bind_cited_specs(ctx) -> dict:
    """Turn each desk's accepted URL into the spec this run measures against.

    A threshold only becomes a measurement by coming out of the evidence
    ledger, which only `extract_spec_page` writes to. A desk that returned a
    URL nobody opened, or a page that stated no reading-speed rule, fails that
    buyer here with the reason attached. It never falls back to a constant.
    """
    specs: dict[str, dict] = {}
    unavailable: dict[str, str] = {}
    for buyer in BUYERS:
        choice = _as_choice(_state_get(ctx, f"spec_choice_{buyer}"))
        raw_urls = choice.get("accepted_urls") or []
        if isinstance(raw_urls, str):
            raw_urls = [raw_urls]
        # Only URLs this run's Extract actually opened. A desk that named a page
        # it never read cannot get that page measured against.
        opened = set(parallel_spec.ledger_urls())
        accepted = [u.strip() for u in raw_urls if u and u.strip() in opened]
        if not accepted:
            unavailable[buyer] = choice.get("reason") or "desk accepted no page it had opened"
            continue
        try:
            spec = parallel_spec.spec_from_ledger(buyer, accepted)
        except parallel_spec.ParallelUnavailableError as exc:
            unavailable[buyer] = str(exc)
            continue
        spec["desk_reason"] = choice.get("reason", "")
        spec["desk_rejected"] = choice.get("rejected", [])
        specs[buyer] = spec

    if not specs:
        raise parallel_spec.ParallelUnavailableError(
            "No buyer desk produced a spec page stating a reading-speed rule: "
            + "; ".join(f"{k}: {v}" for k, v in unavailable.items())
        )
    ctx.state["specs"] = specs
    ctx.state["specs_unavailable"] = unavailable
    return {"cited": sorted(specs), "unavailable": sorted(unavailable)}


def effective_thresholds(spec: dict) -> dict:
    """Only the thresholds this buyer's spec actually resolved to a value.

    A page that never mentions a line-length rule does not get one. The check
    is skipped for that buyer and the matrix says so, which is the honest
    reading of a spec that is silent. A threshold whose provenance is `fallback`
    does have a value and is measured against; it is the profile's own page that
    was silent, not the buyer, and the label travels with the number.
    """
    return {
        k: spec[k]
        for k in ("max_cps", "min_duration_s", "max_line_chars", "max_lines")
        if spec.get(k) is not None
    }


def measure_every_buyer(ctx) -> dict:
    """Measure the same subtitle file against every cited spec. No model."""
    srt_text = _state_get(ctx, "srt_text") or ""
    if not srt_text.strip():
        raise RuntimeError("measure_every_buyer: no subtitle text in state")
    specs = _state_get(ctx, "specs") or {}
    before: dict[str, dict] = {}
    for buyer, spec in specs.items():
        report = measure_mod.measure_subtitles(srt_text, spec=spec)
        before[buyer] = {
            **report.summary(),
            "findings": report.findings_as_dicts(),
        }
    ctx.state["before"] = before
    return {buyer: before[buyer]["total_violations"] for buyer in before}


def repair_every_buyer(ctx) -> dict:
    """Retime cue out-times per buyer. No model.

    The repair is buyer-specific because the target is: a cue that clears
    Netflix's reading-speed rule may still be short for a buyer whose page
    states a longer minimum duration, so each buyer gets its own repaired
    track.
    """
    srt_text = _state_get(ctx, "srt_text") or ""
    specs = _state_get(ctx, "specs") or {}
    repaired: dict[str, str] = {}
    changed: dict[str, int] = {}
    leftovers: dict[str, dict] = {}
    for buyer, spec in specs.items():
        eff = effective_thresholds(spec)
        # A rule this buyer's page never stated is not a target for the repair
        # either. Absent minimum duration means retime for reading speed only;
        # absent line rules mean the leftover explainer never blames a line
        # length nobody published.
        max_cps = eff.get("max_cps")
        min_duration_s = eff.get("min_duration_s", 0.0)
        if max_cps is None and not min_duration_s:
            # This buyer publishes no timing rule, only text rules. Retiming
            # cannot move a line-length verdict, so nothing is changed and the
            # matrix shows the same count before and after. That is the true
            # answer, not a repair that did nothing and claimed a delta.
            repaired[buyer] = srt_text
            changed[buyer] = 0
        else:
            text, n = measure_mod.remediate_subtitles(
                srt_text,
                max_cps=max_cps if max_cps is not None else 0.0,
                min_duration_s=min_duration_s,
            )
            repaired[buyer] = text
            changed[buyer] = n
        leftovers[buyer] = {
            str(k): v
            for k, v in measure_mod.explain_leftovers(
                srt_text,
                max_cps=max_cps if max_cps is not None else 0.0,
                min_duration_s=min_duration_s,
                max_line_chars=eff.get("max_line_chars", 10**6),
                max_lines=eff.get("max_lines", 10**6),
            ).items()
        }
    ctx.state["repaired_srt"] = repaired
    ctx.state["cues_changed"] = changed
    ctx.state["leftover_reasons"] = leftovers
    return changed


def remeasure_every_buyer(ctx) -> dict:
    """Run the same check again on each repaired track. No model.

    This is the number the verdict shows. It is a second measurement of a file
    that exists, never `before minus what we think we fixed`.
    """
    specs = _state_get(ctx, "specs") or {}
    repaired = _state_get(ctx, "repaired_srt") or {}
    before = _state_get(ctx, "before") or {}
    after: dict[str, dict] = {}
    for buyer, spec in specs.items():
        report = measure_mod.measure_subtitles(repaired[buyer], spec=spec)
        after[buyer] = {**report.summary(), "findings": report.findings_as_dicts()}

        # None means that check was never run, which contributes nothing to a
        # count of things the retime was supposed to fix.
        def timing(rep: dict) -> int:
            return (rep["over_cps_count"] or 0) + (rep["under_duration_count"] or 0)

        fixable_before = timing(before[buyer])
        fixable_after = timing(after[buyer])
        if fixable_before > 0 and fixable_after >= fixable_before:
            raise RuntimeError(
                f"Repair did not improve {buyer}: timing violations before="
                f"{fixable_before}, after={fixable_after}"
            )
    ctx.state["after"] = after
    return {buyer: after[buyer]["total_violations"] for buyer in after}


def collect_leftovers_for_triage(ctx) -> dict:
    """Hand the triage node only the cues that are still failing.

    Capped, because a 500-cue track has more leftovers than one model turn can
    usefully judge, and a truncated list that says how many it left behind is
    better than a list that silently drops rows.
    """
    before = _state_get(ctx, "before") or {}
    reasons = _state_get(ctx, "leftover_reasons") or {}
    seen: dict[int, dict] = {}
    for buyer, rep in before.items():
        for f in rep["findings"]:
            reason = reasons.get(buyer, {}).get(str(f["cue_index"]))
            if not reason:
                continue
            row = seen.setdefault(
                f["cue_index"],
                {
                    "cue_index": f["cue_index"],
                    "timecode": f["timecode"],
                    "text": f["text_preview"],
                    "reason": reason,
                    "failing_for": [],
                    "checks": [],
                },
            )
            if buyer not in row["failing_for"]:
                row["failing_for"].append(buyer)
            if f["check"] not in row["checks"]:
                row["checks"].append(f["check"])
    rows = sorted(seen.values(), key=lambda r: r["cue_index"])[:40]
    ctx.state["triage_input"] = rows
    ctx.state["triage_total"] = len(seen)
    return {"leftover_cues": len(seen), "sent_to_triage": len(rows)}


_TRIAGE_INSTRUCTION = """You are a subtitle spotting editor picking up the cues an
automatic retime could not clear.

Each cue below is still failing at least one buyer's delivery spec after the
out-time was extended as far as the next cue allows. The reason field says what
blocked the retime:
  no free space          the next cue starts too soon to give this one more time
  min duration boxed in  even the minimum on-screen time does not fit
  line too long          a text problem; more screen time cannot fix it

For every cue, choose exactly one action:
  split_cue        the text carries two beats and can be split across two cues
  rewrite_shorter  the line has to lose characters to meet the limit
  merge_with_next  this cue is a fragment that belongs with the one after it
  request_waiver   the cue is correct as authored and the buyer should be asked
                   to accept it. Rare, and only when the text cannot be
                   shortened without losing meaning, for example a proper name
                   or a number read aloud.

Cover every cue you are given, once each, using its cue_index exactly. The note
is one short clause a spotting editor can act on without opening the file. Do
not restate the reason. Do not invent cues that are not in the list. Do not
report any measured value.

Cues:
{triage_input}
"""


def triage_agent():
    from google.adk.agents import LlmAgent

    return LlmAgent(
        name="triage_leftovers",
        model=MODEL,
        description="Assigns an editorial action to each cue the retime could not clear.",
        instruction=_TRIAGE_INSTRUCTION,
        output_schema=EditorialQueue,
        output_key="editorial",
    )


# --- the graph ------------------------------------------------------------


def build_workflow():
    """The Cuepass delivery desk graph.

    Fan-out is a tuple in the edge list, one branch per entry in BUYERS. The
    JoinNode holds the deterministic half back until every desk has finished, so
    the measurement always runs against the full set of specs cited this run.
    """
    from google.adk.workflow import START, FunctionNode, JoinNode, Workflow

    desks = tuple(spec_desk(buyer) for buyer in BUYERS)
    join = JoinNode(name="spec_desk_join")
    bind = FunctionNode(func=bind_cited_specs, name="bind_cited_specs")
    measure_node = FunctionNode(func=measure_every_buyer, name="measure_every_buyer")
    repair_node = FunctionNode(func=repair_every_buyer, name="repair_every_buyer")
    remeasure_node = FunctionNode(func=remeasure_every_buyer, name="remeasure_every_buyer")
    collect_node = FunctionNode(
        func=collect_leftovers_for_triage, name="collect_leftovers_for_triage"
    )

    return Workflow(
        name="cuepass_delivery_desk",
        # Counted off the desks actually built, never written down. This string is
        # runtime metadata that surfaces in graph output, so a hardcoded number
        # here would be a false figure printed beside true ones.
        description=(
            f"{len(desks)} delivery-profile desks research their own published "
            "caption spec with Parallel Search and Extract; the same subtitle file "
            "is then measured, repaired and re-measured against every cited spec."
        ),
        edges=[
            (START, desks, join),
            (join, bind, measure_node, repair_node, remeasure_node, collect_node),
            (collect_node, triage_agent()),
        ],
    )


def graph_shape() -> dict:
    """The declared topology, read off the built graph rather than described.

    The UI renders this next to the nodes that actually fired, so a node that
    was declared and never ran is visible as such.
    """
    wf = build_workflow()
    nodes = [
        {
            "name": n.name,
            "kind": type(n).__name__,
            "runs_model": type(n).__name__ in ("LlmAgent", "Agent"),
        }
        for n in wf.graph.nodes
    ]
    edges = [{"from": e.from_node.name, "to": e.to_node.name} for e in wf.graph.edges]
    return {"workflow": wf.name, "nodes": nodes, "edges": edges}
