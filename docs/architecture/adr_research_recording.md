# ADR: Research experiment recording (stop wave-script / proof warehouses)

| Field | Value |
|-------|--------|
| **Status** | **Accepted** |
| **Date** | 2026-08-21 |
| **Supersedes** | Informal W99–W107 practice of `scripts/run_wNN_*.py` + `docs/proof/w08*_wNN_*.md` as eval warehouse |
| **Related** | [`../architecture.md`](../architecture.md), [`cf_native_storage_plane.md`](./cf_native_storage_plane.md), [`llm_nav_map.md`](./llm_nav_map.md), [`adr_llm_friendly_refactor.md`](./adr_llm_friendly_refactor.md) |

**Hard constraints (unchanged):** Mass NO-GO · production READY 未宣言 · Phase 7 OFF · invent COMPLETE 禁止 · 3-default pins 非改変 · `research_candidate` 自動昇格禁止.

---

## Context

`architecture.md` already said: Git = code; **experiment branching = Cloudflare Artifacts**.
`cf_native_storage_plane.md` already said: local SQLite is **not** SoT; compute writes **R2** (D1 meta only).

W90–W98 wrote CF `research/mass_eval/job={id}/`. After W99, daily_path_DD lived only locally, and agents started minting a new `run_wNN_*.py` (~1.3–1.7k lines), 4–5 proof markdowns, and a residual paragraph **per wave**. That is not a registry. Trends cannot be queried.

## Decision

| Store | Holds |
|-------|--------|
| **Git** | Evaluators, one/two runners, logic **catalog**, frozen pins, checklist code, thin residual flags, rare ADRs |
| **R2 `quant-structured`** | Eval artifacts (`research/eval/job={id}/` and existing `research/mass_eval/`) |
| **D1 `quant-ingest`** | Small **job + cell index** only (no bars, no daily path arrays) |
| **Local sqlite / `.glm-logs/`** | Compute input / scratch. **Not a record.** |

New hypothesis workflow:

1. Add a logic spec (catalog), and an `evaluate_*` **function** only if the economics are new.
2. Run existing `cf_mass_eval_job` (screen) and/or `daily_path_eval` (candidate-grade).
3. Runner writes R2 + D1 index with `git_sha`.
4. Do **not** add `scripts/run_wNN_*.py` or a wave proof scorecard.

Markdown that restates numbers already in R2/D1 is not a record.

## Agents must not

- Create `scripts/run_wNN_*.py`
- Create `docs/proof/w08*_wNN_*.md` except a genuine policy ADR
- Append ALL-TRACK experiment logs to `phase62_residual_status.md`
- Import `scripts/run_w*` from `mass_strategy_factory` (evaluators are in `research.unique_logic`)

## Two eval planes

1. **CF screen** — `platform/workers/research-mass-eval` period-net. Incomplete vs checklist.
2. **Candidate-grade** — `run_standard_research_eval` + daily_path_DD. Still never auto-promotes.

## Consequences

Importer-zero `run_w*` scripts are deleted on a staged schedule
(`wave_assets_deprecated.md`). Residual is live flags only. Query is D1/R2,
not grep of markdown.
