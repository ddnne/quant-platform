# Quant Data Access MCP

`mcp_servers.quant_data` is the read-only research data surface for ChatGPT,
Claude, and Codex. It accepts domain arguments only; there is no SQL, database
path, filesystem path, R2 listing, ingestion, backfill, publication, approval,
delete, shell, HTTP, token, or broker tool.

Every fact/feature call requires `as_of`. Dataset queries route through PIT,
enforce `available_at <= as_of`, use a verified content-addressed READY
snapshot, and apply dataset/feature allowlists, bounded date spans, row limits,
opaque pagination, and an in-process daily row quota. Features require an
exact approved `(id, version)`. Raw access returns only the dataset/run
`manifest.json` attestation embedded in the READY snapshot.

Tools:

- Catalog: `list_datasets`, `describe_dataset`
- Coverage: `coverage_summary`, `dataset_coverage`, `coverage_gaps`
- Snapshots: `latest_ready_snapshot`, `describe_snapshot`, `diff_snapshots`
- Quality: `quality_summary`, `quality_failures`
- PIT data: `query_dataset`, `get_series`
- Features: `compute_feature`, `compute_features`
- Provenance: `raw_manifest`, `trace_provenance`

Offline smoke:

```bash
.venv/bin/python -m mcp_servers.quant_data --list-tools
.venv/bin/python scripts/ops_status.py --json
```

Run the newline-delimited JSON-RPC stdio server:

```bash
.venv/bin/python -m mcp_servers.quant_data \
  --snapshot-dir data/research_snapshots
```

Operational writes belong in a future, separately authorized DataOps MCP.

