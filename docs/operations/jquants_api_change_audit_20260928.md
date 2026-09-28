# J-Quants personal API change audit — 2026-09-28

Scope: personal V2 API, source changes only. No production rollout, bulk
replacement, historic receipt rewrite, new subscription or research activation
is implied. Existing signed artifacts remain immutable.

## Margin interest

Official [specification](https://jpx-jquants.com/ja/spec/mkt-margin-int),
[release history](https://jpx-jquants.com/ja/spec/release) and
[correction history](https://jpx-jquants.com/ja/spec/fix-data-info) checked today.

- Same endpoint and Date+Code identity. Date means application date, not release.
- Applications from 2026-09-25 have daily observations, PubDate and six Val
  fields. Earlier observations remain weekly; added fields are null, not zero.
- Default Worker collection after launch uses today's published_date; explicit
  today/from/to requests retain application-date semantics for legacy backfill.
  Python's generic client also accepts published_date. Never combine it with
  date/from/to. Historical collection still walks application dates.
- A publication-day fetch is not complete application-month evidence; it stays
  noncanonical and records PubDate as its query axis. It cannot certify COMPLETE.
- Shared availability uses conservative end-of-publication-day for a date-only
  PubDate; no PubDate means ingest time. The approximate 16:00 schedule is not
  an exact historical release timestamp. Thus a Monday publication is not
  usable for Monday's noon decision. Old research-only repair must not backdate
  margin rows to their application date; previously affected results need rerun.
- Generic named-field JSON preservation retains added numeric/null fields and
  ignores response column order. We do not rebuild a fixed 16-column parser.
- Vendor replaced historical Bulk CSVs with the new layout. Our signed saved
  bytes must not be overwritten or relabeled. Any future CSV ingestion must use
  headers and preserve empty added fields as missing values.

Deployment acceptance remains pending: inspect one bounded cloud-only new
publication, its retained R2 raw/structured fields, PubDate visibility and
noncanonical coverage; no authentic market payload is downloaded locally.
Do not call source tests proof of live collection or READY.
