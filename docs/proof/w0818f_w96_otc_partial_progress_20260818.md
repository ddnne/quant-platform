# W96 / w0818f — OTC PARTIAL tip progress (Track A)

**Wave:** `w0818f` / **W96** / Track A PRIORITY  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** tip island `wait_full_ok` only · **no** archive bulk densify · **no** invent COMPLETE 23 · Mass **NO-GO**  
**Live verified:** 2026-08-18T14:05Z (local + remote health)  
**Artifacts:** [`.glm-logs/w0818f_w96_data_hyps_defaults/`](../../.glm-logs/w0818f_w96_data_hyps_defaults/)

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **4499** |
| OTC COMPLETE AFTER (local + D1) | **4501** (**+2**) |
| Tip codes sealed | **S260818**, **S260819** |
| COMPLETE span AFTER | **2008-03-25 … 2026-08-19** |
| Dataset-level status | **PARTIAL** held (PD-D5) — never force COMPLETE |
| Platform COMPLETE segs | **7888 → 7890** (+2) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Archive densify | **none** (FORBIDDEN) |

**Return: 4499 → 4501 (+2).**

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | PRE remote | POST local | POST remote |
|--------|----------:|-----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 | 4 |
| OTC COMPLETE | **4499** | **4499** | **4501** | **4501** |
| OTC PARTIAL | 4282 | 4282 | 4282 | 4282 |
| Platform COMPLETE segs | 7888 | 7888 | **7890** | **7890** |
| empty COMPLETE | 0 | 0 | 0 | 0 |
| fins COMPLETE segs | 104 | 104 | 104 | 104 |
| bars_am COMPLETE | 1 | 1 | 1 | 1 |
| all_checks_pass | true | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health.json` · `post_complete22_health.json`

---

## 2. Inventory — tip-waitable vs permanent DEFER

### Dataset-level (permanent DEFER / tip-only)

| Dataset | PD id | Mode | Tip-waitable? | History densify |
|---------|-------|------|---------------|-----------------|
| `jsda_otc_bond_reference_prices` | PD-D5 | `tip_island_wait_full_ok` | **YES** (FULL_OK_NEW only) | **FORBIDDEN** |
| `equities_bars_daily_am` | PD-D4-BARS-AM | `tip_continuous` | YES (cron today) | **FORBIDDEN** |
| `equities_earnings_calendar` | PD-D4-EARN-CAL | vendor tip-only | tip only | DEFER |
| `equities_master` | PD-D2-MASTER | MISDATE + PRE_PLAN | not this wave | DEFER |

### OTC segment buckets (PRE)

| Bucket | n | span | Action |
|--------|--:|------|--------|
| COMPLETE | 4499 | 2008-03-25…2026-08-17 | held |
| PARTIAL | 4282 | 2002-08-02…2026-08-15 | **no bulk densify** |
| — pre-2008 PARTIAL | 1978 | 2002-08-02…2007-12-31 | permanent archive DEFER |
| — 2008+ PARTIAL (incl. weekends/holes) | 2304 | mixed | tip-wait / holiday 404; no force |
| PARTIAL with SUCCESS receipt | **0** | — | nothing sealable without new FULL_OK |

### Tip probe (CF worker `quant-platform-jsda-otc-probe-w80`)

Gate: HTTP **200** AND size **> 1.5MB** → `FULL_OK`.

| code | day | weekday | result | notes |
|------|-----|---------|--------|-------|
| S260817 | 2026-08-17 | Mon | FULL_OK (refetch) | already COMPLETE |
| S260818 | 2026-08-18 | Tue | **FULL_OK_NEW** | sealed this wave |
| S260819 | 2026-08-19 | Wed | **FULL_OK_NEW** | sealed / segment repaired |
| S260820 | 2026-08-20 | Thu | 404 | tip-wait (not published) |
| S260821 | 2026-08-21 | Fri | 404 | tip-wait |
| S260811 | 2026-08-11 | Tue | 404 | island hole (holiday/missing) — leave PARTIAL |
| S260720 | 2026-07-20 | Mon | 404 | island hole — leave PARTIAL |
| S260801/802/808/809/815 | weekends | Sat/Sun | 404 | calendar holes — leave PARTIAL |

Direct `market.jsda.or.jp` from host: **TCP timeout** (same as W70+) → CF egress probe required.

---

## 3. Safe progress executed

1. PRE health snapshot (local + remote) → `pre_complete22_health.json`
2. Tip FULL_OK probe via existing W80 CF worker (no archive re-scan)
3. CF `/fetch` download of S260818 / S260819 → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/`
4. Seal path: parse CSV → normalize → fact upsert → SignedReceiptAuthority SUCCESS → `refresh_coverage_ledger`
   - `2026-08-18`: receipt **908319**, facts **12411**, COMPLETE
   - `2026-08-19`: receipt **908320**, facts **12412**; segment row was briefly missing → surgical `record_required_segments` + refresh → COMPLETE
5. `sync_dataset_coverage_from_segments` → dataset stays **PARTIAL** (honest; 4282 PARTIAL remain)
6. `publish_ops_projection --apply-remote` (guard ok local=7890 remote=7888)
7. POST health → `post_complete22_health.json` (local + remote OTC **4501**)

**Not done (correctly forbidden):** archive PARTIAL densify, empty-raw COMPLETE, invent Dataset COMPLETE 23, Mass.

---

## 4. Next actionable segs (tip-wait)

| Priority | Action | Gate |
|----------|--------|------|
| 1 | Re-probe tip advance **S260820+** on next JSDA publish day | FULL_OK then surgical seal |
| 2 | bars_am tip continuous (premium cron) | nz raw only; history re-probe FORBIDDEN |
| 3 | Do **not** schedule archive OTC PARTIAL backfill | permanent DEFER / bulk densify FORBIDDEN |

Island weekday 404s (e.g. S260811, S260720) remain honest PARTIAL until official FULL_OK appears — do not invent.

---

## 5. Freeze / guardrails held

- Mass **NO-GO**
- READY not declared · Phase7 OFF
- COMPLETE **22** exact · no invent 23
- OTC bulk densify **FORBIDDEN**
- empty COMPLETE **0**
