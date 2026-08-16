# W73 / w0816g — COMPLETE 22 health check (maintain floors) (2026-08-16)

**Wave:** W73 / `w0816g` · Task A  
**Implementer:** GLM5.3 (Grok does not implement)  
**Live verified:** `2026-08-16T07:28:08Z` remote D1 `quant-ingest` + local SQLite  
**FRESH:** `projgen-531e7c3a06e8464b8e57f2ff40471e0c` · coverage_segments untouched · mass=NO-GO  
**Mass / READY / Phase7:** **NO-GO / not declared / OFF**  
**Invent COMPLETE 23:** **not done** · residual note: **coverage expand = tip-wait**

**Artifacts:**

| track | path |
|-------|------|
| Script | [`scripts/check_complete22_health.py`](../../scripts/check_complete22_health.py) |
| Unit tests | [`tests/test_complete22_health.py`](../../tests/test_complete22_health.py) |
| Local verify | [`.glm-logs/w0816g_w73_maintain/health_local.json`](../../.glm-logs/w0816g_w73_maintain/health_local.json) |
| Remote verify | [`.glm-logs/w0816g_w73_maintain/health_remote.json`](../../.glm-logs/w0816g_w73_maintain/health_remote.json) |
| FRESH log | [`.glm-logs/w0816g_w73_maintain/reeval_freshness.log`](../../.glm-logs/w0816g_w73_maintain/reeval_freshness.log) |

---

## 1. Purpose (maintain, not growth)

This is a **not-broken** floor check for Dataset COMPLETE **22**. It does **not**
target COMPLETE 23, densify history, or promote tip-only PARTIALs.

| threshold | rule |
|-----------|------|
| Dataset COMPLETE | **== 22** exact baseline (optional `--complete-floor` → ≥22) |
| Dataset PARTIAL | includes **4** tip-only/DEFER: bars_am, earn_cal, master, OTC |
| fins_earnings_date segs | **104** COMPLETE |
| empty COMPLETE | **0** |
| OTC tip COMPLETE | **≥ 93** floor |
| bars_am tip COMPLETE | **≥ 1** floor |

Residual note baked into report: **coverage expand = tip-wait**.

---

## 2. Live numbers (local + remote — no invent)

| metric | expected | local | remote | pass |
|--------|---------:|------:|-------:|:----:|
| Dataset COMPLETE | **22** | **22** | **22** | ✓ |
| Dataset PARTIAL | **4** | **4** | **4** | ✓ |
| fins segs COMPLETE | **104** | **104** | **104** | ✓ |
| empty COMPLETE | **0** | **0** | **0** | ✓ |
| platform COMPLETE segs | (info) | **3482** | **3482** | held |
| OTC COMPLETE | **≥93** | **93** | **93** | ✓ |
| bars_am COMPLETE | **≥1** | **1** | **1** | ✓ |
| bars_am PARTIAL | (info) | **31** | **31** | held |

### PARTIAL list (n=4 — fins **absent**)

1. `equities_bars_daily_am` (PD-D4-BARS-AM) — tip continuous · history DEFER  
2. `equities_earnings_calendar` (PD-D4-EARN-CAL)  
3. `equities_master` (PD-D2-MASTER)  
4. `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC) — tip island **93**

---

## 3. CLI

```bash
# Local
.venv/bin/python scripts/check_complete22_health.py \
  --db data/structured/ingestion.sqlite --json \
  --out .glm-logs/w0816g_w73_maintain/health_local.json

# Remote D1
.venv/bin/python scripts/check_complete22_health.py \
  --remote --json \
  --out .glm-logs/w0816g_w73_maintain/health_remote.json
```

Unit tests use fixtures / temp SQLite — **no live D1 required**.

---

## 4. Explicit non-declarations

- **READY** — not declared  
- **Mass / Phase7** — **NO-GO / OFF**  
- **COMPLETE 23** — not invented  
- **bars_am history densify / re-probe** — not run  
- **OTC bulk densify** — not run  
- **fins roll-back** — not done (104/104 held)  
