"""Near-duplicate / gate-soup audit (not an eval warehouse).

Calendar weekday permutations of the same occupancy rule are not distinct
economic theses. Keep one representative per group; park the rest
(main_pool=false). Never a promote / GO.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

NEAR_DUPLICATE_GROUPS: tuple[dict[str, object], ...] = (
    {
        "group_id": "event_weekday_skip",
        "keep": "event_skip_monday",
        "park": ("event_skip_tuesday", "event_skip_wednesday"),
        "reason": "weekday-skip permutation of Monday-gap PEAD",
    },
    {
        "group_id": "event_calendar_window",
        "keep": "event_first_half_month",
        "park": ("event_not_last_week", "event_month_start7", "event_not_first_week"),
        "reason": "month-window permutation of first-half PEAD",
    },
    {
        "group_id": "event_afterclose_calendar",
        "keep": "event_afterclose_skip_monday",
        "park": ("event_afterclose_skip_friday", "event_afterclose_not_last_week"),
        "reason": "afterclose × weekday permutation",
    },
    {
        "group_id": "event_easing_weekday",
        "keep": "event_skip_monday_easing",
        "park": ("event_easing_skip_tuesday", "event_easy_skip_tuesday"),
        "reason": "easing × weekday permutation",
    },
    {
        "group_id": "event_uncrowded_weekday",
        "keep": "event_skip_monday_uncrowded",
        "park": ("event_uncrowded_skip_friday",),
        "reason": "uncrowded × weekday permutation",
    },
    {
        "group_id": "surprise_calendar",
        "keep": "surprise_xs_skip_monday",
        "park": (
            "surprise_xs_skip_tuesday",
            "surprise_xs_not_last_week",
            "surprise_xs_month_start7",
            "surprise_xs_not_first_week",
        ),
        "reason": "surprise calendar permutation of skip_monday",
    },
    {
        "group_id": "surprise_easing_weekday",
        "keep": "surprise_xs_easing_change",
        "park": ("surprise_xs_easing_skip_friday",),
        "reason": "surprise easing × weekday permutation",
    },
    {
        "group_id": "surprise_afterclose_weekday",
        "keep": "surprise_xs_afterclose",
        "park": ("surprise_xs_afterclose_skip_friday",),
        "reason": "surprise afterclose × weekday permutation",
    },
    {
        "group_id": "cs_weekday_skip",
        "keep": "cs_skip_monday",
        "park": (
            "cs_skip_tuesday",
            "cs_skip_wednesday",
            "cs_not_last_week",
            "cs_month_start7",
            "cs_not_first_week",
        ),
        "reason": "CS weekday/calendar permutation of skip_monday",
    },
    {
        "group_id": "cs_easy_weekday",
        "keep": "cs_easy_skip_monday",
        "park": ("cs_easy_skip_friday",),
        "reason": "easy-overnight × weekday permutation",
    },
    {
        "group_id": "cs_overnight_down_weekday",
        "keep": "overnight_down_skip_monday_cs",
        "park": ("overnight_down_skip_tuesday_cs",),
        "reason": "overnight-down × weekday permutation",
    },
)

NEAR_DUPLICATE_PARK: frozenset[str] = frozenset(
    lid
    for g in NEAR_DUPLICATE_GROUPS
    for lid in tuple(g.get("park") or ())  # type: ignore[union-attr]
)

NEAR_DUPLICATE_KEEP: frozenset[str] = frozenset(
    str(g["keep"]) for g in NEAR_DUPLICATE_GROUPS
)


def thesis_fingerprint(spec: Mapping[str, Any]) -> str:
    """Stable id of (kind, gates/cs_gate, side). Calendar skips collapse."""
    kind = str(spec.get("kind") or "")
    params = spec.get("params") if isinstance(spec.get("params"), Mapping) else {}
    gates = tuple(
        sorted(
            str(g)
            for g in (spec.get("gates") or params.get("gates") or ())  # type: ignore[union-attr]
            if g
        )
    )
    cs = str(spec.get("cs_gate") or params.get("cs_gate") or "")
    if cs in {"None", "none"}:
        cs = ""
    side = str(spec.get("side") or params.get("side") or "orig")
    weekday = {
        "skip_monday",
        "skip_tuesday",
        "skip_wednesday",
        "friday_skip",
        "skip_friday",
    }
    window = {"not_last_week", "month_start7", "not_first_week", "first_half_month"}
    gset = set(gates)
    if kind in {"event", "surprise_xs"} and gset and gset <= weekday:
        return f"{kind}|weekday_skip|{side}"
    if kind in {"event", "surprise_xs"} and gset and gset <= window:
        return f"{kind}|month_window|{side}"
    if cs in {
        "skip_tuesday",
        "skip_wednesday",
        "skip_monday",
        "not_last_week",
        "month_start7",
        "not_first_week",
    }:
        return f"cs|weekday_or_window|{side}"
    return f"{kind}|g:{','.join(gates)}|cs:{cs}|{side}"


def is_near_duplicate(logic_id: str) -> bool:
    return str(logic_id) in NEAR_DUPLICATE_PARK


def audit_combo_specs(specs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Group combo specs by fingerprint. Scores stay off this payload."""
    by_fp: dict[str, list[str]] = {}
    rows: list[dict[str, Any]] = []
    for spec in specs:
        lid = str(spec.get("logic_id") or "")
        if not lid:
            continue
        fp = thesis_fingerprint(spec)
        by_fp.setdefault(fp, []).append(lid)
        parked = is_near_duplicate(lid)
        rows.append(
            {
                "logic_id": lid,
                "fingerprint": fp,
                "family_id": spec.get("family_id"),
                "kind": spec.get("kind"),
                "gates": list(spec.get("gates") or spec.get("params", {}).get("gates") or ()),
                "cs_gate": spec.get("cs_gate") or spec.get("params", {}).get("cs_gate"),
                "parked_near_duplicate": parked,
                "keep": lid in NEAR_DUPLICATE_KEEP,
                "main_pool": (not parked) and bool(spec.get("main_pool", True)),
                "why_different_from": list(spec.get("why_different_from") or []),
            }
        )
    soup = {fp: ids for fp, ids in by_fp.items() if len(ids) > 1}
    return {
        "version": "near-duplicate-audit/v1",
        "n_specs": len(rows),
        "n_parked": sum(1 for r in rows if r["parked_near_duplicate"]),
        "n_keep_representatives": len(NEAR_DUPLICATE_KEEP),
        "groups": [dict(g) for g in NEAR_DUPLICATE_GROUPS],
        "soup_fingerprints": soup,
        "promote_as_main": False,
        "go": False,
        "not_a_pass": True,
        "logics": rows,
        "notes": (
            "Gate permutations are not distinct theses. Parked ids stay out of "
            "the candidate pool. Audit is not a promote/GO."
        ),
    }
