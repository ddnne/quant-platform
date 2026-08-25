# SourceCapability V3 authority and required-domain semantics

Status: contract freeze for Phase 6.3.1 P0-C. This document changes no live
projection, READY state, receipt, or JSDA collection queue.

## Authority split

`canonical_datasets.json` is a meta-index. It owns dataset identity,
membership, source, governance tier, routing metadata, and links to owning
contracts. Natural keys, `historical_start`, coverage grain/frequency,
`available_at`, collection windows, and research eligibility are absent from
the meta-index and mechanically derived from the primary PIT contract,
CollectionCoverage, or SourceCapability. `canonical.validate_derived_metadata()`
rejects any reintroduction of those duplicate authority fields.

`SourceCapabilityContract` owns official availability, history mode, query
shape, research eligibility, and the meaning of the required domain.
`CollectionCoverageContract` owns collection history bounds and segmentation;
all V3-owned fields are mechanically derived by
`derive_collection_coverage_v3()`. Operational receipts and coverage state own
what was actually collected. None of these static contracts asserts
`COMPLETE`, `FRESH`, or `READY`.

## Official evidence and exact starts

The repository endpoint catalog in
`packages/data_plane/data_contracts/jquants_premium_core.json` supplies the
endpoint paths, query shapes, event-time fields, and availability fields.
Official availability starts and update schedules come from the J-Quants
[APIs and Data Storage Period by Subscription](https://jpx-jquants.com/en/spec/data-spec)
and [Data Update Timing](https://jpx-jquants.com/en/spec/data-update) pages,
cross-checked with the endpoint specifications linked below.

| dataset | official start / inventory boundary | history mode | required-domain basis | empty successful response |
| --- | --- | --- | --- | --- |
| `equities_master` | 2008-05-07 ([endpoint](https://jpx-jquants.com/en/spec/eq-master)) | `bounded_history` | calendar months from official start | never completes an empty segment |
| `equities_bars_daily` | 2008-05-07 ([endpoint](https://jpx-jquants.com/en/spec/eq-bars-daily)) | `bounded_history` | calendar months from official start | never completes an empty segment |
| `equities_bars_daily_am` | current same-day AM issuance ([endpoint](https://jpx-jquants.com/en/spec/eq-bars-daily-am)) | `recent_snapshot` | issued same-trading-day snapshot | never completes an empty snapshot |
| `fins_summary` | 2008-07-07 ([endpoint](https://jpx-jquants.com/en/spec/fin-summary)) | `event_stream` | publication windows from official start | only a trusted exhausted receipt may complete a genuine zero-event window |
| `fins_details` | 2009-01-13 ([endpoint](https://jpx-jquants.com/en/spec/fin-details)) | `event_stream` | publication windows from official start | only a trusted exhausted receipt may complete a genuine zero-event window |
| `fins_dividend` | 2013-02-20 ([endpoint](https://jpx-jquants.com/en/spec/fin-dividend)) | `event_stream` | publication windows from official start | only a trusted exhausted receipt may complete a genuine zero-event window |
| `fins_earnings_date` | 2014-09-01 ([endpoint](https://jpx-jquants.com/en/spec/fin-earnings-date)) | `event_stream` | publication windows from official start | only a trusted exhausted receipt may complete a genuine zero-event window |
| `equities_earnings_calendar` | current issued next-business-day snapshot ([endpoint](https://jpx-jquants.com/en/spec/eq-earnings-cal)) | `next_business_day_snapshot` | snapshot actually issued by the collection cutoff | never completes an empty snapshot |
| `markets_calendar` | 2008-01-01 ([endpoint](https://jpx-jquants.com/en/spec/mkt-cal)) | `bounded_history` | calendar months from official start | never completes an empty segment |
| `jsda_otc_bond_reference_prices` | 2002-08-02 ([official archive index](https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html)) | `official_archive_index` | official archive publication days | never completes an unlisted or empty day |

`fins_earnings_date=2018-01-01` was an observed repository collection floor,
not the official vendor history boundary. J-Quants explicitly lists September
1, 2014, and the endpoint retains change history keyed by `PubDate`; V3
therefore freezes 2014-09-01 across SourceCapability, CollectionCoverage, and
the validated canonical projection. This expands the required domain but does
not claim those earlier windows were collected.

## Per-row cutoff semantics

- AM bars are a same-trading-day issuance, normally updated around 12:00 JST.
  They are not monthly history and must not be densified into historical empty
  shells.
- Earnings calendar is a next-business-day snapshot, updated only when the JPX
  source page changes (normally around 19:00 JST). Required state is the
  snapshot actually issued by the collection cutoff. Its historical substitute
  is `fins_earnings_date`.
- Listed Issue Master starts on the official 2008-05-07 provision boundary;
  subscription entitlement dates must not be substituted for that boundary.
- JSDA OTC required days are the dates enumerated by the official archive.
  The archive label is the publication day, normally 17:30/18:30 JST on the
  next business day relative to the 15:00 quote observation. Weekends and
  unlisted weekdays are not gaps.

An empty transport response is never sufficient evidence by itself. Snapshot
and archive-index rows use `never_complete`. Event streams allow an empty
window only when a trusted, query-bound, pagination-exhausted receipt proves
the official publication window was actually queried. This contract adds no
receipt implementation and mints no coverage status.
