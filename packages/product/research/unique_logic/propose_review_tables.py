"""Propose title polarity / occupancy-label SoT.

Python ``review_proposal_row`` and Worker ``titleOccupancyBad`` must share
these tables. ``scripts/sync_cf_new_thesis_ids.py`` copies them into
``propose_review_tables.ts``. Phrases are space-normalized (hyphens become
spaces in both review paths). Does not inject. Does not GO.
"""

from __future__ import annotations

from research.unique_logic.constants import (
    PROPOSE_ALLOWED_GATES,
    SPARSE_GATE_COMBOS,
)

# Window-only LLM rows. Copied into Worker isWindowTweakOnly. Do not import factory.
PROPOSE_TWEAK_WORDS: tuple[str, ...] = (
    "window",
    "hold_days only",
    "mom only",
    "frac only",
)

# Prompt direction echo. Worker matches after × → x and lowercasing.
PROMPT_DIRECTION_ECHO: tuple[str, ...] = (
    "liquidity × fundamentals",
    "liquidity x fundamentals",
    "margin × price",
    "margin x price",
    "disclosure × funding",
    "disclosure x funding",
)

DEFAULT_PROPOSE_DATASETS: tuple[str, ...] = (
    "equities_bars_daily",
    "fins_summary",
    "markets_calendar",
)

# Prompt prefer list. ⊆ PROPOSE_ALLOWED_GATES. roe_low omitted: recorded
# empty 2/3-ANDs belong in SPARSE, not the prefer seed. cheap_pb is never
# a primary seed (cap). Does not GO.
PROPOSE_PROMPT_PREFER_GATES: tuple[str, ...] = (
    "curve_flatten",
    "overnight_p10",
    "pb_rising",
    "eps_down",
    "np_negative",
    "sales_down",
    "invert_curve",
    "tight_funding",
    "price_down",
)
if not set(PROPOSE_PROMPT_PREFER_GATES) <= PROPOSE_ALLOWED_GATES:
    raise RuntimeError("PROPOSE_PROMPT_PREFER_GATES must be propose-allowed")
if "cheap_pb" in PROPOSE_PROMPT_PREFER_GATES:
    raise RuntimeError("cheap_pb must not be a prefer seed")
if "roe_low" in PROPOSE_PROMPT_PREFER_GATES:
    raise RuntimeError("roe_low empty crosses stay SPARSE, not prefer")


def prompt_direction_echo_x() -> tuple[str, ...]:
    """Unique lowercase x-normalized direction echoes for Worker drop."""
    seen: list[str] = []
    have: set[str] = set()
    for echo in PROMPT_DIRECTION_ECHO:
        token = echo.lower().replace("×", "x")
        if token in have:
            continue
        have.add(token)
        seen.append(token)
    return tuple(seen)

# LLM English titles sometimes invert gate polarity (sales_down → "Rising Sales").
# Review follows GATES, not the title; reject the row rather than adopt inverted copy.
GATE_TITLE_CONTRA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sales_down", ("rising sales", "sales up", "sales growth", "high sales", "sales increase")),
    ("np_negative", ("positive np", "positive profit", "rising profit", "profit up")),
    ("price_down", ("price up", "rising price", "increase in price", "price increase")),
    ("ta_down", ("ta up", "rising ta")),
    ("ta_up", ("ta down", "falling ta")),
    ("eq_ar_falling", (
        "rising eqar",
        "eqar rising",
        "eq ar rising",
        "high eqar",
        "high equity",
        "rising equity",
        "equity risk premium is rising",
        "rising equity risk",
    )),
    ("eq_ar_rising", ("falling eqar", "eqar falling", "eq ar falling")),
    ("eq_ar_low", ("high eqar", "eqar high", "eq ar high")),
    ("eq_ar_high", ("low eqar", "eqar low", "eq ar low")),
    ("tight_funding", ("easy funding", "funding easing", "eased funding")),
    ("easy_funding", ("tight funding", "funding tight")),
    ("eps_down", ("eps up", "rising eps")),
    ("eps_up", ("eps down", "falling eps")),
    ("margin_down", ("margin up", "rising margin")),
    ("margin_up", ("margin down", "falling margin")),
    # nky_vol_high_skip occupancy is skip-when-high OFF, not "vol is high".
    (
        "nky_vol_high_skip",
        ("volatility is high", "vol is high", "high volatility", "nky vol high"),
    ),
    ("crowded_margin", ("uncrowded",)),
    ("uncrowded_margin", ("is crowded", "margin is crowded")),
    ("cheap_iv", ("rich iv", "iv is rich", "expensive iv")),
    ("rich_iv", ("cheap iv", "iv is cheap")),
    ("overnight_easing", ("tightening",)),
    ("overnight_tightening", ("easing", "easy funding")),
    ("repo_3m_down", ("high repo", "repo rate is high", "rising repo", "repo up")),
    # overnight_p10 = easiest/low overnight. "rates are high" is inverted.
    (
        "overnight_p10",
        (
            "rates are high",
            "high overnight",
            "overnight is high",
            "overnight rate is high",
            "overnight rates are high",
            "funding is tight",
            "tight overnight",
        ),
    ),
)

# Occupancy is the gate predicate (EqAR change, repo-down). English slang
# ("risk appetite", "repo is low") is not occupancy — reject rather than adopt.
# Store space-normalized phrases only; polar_blob replaces "-" with " ".
GATE_OCCUPANCY_LABEL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("eq_ar_falling", ("risk appetite", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_rising", ("risk appetite", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_high", ("risk appetite", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_low", ("risk appetite", "risk premia", "risk premium", "risk arbitrage")),
    ("repo_3m_down", ("repo rates are low", "low repo", "repo is low")),
    ("ta_up", ("technical analysis", "technical signal", "ta signals")),
    ("ta_down", ("technical analysis", "technical signal", "ta signals")),
    ("overnight_p10", ("at 10%", "funding at 10", "10 percent", "10% predicts", "funding is loose", "loose")),
    ("pb_rising", ("is rising", "pb rose", "rising price to book", "price to book is rising")),
    ("np_negative", ("profitability is weak", "weak profitability", "weak profit")),
)

# Title claims a gate that is not in the AND-set.
EXTRA_TITLE_GATES: tuple[tuple[str, str], ...] = (
    ("tight funding", "tight_funding"),
    ("funding is tight", "tight_funding"),
    ("funding tight", "tight_funding"),
    ("easy funding", "easy_funding"),
    ("funding is easy", "easy_funding"),
    ("funding easy", "easy_funding"),
    ("eased funding", "easy_funding"),
    ("eps surprises", "eps_down"),
    ("eps surprise", "eps_down"),
    ("sales contraction", "sales_down"),
    ("sales contracted", "sales_down"),
    ("poor sales", "sales_down"),
    ("sales performance", "sales_down"),
    ("sales decline", "sales_down"),
    ("declining sales", "sales_down"),
    ("falling sales", "sales_down"),
    ("sales are down", "sales_down"),
    ("weak sales", "sales_down"),
    ("roe decline", "roe_low"),
    ("roe is low", "roe_low"),
    ("low roe", "roe_low"),
    ("roe down", "roe_low"),
    ("falling roe", "roe_low"),
    ("poor roe", "roe_low"),
    ("profitability is weak", "np_negative"),
    ("weak profitability", "np_negative"),
)

PROPOSE_CONTRADICTORY_GATE_PAIRS: tuple[frozenset[str], ...] = (
    frozenset({"easy_funding", "tight_funding"}),
    frozenset({"crowded_margin", "uncrowded_margin"}),
    frozenset({"eq_ar_high", "eq_ar_low"}),
    frozenset({"eq_ar_rising", "eq_ar_falling"}),
    frozenset({"cheap_iv", "rich_iv"}),
    frozenset({"ta_up", "ta_down"}),
    frozenset({"overnight_easing", "overnight_tightening"}),
    frozenset({"margin_up", "margin_down"}),
    frozenset({"eps_up", "eps_down"}),
)

# Occupancy-label continue exceptions: slang is OK when the predicate is named.
OCCUPANCY_LABEL_EXCEPTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("eq_ar_falling", ("eqar", "eq ar", "equity to asset")),
    ("eq_ar_rising", ("eqar", "eq ar", "equity to asset")),
    ("eq_ar_high", ("eqar", "eq ar", "equity to asset")),
    ("eq_ar_low", ("eqar", "eq ar", "equity to asset")),
    ("ta_up", ("total assets",)),
    ("ta_down", ("total assets",)),
    ("overnight_p10", ("easiest", "percentile", "decile", "p10")),
    ("pb_rising", ("median", "pit median", "above median")),
    ("np_negative", ("net profit", "np is negative", "np negative")),
)


def occupancy_exception_tokens(gate: str) -> tuple[str, ...]:
    for g, tokens in OCCUPANCY_LABEL_EXCEPTIONS:
        if g == gate:
            return tokens
    if gate.startswith("eq_ar"):
        return ("eqar", "eq ar", "equity to asset")
    if gate.startswith("ta_"):
        return ("total assets",)
    return ()


def sparse_gate_combos_for_propose() -> tuple[tuple[str, ...], ...]:
    """SPARSE subsets that can appear in propose AND-sets (economic gates)."""
    out: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for combo, _reason in SPARSE_GATE_COMBOS:
        if not combo <= PROPOSE_ALLOWED_GATES:
            continue
        key = tuple(sorted(combo))
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return tuple(out)


__all__ = [
    "DEFAULT_PROPOSE_DATASETS",
    "EXTRA_TITLE_GATES",
    "PROPOSE_PROMPT_PREFER_GATES",
    "GATE_OCCUPANCY_LABEL",
    "GATE_TITLE_CONTRA",
    "OCCUPANCY_LABEL_EXCEPTIONS",
    "PROMPT_DIRECTION_ECHO",
    "PROPOSE_CONTRADICTORY_GATE_PAIRS",
    "PROPOSE_TWEAK_WORDS",
    "occupancy_exception_tokens",
    "prompt_direction_echo_x",
    "sparse_gate_combos_for_propose",
]
