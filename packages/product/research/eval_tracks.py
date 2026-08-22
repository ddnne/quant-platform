"""First-class research eval tracks. Not a pass / not GO.

mid_n_explore
    50–80 names, ADV-ranked (never head-N). Explore band for
    theme_fund / theme_flow materials.

liq_large
    100 names, ADV-ranked skip-missing. Durability check at scale.

Neither track is a stability or promote/GO call. Do not narrate the
factory from a single print.
"""
from __future__ import annotations

from typing import Any, Mapping

UNIVERSE_SELECT_ADV: str = "adv_desc_skip_missing_bars_and_fins"

EVAL_TRACK_MID_N: str = "mid_n_explore"
EVAL_TRACK_LIQ_LARGE: str = "liq_large"
BOTH_EVAL_TRACK_IDS: tuple[str, ...] = (EVAL_TRACK_MID_N, EVAL_TRACK_LIQ_LARGE)

EVAL_TRACKS: dict[str, dict[str, Any]] = {
    EVAL_TRACK_MID_N: {
        "track_id": EVAL_TRACK_MID_N,
        "max_codes": 80,
        "min_codes": 50,
        "universe_select": UNIVERSE_SELECT_ADV,
        "head_n_forbidden": True,
        "preferred_materials": ["basket_theme_fund", "basket_theme_flow"],
        "role": "explore_band_50_80",
        "not_a_pass": True,
        "go": False,
        "promote_as_main": False,
    },
    EVAL_TRACK_LIQ_LARGE: {
        "track_id": EVAL_TRACK_LIQ_LARGE,
        "max_codes": 100,
        "min_codes": 100,
        "universe_select": UNIVERSE_SELECT_ADV,
        "head_n_forbidden": True,
        "preferred_materials": ["basket_theme_fund", "basket_theme_flow"],
        "role": "adv_large_durability",
        "not_a_pass": True,
        "go": False,
        "promote_as_main": False,
    },
}


def eval_track(track_id: str | None = None) -> dict[str, Any]:
    tid = str(track_id or EVAL_TRACK_LIQ_LARGE).strip()
    spec = EVAL_TRACKS.get(tid)
    if spec is None:
        raise KeyError(f"unknown eval track {tid!r}; known={sorted(EVAL_TRACKS)}")
    return dict(spec)


def infer_eval_track(*, max_codes: int) -> str:
    """Map N onto a track. Never infers head-N."""
    n = int(max_codes)
    if n <= int(EVAL_TRACKS[EVAL_TRACK_MID_N]["max_codes"]):
        return EVAL_TRACK_MID_N
    return EVAL_TRACK_LIQ_LARGE


NEXT_RESEARCH_QUEUE: tuple[dict[str, Any], ...] = (
    {
        "id": "cf_propose_llm_not_stub",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "Workers AI 70B then glm-4.7-flash then 8B CF-internal; "
            "parse fills missing signal/datasets; llm_failed is ok:false not "
            "stub ok:true; no auto-inject"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "inventory_bias_recorded",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "recorded research/eval/job=eval-inventory-bias-20260824ai/ "
            "inventory_bias.json; assert_new_batch_cheap_pb_cap refuses "
            "new batches at 20%; 24aw adopted np×tight thin (~0.081)"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "propose_review_no_inject",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "review_proposal_row is the adopt gate; occupancy-equal Worker "
            "body required before a thesis counts; never catalog inject"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "propose_clone_retry",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "why_avoid prepends SPARSE economic ANDs then newest 3/2-gates; "
            "zero-adopt retries once (clone/sparse extra; polarity keeps AND); "
            "still no auto-inject"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "llm_title_gate_polarity",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "review_proposal_row title_gate_polarity_mismatch and "
            "occupancy_label_only; Worker prompt joins generated "
            "PROPOSE_ALLOWED_GATES / prefer / GOOD example; YAML follows GATES"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "cheap_pb_event_reuse",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "event cheap_pb = bars×fins close/bps; CS cheap_pb = csFundSnaps; "
            "CHEAP_PB_UNIFIED=false; do not invent a shared book"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "otc_parse_zero",
        "track": EVAL_TRACK_MID_N,
        "why": "jsda_otc remaining official 2002 PARSE_ZERO (2002-08-02, 2002-08-05)",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "unique22_leftover_lids",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "5 leftover occupancy-equal lifts send params.gates (comboImpl); "
            "17 parked unique22_occupancy_mismatch; pre_mom leftover stays "
            "momentumAt(entryIdx)"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "options_225_vol_series_hold",
        "track": EVAL_TRACK_MID_N,
        "why": "options_225_vol_series.py ~1140 is live ATM/skew/term math; do not fake-split",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "cost_models_modulation_hold",
        "track": EVAL_TRACK_MID_N,
        "why": "live math stays in cost_models; daily_path uses ADV 3-bucket + repo short-drag fail-closed missing ADV",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "local_combo_fail_closed",
        "track": EVAL_TRACK_MID_N,
        "why": (
            "Python evaluate_combo_daily_mtm fail-closes gated combos; "
            "Worker comboEventGateOk is SoT — do not dual-def predicates"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "meta_not_a_pass_hold",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "active metas stay equal-weight descriptive blends; no correlation weights",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "month_start_leftover_hold",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "surprise_xs_month_start leftover dd>05 vs catalog first_half_month "
            "dd<=15; do not drop leftover without catalog retune + re-eval"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "both_track_sleeve_durability",
        "track": EVAL_TRACK_LIQ_LARGE,
        "tracks": BOTH_EVAL_TRACK_IDS,
        "entry": "research.cf_daily_path_job.run_both_track_sleeve_fanout",
        "why": (
            "recorded eval-cf-dp-both-sleeves-20260824e mid+liq 12 logics "
            "including flatten×eps; 24l flatten×px not added (5-member cap); "
            "descriptive summary not_a_pass; do not narrate majority as stable"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "thesis_counts_only_with_worker_body",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "catalog+Worker body+gates implemented; YAML-only clones do not count",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "plus32vf_near_empty_not_materials",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "eval-occupancy-audit-20260823i: 4/32 plus32vf near_empty on "
            "both tracks including occupancy 0; CANDIDATE_POLICY excludes; "
            "prefer propose-adopt over hand-enumerated soup"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "unique22_park_map_recorded",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "eval-unique22-park-20260823i/park.json file-level reasons; "
            "17 park; do not silent unpark leftover occupancy"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "adopt_occupancy_recorded",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "eval-occupancy-audit-20260824aw both tracks: np×tight ~0.081 "
            "thin not sleeve; flatten_eps band not exceeded; not a pass"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "near_empty_parked_not_countable",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "NEAR_EMPTY_PARK_IDS includes 24aa p10×sales×eps_up; "
            "is_countable_spec and validate_basket_members exclude them; "
            "assert_new_batch_occupancy_not_near_empty refuses empty batches"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "factory_template_default_off",
        "track": EVAL_TRACK_MID_N,
        "why": (
            "LogicTemplate.generation_enabled defaults False; bar-native "
            "and factory-only set True explicitly; unique/combo stay off"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "no_go_until_both_tracks",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "GO needs mid_n_explore AND liq_large agreement plus human main",
        "not_a_pass": True,
        "go": False,
    },
)


def track_is_not_a_pass(track: Mapping[str, Any] | str) -> bool:
    if isinstance(track, str):
        track = eval_track(track)
    return bool(track.get("not_a_pass")) and not bool(track.get("go"))
