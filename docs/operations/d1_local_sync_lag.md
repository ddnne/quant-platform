# D1 → local sync lag (visibility)

**Live 2026-08-12 (remote):**

| Metric | Value |
|--------|--------|
| ingestion_watermarks total | 23 |
| null last_export_cursor | **0** |
| ingestion_change_log rows | ~362 |

Interpretation: export cursors are populated (not all-null). Full research
`applied_cursor` / materialization lag remains a READY-path concern (DEFER / NO-GO).

Minimum one closed visibility path: query watermarks null_export + change_log size
via wrangler/quant-mcp `sync_status`.
