# Quant Ops migration ownership

The Ops Worker no longer owns migrations for `quant-ingest`.

- `migrations/projection/` owns only the dedicated `quant-ops-projection`
  read-model database.
- `migrations/quota/` owns only the dedicated `quant-ops-quota` database.
- `platform/workers/ingestion-premium/migrations/` is the sole migration owner
  for `quant-ingest`.

The pre-isolation root migration sequence was removed because leaving an
inactive second `quant-ingest` migration series in the Ops package made owner
and checksum drift possible. Git history remains the audit record.

`specs/cloudflare/d1_migration_manifest.json` is the deterministic canonical
inventory for all Cloudflare D1 migration files. Regenerate/check it with
`scripts/cloudflare_d1_migration_manifest.py --write` and
`scripts/cloudflare_d1_migration_manifest.py`. Its per-environment
`applied_state` remains `UNVERIFIED`; actual remote state belongs in immutable
release evidence after apply.
