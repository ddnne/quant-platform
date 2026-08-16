# W82 / w0816q — Task A: event_post PIT definition (no invent timestamps)

**Wave:** W82 / `w0816q` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Task:** **A** Event definition PIT for `event_post`  
**Logs:** [`.glm-logs/w0816q_w82_event/`](../../.glm-logs/w0816q_w82_event/)  
**Code:** `packages/research_runtime/features/class_signals.py` (v5) · `packages/product/research/class_hyp_eval.py` (v5)  
**Tests:** `tests/test_class_signals.py::test_event_post_pit_entry_no_lookahead`

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| invent DiscTime / event times | **forbidden** |
| look-ahead on session close | **forbidden** (W82 entry fix) |
| READY / Mass / Phase7 / operational GO | undeclared / NO-GO / OFF / closed |
| live / continuous paper arm | **OFF** |
| commit / push | **not this task** |

---

## 1. Signal identity

| field | value |
|-------|-------|
| `hypothesis_class` | `event_post` |
| `signal_id` | `c21_event_post_disclosure_hold` |
| class_signals version | **class-signals/v5** (W82) |
| default `post_hold_days` | **5** |
| `entry_mode` | `same_day_close_if_pre_close` |
| status | research `candidate` only (never READY/Mass) |

---

## 2. Source datasets / fields for event datetime (SoT)

### 2.1 Primary: `fins_summary` (J-Quants `/v2/fins/summary`)

Contract (`packages/data_plane/data_contracts/jquants_premium_core.json`):

| contract field | value |
|----------------|-------|
| natural key | `Code`, `DiscDate`, `DiscNo` |
| event_time_policy | `explicit_timestamp_field` |
| event_time_fields | `DiscDate`, `DiscTime` |
| available_at_policy | `explicit_timestamp_field` |
| availability_field | `DiscDate+DiscTime` |
| aliases | `DiscDate`←`DisclosedDate`, `DiscTime`←`DisclosedTime` |
| assumption | explicit disclosure fields; **absent time falls back to ingest — research must not invent 00:00/09:00** |

Loader (`load_fins_events_from_sqlite`):

| event key | source |
|-----------|--------|
| `disc_date` | payload `DiscDate` \| `DisclosedDate` \| `event_time[:10]` |
| `disc_time` | payload `DiscTime` \| `DisclosedTime` (**None if missing — no invent**) |
| `event_time` | SQLite `jquants_records.event_time` (usually DiscDate+DiscTime stamped) |
| `available_at` | envelope column when present |
| surprise fields | `EPS`, `FEPS`, `BPS`; `prior_eps` from chronological prior row with EPS |

Local sample (ingestion.sqlite, n=2000): **DiscTime present on all sampled rows**; majority at/after 15:00 (session close for pre-2024-11-05).

### 2.2 Calendar thickener: `fins_earnings_date` (optional)

Contract:

| field | role |
|-------|------|
| `SchDate` | scheduled earnings / observation date |
| `PubDate` | publication date of the schedule (availability) |
| natural key | `Code`, `PubDate`, `SchDate` |

Loader (`load_fins_earnings_date_from_sqlite`):

| event key | rule |
|-----------|------|
| `disc_date` | `PubDate` **prefer**, else `SchDate`, else `event_time[:10]` |
| `eps`/`feps`/`bps` | **always None** (no invent) |
| `source` | `fins_earnings_date` |

`merge_event_calendars`: same `(code, disc_date)` prefers `fins_summary` (has EPS/FEPS). Earnings-date-only rows **cannot score surprise** → inflate `n_events` only, not `n_scored`.

### 2.3 Price path: `equities_bars_daily` + calendar

Bars supply close series for entry/exit. Non-trading DiscDate → first trading bar **after** calendar day (not invent fills).

---

## 3. When the signal becomes available (PIT)

```text
available_at priority (no invent):
  1. full event_time / envelope available_at ISO if present
  2. DiscDate + DiscTime when both present → "{DiscDate}T{DiscTime}+09:00"
  3. DiscDate only, DiscTime missing → time_unknown
       → do NOT invent 00:00 or 09:00
       → force next-session entry
```

Helpers: `event_post_available_at_from_fields`, `parse_disc_time_hhmmss`, `session_close_hhmmss` in `class_signals.py`.

Session close clock (TSE SoT, aligned with `data_contracts.identity.session_close_jst`):

| date | cash close (JST) |
|------|------------------|
| `< 2024-11-05` | **15:00:00** |
| `≥ 2024-11-05` | **15:30:00** |

**Research surprise** uses only fields on the disclosure row (EPS/FEPS/prior EPS). No future revision pull.

---

## 4. When the position opens

| case | entry bar (close) |
|------|-------------------|
| DiscTime **strictly before** session close on DiscDate, and DiscDate is a trading bar | **same-day close** |
| DiscTime ≥ session close | **next trading bar close** |
| DiscTime missing / unparseable | **next trading bar close** (conservative) |
| DiscDate is non-trading (weekend/holiday) | **first trading bar after DiscDate** |

Implementation: `event_post_entry_bar_index` → `entry_index` on bar calendar.  
Hard guards: entry calendar day never `< DiscDate`; post-close/unknown never same-day when DiscDate is a trading session.

**Not used:** invented open prices; next-open path is not in the bar SoT for this research path (close-to-close only).

Paper runner (separate path) uses `execution_mode=next_close` (decision at session close → fill next close) — more conservative for mid-day disclosures, looser mapping to event-day than research pre-close same-day entry.

---

## 5. Hold horizon

| item | value |
|------|-------|
| horizon | **5 trading sessions** close-to-close from **entry** index |
| formula | `R = close[entry + 5] / close[entry] − 1` |
| cost (research) | one-way **10bp** base, liquidity-linked mult; **amortized** as `one_way / 5` on hold mean |
| signed PnL | `sign(surprise_proxy) * R` |
| non-event days | **no trade** (`value=None`) |

Surprise proxy (`earnings_surprise_proxy`) — no invent:

1. `FEPS − EPS` when both numeric  
2. else `EPS − prior_eps` when prior present  
3. else **None** → not scored  

---

## 6. No look-ahead proof

### 6.1 Unit tests

`tests/test_class_signals.py::test_event_post_pit_entry_no_lookahead`:

* morning DiscTime → same-day entry  
* DiscTime `15:00` (at close pre-cutover) → **next** session  
* after-close `16:30` → next session  
* missing DiscTime → next session, `time_known=False`  
* weekend DiscDate → first trading bar after  

Pytest: **passed** (log `.glm-logs/w0816q_w82_event/pytest_class_signals.log`).

### 6.2 Empirical entry split (DEFAULT_EVAL_CODES · DEFAULT_PERIODS)

From `.glm-logs/w0816q_w82_event/entry_split.json`:

| period | n_events | n_scored | same-day entry | next-session entry | net_bp (PIT) |
|--------|---------:|---------:|---------------:|-------------------:|-------------:|
| y2015_full | 94 | 74 | 19 | 75 | +33.6 |
| y2017_q4 | 30 | 25 | 7 | 23 | +44.5 |
| y2019_full | 168 | 82 | 101 | 67 | **−31.5** |
| y2021_full | 167 | 83 | 100 | 67 | +58.0 |
| y2023_full | 164 | 80 | 100 | 64 | +21.5 |
| y2025_q4 | 71 | 27 | 57 | 14 | **−91.0** |
| **total** | **694** | **371** | **384** | **310** | — |

Scorable fins rows with EPS/FEPS: DiscTime **100%** present in sample; **~72%** at/after session close globally → W81 same-day-always entry was systematically look-ahead for after-hours disclosures.

### 6.3 What W81 did wrong (disclosed)

W81 `evaluate_event_post_on_bars` matched `DiscDate` → bar day (or next bar if holiday) and always used **that close**, ignoring DiscTime. After-hours releases traded the event-day close that was not knowable → **look-ahead**. W82 removes that path.

---

## 7. Code map

| step | location |
|------|----------|
| surprise / signal value | `features.class_signals.compute_event_post_signal` |
| available_at / entry index | `event_post_available_at_from_fields`, `event_post_entry_bar_index` |
| forward return | `multi_day_forward_return` |
| load fins | `research.class_hyp_eval.load_fins_events_from_sqlite` |
| load earnings calendar | `load_fins_earnings_date_from_sqlite` |
| merge | `merge_event_calendars` |
| multi-year eval | `evaluate_event_post_on_bars` · `run_class_hyp_multi_year_eval` |
| approved feature (paper proxy only) | `disclosure_flag_fins` in `complete21_min.py` — **not** the research surprise signal |

---

## 8. Residual honesty

* Surprise proxy is research-grade (FEPS−EPS / EPS−prior), **not** audited PEAD.  
* `fins_earnings_date` thickens calendar; PubDate≠earnings announcement economics.  
* Intraday open/VWAP not used (bar SoT is daily close).  
* Envelope `available_at` can be bulk-ingest polluted on some historical archives; research prefers DiscDate+DiscTime / event_time and documents repair policy elsewhere (`r2_feature_context`).  
* W82 PIT fix **materially changes** research metrics (see Task B proof).

---

## Summary

| question | answer |
|----------|--------|
| Event datetime SoT | `fins_summary.DiscDate+DiscTime` (+ envelope event_time); thickener `fins_earnings_date` PubDate\|SchDate without inventing surprise |
| Signal available | at disclosure timestamp from those fields; missing time → unknown, not invented |
| Position opens | first non-look-ahead session **close** (pre-close same day; else next session) |
| Hold | 5 sessions close-to-close from entry |
| No look-ahead | unit test + entry-mode code + after-close → next bar |

**Return for orchestrator:** PIT definition sealed · code v5 · tests green · no invent · no push.
