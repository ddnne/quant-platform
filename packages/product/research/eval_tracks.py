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


# Next phase (not GO). Isolate park empty after v21 csFundSnaps hoist.
# Dense parallel work. Do not +N theses until Worker bodies occupancy-equal.
# Standing holds (not queue items): freeze SoT, pins untouched, no head-N,
# no ungated CS sticky, no PARSE_ZERO invent, no correlation weights.
NEXT_RESEARCH_QUEUE: tuple[dict[str, Any], ...] = (
    {
        "id": "both_track_sleeve_durability",
        "track": EVAL_TRACK_LIQ_LARGE,
        "tracks": BOTH_EVAL_TRACK_IDS,
        "entry": "research.cf_daily_path_job.run_both_track_sleeve_fanout",
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
        "id": "unique22_leftover_lids",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": (
            "unique-22 leftover lid bodies remain (event_pre_mom_agree_hold "
            "still momentumAt(entryIdx)); lift only occupancy-equal"
        ),
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "eval_harness_multiyear_shrink",
        "track": EVAL_TRACK_MID_N,
        "why": "eval_harness_multiyear.py ~1615 is W56 checklist/S1; candidate SoT is daily_path",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "factory_eval_shrink",
        "track": EVAL_TRACK_MID_N,
        "why": "offline/factory_eval.py ~1292 batch eval leftover after generation split",
        "not_a_pass": True,
        "go": False,
    },
    {
        "id": "cost_models_modulation_hold",
        "track": EVAL_TRACK_MID_N,
        "why": "cost_models.py ~2255 is live ADV/liquidity/short math; do not fake-split",
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
