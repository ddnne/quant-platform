# data/ (local only)

This directory holds **local-only** ingestion artifacts and is **gitignored**
(see `.gitignore`). Never commit raw dumps or the SQLite DB.

Layout (created on demand by ingestion):

```
data/
  raw/{source}/{yyyy}/{mm}/{dd}/<file>     # verbatim source bytes (Pattern B fetch side)
  structured/ingestion.sqlite               # normalized rows with PIT columns
  tmp/                                       # scratch
```

Future Cloudflare R2 layout (Phase 2+, documented only — not implemented):

```
raw/    -> quant-raw/{source}/{yyyy}/{mm}/{dd}/{file}
structured/ -> quant-structured/{source}/{table}.parquet (or D1 rows)
```
