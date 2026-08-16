# W72 / w0816f — bars_am / OTC tip-only policy lock (2026-08-16)

**Wave:** W72 / `w0816f` · Task A  
**Implementer:** GLM5.3 (Grok does not implement)  
**Live verified:** `2026-08-16T05:05:31Z` · Dataset COMPLETE **22** held · PARTIAL **4** · segs **3482** · fins **104/104** · empty **0** · OTC **93** · bars_am **1/31**  
**Mass / READY / Phase7:** **NO-GO / not declared / OFF**  
**empty-raw COMPLETE:** **FORBIDDEN** (held)  
**Invent COMPLETE 23:** **FORBIDDEN** (held)  
**Commit/push:** wave close (Task D)

**Machine logs:** [`.glm-logs/w0816f_w72_tip_only/`](../../.glm-logs/w0816f_w72_tip_only/)  
**Code SoT:** [`packages/data_plane/data_contracts/permanent_defer.py`](../../packages/data_plane/data_contracts/permanent_defer.py)  
**Residual SoT:** [`docs/phase62_residual_status.md`](../phase62_residual_status.md)

---

## Policy lock (W72)

### `equities_bars_daily_am` — PD-D4-BARS-AM

| field | value |
|-------|-------|
| mode | **`tip_continuous`** |
| history | **DEFER** |
| history_reason | **W71 LIVE_API_EMPTY** all **31** PARTIAL months (`2024-01…2026-07`) · sealed_n **0** |
| history_reprobe | **FORBIDDEN** — no regular history re-probe after W71 |
| history_densify | **FORBIDDEN** |
| tip collect | continuous only (vendor `date_mode=today`) |
| empty-raw COMPLETE | **FORBIDDEN** |
| Dataset COMPLETE invent | **FORBIDDEN** (needs honest 32/32; held **1/32** tip `2026-08`) |

Prior W71 proof: [`w0816e_w71_bars_am_history_live_probe_20260816.md`](w0816e_w71_bars_am_history_live_probe_20260816.md).

### `jsda_otc_bond_reference_prices` — PD-D5-JSDA-OTC

| field | value |
|-------|-------|
| mode | **`tip_island_wait_full_ok`** |
| history | **DEFER** (archive long-tail PARTIAL) |
| bulk_densify | **FORBIDDEN** — never densify **8688** archive PARTIALs |
| tip collect | wait official **FULL_OK** tip advance |
| seal_gate | **FULL_OK** (HTTP 200 + body > 1.5MB + nz reconcile) |
| empty-raw COMPLETE | **FORBIDDEN** |
| Dataset COMPLETE invent | **FORBIDDEN** (tip island only; never force dataset COMPLETE) |
| tip island COMPLETE | **93** held (`2026-04-01…2026-08-17` / tip **S260817**) |

Prior W71 rescan: [`w0816e_w71_otc_rescan_20260816.md`](w0816e_w71_otc_rescan_20260816.md) · FULL_OK_NEW **0**.

---

## Code / residual fields

### `permanent_defer.py`

- Module docstring updated: W71 LIVE_API_EMPTY + W72 tip-only ops narrative.
- New machine-readable map: **`TIP_ONLY_POLICY`** for bars_am + OTC.
- Helpers: `is_tip_only_policy`, `tip_only_policy_for`, `history_reprobe_forbidden`.
- Fail-closed research history guards **unchanged** (n=4 DEFER; fins still superseded).
- Exported via `data_contracts.__init__`.

### Residual SoT

`docs/phase62_residual_status.md` TOP = **W72 tip-only ops** · W71 LIVE_API_EMPTY underneath · DEFER **4** held.

### Tests

`tests/test_permanent_defer_history_guard.py` · `test_w72_tip_only_policy_bars_am_and_otc` · suite green.

---

## Explicit non-actions (held)

| claim / action | status |
|----------------|--------|
| bars_am history re-probe / densify | **FORBIDDEN** · not executed |
| invent bars_am Dataset COMPLETE / COMPLETE 23 | **FORBIDDEN** · not claimed |
| OTC bulk archive densify | **FORBIDDEN** · not executed |
| empty-raw COMPLETE | **FORBIDDEN** · empty **0** held |
| Mass / READY / Phase7 ON | **OFF** |
| S1–S5 un-reject | **not done** |
| earn_cal / master bulk densify | **not done** |

---

## Live snapshot (Task C D1; no invent)

| metric | value |
|--------|------:|
| Dataset COMPLETE | **22** |
| Dataset PARTIAL | **4** |
| platform COMPLETE segs | **3482** |
| fins_earnings_date | **104/104** |
| empty COMPLETE | **0** |
| bars_am COMPLETE / PARTIAL | **1 / 31** |
| OTC COMPLETE | **93** |

PARTIAL list: `equities_bars_daily_am` · `equities_earnings_calendar` · `equities_master` · `jsda_otc_bond_reference_prices`.
