# W67 / w0816a — Task C other PARTIAL next plan (short)

**Wave:** W67 / w0816a · Task C  
**Scope:** plan only for three residual PARTIAL datasets  
**No bulk OTC / master writes this wave**  
**densify invent COMPLETE:** **forbidden**  
**Commit / push:** **out of scope**

**Live D1 (remote `quant-ingest`, ~2026-08-15T15:26Z):**  
[`.glm-logs/w0816a_w67_coverage/partial_datasets_status_counts.json`](../../.glm-logs/w0816a_w67_coverage/partial_datasets_status_counts.json)

---

## Live residual snapshot

| dataset | COMPLETE | PARTIAL | permanent DEFER id | class |
|---------|---------:|--------:|--------------------|-------|
| `equities_earnings_calendar` | **1** (`2026-08`) | **199** (`2010-01…2026-07`) | **PD-D4-EARN-CAL** | TIP_ONLY_VENDOR |
| `equities_master` | **220** (`2008-05…2026-08`) | **94** (`2000-07…2008-04`) | **PD-D2-MASTER** | MISDATE + PRE_PLAN |
| `jsda_otc_bond_reference_prices` | **93** tip island | **8688** archive | **PD-D5-JSDA-OTC** | ARCHIVE long-tail |

Platform held: Dataset COMPLETE **21** / DEFER **5** / COMPLETE segs **3478**.

---

## 1. `equities_earnings_calendar` (PD-D4-EARN-CAL)

### What is needed next

| item | detail |
|------|--------|
| **Not densify history** | Vendor endpoint is next-business-day / tip calendar only; range shells return tip `Date` → `window_ok=0` for history months |
| **Honest history path** | Prefer **`fins_earnings_date`** for publication-history events (separate dataset; still has tip4 PD-MX-EARN-TIP holes) |
| **Catalog / product** | Either vendor historical range API, or de-scope `history_target_start` / expected segments under explicit product gate — **not** invent by floor-raise alone |
| **Ops** | Keep tip month COMPLETE via cron tip collect only; do not residual-plan 199 history months |

### Why not this wave

- Permanent DEFER already locked (W44); history densify **FORBIDDEN**.  
- No vendor capability change since last re-verify.  
- Closing 199 PARTIAL would require product/catalog decision, not RPM burn.  
- Task C is **plan only** — no residual execute.

---

## 2. `equities_master` (PD-D2-MASTER)

### What is needed next

| residual band | n | next action |
|---------------|--:|-------------|
| **MISDATE** `2006-08…2008-04` | **21** | Wait for in-window `Date` raw (not tip-misdated ~`2008-05-07`); only then seal. No densify-as-success |
| **PRE_PLAN** `2000-07…2006-07` | **73** | Below J-Quants subscription floor (`2006-08-13`); no planner jobs; do **not** raise floor dishonestly |
| Post-2008 plane | **0** PARTIAL | Continuous COMPLETE **220** held — do not re-open |

Optional later (not bulk): targeted R2 re-probe of 1–2 MISDATE months if vendor Date behavior is re-checked; seal **only** if `Date ∈ segment month`.

### Why not this wave

- Permanent DEFER; densify residual 94 **FORBIDDEN** unless true window_ok raw appears.  
- **No bulk master writes** (explicit wave policy).  
- Root cause is vendor Date misdate + subscription floor, not missing ops loops.  
- Raising `history_target_start` past MISDATE invents Dataset COMPLETE — banned.

---

## 3. `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)

### What is needed next

| item | detail |
|------|--------|
| **Tip island** | Hold COMPLETE tip/recent days (live **93**); extend only **FULL_OK** official full CSV days when published |
| **Archive long-tail** | **8688** PARTIAL = archive residual; site timeout/404/403 + R2 MISS class — not auto densify |
| **Seal rule** | FULL_OK only (official `market.jsda.or.jp` full CSV ≥ size floor + parse + receipt); never empty shell COMPLETE |
| **Dataset COMPLETE** | **Never** the goal under current archive scope; tip island ≠ dataset COMPLETE |
| **Later work shape** | Small tip-day digests or CF-egress oneshot for **named** residual days — **not** bulk archive sweep |

### Why not this wave

- Permanent DEFER long-tail; **no bulk OTC writes** this wave.  
- Archive residual is multi-thousand day site capability, not a one-wave close.  
- Task C is plan only; tip island already held at **93**.  
- Inventing COMPLETE or raising floor to tip would abandon archive scope dishonestly.

---

## Cross-cutting (held for all three)

| rule | value |
|------|-------|
| densify as success metric | **no** |
| invent COMPLETE | **forbidden** |
| empty-raw COMPLETE | **forbidden** |
| permanent DEFER densify history | **FORBIDDEN** |
| Mass / READY / Phase7 | **NO-GO / not declared / OFF** |
| this wave writes | **docs/proof plan only** — no bulk OTC/master acquisition |

### Suggested order for a future wave (when product re-opens)

1. **bars_am / earn_cal** — product decision (alternate source or de-scope), not densify.  
2. **master MISDATE** — only if fresh in-window Date raw proven (surgical, not bulk 94).  
3. **OTC** — tip FULL_OK days only; archive in dedicated multi-wave CF-egress budget, never dataset COMPLETE target.

---

## Return card

| field | value |
|-------|------:|
| **earn_cal** | COMPLETE **1** / PARTIAL **199** · next: product/de-scope or fins_earnings_date · **not this wave** |
| **master** | COMPLETE **220** / PARTIAL **94** · next: window_ok Date only · **no bulk** |
| **otc** | COMPLETE **93** / PARTIAL **8688** · next: FULL_OK tip only · **no bulk archive** |
| **bulk OTC/master this wave** | **none** |
| **commit / push** | **no** |

---
