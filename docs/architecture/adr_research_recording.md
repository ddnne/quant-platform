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

1. Add a current strategy/feature definition only if the economics are new; do not expand the retired catalog.
2. Use the authorized cloud personal DRAFT batch or the separately READY-bound Controlled Pilot service.
3. Runner writes immutable results with source/snapshot identity; history stays in R2, D1 holds small metadata.
4. Do **not** add `scripts/run_wNN_*.py` or a wave proof scorecard.

Markdown that restates numbers already in R2/D1 is not a record.

## Agents must not

- Create `scripts/run_wNN_*.py`
- Create `docs/proof/w08*_wNN_*.md` except a genuine policy ADR
- Append ALL-TRACK experiment logs to `phase62_residual_status.md`
- Add a Mass strategy factory or `scripts/run_w*` runners; reuse the current personal/Controlled entrypoints.

## Current execution paths (updated 2026-09-29)

The old daily-path/period-net Python clients are removed; their Worker routes
already refuse execution. Current personal DRAFT uses
`POST /v1/personal-research-batch` against an authorized cloud snapshot.
Controlled Pilot is a different service and requires its existing READY and
Trader evidence. Neither path grants automatic promotion or enables Mass.

Keep comparable return/risk/cost metrics and actual observation periods with
results. A source change or survivor count is not an executed experiment.
Do not spend money just to finish a development turn, and do not persist market
history on the developer's machine. Historical artifacts remain audit records,
not callable execution recipes.

## Consequences

All `scripts/run_w*` are deleted (`ALLOWED_RUN_W` empty)
(`wave_assets_deprecated.md`). Residual is live flags only. Query is D1/R2,
not grep of markdown.
