# Cuepass deepeners patch notes

## Deepener 2 (app.py)
In `_buyer_view` spec dict, add:
- search_id from first source_discovery row
- session_id from spec.session_id (already stored on run JSON)

In specBand JS (discovery block ~1883), print search_id and session_id as dedicated spans, and list all search_queries not just [0].

In provenanceHtml, add a "Parallel this run" line that repeats surfaces + instructs judges to read search_id/session_id on the measured-against band.

## Deepener 1 docs
Add README + STORY sections pointing at ./scripts/verify_parallel_cli.sh

## Deepener 5
pytest test_real_data.py -k parallel_search_then_extract -q
