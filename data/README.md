# data/

Gitignored host-local recovery artifacts. Normal operation is Cloudflare:
R2 is persistent authority, D1 holds metadata, and Container SQLite is
ephemeral. Never commit raw dumps or SQLite files.

This tree is created only by opt-in developer/recovery tools
(`QP_ALLOW_LOCAL_MARKET_DATA=1`). It is not the operator store.

Layout (recovery/compatibility):

```
data/
  raw/{source}/{yyyy}/{mm}/{dd}/<file>
  structured/ingestion.sqlite
  tmp/
```
