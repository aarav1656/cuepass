"""Produce the run Cuepass opens on, by actually running it.

The landing state has to be a real measurement, so it is made by driving the
same graph the Run button drives, against the same archive.org file, and writing
down whatever came out. Nothing in `data/runs/` is typed by hand.

    export PARALLEL_API_KEY=...
    export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=...
    python seed_run.py [identifier]

The record it writes carries `measured_at`, which the page shows, so a reader can
see how old the landing measurement is and re-run it themselves.
"""

from __future__ import annotations

import json
import logging
import sys

import agent
import runstore


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    identifier = sys.argv[1] if len(sys.argv) > 1 else agent.DEFAULT_FILM

    record = agent.run_agent(identifier)

    timing_before = 0
    timing_after = 0
    print(f"\nrun {record['run_id']} measured at {record['measured_at']}")
    print(f"{record['film_title']}, {record['cue_count']} cues")
    print(f"source {record['subtitle_url']}\n")
    for buyer, entry in record["buyers"].items():
        spec = entry["spec"]
        before, after = entry["before"], entry["after"]
        tb = before["over_cps_count"] + before["under_duration_count"]
        ta = after["over_cps_count"] + after["under_duration_count"]
        timing_before = max(timing_before, tb)
        timing_after = max(timing_after, ta)
        print(f"  {spec['platform']}  [{entry['verdict']}]")
        print(f"    cited {spec['source_url']}")
        for name, ev in spec.get("evidence", {}).items():
            print(f"      {name} = {ev['value']}   \"{ev['clause'][:100]}\"")
        skipped = before.get("checks_skipped") or []
        if skipped:
            print(f"      not published by this buyer, so not measured: {', '.join(skipped)}")
        print(
            f"    violations {before['total_violations']} -> {after['total_violations']}"
            f"   timing {tb} -> {ta}   cues retimed {entry['cues_changed']}"
        )
    for buyer, reason in record.get("unavailable", {}).items():
        print(f"  {buyer}: no citable spec page. {reason}")

    if timing_before == 0:
        print("\nFAILED: the seeded run has no timing violations to repair.")
        print("A landing page that opens on a clean file demonstrates nothing.")
        return 1

    print(f"\nstored in {record.get('stored_in')}")
    print(f"repaired tracks: {json.dumps(record.get('repaired_files', {}))}")
    print(f"runs now listed: {len(runstore.list_runs())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
