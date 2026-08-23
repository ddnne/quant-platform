# Audit A01 — Python clean tests (remaining after wave-1)

**Lane:** A01 (clean tests / host isolation)  
**HEAD at remaining-audit:** `03cd1b1` (`origin/main`)  
**Mass / READY / Phase 7:** NO-GO. Do not invent COMPLETE.

Wave-1 already FIXED (do not re-open): eval_loaders tmp sqlite (`4cc0a47`);
receipt tmp keys (`3e46c97`); `trust_env=False` (`331f3c4`); JSDA/JQ
authority-before-write (`5f95b8f`). Residual below is what `5f95b8f` left.

---

ID: A01-JSDA-UNSIGNED-COMPLETE  
severity: high  
affected: `tests/test_jsda_governed.py`; `tests/test_jsda_repo_governed.py`; `tests/test_jsda_corrections.py`; `ingestion.jsda.archive` / `repo_archive` / `corrections`  
observed fact: Happy-path tests still expect segment/dataset COMPLETE (or SUCCESS apply) **without** `receipt_ed25519_keys`.  
- `test_otc_archive_backfill_receipts_raw_resume_and_missing_partial` asserts `evaluate_required_segments` → `["COMPLETE","COMPLETE","PARTIAL"]`.  
- `test_tokyo_repo_runner_raw_receipt_coverage_and_resume` asserts `dataset_coverage.status == "COMPLETE"`.  
- correction happy-path / rerun apply SUCCESS without injecting keys.  
`evaluate_segment` only COMPLETE-eligible on Ed25519 `TRUSTED_COLLECTION`. After `5f95b8f`, those paths call `require_jsda_receipt_authority()` → host `QUANT_RECEIPT_SIGNING_KEY_PEM` or `~/.config/quant-platform/receipt_signing_key.pem`. Fail-closed tests (`*_without_authority`) patch `load_signing_key` → `None`; happy-path does not.  
root cause: authority gate landed; tests still assume a host signing key + production verify registry.  
why it matters: green depends on operator PEM matching `data_contracts/receipt_verify_public_keys.json`. Clean CI / no-PEM hosts fail; host PEM signs unit receipts.  
structural fix: inject `receipt_ed25519_keys` (or equivalent tmp pair + `QUANT_RECEIPT_VERIFY_KEYS`) on every SUCCESS/COMPLETE JSDA/JQ path. Do not COMPLETE on unsigned receipts.  
status: OPEN  

---

ID: A01-HOST-PEM  
severity: high  
affected: `storage.receipt_crypto.load_signing_key`; `storage.trusted_receipt.open_signed_receipt_authority`; `research.readiness._attestation_secret`; tests that omit `receipt_ed25519_keys`  
observed fact: Default private material is host file `~/.config/quant-platform/receipt_signing_key.pem`. Readiness HMAC falls back to SHA-256 of that PEM if `QUANT_READINESS_HMAC_SECRET` is unset. `receipt_ed25519_keys` isolates verify JSON via env, but JSDA/JQ happy-path and readiness tests do not isolate the host private file. Operator machine at audit has the PEM.  
root cause: library load path is env-or-host-file; pytest does not sandbox `Path.home()`.  
why it matters: unit tests can sign with production authority; readiness MAC can bind to the same key.  
structural fix: tests must pass explicit pem/path or monkeypatch `PRIVATE_KEY_FILE` / `load_signing_key`. Never read host PEM in pytest.  
status: OPEN  

Wave-1 unsigned fail-closed (`test_otc_archive_without_authority`, JQ `require_signed_receipt_authority_fails_closed_without_key`) is FIXED and must stay.
