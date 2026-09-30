# D1 historical-body reclamation

This is a manual, separately approved operation, not routine ingestion or a
prerequisite for DRAFT research. No reclamation is authorized by this document.
The old Worker `archive-cold` and `prune-changelog` routes are retired. Do not
restore them or invoke old instructions from historical proof documents.

## Decide once for the whole bounded operation

Name the database, table/key or date range, maximum rows/batches, recovery
source, cost/time target and stop conditions. Obtain one grouped approval;
do not ask again for each unchanged batch. Preserve unrelated product resources.

An extra full database backup is not automatically needed. Reuse a verified R2
copy when it contains the required data and provenance. Refetch is a recovery
option only if the provider still supplies the same history and the loss of
original vintage, retrieval cost and downtime are acceptable. Unique raw data,
signed receipts and non-reproducible artifacts must not be treated as replaceable.

## Perform only the approved work

1. Confirm the retired body writer/reader is no longer a current consumer.
   Do not delete metadata that READY, Receipt or Ops still references.
2. Resolve the exact bounded keys and recovery evidence, using indexed queries
   and existing manifests. Do not discover targets with repeated history scans.
3. Delete only the approved keys in bounded transactions. Advance a key cursor
   and use each statement's returned change count; do not repeatedly count the
   whole database before/after each batch.
4. Verify the named recovery/consumer contract with the smallest relevant check.
   Record affected keys/range, actual changed rows and recovery location.

Stop on unexpected rows, active consumers, missing recovery evidence, auth
errors or the agreed bound. Do not delete receipts, coverage, raw-retention or
active projection metadata as a space-saving shortcut. No global PASS or FRESH
claim follows from reclaiming old body rows.
