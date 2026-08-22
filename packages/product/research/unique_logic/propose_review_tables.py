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

# Occupancy-correct English for prefer gates. YAML follows these predicates.
_GATE_OCCUPANCY_SENTENCE: dict[str, str] = {
    "curve_flatten": "the repo curve flattened",
    "overnight_p10": "overnight is in the easiest PIT decile",
    "pb_rising": "PB is above its PIT median",
    "eps_down": "EPS contracted versus the last prior print",
    "np_negative": "net profit is negative",
    "sales_down": "sales contracted versus the last prior print",
    "invert_curve": "the repo curve inverted",
    "tight_funding": "overnight funding is tight",
    "price_down": "price is down",
    "steep_curve": "the repo curve is steep",
    "overnight_easing": "overnight funding eased",
}
_FUNDING_GATES: frozenset[str] = frozenset(
    {
        "tight_funding",
        "easy_funding",
        "overnight_p10",
        "overnight_easing",
        "overnight_tightening",
        "curve_flatten",
        "invert_curve",
        "steep_curve",
        "repo_3m_down",
    }
)

PROPOSE_PROMPT_BAD: str = (
    'thesis "Rising Sales" with gates sales_down, or "Liquidity × Price × Margin"'
)


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
    ("sales_down", (
        "rising sales",
        "sales up",
        "sales growth",
        "high sales",
        "sales increase",
        "sales tend to rise",
        "sales rise",
    )),
    ("np_negative", (
        "positive np",
        "positive profit",
        "rising profit",
        "profit up",
        "profits tend to rise",
        "profit tends to rise",
        "high np",
        "high profit",
    )),
    ("price_down", (
        "price up",
        "rising price",
        "increase in price",
        "price increase",
        "prices tend to rise",
        "prices rise",
        "price rise",
        "price is rising",
        "the price is rising",
        "market rallies",
        "equity market rallies",
        "rallies",
    )),
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
    ("eps_down", (
        "eps up",
        "rising eps",
        "eps tend to rise",
        "earnings tend to rise",
        "earnings rise",
        "positive earnings surprise",
        "positive earnings",
        "positive surprise",
    )),
    ("eps_up", ("eps down", "falling eps", "earnings down")),
    ("roe_low", ("high roe", "high return on equity", "rising roe")),
    ("margin_down", (
        "margin up",
        "rising margin",
        "margins tend to rise",
        "margins rise",
    )),
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
    ("eq_ar_falling", ("risk appetite", "appetite for risk", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_rising", ("risk appetite", "appetite for risk", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_high", ("risk appetite", "appetite for risk", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_low", ("risk appetite", "appetite for risk", "risk premia", "risk premium", "risk arbitrage")),
    ("repo_3m_down", ("repo rates are low", "low repo", "repo is low")),
    ("ta_up", ("technical analysis", "technical signal", "ta signals")),
    ("ta_down", ("technical analysis", "technical signal", "ta signals")),
    ("overnight_p10", (
        "at 10%",
        "funding at 10",
        "10 percent",
        "10% predicts",
        "funding is loose",
        "loose",
        "repo rate is low",
        "repo rates are low",
        "the repo rate is low",
    )),
    ("pb_rising", (
        "is rising",
        "pb rose",
        "rising price to book",
        "rising price book",
        "rising pb",
        "price to book is rising",
        "price book is rising",
        "price book ratio is rising",
        "price to book ratio increase",
        "price to book ratio increases",
        "pb ratio increase",
        "pb ratio increases",
        "pb increase",
        "increase in pb",
        "price to book ratio tends to rise",
        "price to book tends to rise",
        "pb tends to rise",
        "pb ratio rising",
        "ratio rising",
    )),
    # pre_mom occupancy is surprise-sign agreement at entryIdx-1, not "mom is positive".
    ("pre_mom", (
        "positive price momentum",
        "positive momentum",
        "momentum is positive",
        "high price momentum",
    )),
    # curve_flatten occupancy is the repo curve, not a generic yield curve.
    ("curve_flatten", (
        "yield curve",
        "is flattening",
        "flattening",
        "curve flattened",
        "is flattened",
    )),
    ("invert_curve", (
        "invert curve",
        "inverted curve",
        "inverting",
        "is inverted",
        "curve inverted",
        "curve inversion",
        "yield curve",
    )),
    ("steep_curve", ("curve is steep", "is steep", "yield curve")),
    ("np_negative", (
        "profitability is weak",
        "weak profitability",
        "weak profit",
        "earnings per share are negative",
        "eps are negative",
        "unprofitable",
        "net loss",
    )),
    ("eps_down", (
        "earnings disappointment",
        "earnings disappoint",
        "earnings per share are falling",
        "eps are falling",
        "earnings per share tend to decrease",
        "earnings per share are down",
        "eps down",
        "eps is down",
    )),
    ("eps_up", (
        "earnings per share are rising",
        "eps are rising",
        "eps is rising",
        "rising earnings per share",
        "rising eps",
    )),
    ("sales_down", (
        "sales are down",
        "sales down",
        "falling sales",
    )),
    ("tight_funding", (
        "funding conditions are tight",
        "funding conditions tighten",
        "conditions tighten",
        "funding tightness",
    )),
    ("price_down", (
        "under pressure",
        "price pressure",
        "price is low",
        "price is falling",
        "price falling",
        "falling price",
        "prices drop",
        "price drops",
        "price contracted",
        "prices are declining",
        "prices declining",
    )),
    ("crowded_margin", ("market is crowded",)),
)

# Title claims a gate that is not in the AND-set.
# EqAR risk-slang extra-title is derived from GATE_OCCUPANCY_LABEL
# (occupancy_extra_families). Do not duplicate those phrases here.
EXTRA_TITLE_GATES: tuple[tuple[str, str], ...] = (
    ("low pb", "cheap_pb"),
    ("low price to book", "cheap_pb"),
    ("undervaluation", "cheap_pb"),
    ("undervalued", "cheap_pb"),
    ("tight funding", "tight_funding"),
    ("funding is tight", "tight_funding"),
    ("funding tight", "tight_funding"),
    ("funding became tight", "tight_funding"),
    ("funding conditions are tight", "tight_funding"),
    ("curve inversion", "invert_curve"),
    ("became tight", "tight_funding"),
    ("easy funding", "easy_funding"),
    ("funding is easy", "easy_funding"),
    ("funding easy", "easy_funding"),
    ("eased funding", "easy_funding"),
    ("funding conditions are easy", "easy_funding"),
    ("overnight funding is easing", "overnight_easing"),
    ("funding is easing", "overnight_easing"),
    ("positive earnings surprise", "eps_up"),
    ("positive earnings", "eps_up"),
    ("earnings per share are negative", "eps_down"),
    ("eps are negative", "eps_down"),
    ("eps surprises", "eps_down"),
    ("eps surprise", "eps_down"),
    ("earnings surprises", "eps_down"),
    ("earnings surprise", "eps_down"),
    ("earnings disappointment", "eps_down"),
    ("earnings disappoint", "eps_down"),
    ("earnings per share tend to decrease", "eps_down"),
    ("eps growth", "eps_up"),
    ("earnings growth", "eps_up"),
    ("high np", "np_negative"),
    ("high net profit", "np_negative"),
    ("high net profits", "np_negative"),
    ("sales contraction", "sales_down"),
    ("sales contracted", "sales_down"),
    ("sales will contract", "sales_down"),
    ("poor sales", "sales_down"),
    ("sales performance", "sales_down"),
    ("sales decline", "sales_down"),
    ("sales declines", "sales_down"),
    ("declining sales", "sales_down"),
    ("falling sales", "sales_down"),
    ("sales are down", "sales_down"),
    ("sales are declining", "sales_down"),
    ("price declines", "price_down"),
    ("price decline", "price_down"),
    ("weak sales", "sales_down"),
    ("roe decline", "roe_low"),
    ("roe is low", "roe_low"),
    ("low roe", "roe_low"),
    ("roe down", "roe_low"),
    ("falling roe", "roe_low"),
    ("poor roe", "roe_low"),
    ("high roe", "roe_low"),
    ("high return on equity", "roe_low"),
    ("return on equity", "roe_low"),
    ("risk averse", "eq_ar_falling"),
    ("buying opportunity", "cheap_pb"),
    ("selling opportunity", "cheap_pb"),
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
    frozenset({"curve_flatten", "invert_curve"}),
    frozenset({"curve_flatten", "steep_curve"}),
    frozenset({"invert_curve", "steep_curve"}),
    frozenset({"overnight_p10", "tight_funding"}),
    frozenset({"overnight_p10", "overnight_tightening"}),
    frozenset({"overnight_easing", "tight_funding"}),
    frozenset({"easy_funding", "overnight_tightening"}),
)


def propose_prompt_good() -> dict[str, object]:
    """Occupancy-correct 2-AND that is not already catalog. Format example only."""
    from research.unique_logic.catalog import yaml_combo_rows

    catalog: set[frozenset[str]] = set()
    for row in yaml_combo_rows():
        gates = frozenset(
            str(x)
            for x in ((row.get("params") or {}).get("gates") or [])
            if str(x).strip()
        )
        if gates:
            catalog.add(gates)
    prefer = list(PROPOSE_PROMPT_PREFER_GATES)
    for i, a in enumerate(prefer):
        for b in prefer[i + 1 :]:
            pair = frozenset({a, b})
            if pair in catalog:
                continue
            if any(combo <= pair for combo, _reason in SPARSE_GATE_COMBOS):
                continue
            if any(contra <= pair for contra in PROPOSE_CONTRADICTORY_GATE_PAIRS):
                continue
            sa = _GATE_OCCUPANCY_SENTENCE.get(a)
            sb = _GATE_OCCUPANCY_SENTENCE.get(b)
            if not sa or not sb:
                continue
            datasets = list(DEFAULT_PROPOSE_DATASETS)
            if pair & _FUNDING_GATES and "jsda_tokyo_repo_rates" not in datasets:
                datasets.append("jsda_tokyo_repo_rates")
            return {
                "thesis": (
                    f"PEAD when {sa} AND {sb}. Skip missing PIT prints (no invent)."
                ),
                "signal_definition": (
                    f"AND({a}, {b}) PIT; skip missing prints (no invent)."
                ),
                "position_rule": (
                    "Event-hold original surprise sign when both gates are "
                    "PIT-true; otherwise flat."
                ),
                "datasets": datasets,
                "gates": [a, b],
                "why_different_from": ["ungated PEAD"],
            }
    raise RuntimeError("no unique prefer 2-AND for PROPOSE_PROMPT_GOOD")


PROPOSE_PROMPT_GOOD: dict[str, object] = propose_prompt_good()
if frozenset(str(g) for g in PROPOSE_PROMPT_GOOD["gates"]) - PROPOSE_ALLOWED_GATES:
    raise RuntimeError("PROPOSE_PROMPT_GOOD gates must be propose-allowed")
if "cheap_pb" in set(str(g) for g in PROPOSE_PROMPT_GOOD["gates"]):
    raise RuntimeError("PROPOSE_PROMPT_GOOD must not seed cheap_pb")

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
    ("pre_mom", ("agrees", "pre event", "pre entry", "surprise sign")),
    ("eps_up", ("rose", "versus the last prior", "last prior print")),
    ("eps_down", ("contracted", "versus the last prior", "last prior print")),
    ("sales_down", ("contracted", "versus the last prior", "last prior print")),
    ("np_negative", ("net profit", "np is negative", "np negative")),
    ("crowded_margin", ("margin is crowded", "margin crowding")),
    ("curve_flatten", ("repo curve",)),
    ("invert_curve", ("repo curve",)),
    ("steep_curve", ("repo curve",)),
    ("price_down", ("price is down",)),
)


# Occupancy slang that is too generic to extra-title when the gate is absent.
_OCCUPANCY_EXTRA_SKIP: frozenset[str] = frozenset(
    {"is rising", "loose", "pb rose", "at 10%"}
)

# Title talks about occupancy as a metric, not the gate predicate.
TITLE_OCCUPANCY_META: tuple[str, ...] = (
    "occupancy increases",
    "occupancy increase",
    "occupancy is high",
    "occupancy is low",
    "occupancy when",
    "equities occupancy",
    "tends to be occupied",
    "occupy lower",
    "occupy",
)


def occupancy_extra_families() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Occupancy-label phrases → owner gates. Extra-title if none are in the AND."""
    owners: dict[str, set[str]] = {}
    for gate, phrases in GATE_OCCUPANCY_LABEL:
        for phrase in phrases:
            if phrase in _OCCUPANCY_EXTRA_SKIP or len(phrase) < 8:
                continue
            owners.setdefault(phrase, set()).add(gate)
    return tuple(sorted((p, tuple(sorted(g))) for p, g in owners.items()))


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
    "TITLE_OCCUPANCY_META",
    "PROPOSE_PROMPT_BAD",
    "PROPOSE_PROMPT_GOOD",
    "propose_prompt_good",
    "PROPOSE_PROMPT_PREFER_GATES",
    "GATE_OCCUPANCY_LABEL",
    "GATE_TITLE_CONTRA",
    "OCCUPANCY_LABEL_EXCEPTIONS",
    "PROMPT_DIRECTION_ECHO",
    "PROPOSE_CONTRADICTORY_GATE_PAIRS",
    "PROPOSE_TWEAK_WORDS",
    "occupancy_exception_tokens",
    "occupancy_extra_families",
    "prompt_direction_echo_x",
    "sparse_gate_combos_for_propose",
]
