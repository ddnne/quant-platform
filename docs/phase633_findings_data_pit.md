# Independent Data / PIT / Receipt review

**HEAD:** `58133512e1e896f1e811d1fb597337aa8f53d965`  
**vs:** `origin/main` `b5c326a7f612563f2da4a84f08063a307ec38e0a`  
**Scope:** signed vs outer receipt, extra_digests, as_of, VerifiedReceipt, empty-raw COMPLETE, master CURRENT parse, recovery COMPLETE, Python R2 TOCTOU.

Checked closed (not reopened): PIT `available_at <= as_of` + explicit `as_of` on `pit.get_*` / eval sqlite; remote `default_r2_put` refuses CLI put (`python CLI put is not artifact authority`). Honest recovered-raw-only receipts without signature material stay PARTIAL.

### Issue 1 -- Severity: P0
- **File**: packages/data_plane/storage/coverage_ledger.py:1423
- **Description**: `evaluate_segment` grants Coverage COMPLETE from a `CollectionReceipt` plus `is_complete_eligible_receipt` (outer `eligibility==TRUSTED_COLLECTION` and `verify_receipt_signature` over `digests.signed_body_b64` only). There is no `VerifiedReceipt` type. Identity matching (lines 365-373) uses **outer** `source/dataset/segment_id/window/expected_*`. The signed body carries `dataset/segment_id/source/run_id/raw_digest/raw_count/structured_count` (`receipt_crypto.py:256-272`) and is never compared to those outer fields. A valid Ed25519 blob for segment A copied onto a SUCCESS receipt whose outer identity is segment B evaluates COMPLETE for B. Confirmed at this SHA: 2025-01 signed digests transplanted onto 2025-02 outer identity → COMPLETE.
- **Suggestion**: Parse `signed_body_b64` into a bound `VerifiedReceipt`. `evaluate_segment` must accept only that object. Reject unless signed `dataset/segment_id/source/run_id/raw_digest/raw_count/structured_count/pagination_exhausted` equal the outer receipt (and required segment). Do not COMPLETE on detached signature + outer identity.
- **Status**: open

### Issue 2 -- Severity: P0
- **File**: packages/data_plane/storage/coverage_receipts.py:56
- **Description**: `build_collection_receipt` does `digests.update(dict(extra_digests))` after computing `raw`. The only post-update guard strips `TRUSTED_COLLECTION` when signature fields are **absent**. If `extra_digests` already contains `signature` / `signed_body_b64` / `issuer_key_id` (Issue 1 transplant), eligibility stays TRUSTED and `raw` is overwritten by the donor receipt. `SignedReceiptAuthority.issue` (trusted_receipt.py:90-101) blocks extras from replacing `eligibility/signature/signed_body_b64/issuer_key_id/issuer_class` but still copies `raw` and `origin` into the signed dict; the builder then overwrites the computed digest. Confirmed: `extra_digests={"raw": "sha256:"+"ab"*32}` on a real SUCCESS issue → outer `raw` is the fake, `is_complete_eligible_receipt` still True, evaluate COMPLETE. Confirmed: `build_collection_receipt(..., extra_digests=signed_A.digests)` for segment B → COMPLETE for B, outer `raw` is A's digest.
- **Suggestion**: Freeze signed fields after `build_signed_digest_fields`. Never `update()` extras over `raw` / eligibility / signature material. If extras are allowed, they must be a denylist-empty allowlist of non-claim keys. Recompute `raw` from `raw` bytes last, or drop extras on the COMPLETE path.
- **Status**: open

### Issue 3 -- Severity: P0
- **File**: packages/data_plane/ingestion/jquants/receipts.py:74
- **Description**: Empty-bytes SUCCESS is rejected (`not raw`) and evaluate PARTIALs `raw_page_count==0`. Empty **envelope** is not: `authority.issue(raw=b'{"data":[]}', observed_items=1, structured_row_count=1)` is COMPLETE-eligible and evaluate COMPLETE (raw_page_count=1, digest present, observed==expected). `emit_segment_receipt` only tests falsy bytes. `scripts/issue_signed_receipts_for_segments.py:65-75` rejects `[]`/`{}` but accepts `{"data":[]}` (the parallel CLI bans that envelope). That CLI then sets `observed_items` to `expected_items` for `source_query` (lines 298-300) even when the raw file has zero rows, as long as `--min-structured` is met from `jquants_records` (possibly a CURRENT ingest in the same calendar window). That mints Coverage COMPLETE over empty vendor payload.
- **Suggestion**: Ban empty envelopes in `SignedReceiptAuthority.issue` and both issue CLIs (share `issue_receipts_parallel._is_usable_raw`). COMPLETE must use counts from the signed raw, not from unrelated structured rows or `expected_items`.
- **Status**: open

### Issue 4 -- Severity: P0
- **File**: platform/workers/ingestion-premium/src/master_scd2/write.ts:136
- **Description**: `loadCurrent` on JSON parse failure (or missing `by_code`) returns `{count:0, by_code:{}}` and does not fail closed. `writeMasterScd2` then diffs incoming listed-info against that empty snapshot and unconditionally `put`s `structured/scd2/equities_master/CURRENT.json`. A corrupt / HTML / schema-mismatched CURRENT plus a partial page becomes the entire master (prev empty skips the “preserve previous codes” branch at line 205). Codes disappear from CURRENT without DELISTED events. This is not Coverage COMPLETE; it is silent SCD2 wipe / empty snapshot from CURRENT parse.
- **Suggestion**: Fail the ingest if CURRENT exists and cannot be parsed as `equities_master_scd2_current/v1` with a `by_code` object. Do not put CURRENT until the previous snapshot is verified. Treat parse miss like a 409, not an empty universe.
- **Status**: open

### Issue 5 -- Severity: P1
- **File**: packages/data_plane/storage/coverage_ledger.py:1423
- **Description**: `receipt_eligibility` maps `origin in {recovered-raw-only, parsed-staging-only, failed-collection}` to `RECOVERED_RAW_ONLY`. `is_complete_eligible_receipt` / `evaluate_segment` do not. JSDA staging writes SUCCESS + `origin=parsed-staging-only` without a signature (r2_parse.py:183-186) and correctly stays PARTIAL. The same origin (or `recovered-raw-only`) plus any valid signature blob — including Issue 1/2 extras — evaluates COMPLETE. Recovery evidence is not a COMPLETE ban at the gate that actually mints status.
- **Suggestion**: `is_complete_eligible_receipt` must return False for recovered / staging / failed origins and for `eligibility!=TRUSTED_COLLECTION` after origin check. Staging SUCCESS must remain unsigned and unevaluable as COMPLETE.
- **Status**: open

Unresolved P0 count: 4
