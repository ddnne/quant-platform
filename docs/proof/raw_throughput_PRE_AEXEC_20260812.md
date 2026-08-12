# Raw throughput report (PRE_AEXEC)

- generated_at: `2026-08-12T13:58:21+00:00` (session start; local research mirror)
- note: Local/research mirror metrics. Not CF control-plane SoT. Remote D1 raw captured separately via wrangler RO.

## raw_retention_manifests (local)

| metric | value |
|--------|------:|
| total | 0 |

## Remote D1 (wrangler RO at PRE)

| metric | value |
|--------|------:|
| total | 1488 |
| COMPLETE | 1449 |
| FAILED | 39 |

## coverage (local)

| metric | value |
|--------|------:|
| complete_segments | 404 |
| complete_datasets | 2 |
| stale_datasets | 1 (`markets_margin_interest`) |
| projection | FRESH |

Track A focus: equities/topix PARTIAL; margin STALE. Worker pass ≠ COMPLETE.
