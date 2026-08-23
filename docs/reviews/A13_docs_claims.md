# Audit A13 — Docs claims remaining (after wave-1 / A10)

**Lane:** A13 (docs honesty)  
**HEAD at remaining-audit:** `03cd1b1`  
**Coverage gaps:** see [`A10_coverage_gaps.md`](A10_coverage_gaps.md) (22 COMPLETE held · 4 PARTIAL; do not invent 23).

Do not restate A10 gap mechanics. Residual claims below.

---

ID: A13-COMPLETE-UNDER-STALE  
severity: high (docs)  
affected: `docs/phase62_residual_status.md`; MCP/projection plane  
observed fact: Residual table lists **COMPLETE datasets 22 held** while **projection STALE** (`projgen-ef18b4f86ee946048161d25e2a30a2a8`). Same paragraph: coverage without an active projection generation is **UNKNOWN**; last-known-good is not current COMPLETE. A10 SLA-AM already notes STALE hides session proof.  
root cause: dataset COMPLETE counts copied from last-known-good ledger under a STALE ops projection.  
why it matters: readers treat “22 COMPLETE” as live Coverage V2. MCP `dataset_coverage` without a FRESH projection is not that claim.  
structural fix: label 22 as last-known-good under STALE / not current; do not promote to FRESH or invent 23. Refresh projection is ops hygiene, not COMPLETE mint.  
status: OPEN  

---

ID: A13-UNIQUE22-PARK-YAML  
severity: low (docs drift)  
affected: `docs/phase62_residual_status.md` (“HOLD: … unique22 park YAML”); `docs/phase63_dead_code.md`; `UNIQUE22_PARK_REASONS` in `unique_logic/worker_bodies.py`  
observed fact: `specs/research_logics/` YAML is gone (`yaml_still_present: false`). Park set is code: `unique22_occupancy_park()` + `UNIQUE22_PARK_REASONS` (17 parked / 5 occupancy-equal lifts). Residual still says “unique22 park YAML”.  
root cause: HOLD sentence not updated after catalog YAML deletion.  
why it matters: implies YAML files to edit/unpark; silent YAML add is forbidden while `CATALOG_AND_PLUS_N_STOPPED`.  
structural fix: docs say park reasons live in `UNIQUE22_PARK_REASONS`; do not add YAML to unpark.  
status: OPEN  

---

ID: A13-GATEWAY-DEPLOYED-NE-PHASE7  
severity: medium (docs)  
affected: `docs/phase62_residual_status.md` (“AI Gateway deployed (`99a745e6-…`)”); `docs/roadmap.md` Phase 7 row (“選抜・Knowledge・AI Gateway”); `docs/architecture/phase7_fail_closed.md`  
observed fact: Worker `research-ai-gateway` is deployed (typed decode FIXED `ccf486a`). Phase 7 remains **OFF** / NO-GO until READY + Coverage V2 COMPLETE. Roadmap Phase 7 title includes “AI Gateway”.  
root cause: deploy id ≠ phase switch.  
why it matters: “AI Gateway deployed” is read as Phase 7 GO. Foundation worker + fail-closed `/v1/complete` is not selection/Knowledge loops.  
structural fix: residual must say deployed ≠ Phase 7; roadmap Phase 7 stays NO-GO.  
status: OPEN  
