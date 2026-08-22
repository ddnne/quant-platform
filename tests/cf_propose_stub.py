"""Historical unbound-AI propose payload shape. Test fixture only.

Live Worker ``/v1/propose-thesis`` returns ``ok:false`` ``llm_failed``.
``research.cf_propose_thesis.invoke_cf_propose_thesis`` never calls this.
Does not write catalog. Does not GO.
"""

from __future__ import annotations

from typing import Any, Sequence

STUB_PROPOSAL_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "thesis": (
            "STUB (not catalog): liquidity × fundamentals — high-ADV names "
            "with conservative EqAR/TA change after disclosure."
        ),
        "signal_definition": (
            "AND(liq_high, EqAR-or-TA-change) on the event window; skip "
            "missing ADV/EqAR/TA (no invent)."
        ),
        "position_rule": (
            "Event-hold original surprise sign when both gates are PIT-true; "
            "otherwise flat."
        ),
        "datasets": ["equities_bars_daily", "fins_summary", "markets_calendar"],
        "gates": ["liq_high", "eq_ar_high"],
        "why_different_from": ["ungated PEAD", "always-on CS EqAR sticky"],
    },
    {
        "thesis": (
            "STUB (not catalog): margin × price disagreement — fade names "
            "where margin is crowded while price still rises."
        ),
        "signal_definition": (
            "AND(crowded_margin, price_up) occupancy; skip missing margin "
            "PIT prints (no ffill)."
        ),
        "position_rule": "CS fade (invert mom) while both gates hold; otherwise flat.",
        "datasets": [
            "equities_bars_daily",
            "markets_margin_interest",
            "markets_calendar",
        ],
        "gates": ["crowded_margin"],
        "why_different_from": ["ungated CS mom", "margin-only crowd fade"],
    },
    {
        "thesis": (
            "STUB (not catalog): disclosure × funding — PEAD only when "
            "overnight repo eased into the print cluster."
        ),
        "signal_definition": (
            "AND(afterclose-or-cluster, overnight_easing) on disclosure; "
            "skip missing repo (no invent)."
        ),
        "position_rule": (
            "Event-hold original surprise sign when funding eased; otherwise flat."
        ),
        "datasets": [
            "equities_bars_daily",
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "markets_calendar",
        ],
        "gates": ["afterclose", "overnight_easing"],
        "why_different_from": ["ungated PEAD", "overnight-level CS sticky"],
    },
)


def stub_propose_thesis_result(
    *,
    n: int = 3,
    why_avoid: Sequence[str] | None = None,
) -> dict[str, Any]:
    want = max(1, min(3, int(n)))
    avoid = {str(x) for x in (why_avoid or ())}
    proposals: list[dict[str, Any]] = []
    for tpl in STUB_PROPOSAL_TEMPLATES:
        if len(proposals) >= want:
            break
        proposals.append(
            {
                "thesis": tpl["thesis"],
                "signal_definition": tpl["signal_definition"],
                "position_rule": tpl["position_rule"],
                "datasets": list(tpl["datasets"]),
                "gates": list(tpl["gates"]),
                "why_different_from": [
                    x for x in tpl["why_different_from"] if x not in avoid
                ],
                "not_injected": True,
                "status": "stub_not_catalog",
            }
        )
    return {
        "ok": True,
        "proposals": proposals,
        "auto_inject": False,
        "go": False,
        "not_a_pass": True,
        "catalog_written": False,
        "ids_injected": False,
    }
