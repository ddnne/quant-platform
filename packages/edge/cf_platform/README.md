# cf_platform

Python half of Cloudflare-adjacent algorithms (Premium ingest validation, natural keys, coverage helpers, B0 volume gates).

**Not** the Workers tree (`platform/workers/**` is path-frozen). **Not** stdlib `platform`.

## Public entry

```python
from cf_platform.ingest_premium import availability, coverage, natural_key, validate, matrix
from cf_platform.live_gates import measure_b0  # order-of-magnitude volume gates — ≠ Mass GO
```

`coverage`, `matrix`, and `live_gates` re-export DataPlane `storage.coverage`,
`storage.matrix`, and `storage.live_gates`. Worker-mirror logic (`validate`,
`availability`, `natural_key`) stays in this package.

## Allowed imports

- `data_contracts`
- `ingestion` (catalog / shared helpers)
- `storage` (coverage / matrix / live_gates re-exports)

## Forbidden

- Importing Worker runtime or moving `platform/workers/**`
- Treating `live_gates` as Mass / READY enablement
- Product packages (`agents`, `gateway`, …)

See [docs/phase35_cf_ingest.md](../../../docs/phase35_cf_ingest.md).
