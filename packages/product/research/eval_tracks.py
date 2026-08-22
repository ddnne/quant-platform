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


# Next research queue (not GO). Dense work, not +N calendar clones.
NEXT_RESEARCH_QUEUE: tuple[dict[str, Any], ...] = (
    {
        "id": "cs_fund_scan_linear",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "csFundSnaps hoist shipped in v21; confirm N=100 isolate re-eval",
        "not_a_pass": True,
    },
    {
        "id": "sleeve_members_refresh",
        "track": EVAL_TRACK_MID_N,
        "why": "theme_fund/flow members were chosen on head-N 50; re-pick on ADV tracks",
        "not_a_pass": True,
    },
    {
        "id": "meta_not_a_pass_hold",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "active metas stay descriptive blends; no correlation weights yet",
        "not_a_pass": True,
    },
    {
        "id": "catalog_yaml_as_sot",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "event_combos._SPECS duplicates specs/research_logics YAML",
        "not_a_pass": True,
    },
    {
        "id": "offline_eval_shrink",
        "track": EVAL_TRACK_MID_N,
        "why": "class_hyp_eval/factory/single_shot are W78-W86 offline; CF daily_path is SoT",
        "not_a_pass": True,
    },
    {
        "id": "no_go_until_both_tracks",
        "track": EVAL_TRACK_LIQ_LARGE,
        "why": "GO needs mid_n_explore AND liq_large agreement plus human main; neither exists",
        "not_a_pass": True,
        "go": False,
    },
)


def track_is_not_a_pass(track: Mapping[str, Any] | str) -> bool:
    if isinstance(track, str):
        track = eval_track(track)
    return bool(track.get("not_a_pass")) and not bool(track.get("go"))
