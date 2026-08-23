"""Phrase cases for review_proposal_row. Data, not new tests. Does not GO.

Representative rows only: one occupancy class is not a 50-row catalog.
Reason classes stay; extra occupancy_label_only paraphrases were combinatorial.
"""
from __future__ import annotations

REVIEW_PHRASE_CASES: tuple[tuple[str, list[str], str, str | None], ...] = tuple(
    [
        (
            "Overnight funding at 10% predicts EPS decline.",
            ["overnight_p10", "eps_down"],
            "occupancy_label_only",
            "PEAD when overnight is in the easiest PIT decile AND EPS contracted",
        ),
        (
            "Stocks are more likely to be bought when the margin is uncrowded AND overnight funding is tightening AND technical analysis signals are up.",
            ["uncrowded_margin", "overnight_tightening", "ta_up"],
            "occupancy_label_only",
            None,
        ),
        (
            "Equity risk arbitrage opportunities arise when TA signals are down and funding is easy.",
            ["eq_ar_falling", "ta_down", "easy_funding"],
            "occupancy_label_only",
            None,
        ),
        (
            "Inverted curve when EPS surprises are negative AND price momentum is down.",
            ["invert_curve", "np_negative", "price_down"],
            "occupancy_label_only",
            "PEAD when the repo curve inverted AND net profit is negative AND price is down",
        ),
        (
            "Investors tend to prefer stocks with low PB ratios when the market is crowded AND there is a large surprise in earnings.",
            ["crowded_margin", "large_surprise"],
            "occupancy_label_only",
            "PEAD when margin is crowded AND surprise is large versus the window",
        ),
        (
            "The price-to-book ratio increases when there is a positive price momentum AND the overnight funding becomes tighter.",
            ["pre_mom", "tight_funding"],
            "occupancy_label_only",
            "PEAD when pre-event momentum agrees AND overnight funding is tight. Skip missing PIT prints (no invent).",
        ),
        (
            "Stocks with high price momentum tend to outperform when the yield curve flattens AND funding conditions are easy, but not overly crowded.",
            ["curve_flatten", "easy_funding", "uncrowded_margin"],
            "occupancy_label_only",
            "PEAD when the repo curve flattened AND overnight funding is easy AND margin is uncrowded. Skip missing PIT prints (no invent).",
        ),
        (
            "The market is occupied with stocks having high total assets when overnight funding is easing AND the price is going down.",
            ["ta_up", "overnight_easing", "price_down"],
            "occupancy_label_only",
            "PEAD when total assets rose versus the last prior print AND overnight funding eased AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "Investors become risk-averse when overnight funding is tight AND the repo curve inverted.",
            ["invert_curve", "tight_funding"],
            "occupancy_label_only",
            None,
        ),
        (
            "PEAD when the curve flattened AND EPS contracted AND overnight rates are high.",
            ["curve_flatten", "eps_down", "overnight_p10"],
            "title_gate_polarity_mismatch",
            None,
        ),
        (
            "Equity prices tend to rise when the yield curve is flattening AND price momentum is downward.",
            ["curve_flatten", "price_down"],
            "title_gate_polarity_mismatch",
            "PEAD when the repo curve flattened AND price is down",
        ),
        (
            "Sales tend to rise when overnight funding is tight AND EPS contracted.",
            ["tight_funding", "sales_down", "eps_down"],
            "title_gate_polarity_mismatch",
            "PEAD when overnight funding is tight AND sales contracted AND EPS contracted",
        ),
        (
            "Stocks with high EPS growth tend to outperform when overnight funding is easy AND the price is rising.",
            ["easy_funding", "price_down"],
            "title_gate_polarity_mismatch",
            "PEAD when overnight funding is easy AND price is down",
        ),
        (
            "Equity market rallies when the price is down AND the earnings per share are rising, indicating a potential buying opportunity.",
            ["price_down", "eps_up"],
            "title_gate_polarity_mismatch",
            "PEAD when EPS rose versus the last prior print AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "Positive earnings surprise when eps is down AND overnight is easing AND np is negative.",
            ["eps_down", "overnight_easing", "np_negative"],
            "title_gate_polarity_mismatch",
            "PEAD when EPS contracted versus the last prior print AND overnight funding eased AND net profit is negative. Skip missing PIT prints (no invent).",
        ),
        (
            "Earnings per share is expected to fall when the price of the stock has been falling and the repo 3M rate is high.",
            ["price_down", "repo_3m_down"],
            "title_gate_polarity_mismatch",
            "PEAD when price is down AND 3m repo rate is down. Skip missing PIT prints (no invent).",
        ),
        (
            "PEAD when earnings are down AND price is down AND the curve is not steep.",
            ["eps_down", "price_down", "steep_curve"],
            "title_gate_polarity_mismatch",
            "PEAD when EPS contracted versus the last prior print AND price is down AND the repo curve is steep. Skip missing PIT prints (no invent).",
        ),
        (
            "The bond market is experiencing a liquidity squeeze when the repo curve steepens AND the market is experiencing a liquidity squeeze AND the overnight policy rate is tight.",
            ["curve_flatten", "liq_high", "overnight_tightening"],
            "title_gate_polarity_mismatch",
            "PEAD when the repo curve flattened AND liquidity is high AND overnight tightened. Skip missing PIT prints (no invent).",
        ),
        (
            "PEAD when EPS contracted versus the last prior print AND the repo curve is steep AND overnight funding is tight. Skip missing PIT prints (no invent).",
            ["eps_down", "steep_curve", "tight_funding"],
            "sparse_gate_combo",
            None,
        ),
    ]
)
