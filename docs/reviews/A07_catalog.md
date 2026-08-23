# Audit A07 — Catalog remaining (after compiled-n SoT)

> **Pointer (not a rewrite).** At HEAD `07b4435`, occupancy `yaml_remains_sot` is **FIXED** (`yaml_still_present: False`). The body below is a freeze at `03cd1b1` and still speaks as if that item is OPEN.

**Lane:** A07 (catalog SoT)  
**HEAD at remaining-audit:** `03cd1b1`  
**Mass / READY / Phase 7:** NO-GO. Catalog compile is not GO.

FIXED (do not re-open): `catalog_index` `n` / `n_compiled` from migration after YAML deletion (`e8bdf17`); `yaml_still_present: false`; combo jsonl dump has no `yaml_remains_sot`.

---

ID: A07-YAML-REMAINS-SOT  
severity: medium  
affected: `research.occupancy_audit.write_usable_eval_snapshot`; `tests/test_occupancy_audit.py`  
observed fact: At `03cd1b1`, snapshot return still hardcodes `"yaml_remains_sot": True` and the test asserts that. YAML dir is empty (`specs/research_logics/` README only). `catalog_index` / `write_combo_thesis_jsonl` already dropped the flag (`e8bdf17`). Occupancy pack is the leftover SoT lie.  
root cause: occupancy snapshot not updated when compiled map became load SoT.  
why it matters: wave JSON tells operators YAML is still source of truth; contradicts `CATALOG_AND_PLUS_N_STOPPED` + `yaml_still_present: false`.  
structural fix: emit `yaml_still_present` from catalog glob/manifest (false today); stop asserting `yaml_remains_sot is True`. Do not add YAML.  
status: OPEN  

---

ID: A07-FABRICATED-CATALOG-PATH  
severity: medium  
affected: `research.unique_logic.catalog.load_compiled_specs`; `tests/test_unique_logic_catalog.py`; `tests/test_catalog_yaml_parity.py`; `event_combos.assert_yaml_matches_specs`  
observed fact: Compiled rows set `catalog_path` to `catalog_dir / f"{lid}.yaml"` with `catalog_present: False`. File does not exist. Tests pin `path.stem == logic_id` and `path.is_file() is False`. `e8bdf17` kept stem identity on purpose. Combo self-check still names the stem “YAML”.  
root cause: path field reused as identity after YAML deletion.  
why it matters: tools/operators may open `catalog_path` as a real spec; missing file looks like a checkout error, not compiled SoT.  
structural fix: drop `catalog_path` on compiled rows, or mark it `catalog_path_stem` / null when `catalog_present` is false. Keep identity via `logic_id` + migration.jsonl.  
status: OPEN (residual of `e8bdf17`)  
