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

## Other current specifications checked

| Official change / observation | Repository impact and disposition |
| --- | --- |
| Sep14 valuation endpoint, 8 metrics and MktCap | Already catalogued with source capability, bounded backfill implementation and missing-value retention. No duplicate endpoint added. |
| Future removal of bars MktCap, date not announced | Existing AM/price size features return missing when absent (covered by existing tests). Do not silently substitute valuation MktCap: treasury-share definitions differ. A separately versioned valuation-based size feature is still needed before the removal; current size history/experiment results are not redefined. |
| Sep14 EDINET correction reports, ParDocId, RptOblgDate | Generic payload already retains added fields; Code+DocId keeps original and correction distinct. Contract documents the semantics and edinet_code selector. Submission timestamp remains availability, not the obligation date. No standalone numeric trading signal is inferred from a correction or the May1 regime change. |
| Aug17 major-shareholders CurPerSt/CurPerEn and half/quarterly reports | Generic payload retention has no annual-only filter or fixed-column schema; no extra parser needed. |
| Aug10 bars MktCap/ExRT; Aug3 financial ShEq/NCShEq/ROE/NCROE | Named-field raw retention already keeps additions; existing valuation feature uses its explicit dataset. No meaning-changing alias introduced. |
| June8 Premium financial cursor | Full date queries still retrieve complete pages; cursor is an optional incremental optimization, not a replacement for pagination_key. No new always-on poller or cursor framework added. |
| Sector short-ratio frequency | Official spec says daily. Corrected stale weekly Coverage/SLA metadata to trading_day; no backfill or COMPLETE promotion implied. |

Sources: [release](https://jpx-jquants.com/ja/spec/release),
[EDINET](https://jpx-jquants.com/ja/spec/edinet-large-volume-shareholders),
[short ratio](https://jpx-jquants.com/ja/spec/mkt-short-ratio),
[timing](https://jpx-jquants.com/ja/spec/data-update).
This is a release/correction-log and affected-consumer audit, not a claim that
every historical field of every vendor API has been revalidated live.

## Data corrections are not schema changes

The official correction log also identifies TDnet missing records for
2022-08-29/2023-11-02, EQOP settlement/IV on 2026-08-03, and June29 rights-issue
adjustment corrections for codes 17730,33180,37500,38320,38560,45410,57210,63970,
69930,77780,94780. Stored revisions may need targeted cloud re-acquisition.
We have not claimed these historical artifacts were refreshed. Before doing so,
inventory affected cloud objects and entitlement, retain the previous signed
generation, bound the read/write cost and reprove only the affected generation.
Do not redownload the entire history, overwrite signed evidence or silently
relabel old research. EQOP is not the requested primary Nikkei225 option feed.
Pro-only Sep28 minute/futures additions are not personal-API entitlements.
