# Segment COMPLETE checklist

Live counts live only in [phase62_residual_status.md](phase62_residual_status.md).
Mass, READY, and Pilot do not become GO from this checklist or from green code.

A segment is COMPLETE only when one governed ingestion transaction proves this
minimal invariant chain:

1. The required segment was derived from that dataset's effective Coverage
   policy and SourceCapability; policy id/version/digest match.
2. The actual source request set exactly covers the required time, universe,
   discovery, and pagination scope. An overlapping or filtered request is not
   sufficient.
3. Every verbatim response page is persisted immutable before parsing, with a
   canonical manifest and continuation/discovery chain.
4. The canonical parser and normalizer reproduce the structured transaction.
5. A contract-derived reread of the complete segment has exactly the same
   natural-key set and payloads—no missing or extra rows.
6. The trusted ingestion service derives counts, digests, exhaustion,
   generation, and timestamp itself, then signs an Ed25519
   `TRUSTED_COLLECTION` receipt in the same transaction.
7. The current parser/normalizer authority version and trusted public-key
   registry verify the receipt. Historical signatures remain audit records but
   do not retain eligibility across an authority-version change.
8. The ledger evaluates that receipt and promotes the dataset only if every
   required segment is COMPLETE.
9. A signed, immutable Ops Projection generation binds the resulting D1 rows,
   and its active pointer moves last.

The following are explicitly not COMPLETE:

| Evidence | Result |
| --- | --- |
| `RECOVERED_RAW_ONLY` or operator recovery CLI | audit/reparse input only |
| readonly local file plus caller URL | no trusted acquisition provenance |
| raw/structured counts supplied by a caller | self-report, not reconciliation |
| one day or partial window overlapping a monthly segment | incomplete scope |
| code-filtered query for an all-universe segment | incomplete universe |
| empty response plus caller `EXPECTED_EMPTY_WITH_EVIDENCE` | forbidden override |
| Cloudflare fetch/Cron PASS | acquisition health only |
| FRESH Ops projection | Ops Current, not Research READY |

There is no sanctioned operator command that mints signed COMPLETE from
after-the-fact files. The legacy recovery utilities record non-eligible
evidence only. To advance Coverage, rerun the governed ingestion path for the
exact required scope, refresh the ledger, publish a signed Ops Projection, and
then remeasure it. Never edit `coverage_segments` or receipt claims by hand.

READY adds further gates: canonical exact-four dependency closure, profile and
plan digests, B0/B4 PASS, current non-null source/export/applied cursor,
immutable snapshot publication, and a dedicated READY signature. Pilot READY
cannot authorize Mass.
