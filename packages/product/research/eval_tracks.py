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


# Next phase (not GO). Isolate park empty after v21 csFundSnaps hoist.
# Dense parallel work. Do not +N theses until Worker bodies occupancy-equal.
# Standing holds (not queue items): freeze SoT, pins untouched, no head-N,
# no ungated CS sticky, no PARSE_ZERO invent, no correlation weights.
NEXT_RESEARCH_QUEUE: tuple[dict[str, Any], ...] = (
    {
        "id": "pre_mom_occupancy_equal",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "pre_mom leftover uses momentumAt(entryIdx); comboEventGateOk "
            "uses entryIdx-1. Rewrite leftover to match, then lift"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "both_track_sleeve_durability",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "re-eval fund/flow/event sleeves on mid_n_explore AND liq_large; "
            "R2 only; still not a pass"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "cheap_pb_event_reuse",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "event cheap_pb still bars×fins; csFundSnaps not 1:1 with ev.bps hist",
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
        "id": "factory_batch_extract",
        "track": EVAL_TRACK_MID_N,
        "why": "offline/factory.py still ~2939 after template extract; batch eval vs generation",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "single_shot_feature_extract",
        "track": EVAL_TRACK_MID_N,
        "why": "single_shot_job.py ~4107; D1 tip extract already used by r2_feature_context",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "cost_models_boundary",
        "track": EVAL_TRACK_MID_N,
        "why": "cost_models.py ~2732; series construction vs modulation vs document",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "eval_harness_vs_daily_path",
        "track": EVAL_TRACK_MID_N,
        "why": "eval_harness.py ~2733 is W56 next-day; candidate SoT is daily_path",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "event_combos_glue",
        "track": EVAL_TRACK_MID_N,
        "why": "event_combos.py ~1205 after _SPECS delete; evaluate_combo_daily_mtm glue",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "worker_leftover_lid_bodies",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "daily_path.ts leftover lid branches for unique-22 and pre_mom; "
            "reduce only when occupancy-equal to comboEventGateOk"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "economic_theme_yaml",
        "track": EVAL_TRACK_MID_N,
        "why": "ECONOMIC_THEME_IDS still a Python grouping; YAML theme: would drop dual-def",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "multiyear_runner_split",
        "track": EVAL_TRACK_MID_N,
        "why": "offline/multiyear.py ~1947 window stitch vs reporting",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "phase35_matrix_test_split",
        "track": EVAL_TRACK_MID_N,
        "why": "tests/test_phase35_coverage_matrix.py ~1241 slows LLM-local iteration",
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
        "id": "no_new_theses_until_worker_bodies",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "+N YAML clones without occupancy-equal Worker bodies is waste",
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
