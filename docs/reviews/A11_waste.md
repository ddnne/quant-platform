# Audit A11 — Waste / leftover identity (remaining)

**Lane:** A11 (waste vs HOLD identity)  
**HEAD at remaining-audit:** `03cd1b1`  
**Mass / READY / Phase 7:** NO-GO. Do not unfreeze catalog to “use” leftover helpers.

---

ID: A11-COMBO-PLUS-N-HOLD-IDENTITY  
severity: medium (policy HOLD, not dead code)  
affected: `research.eval_flags.CATALOG_AND_PLUS_N_STOPPED`; `EVENT_THREE_AND_PLUS_N_STOPPED`; `occupancy_guards.assert_catalog_and_plus_n_stopped`; `catalog_compiler`; `catalog_ids.ts`  
observed fact: Combo AND +N expansion is frozen at compiled n=2254. `assert_catalog_and_plus_n_stopped` refuses yaml n or compiled n ≠ freeze. Identity tests (`test_catalog_yaml_parity`, compiler digest) treat `RESEARCH_UNIQUE_LOGIC_IDS` == compiled migration == Worker `catalog_ids.ts`. Expanding combos would change that identity set. Runtime still named `yaml_combo_rows` / `combo_row_from_yaml` after YAML deletion.  
root cause: identity freeze, not unused expansion machinery.  
why it matters: “waste” cleanup that deletes guards or resumes +N without a dated brief would drift Worker/Python identity. HOLD is correct.  
structural fix: keep freeze. Any +N needs a dated brief that flips the flags **and** re-emits compiled map + `catalog_ids.ts`. Do not treat HOLD as D-dead.  
status: HOLD (identity)  

---

ID: A11-YAML-REMAINS-SOT  
severity: medium  
affected: `research.occupancy_audit.write_usable_eval_snapshot`  
observed fact: Occupancy snapshot still advertises `yaml_remains_sot: True` while catalog load SoT is compiled (`e8bdf17`). Same leftover as A07-YAML-REMAINS-SOT.  
why it matters: waste signal to operators (write YAML) after YAML was removed.  
status: OPEN (see A07)  

---

ID: A11-CELLS-CANDIDATE-COUNTS  
severity: low  
affected: `research.candidate_policy.cells_candidate_counts`  
observed fact: Helper is defined next to `job_candidate_grade` and has **zero** importers (packages / tests / Worker). Live grade path is counts already aggregated, then `job_candidate_grade` (`evaluation_ir`, `eval_summary`, `combo_basket`).  
root cause: unused cell-aggregation twin of the shared predicate.  
why it matters: a second counting definition can drift from Worker `daily_path` / IR golden if someone starts calling it.  
structural fix: wire it as the single cell→counts path **or** delete it. Do not copy `job_candidate_grade`.  
status: OPEN (unused)  
