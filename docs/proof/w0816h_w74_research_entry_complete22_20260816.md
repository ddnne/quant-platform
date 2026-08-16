# W74 / w0816h — Research entry under COMPLETE 22

**Wave:** W74 / `w0816h` · 2026-08-16  
**Purpose:** Document the **only** research entry path under Dataset COMPLETE **22** maintain baseline.  
**Not:** coverage expand · Mass ON · READY declare · invent COMPLETE 23 · S1–S5 un-reject.

---

## Prerequisites (must all hold)

| gate | required |
|------|----------|
| Dataset COMPLETE | **22** (exact; do not invent 23) |
| COMPLETE 22 health | **OK** via `scripts/check_complete22_health.py` |
| COMPLETE expand | **tip-wait** only (no history densify invent) |
| Mass / READY / Phase7 | **OFF / NO-GO / 未宣言** |
| empty COMPLETE segments | **0** |
| S1–S5 | **`research_baseline_rejected`** (catalog) |

---

## How to run COMPLETE 22 health

```bash
# Local SQLite
.venv/bin/python scripts/check_complete22_health.py \
    --db data/structured/ingestion.sqlite

# Remote D1
.venv/bin/python scripts/check_complete22_health.py --remote

# Both + JSON
.venv/bin/python scripts/check_complete22_health.py \
    --db data/structured/ingestion.sqlite --remote --json
```

Floors: COMPLETE==22 · PARTIAL defer4 · fins segs 104 · empty 0 · OTC≥93 · bars_am≥1.  
Health is a **maintain floor**, not a growth target.

---

## Research entry (default)

Use the W66 standard checklist entry — **not** ad-hoc short-window notebooks.

```python
from research.eval_harness import run_standard_research_eval

# wiring_only / dry_run: freezes + cost + window design (no heavy R2)
out = run_standard_research_eval(dry_run=True, mode="wiring_only")
assert out["checklist_version"] == "standard-research-eval-checklist/v1"
assert out["ready_declared"] is False
assert out["mass_research"] == "NO-GO"
assert out["phase7"] == "OFF"
assert out["research_candidate"] is False  # never auto-promotes
```

| rule | held |
|------|------|
| Checklist | `standard-research-eval-checklist/v1` |
| Default entry | `run_standard_research_eval` |
| Gate | cost-aware v2 (`net_sign_majority`, 10bp one-way) |
| Short-window-only | **insufficient** for `research_candidate` |
| Pass → READY/Mass | **never** |

Module / package notes: [`packages/product/research/README.md`](../../packages/product/research/README.md).  
Checklist proof: [`w0815bg_w66_standard_research_eval_checklist_20260815.md`](w0815bg_w66_standard_research_eval_checklist_20260815.md).  
Harness proof: [`w0815bg_w66_standard_eval_harness_entry_20260815.md`](w0815bg_w66_standard_eval_harness_entry_20260815.md).

---

## Forbidden (this entry path)

- Re-candidate / un-reject **S1–S5** (`research_baseline_rejected` stays)
- Declare **READY** or arm **Mass** / Phase7 ON
- Mint **empty COMPLETE** or invent **COMPLETE 23**
- Short-window-only candidate claim
- New simple daily signs from this path
- bars_am history re-probe · OTC bulk densify

---

## Residual link

Residual TOP (W74) points here: [`docs/phase62_residual_status.md`](../phase62_residual_status.md).  
Close proof: [`w0816h_w74_research_entry_close_20260816.md`](w0816h_w74_research_entry_close_20260816.md).
