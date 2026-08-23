# Audit 10 — 26 governed datasets / 4 PARTIAL gaps

**Lane:** J (coverage honesty)  
**HEAD at audit:** `069913c` (later main may have moved; live SoT is quant-mcp + residual)  
**Mass / READY / Phase 7:** NO-GO. **Dataset COMPLETE 23:** forbidden.

Live: 22 COMPLETE held · 4 PARTIAL. Do not invent COMPLETE. Do not shorten `history_target_start`.

---

ID: GAP-AM-001  
severity: high  
affected files/layers: `equities_bars_daily_am`; `collection_coverage.json`; `permanent_defer.py` PD-D4-BARS-AM  
observed fact: PARTIAL 1/32. Vendor AM is recent-only (`code` + `pagination_key`). 31 history months `2024-01…2026-07` cannot be backfilled on this endpoint.  
root cause: VENDOR_TIP_ONLY + missing receipts + stale eval + empty-raw ban  
why it matters: raising the floor to the tip month invents Dataset COMPLETE  
structural fix: keep `history_target_start=2024-01-04`; AM SLA 12:30 is ops freshness, not history COMPLETE; history OHLC is `equities_bars_daily`  
minimal tests retained: empty-raw COMPLETE ban; invent-COMPLETE-23 health  
tests removable after fix: none of the PIT/receipt bans  
residual risk: contract still lists `params=["code","date"]` vs vendor (see JQ-PARAM-008)  
status: OPEN / PARTIAL held  

---

ID: GAP-EARN-002  
severity: high  
affected files/layers: `equities_earnings_calendar`; `plan_required_segments` calendar months; JQ earnings-calendar spec  
observed fact: PARTIAL 1/200. Vendor is next-business-day snapshot (`pagination_key` only). Planner still requires one month per calendar month.  
root cause: FALSE_PARTIAL_SEGMENT_SEMANTICS + VENDOR_TIP_ONLY  
why it matters: 199 missing receipts are not 199 missing source months; fabricating COMPLETE shells is forbidden  
structural fix: grain ADR (`snapshot` / event window) — not a floor bump from 2010-01-04; history dates already COMPLETE via `fins/earnings-date`  
minimal tests retained: event-zero COMPLETE requires trusted receipt  
tests removable after fix: none  
residual risk: JQ contract still `date_mode=range` with `from`/`to`/`date`  
status: OPEN / PARTIAL held  

---

ID: GAP-MASTER-003  
severity: high  
affected files/layers: `equities_master`; `MASTER_JQ_SCOPE`; `permanent_defer.py` PD-D2-MASTER  
observed fact: PARTIAL 220/241. Honest island 2008-05→tip. Remaining 21 months 2006-08…2008-04 are MISDATE clamp (`date=` returns Date=2008-05-07).  
root cause: VENDOR_MISDATE_CLAMP vs SUBSCRIPTION_ENTITLEMENT_FLOOR 2006-08-19 (HTTP 400 plan window, not provision start)  
why it matters: moving floor to 2008-05 invents COMPLETE  
structural fix: keep `history_target_start=2006-08-13`; record 2008-05-07 as metadata only  
minimal tests retained: no_invent_complete_23  
tests removable after fix: none  
residual risk: re-probe only if vendor returns in-window Date  
status: OPEN / PARTIAL held  

---

ID: GAP-OTC-004  
severity: high  
affected files/layers: `jsda_otc_bond_reference_prices`; official-archive planner; `parse_otc_reference_csv`  
observed fact: required 8784 = 5886 COMPLETE + 2898 PARTIAL. Official remaining failed seal = **2 PARSE_ZERO** (`2002-08-02`, `2002-08-05`; 23-col vs 29-col parser). 2898 ≠ 2.  
root cause: CALENDAR_DAY_INVENTORY_OVERHANG + PARSER_SCHEMA_GAP  
why it matters: weekend/non-index calendar ids must not COMPLETE; PARSE_ZERO must not invent  
structural fix: planner grain = official index days (ADR); 23-col parser then seal only if nz parse and raw==struct  
minimal tests retained: empty-raw / PARSE_ZERO not COMPLETE  
tests removable after fix: none  
residual risk: row-count on sealed days is not Dataset COMPLETE  
status: OPEN / PARTIAL held  

---

ID: POL-FLOOR-005  
severity: critical (policy)  
affected files/layers: all four gaps; `CollectionCoverageContract.from_dict` ignores vendor annotation keys  
observed fact: truncating required inventory to the honest island would mint Dataset COMPLETE 23  
root cause: floor bump as fake COMPLETE  
why it matters: the only cheap “close 4 PARTIAL” path is dishonest  
structural fix: keep floors AM 2024-01-04 · earnings 2010-01-04 · master 2006-08-13 · OTC 2002-08-02  
minimal tests retained: `check_complete22_health` invent-23  
tests removable after fix: none  
residual risk: future grain ADRs must not be sold as COMPLETE  
status: blocked in policy; temptation OPEN  

---

ID: POL-EMPTY-006  
severity: medium  
affected files/layers: `evaluate_segment`; MCP `classifyRawAcquisition`  
observed fact: raw 0-row COMPLETE attestation ≠ coverage COMPLETE; event-zero COMPLETE needs trusted receipt  
root cause: collapsing evidence planes  
why it matters: Sunday AM envelope / earnings no-event / OTC PARSE_ZERO would seal  
structural fix: keep five planes (raw / parse / structured / receipt / evaluate)  
minimal tests retained: empty receipt ban; event-zero receipt required  
tests removable after fix: none  
residual risk: MCP raw labels can be misread as Coverage  
status: standing ban  

---

ID: SLA-AM-007  
severity: low (ops)  
affected files/layers: AM inventory SLA `usable_by=12:30`  
observed fact: noon ingest ≠ dataset COMPLETE; projection STALE hides session proof  
root cause: SLA clock confused with history completeness  
why it matters: refreshing `evaluated_at` will not promote 31 months  
structural fix: projection hygiene only; keep PARTIAL  
minimal tests retained: none new  
tests removable after fix: none  
residual risk: PROJECTION_STALE  
status: OPEN / SLA not proven for session  

---

ID: JQ-PARAM-008  
severity: medium  
affected files/layers: JQ AM and earnings-calendar contracts  
observed fact: repo params overstate vendor (`date` / `from`/`to` vs `pagination_key` only)  
root cause: contract drift feeding false history planning  
why it matters: planner invents required months the API cannot fill  
structural fix: contract/grain ADR, not densify, not COMPLETE  
minimal tests retained: identity parity with Worker catalog if params change  
tests removable after fix: none  
residual risk: docs vs live JQ spec  
status: OPEN (not a seal)  
