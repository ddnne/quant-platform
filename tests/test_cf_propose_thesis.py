"""CF /v1/propose-thesis contract. Does not write catalog. Does not GO."""
from __future__ import annotations

from pathlib import Path

from research.cf_propose_thesis import (
    PROPOSE_ALLOWED_DATASETS,
    PROPOSE_WHY_AVOID_LIMIT,
    invoke_cf_propose_thesis,
    reject_window_tweak,
    review_proposal_row,
    stub_propose_thesis_result,
)
from research.unique_logic.constants import (
    COMBO_EVENT_GATES,
    PROPOSE_ALLOWED_GATES,
    PROPOSE_CALENDAR_GATES,
)

_REPO = Path(__file__).resolve().parents[1]
_WORKER_INDEX = (
    _REPO
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "src"
    / "index.ts"
)
_WORKER_PROPOSE = (
    _REPO
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "src"
    / "propose_thesis.ts"
)
_WORKER_ALLOWED = (
    _REPO
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "src"
    / "propose_allowed.ts"
)
_WRANGLER = (
    _REPO / "platform" / "workers" / "research-mass-eval" / "wrangler.toml"
)


def test_window_tweak_rejected() -> None:
    assert reject_window_tweak(
        {
            "thesis": "hold_days only",
            "signal_definition": "window",
            "position_rule": "hold 15",
        }
    )
    assert reject_window_tweak({})
    good = {
        "thesis": "liquidity-conditioned EqAR after disclosure",
        "signal_definition": "AND(liq_high, eq_ar_high) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary"],
    }
    assert reject_window_tweak(good) is False
    out = invoke_cf_propose_thesis(
        proposal={
            "thesis": "mom only",
            "signal_definition": "window",
            "position_rule": "hold",
        },
        http_post=lambda **_k: (_ for _ in ()).throw(
            AssertionError("must not POST window tweak")
        ),
    )
    assert out["ok"] is False
    assert out["error"] == "window_tweak_only_forbidden"
    assert out["auto_inject"] is False
    assert out["go"] is False


def test_stub_output_not_injected() -> None:
    stub = stub_propose_thesis_result(n=3)
    assert stub["ok"] is True
    assert stub["auto_inject"] is False
    assert stub["go"] is False
    assert stub["not_a_pass"] is True
    assert stub["catalog_written"] is False
    assert 1 <= len(stub["proposals"]) <= 3
    for p in stub["proposals"]:
        assert p["not_injected"] is True
        assert p["status"] == "stub_not_catalog"
        assert "logic_id" not in p
        assert "STUB" in p["thesis"]
        assert p["gates"]
        assert set(p["gates"]) <= PROPOSE_ALLOWED_GATES
        assert set(p["datasets"]) <= PROPOSE_ALLOWED_DATASETS
        reviewed = review_proposal_row(p)
        assert reviewed["ok"] is True
        assert reviewed["auto_inject"] is False

    posted: dict[str, object] = {}

    def _post(*, url: str, body: bytes, headers: dict[str, str]) -> dict:
        posted["url"] = url
        posted["headers"] = headers
        posted["body"] = body
        return stub_propose_thesis_result(n=2)

    out = invoke_cf_propose_thesis(n=2, why_avoid=["event_skip_monday"], http_post=_post)
    assert str(posted["url"]).endswith("/v1/propose-thesis")
    assert out["proposals"][0]["not_injected"] is True
    assert out["auto_inject"] is False
    assert out["go"] is False
    assert out["n_adoptable"] == 0
    assert "reviews" in out

    failed: dict[str, object] = {}

    def _fail(*, url: str, body: bytes, headers: dict[str, str]) -> dict:
        failed["url"] = url
        return {
            "ok": False,
            "error": "llm_failed",
            "proposals": [],
            "proposal_source": "llm_failed",
            "llm_fallback_reason": "parse_empty",
            "workers_ai_used": False,
            "auto_inject": False,
            "go": False,
            "not_a_pass": True,
        }

    fail_out = invoke_cf_propose_thesis(n=2, http_post=_fail)
    assert fail_out["ok"] is False
    assert fail_out.get("proposal_source") == "llm_failed"
    assert fail_out["n_adoptable"] == 0
    assert fail_out["auto_inject"] is False
    assert fail_out["go"] is False
    assert "llm_failed" in (_WORKER_PROPOSE.read_text(encoding="utf-8"))


def test_worker_index_contains_propose_thesis_route() -> None:
    src = (
        _WORKER_INDEX.read_text(encoding="utf-8")
        + "\n"
        + _WORKER_PROPOSE.read_text(encoding="utf-8")
        + "\n"
        + _WORKER_ALLOWED.read_text(encoding="utf-8")
    )
    assert "/v1/propose-thesis" in src
    assert "llm_failed" in src
    assert "llama-3.3-70b-instruct-fp8-fast" in src
    assert "glm-4.7-flash" in src
    assert "signal_definition" in src
    assert "proposal_source: \"llm_failed\"" in src or "proposal_source: 'llm_failed'" in src or 'proposal_source: "llm_failed"' in src
    assert "auto_inject: false" in src
    assert "go: false" in src
    assert "not_a_pass: true" in src
    wr = _WRANGLER.read_text(encoding="utf-8")
    assert 'binding = "AI"' in wr
    assert "[ai]" in wr
    assert "env.AI.run" in src
    assert "llm_not_catalog" in src
    assert "stubProposals" not in src
    assert "stub_propose_thesis_result" not in src
    assert "STUB_PROPOSAL_TEMPLATES" not in src
    assert "titleOccupancyBad" in src
    propose_src = _WORKER_PROPOSE.read_text(encoding="utf-8")
    assert "const PROPOSE_ALLOWED_GATES = [" not in propose_src
    assert "const PROPOSE_ALLOWED_DATASETS = [" not in propose_src
    assert "PROPOSE_ALLOWED_GATES.join" in propose_src
    assert "PROPOSE_PROMPT_PREFER_GATES.join" in propose_src
    assert "JSON.stringify(PROPOSE_PROMPT_GOOD)" in propose_src
    from research.unique_logic.catalog import yaml_combo_rows
    from research.unique_logic.constants import SPARSE_GATE_COMBOS
    from research.unique_logic.propose_review_tables import (
        PROPOSE_CONTRADICTORY_GATE_PAIRS,
        PROPOSE_PROMPT_GOOD,
        PROPOSE_PROMPT_PREFER_GATES,
        propose_prompt_good,
    )

    assert set(PROPOSE_PROMPT_PREFER_GATES) <= set(PROPOSE_ALLOWED_GATES)
    good = propose_prompt_good()
    assert good["gates"] == PROPOSE_PROMPT_GOOD["gates"]
    catalog_sets = {
        frozenset(
            str(x)
            for x in ((row.get("params") or {}).get("gates") or [])
            if str(x).strip()
        )
        for row in yaml_combo_rows()
    }
    assert frozenset(str(g) for g in good["gates"]) not in catalog_sets
    prefer = list(PROPOSE_PROMPT_PREFER_GATES)
    first: list[str] | None = None
    for i, a in enumerate(prefer):
        for b in prefer[i + 1 :]:
            pair = frozenset({a, b})
            if pair in catalog_sets:
                continue
            if any(combo <= pair for combo, _reason in SPARSE_GATE_COMBOS):
                continue
            if any(contra <= pair for contra in PROPOSE_CONTRADICTORY_GATE_PAIRS):
                continue
            first = [a, b]
            break
        if first is not None:
            break
    assert first == list(good["gates"])
    assert "markets_margin_interest" in src
    assert '"margin_interest"' not in src
    # Generated allowlists: scripts/sync_cf_new_thesis_ids.py --check is SoT.
    assert PROPOSE_CALENDAR_GATES <= COMBO_EVENT_GATES
    assert PROPOSE_CALENDAR_GATES.isdisjoint(PROPOSE_ALLOWED_GATES)
    assert "skip_monday" not in PROPOSE_ALLOWED_GATES
    assert "friday_only" not in PROPOSE_ALLOWED_GATES


def test_review_proposal_row_rejects_invent_and_weekday() -> None:
    good = {
        "thesis": "liquidity-conditioned EqAR rising after impulse",
        "signal_definition": "AND(liq_high, eq_ar_rising, on_impulse) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary"],
        "gates": ["liq_high", "eq_ar_rising", "on_impulse"],
    }
    ok = review_proposal_row(good)
    assert ok["ok"] is True
    assert ok["auto_inject"] is False
    assert ok["go"] is False

    weekday = dict(good)
    weekday["gates"] = ["skip_monday", "friday_only"]
    bad_wd = review_proposal_row(weekday)
    assert bad_wd["ok"] is False
    assert "invented_or_calendar_gates" in bad_wd["reasons"]
    assert "gates_empty_or_not_economic" in bad_wd["reasons"]

    invent = dict(good)
    invent["datasets"] = ["institutional_ownership"]
    bad_ds = review_proposal_row(invent)
    assert bad_ds["ok"] is False
    assert "invented_datasets" in bad_ds["reasons"]

    no_gates = dict(good)
    no_gates["gates"] = []
    bad_g = review_proposal_row(no_gates)
    assert bad_g["ok"] is False
    assert "gates_empty_or_not_economic" in bad_g["reasons"]

    with_id = dict(good)
    with_id["logic_id"] = "event_eqar_high_pead"
    bad_id = review_proposal_row(with_id)
    assert bad_id["ok"] is False
    assert "logic_id_forbidden" in bad_id["reasons"]

    clone = dict(good)
    clone["gates"] = ["eq_ar_high", "liq_high"]
    bad_clone = review_proposal_row(clone)
    assert bad_clone["ok"] is False
    assert "gate_set_already_catalog" in bad_clone["reasons"]
    assert bad_clone["auto_inject"] is False

    contra = dict(good)
    contra["gates"] = ["easy_funding", "tight_funding"]
    bad_c = review_proposal_row(contra)
    assert bad_c["ok"] is False
    assert "contradictory_gates" in bad_c["reasons"]

    flatten_invert = dict(good)
    flatten_invert["gates"] = ["curve_flatten", "invert_curve"]
    flatten_invert["datasets"] = [
        "equities_bars_daily",
        "fins_summary",
        "jsda_tokyo_repo_rates",
    ]
    flatten_invert["thesis"] = (
        "PEAD when the repo curve flattened AND the repo curve inverted."
    )
    bad_fi = review_proposal_row(flatten_invert)
    assert bad_fi["ok"] is False
    assert "contradictory_gates" in bad_fi["reasons"]

    p10_tightening = dict(good)
    p10_tightening["gates"] = ["overnight_p10", "overnight_tightening"]
    p10_tightening["datasets"] = [
        "equities_bars_daily",
        "fins_summary",
        "jsda_tokyo_repo_rates",
    ]
    p10_tightening["thesis"] = (
        "PEAD when overnight is in the easiest PIT decile AND overnight tightening."
    )
    bad_p10t = review_proposal_row(p10_tightening)
    assert bad_p10t["ok"] is False
    assert "contradictory_gates" in bad_p10t["reasons"]

    one = dict(good)
    one["gates"] = ["liq_high"]
    bad_one = review_proposal_row(one)
    assert bad_one["ok"] is False
    assert "gates_not_a_cross" in bad_one["reasons"]

    echo = dict(good)
    echo["thesis"] = "Japanese Equities: Liquidity × Fundamentals"
    bad_echo = review_proposal_row(echo)
    assert bad_echo["ok"] is False
    assert "prompt_direction_echo" in bad_echo["reasons"]

    wide = dict(good)
    wide["gates"] = ["ta_down", "margin_up", "repo_3m_down", "afterclose"]
    bad_w = review_proposal_row(wide)
    assert bad_w["ok"] is False
    assert "and_cross_too_wide" in bad_w["reasons"]

    polar = dict(good)
    polar["thesis"] = "Japanese Equities: Falling EqAR after impulse"
    polar["gates"] = ["liq_high", "eq_ar_rising", "on_impulse"]
    bad_p = review_proposal_row(polar)
    assert bad_p["ok"] is False
    assert "title_gate_polarity_mismatch" in bad_p["reasons"]
    assert bad_p["auto_inject"] is False

    mash = dict(good)
    mash["thesis"] = "Liquidity × Price × Margin"
    mash["gates"] = ["liq_high", "ta_down", "margin_down"]
    bad_m = review_proposal_row(mash)
    assert bad_m["ok"] is False
    assert "title_not_occupancy" in bad_m["reasons"]
    assert bad_m["auto_inject"] is False

    invert_sales = {
        "thesis": "After a steep curve and high sales, expect an increase in price",
        "signal_definition": "AND(steep_curve, sales_down, price_down) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary"],
        "gates": ["steep_curve", "sales_down", "price_down"],
    }
    bad_s = review_proposal_row(invert_sales)
    assert bad_s["ok"] is False
    assert "title_gate_polarity_mismatch" in bad_s["reasons"]

    invert_high_eqar = {
        "thesis": "Stocks with high equity risk arbitrage tend to outperform when the TA is down AND overnight funding is easing.",
        "signal_definition": "AND(eq_ar_falling, ta_down, overnight_easing) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"],
        "gates": ["eq_ar_falling", "ta_down", "overnight_easing"],
    }
    bad_h = review_proposal_row(invert_high_eqar)
    assert bad_h["ok"] is False
    assert "title_gate_polarity_mismatch" in bad_h["reasons"]
    assert bad_h["auto_inject"] is False

    invert_eqar_english = {
        "thesis": "Stocks with rising equity risk premia and high volume experience mean reversion.",
        "signal_definition": "AND(eq_ar_falling, nky_vol_high_skip) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"],
        "gates": ["eq_ar_falling", "nky_vol_high_skip"],
    }
    bad_e = review_proposal_row(invert_eqar_english)
    assert bad_e["ok"] is False
    assert "title_gate_polarity_mismatch" in bad_e["reasons"]
    assert bad_e["auto_inject"] is False

    invert_repo = {
        "thesis": "Stocks with high repo rates and rising equity risk premia outperform when volatility is low.",
        "signal_definition": "AND(repo_3m_down, eq_ar_rising, nky_vol_high_skip) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"],
        "gates": ["repo_3m_down", "eq_ar_rising", "nky_vol_high_skip"],
    }
    bad_r = review_proposal_row(invert_repo)
    assert bad_r["ok"] is False
    assert "title_gate_polarity_mismatch" in bad_r["reasons"]

    sparse_steep = {
        "thesis": "PEAD when NKY vol-high skip is off AND the repo curve is steep.",
        "signal_definition": "AND(nky_vol_high_skip, steep_curve) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"],
        "gates": ["nky_vol_high_skip", "steep_curve"],
    }
    bad_st = review_proposal_row(sparse_steep)
    assert bad_st["ok"] is False
    assert "sparse_gate_combo" in bad_st["reasons"]

    invert_nky = {
        "thesis": "Prices drop when overnight funding is tightening AND margin is down AND volatility is high.",
        "signal_definition": "AND(overnight_tightening, margin_down, nky_vol_high_skip) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"],
        "gates": ["overnight_tightening", "margin_down", "nky_vol_high_skip"],
    }
    bad_n = review_proposal_row(invert_nky)
    assert bad_n["ok"] is False
    assert "title_gate_polarity_mismatch" in bad_n["reasons"]
    assert bad_n["auto_inject"] is False


def test_review_proposal_row_occupancy_and_polarity_table() -> None:
    """SoT phrase cases. Reason classes stay; rows are data not new tests."""
    ds = ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"]
    rows: list[tuple[str, list[str], str, str | None]] = [
        (
            "Overnight funding at 10% predicts EPS decline.",
            ["overnight_p10", "eps_down"],
            "occupancy_label_only",
            "PEAD when overnight is in the easiest PIT decile AND EPS contracted",
        ),
        (
            "Curve flattening indicates poor sales performance when EPS is down.",
            ["curve_flatten", "eps_down"],
            "occupancy_label_only",
            "PEAD when the repo curve flattened AND EPS contracted versus the last prior print",
        ),
        (
            "ROE decline when price-to-book is high AND overnight funding is loose.",
            ["pb_rising", "overnight_p10"],
            "occupancy_label_only",
            "PEAD when PB is above its PIT median AND overnight is in the easiest PIT decile",
        ),
        (
            "Tight funding regime when EPS is down AND NP is negative.",
            ["eps_down", "np_negative"],
            "occupancy_label_only",
            "PEAD when EPS contracted AND net profit is negative",
        ),
        (
            "Price contraction when earnings per share are down AND price-to-book is rising.",
            ["eps_down", "pb_rising"],
            "occupancy_label_only",
            "PEAD when EPS contracted AND PB is above its PIT median",
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
            "Market rallies when repo rates are low AND equity risk appetite is falling",
            ["repo_3m_down", "eq_ar_falling"],
            "occupancy_label_only",
            "PEAD when 3m repo rate is down AND EqAR fell versus the last prior print",
        ),
        (
            "PEAD when the curve flattened AND EPS contracted AND overnight rates are high.",
            ["curve_flatten", "eps_down", "overnight_p10"],
            "title_gate_polarity_mismatch",
            None,
        ),
        (
            "Mean reversion when rising price-to-book ratios AND TA is up AND overnight funding is easy.",
            ["pb_rising", "ta_up", "easy_funding"],
            "occupancy_label_only",
            None,
        ),
        (
            "Overnight funding is tight AND profitability is weak",
            ["tight_funding", "np_negative"],
            "occupancy_label_only",
            "PEAD when overnight funding is tight AND net profit is negative",
        ),
        (
            "Curve flattening indicates declining sales when EPS is down.",
            ["curve_flatten", "eps_down"],
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
            "When the yield curve is flattening and price is down, we expect a positive return due to decreased investor appetite for risk.",
            ["curve_flatten", "price_down"],
            "occupancy_label_only",
            "PEAD when the repo curve flattened AND price is down",
        ),
        (
            "Stocks with high EPS growth tend to outperform when overnight funding is easy AND the price is rising.",
            ["easy_funding", "price_down"],
            "title_gate_polarity_mismatch",
            "PEAD when overnight funding is easy AND price is down",
        ),
        (
            "Investors tend to prefer stocks with low PB ratios when the market is crowded AND there is a large surprise in earnings.",
            ["crowded_margin", "large_surprise"],
            "occupancy_label_only",
            "PEAD when margin is crowded AND surprise is large versus the window",
        ),
        (
            "Invert curve regime tends to coincide with sales downturn and PB ratio increase.",
            ["invert_curve", "sales_down", "pb_rising"],
            "occupancy_label_only",
            "PEAD when the repo curve inverted AND sales contracted AND PB is above its PIT median",
        ),
        (
            "EPS growth momentum when price is down AND sales are falling.",
            ["price_down", "sales_down"],
            "occupancy_label_only",
            "PEAD when price is down AND sales contracted versus the last prior print",
        ),
        (
            "Stocks with high NP margins outperform when the curve is inverting AND funding is tight.",
            ["invert_curve", "tight_funding"],
            "occupancy_label_only",
            "PEAD when the repo curve inverted AND overnight funding is tight",
        ),
        (
            "Tight funding conditions and sales declines can lead to underperformance.",
            ["tight_funding", "eps_down"],
            "occupancy_label_only",
            "PEAD when overnight funding is tight AND EPS contracted versus the last prior print",
        ),
        (
            "Negative earnings surprises when overnight funding is easy AND sales contracted.",
            ["easy_funding", "sales_down"],
            "occupancy_label_only",
            "PEAD when overnight funding is easy AND sales contracted versus the last prior print",
        ),
        (
            "Overnight funding is easy AND EPS contracted AND sales are declining.",
            ["easy_funding", "eps_down"],
            "occupancy_label_only",
            "PEAD when overnight funding is easy AND EPS contracted versus the last prior print",
        ),
        (
            "The price-to-book ratio increases when there is a positive price momentum AND the overnight funding becomes tighter.",
            ["pre_mom", "tight_funding"],
            "occupancy_label_only",
            "PEAD when pre-event momentum agrees AND overnight funding is tight. Skip missing PIT prints (no invent).",
        ),
        (
            "Earnings growth slows down when overnight funding is easy AND the repo curve inverted.",
            ["easy_funding", "invert_curve"],
            "occupancy_label_only",
            "PEAD when overnight funding is easy AND the repo curve inverted. Skip missing PIT prints (no invent).",
        ),
        (
            "Stocks with high price momentum tend to outperform when the yield curve flattens AND funding conditions are easy, but not overly crowded.",
            ["curve_flatten", "easy_funding", "uncrowded_margin"],
            "occupancy_label_only",
            "PEAD when the repo curve flattened AND overnight funding is easy AND margin is uncrowded. Skip missing PIT prints (no invent).",
        ),
        (
            "The price-to-book ratio tends to rise when the curve inverts AND the company has a high return on equity, signaling a potential undervaluation opportunity.",
            ["invert_curve", "pb_rising"],
            "occupancy_label_only",
            "PEAD when the repo curve inverted AND PB is above its PIT median. Skip missing PIT prints (no invent).",
        ),
        (
            "Earnings disappointment is more likely to be followed by price declines when the repo rate is low and the price is already under pressure.",
            ["eps_down", "price_down", "overnight_p10"],
            "occupancy_label_only",
            "PEAD when overnight is in the easiest PIT decile AND EPS contracted versus the last prior print AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "The price of the stock went down when the curve flattened and funding became tight.",
            ["curve_flatten", "eps_down"],
            "occupancy_label_only",
            "PEAD when the repo curve flattened AND EPS contracted versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "Equity market rallies when the price is down AND the earnings per share are rising, indicating a potential buying opportunity.",
            ["price_down", "eps_up"],
            "title_gate_polarity_mismatch",
            "PEAD when EPS rose versus the last prior print AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "Investors become risk-averse when overnight funding is tight AND the repo curve inverted.",
            ["invert_curve", "tight_funding"],
            "occupancy_label_only",
            None,
        ),
        (
            "Earnings per share tend to decrease when the overnight funding is easing and the sales are falling, indicating a potential selling opportunity.",
            ["overnight_p10", "sales_down"],
            "occupancy_label_only",
            "PEAD when overnight is in the easiest PIT decile AND sales contracted versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "The stock price tends to decrease when the earnings per share are falling and the price is already down, indicating a potential selling opportunity.",
            ["eps_down", "price_down"],
            "occupancy_label_only",
            "PEAD when EPS contracted versus the last prior print AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "EPS down when price is down AND overnight funding is tight.",
            ["price_down", "tight_funding", "eps_down"],
            "occupancy_label_only",
            "PEAD when overnight funding is tight AND EPS contracted versus the last prior print AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "Invert curve when sales are falling AND funding is tight. High net profit is not required.",
            ["invert_curve", "sales_down", "tight_funding"],
            "occupancy_label_only",
            "PEAD when the repo curve inverted AND overnight funding is tight AND sales contracted versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "PEAD when curve is flattening AND price is falling. High net profit is not required.",
            ["curve_flatten", "sales_down"],
            "occupancy_label_only",
            "PEAD when the repo curve flattened AND sales contracted versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "Occupancy increases when overnight is in the easiest PIT decile AND sales contracted versus the last prior print.",
            ["overnight_p10", "eps_down"],
            "occupancy_label_only",
            "PEAD when overnight is in the easiest PIT decile AND EPS contracted versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "Tight funding when curve is steep AND funding is tight AND price is down.",
            ["steep_curve", "tight_funding", "price_down"],
            "occupancy_label_only",
            "PEAD when the repo curve is steep AND overnight funding is tight AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "Positive earnings surprise when eps is down AND overnight is easing AND np is negative.",
            ["eps_down", "overnight_easing", "np_negative"],
            "title_gate_polarity_mismatch",
            "PEAD when EPS contracted versus the last prior print AND overnight funding eased AND net profit is negative. Skip missing PIT prints (no invent).",
        ),
        (
            "Positive earnings surprise when overnight funding eased AND net profit is negative.",
            ["overnight_easing", "np_negative"],
            "occupancy_label_only",
            "PEAD when overnight funding eased AND net profit is negative. Skip missing PIT prints (no invent).",
        ),
        (
            "Stocks with rising earnings per share tend to outperform when overnight funding is in the easiest decile and sales are down.",
            ["overnight_p10", "sales_down", "eps_up"],
            "occupancy_label_only",
            "PEAD when overnight is in the easiest PIT decile AND sales contracted versus the last prior print AND EPS rose versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "Price is low when overnight is in the easiest PIT decile AND net profit is negative.",
            ["overnight_p10", "np_negative"],
            "occupancy_label_only",
            "PEAD when overnight is in the easiest PIT decile AND net profit is negative. Skip missing PIT prints (no invent).",
        ),
        (
            "The curve is inverted when overnight is in the easiest PIT decile.",
            ["overnight_p10", "invert_curve"],
            "occupancy_label_only",
            "PEAD when overnight is in the easiest PIT decile AND the repo curve inverted. Skip missing PIT prints (no invent).",
        ),
        (
            "Firms with falling sales and negative net profit tend to be avoided when funding conditions are tight.",
            ["sales_down", "np_negative", "tight_funding"],
            "occupancy_label_only",
            "PEAD when overnight funding is tight AND sales contracted versus the last prior print AND net profit is negative. Skip missing PIT prints (no invent).",
        ),
        (
            "The curve flattened AND price is down.",
            ["curve_flatten", "price_down"],
            "occupancy_label_only",
            "PEAD when the repo curve flattened AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "Investors tend to occupy lower positions when the price is down and earnings per share are negative.",
            ["price_down", "np_negative"],
            "occupancy_label_only",
            "PEAD when price is down AND net profit is negative. Skip missing PIT prints (no invent).",
        ),
        (
            "The market tends to be occupied when PB is above its PIT median AND price is down.",
            ["pb_rising", "price_down"],
            "occupancy_label_only",
            "PEAD when PB is above its PIT median AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "The market tends to be occupied when earnings per share are down and price is also down.",
            ["eps_down", "price_down"],
            "occupancy_label_only",
            "PEAD when EPS contracted versus the last prior print AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "Curve inversion when price is falling AND funding is tight.",
            ["price_down", "tight_funding"],
            "occupancy_label_only",
            "PEAD when overnight funding is tight AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "Curve inversion when EPS contracted versus the last prior print AND sales contracted versus the last prior print.",
            ["eps_down", "sales_down"],
            "occupancy_label_only",
            "PEAD when EPS contracted versus the last prior print AND sales contracted versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "Tight funding and a rising price-book ratio are more likely to occur when EPS is contracting versus the last prior print. Skip missing PIT prints (no invent).",
            ["tight_funding", "pb_rising", "eps_down"],
            "occupancy_label_only",
            "PEAD when overnight funding is tight AND PB is above its PIT median AND EPS contracted versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "PEAD when the inverted curve AND price is down.",
            ["invert_curve", "price_down"],
            "occupancy_label_only",
            "PEAD when the repo curve inverted AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "PEAD when names are unprofitable AND sales contracted versus the last prior print.",
            ["np_negative", "sales_down"],
            "occupancy_label_only",
            "PEAD when net profit is negative AND sales contracted versus the last prior print. Skip missing PIT prints (no invent).",
        ),
        (
            "When the market experiences a combination of tight funding and a falling price, it's likely that the sales will contract versus the last prior print.",
            ["tight_funding", "price_down"],
            "occupancy_label_only",
            "PEAD when overnight funding is tight AND price is down. Skip missing PIT prints (no invent).",
        ),
        (
            "PEAD when overnight funding is tight AND price is down. Sales will contract versus the last prior print.",
            ["tight_funding", "price_down"],
            "occupancy_label_only",
            "PEAD when overnight funding is tight AND price is down. Skip missing PIT prints (no invent).",
        ),
    ]
    for bad_thesis, gates, reason, good_thesis in rows:
        payload = {
            "thesis": bad_thesis,
            "signal_definition": f"AND({', '.join(gates)}) PIT",
            "position_rule": "event-hold surprise sign",
            "datasets": ds,
            "gates": gates,
        }
        bad = review_proposal_row(payload)
        assert bad["ok"] is False, (gates, bad["reasons"])
        assert reason in bad["reasons"], (gates, reason, bad["reasons"])
        assert bad["auto_inject"] is False
        if good_thesis is None:
            continue
        good = review_proposal_row(dict(payload, thesis=good_thesis))
        assert good["auto_inject"] is False
        assert good["go"] is False
        if good["ok"]:
            assert reason not in good["reasons"]
        else:
            assert "gate_set_already_catalog" in good["reasons"]


def test_catalog_gate_set_avoid_is_existing_crosses() -> None:
    from research.cf_propose_thesis import catalog_gate_set_avoid
    from research.unique_logic.constants import PROPOSE_CALENDAR_GATES

    tokens = catalog_gate_set_avoid(limit=8)
    assert 1 <= len(tokens) <= 8
    full = catalog_gate_set_avoid()
    assert len(full) == PROPOSE_WHY_AVOID_LIMIT
    assert PROPOSE_WHY_AVOID_LIMIT == 24
    assert any(t.count("+") == 2 for t in full)
    assert any(t.count("+") == 1 for t in full)
    n3 = sum(1 for t in full if t.count("+") == 2)
    n2 = sum(1 for t in full if t.count("+") == 1)
    assert n3 >= 8 and n2 >= 8
    assert all("+" in t for t in tokens)
    blob = " ".join(tokens)
    assert "skip_monday" not in blob
    assert "friday_skip" not in blob
    assert PROPOSE_CALENDAR_GATES.isdisjoint(
        {p for t in tokens for p in t.split("+")}
    )


def test_sparse_gate_set_avoid_is_prepended_to_why_avoid() -> None:
    import json

    from research.cf_propose_thesis import sparse_gate_set_avoid

    sparse = sparse_gate_set_avoid()
    assert "nky_vol_high_skip+steep_curve" in sparse
    assert "cheap_iv+steep_curve" in sparse
    assert "cheap_iv+cheap_pb" in sparse
    posted: dict[str, object] = {}

    def _post(*, url: str, body: bytes, headers: dict[str, str]) -> dict:
        posted["body"] = json.loads(body.decode("utf-8"))
        return stub_propose_thesis_result(n=1)

    out = invoke_cf_propose_thesis(n=1, http_post=_post)
    avoid = list((posted.get("body") or {}).get("why_avoid") or [])  # type: ignore[union-attr]
    assert avoid
    assert len(avoid) <= PROPOSE_WHY_AVOID_LIMIT
    assert "nky_vol_high_skip+steep_curve" in avoid
    assert out["auto_inject"] is False
    assert out["go"] is False


def test_clone_retry_reposts_catalog_gate_sets() -> None:
    import json

    calls: list[dict] = []

    def _post(*, url: str, body: bytes, headers: dict[str, str]) -> dict:
        calls.append(json.loads(body.decode("utf-8")))
        if len(calls) == 1:
            return {
                "ok": True,
                "workers_ai_used": True,
                "proposals": [
                    {
                        "thesis": "clone of existing EqAR x liquidity",
                        "signal_definition": "AND(eq_ar_high, liq_high) PIT",
                        "position_rule": "event-hold surprise sign",
                        "datasets": ["equities_bars_daily", "fins_summary"],
                        "gates": ["eq_ar_high", "liq_high"],
                        "status": "llm_not_catalog",
                    }
                ],
            }
        return {
            "ok": True,
            "workers_ai_used": True,
            "proposals": [
                {
                    "thesis": "impulse EqAR rising with high ADV",
                    "signal_definition": "AND(liq_high, eq_ar_rising, on_impulse) PIT",
                    "position_rule": "event-hold surprise sign",
                    "datasets": ["equities_bars_daily", "fins_summary"],
                    "gates": ["liq_high", "eq_ar_rising", "on_impulse"],
                    "status": "llm_not_catalog",
                }
            ],
        }

    out = invoke_cf_propose_thesis(n=1, job_id="test-clone-retry", http_post=_post)
    assert len(calls) == 2
    assert calls[1]["why_avoid"][0] == "eq_ar_high+liq_high"
    assert calls[1]["job_id"] == "test-clone-retry-retry"
    assert out["n_adoptable"] == 1
    assert out["auto_inject"] is False
    assert out["go"] is False

    once: list[int] = []

    def _once(*, url: str, body: bytes, headers: dict[str, str]) -> dict:
        once.append(1)
        return {
            "ok": True,
            "workers_ai_used": True,
            "proposals": [
                {
                    "thesis": "clone of existing EqAR x liquidity",
                    "signal_definition": "AND(eq_ar_high, liq_high) PIT",
                    "position_rule": "event-hold surprise sign",
                    "datasets": ["equities_bars_daily", "fins_summary"],
                    "gates": ["eq_ar_high", "liq_high"],
                    "status": "llm_not_catalog",
                }
            ],
        }

    stuck = invoke_cf_propose_thesis(
        n=1, http_post=_once, retry_on_clone=False
    )
    assert len(once) == 1
    assert stuck["n_adoptable"] == 0
    assert "gate_set_already_catalog" in stuck["reviews"][0]["reasons"]

    polar_calls: list[dict] = []

    def _polar(*, url: str, body: bytes, headers: dict[str, str]) -> dict:
        polar_calls.append(json.loads(body.decode("utf-8")))
        if len(polar_calls) == 1:
            return {
                "ok": True,
                "workers_ai_used": True,
                "proposals": [
                    {
                        "thesis": (
                            "Equity price drops when repo rate is high AND "
                            "margin is crowded AND TA is bearish."
                        ),
                        "signal_definition": (
                            "AND(repo_3m_down, crowded_margin, ta_down) PIT"
                        ),
                        "position_rule": "event-hold surprise sign",
                        "datasets": [
                            "equities_bars_daily",
                            "fins_summary",
                            "jsda_tokyo_repo_rates",
                        ],
                        "gates": ["repo_3m_down", "crowded_margin", "ta_down"],
                        "status": "llm_not_catalog",
                    }
                ],
            }
        return {
            "ok": True,
            "workers_ai_used": True,
            "proposals": [
                {
                    "thesis": (
                        "PEAD when 3m repo is down AND margin is crowded "
                        "AND total assets contracted"
                    ),
                    "signal_definition": (
                        "AND(repo_3m_down, crowded_margin, ta_down) PIT"
                    ),
                    "position_rule": "event-hold surprise sign",
                    "datasets": [
                        "equities_bars_daily",
                        "fins_summary",
                        "jsda_tokyo_repo_rates",
                    ],
                    "gates": ["repo_3m_down", "crowded_margin", "ta_down"],
                    "status": "llm_not_catalog",
                }
            ],
        }

    polar_out = invoke_cf_propose_thesis(
        n=1, job_id="test-polar-retry", http_post=_polar
    )
    assert len(polar_calls) == 2
    # Polarity is a title bug: do not avoid the unique AND on retry.
    assert polar_calls[1]["why_avoid"][0] != "crowded_margin+repo_3m_down+ta_down"
    assert polar_calls[1]["job_id"] == "test-polar-retry-retry"
    assert polar_out["n_adoptable"] == 1
    assert polar_out["auto_inject"] is False
    assert polar_out["go"] is False
