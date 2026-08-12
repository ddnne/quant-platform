> **Historical snapshot** — not current residual SoT.
> Current residual: [phase62_residual_status.md](phase62_residual_status.md).
> Mass / READY / Phase7: **NO-GO / OFF** unless residual says otherwise.

# Phase 3.5 / 4 ops verification (R1–R7)

**When:** 2026-08-11 JST  
**DB:** `data/structured/ingestion.sqlite`  
**tip:** `38f9012`

| ID | Check | Result |
|----|--------|--------|
| R1 | B0 strict (`b0_pass` QP_LIVE=1) | **PASS** master=4444, bar issuers=4660, latest day rows=4444 (gate≥3000) |
| R2 | Daily validation | **PASS** exit 0 — pass=138 fail=0 skip=3 warn=2 |
| R3 | Weekly `--require-implemented` | **PASS** exit 0 — pass=25 fail=0 skip=4 warn=61 (warn=thin history C6/C7; not_implemented=0) |
| R4 | Phase4 live smoke | **PASS** B0 ok; return_1d hit=0.92 (n=50); trading_days=333≥50 |
| R5 | Premium 23 only | **PASS** n=23; addons not in core |
| R6 | Secrets | **ASSUMED OK** — CF Worker health has_jquants_key; no reissue; keys not logged this run |
| R7 | Docs | This report + `docs/phase35_4_acceptance_status.md` |

**Verdict:** Phase 3.5/4 **ops-close green**. Proceed to Phase 5 (Paper).
