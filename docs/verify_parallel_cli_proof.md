# Parallel CLI verify proof (live)

Captured on Mac with `parallel-cli` OAuth (PARALLEL_API_KEY unset in shell).

```bash
export PATH="$HOME/.local/bin:$PATH"
./scripts/verify_parallel_cli.sh
```

Observed output (trimmed):

```
PARALLEL_API_KEY unset; using parallel-cli stored OAuth credentials.
== Search (netflix_en_us hosts) ==
search_id: search_2f4fe5720f8e8755c02db25d5a91f49c
session_id: cuepass-verify-1788984140
results: 10
picked official rank 1: https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide
== Extract (session-linked) ==
extract_id: extract_8ee26f1b850efd715a3434aae4029cd5
extract_url: https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide
search_id: search_2f4fe5720f8e8755c02db25d5a91f49c
session_id: cuepass-verify-1788984140
search_rank: 1
chars_in_extract_payload: 61966
cps_sentences_found: ['17', '20']
OK: Parallel CLI Search then Extract mirrored Cuepass netflix_en_us path.
```

This is the same Netflix EN-US page Cuepass measures against (20 cps adult / 17 cps children).
