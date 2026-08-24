# Phase 6.3 — reconstitution pending (human only)

**Lane:** human reconstitution is pending  
**HEAD base:** `3a53732` (`origin/main`)  
**Worktree:** `p63/lane-reconstitution-pending`  
**`RECONSTITUTION_APPLY`:** **False** (must stay False)  
**Mass / READY / Phase 7 / GO:** unchanged (NO-GO / not declared / OFF)

This note records that two primary sleeves still have nested parents.
It does **not** choose an option, restitch a blend, mutate YAML, flip
apply, or GO.

Live residual flags remain [`phase62_residual_status.md`](phase62_residual_status.md).
Catalog SoT is the compiled map (`specs/research_catalog/migration.jsonl`).
Occupancy numbers live on R2/D1, not here. Do not add YAML. Do not
auto-choose `drop_parents` vs `drop_children`.

---

## HUMAN_RECONSTITUTION_PENDING

Source: `research.combo_basket_catalog.HUMAN_RECONSTITUTION_PENDING`.

| `basket_id` | rule | primary | nested parent pairs | auto-chosen? |
|-------------|------|---------|--------------------:|--------------|
| `basket_theme_fund` | `fundamentals_sleeve` | True | 1 | **no** |
| `basket_event_fund` | `event_fund_cross` | True | 3 | **no** |

These two ids are the **only** human-pending reconstitution baskets.
Other active sleeves (`basket_theme_flow` primary; `basket_theme_repo` /
`basket_theme_invert` non-primary) are **not** pending. Historical
`basket_head4` / `basket_event4` / `basket_family4` / `basket_midocc4` /
`basket_cs4` stay historical.

Queue item `reconstitution_human_pending` in `research.eval_tracks` is
the same hold: not a pass, not GO.

---

## drop_parents vs drop_children is HUMAN ONLY

`research.combo_basket_catalog.reconstitution_options` emits both cuts.
`apply_reject` stays False. Empty leftover is recorded, not auto-filled.
**No code path may pick one.**

| Option | Meaning | Who may choose |
|--------|---------|----------------|
| `drop_parents_keep_children` | drop the 2-AND parent of a 3-AND sibling | **HUMAN ONLY** |
| `drop_children_keep_parents` | drop the 3-AND child of nested 2-AND parents | **HUMAN ONLY** |
| auto-choose from occupancy mean / lo | forbidden | nobody |
| auto-choose from stitch / blend | forbidden | nobody |

### `basket_theme_fund` (current KEEP members)

`event_ta_up_positive_eps`, `event_large_surprise_positive_eps`,
`event_ac_peps_taup`, `event_eqar_high_positive_eps`,
`event_positive_eps_liq_high`

Nested pair (detect only): `event_ta_up_positive_eps` ⊂ `event_ac_peps_taup`
(`positive_eps`+`ta_up` ⊂ `afterclose`+`positive_eps`+`ta_up`).

- drop_parents → drop `event_ta_up_positive_eps`
- drop_children → drop `event_ac_peps_taup`

### `basket_event_fund` (current KEEP members)

`event_afterclose_positive_eps`, `event_ta_up_positive_eps`,
`event_large_surprise_positive_eps`, `surprise_xs_afterclose_ta_up`,
`event_ac_peps_taup`

Three nested pairs, all parents of `event_ac_peps_taup`:
`event_afterclose_positive_eps`, `event_ta_up_positive_eps`,
`surprise_xs_afterclose_ta_up`.

- drop_parents → drop those three 2-AND parents (sleeve shrinks to 2)
- drop_children → drop `event_ac_peps_taup`

Neither cut is applied. A later human reconstitution replaces primary
members with a **dated brief**. Until then `RECONSTITUTION_APPLY` stays
False.

---

## Occupancy preview is not a blend and not apply

`research.combo_basket_catalog.reconstitution_occupancy_preview`:

- `apply` is `bool(RECONSTITUTION_APPLY)` → **False**
- `occupancy_mean_not_a_blend` is True (per-member lo / mean is **not** a
  sleeve blend)
- `do_not_restitch_blend` is True
- `human_choice_required` is True
- `go` is False / `not_a_pass` is True
- does not fan out occupancy, does not stitch `net_daily`, does not write
  YAML

`research.occupancy_audit.write_eval_wave_pack` records the same preview
under `eval-reconstitution-plan-{wave}`. That JSON is detect-only.

---

## KEEP sleeves from 24df stay

Recorded KEEP job: `eval-cf-dp-both-sleeves-20260824df`
(`KEEP_BOTH_SLEEVES_JOB`). Current primary members above **stay**. This
lane does not replace them.

`basket_theme_flow` has `needs_reconstitution` False and is not pending.

---

## Do not restitch 24ek

`eval-flow-5th-blend-20260824ek` (`FLOW_FIFTH_BLEND_THINNER_JOB`) is a
thinner-alt record, not a reconstitution. Do **not** restitch it into
KEEP sleeves.

`BLEND_THINNER_KEEP_IDS` stay excluded as replacements:

- `event_afterclose_uncrowded`
- `surprise_xs_peps_uncr`

---

## Do not auto-choose

Forbidden in this lane (and until a human dated brief):

1. Flip `research.eval_flags.RECONSTITUTION_APPLY` to True
2. Pick drop_parents or drop_children from occupancy / lo / DD / stitch
3. Restitch 24ek thinner alts into 24df KEEP members
4. Hand-edit `specs/research_logics/*.yaml` as a reconstitution
5. Treat occupancy preview, series-sleeve candidates, or this markdown
   as a pass / GO
6. Enable Mass / READY / Phase 7 from reconstitution detect

Print the pending pack (does not apply):

```text
python -m research.reconstitution_pending
```

Helper: `research.reconstitution_pending.pending_reconstitution_pack`
reads `reconstitution_occupancy_preview` if it exists. It prints
`HUMAN_RECONSTITUTION_PENDING` plus both human-only cuts. It does not
apply.

---

## Evidence pack (compare only; apply stays false)

`research.reconstitution_evidence.reconstitution_evidence_pack` (also
`research.combo_basket_catalog.reconstitution_evidence_builder`) emits a
comparison artifact for the two human-pending sleeves. It does **not**
choose a live cut, does not flip `RECONSTITUTION_APPLY`, and does not
mutate KEEP 24df members.

Print (does not apply):

```text
python -m research.reconstitution_evidence
```

Default `recommended_choice` is `drop_children_keep_parents` when
economics are not clearly better (prefer 2-condition hypotheses; avoid
3-AND overfit; keep occupancy/breadth; do not shrink event fund to 2).
`evidence_status` is `local_schema_only` or `r2_missing` until live KEEP
job cells are supplied. Do not invent Sharpe. Live R2 put is dry_run
only. `apply` stays False.
