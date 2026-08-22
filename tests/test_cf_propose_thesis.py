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
    )
    assert "/v1/propose-thesis" in src
    assert "llm_failed" in src
    assert "llama-3.3-70b-instruct-fp8-fast" in src
    assert "glm-4.7-flash" in src
    assert "extractAiText" in src
    assert "coerceGateList" in src
    assert "DEFAULT_PROPOSE_DATASETS" in src
    assert "signal_definition" in src
    assert "proposal_source: \"llm_failed\"" in src or "proposal_source: 'llm_failed'" in src or 'proposal_source: "llm_failed"' in src
    assert "auto_inject: false" in src
    assert "go: false" in src
    assert "not_a_pass: true" in src
    assert "liquidity × fundamentals" in src or "liquidity" in src
    assert "margin × price" in src or "margin" in src
    assert "disclosure × funding" in src or "disclosure" in src
    wr = _WRANGLER.read_text(encoding="utf-8")
    assert 'binding = "AI"' in wr
    assert "[ai]" in wr
    assert "env.AI.run" in src
    assert "llm_not_catalog" in src
    assert "llm_fallback_reason" in src
    assert "parse_empty" in src
    assert "ai_unbound" in src
    assert "stubProposals" not in src
    assert "stub_propose_thesis_result" not in src
    assert "STUB_PROPOSAL_TEMPLATES" not in src
    assert "equities_bars_daily" in src
    assert "fins_summary" in src
    assert "PROPOSE_ALLOWED_GATES" in src
    assert "Do not invent datasets" in src or "do not invent datasets" in src.lower()
    assert "gate polarity" in src.lower()
    assert "occupancy sentence" in src.lower()
    assert "slice(0, 24)" in src or "slice(0,24)" in src
    assert "No weekday" in src
    assert "2 or 3" in src
    assert "Liquidity × Price × Margin" in src
    assert "auto_inject: false" in src
    assert "markets_margin_interest" in src
    assert '"margin_interest"' not in src

    import re

    def _ids(name: str) -> set[str]:
        m = re.search(
            rf"(?:export )?const {name} = (?:new Set\()?\[(.*?)](?: as const)?",
            src,
            flags=re.S,
        )
        assert m, name
        return set(re.findall(r'"([^"]+)"', m.group(1)))

    assert _ids("PROPOSE_ALLOWED_GATES") == set(PROPOSE_ALLOWED_GATES)
    assert _ids("PROPOSE_ALLOWED_DATASETS") == set(PROPOSE_ALLOWED_DATASETS)
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

    occupancy_ta = {
        "thesis": (
            "Stocks are more likely to be bought when the margin is uncrowded "
            "AND overnight funding is tightening AND technical analysis "
            "signals are up."
        ),
        "signal_definition": "AND(uncrowded_margin, overnight_tightening, ta_up) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"],
        "gates": ["uncrowded_margin", "overnight_tightening", "ta_up"],
    }
    bad_ta = review_proposal_row(occupancy_ta)
    assert bad_ta["ok"] is False
    assert "occupancy_label_only" in bad_ta["reasons"]
    assert bad_ta["auto_inject"] is False

    occupancy_arb = {
        "thesis": (
            "Equity risk arbitrage opportunities arise when TA signals are "
            "down and funding is easy."
        ),
        "signal_definition": "AND(eq_ar_falling, ta_down, easy_funding) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"],
        "gates": ["eq_ar_falling", "ta_down", "easy_funding"],
    }
    bad_arb = review_proposal_row(occupancy_arb)
    assert bad_arb["ok"] is False
    assert "occupancy_label_only" in bad_arb["reasons"]
    assert bad_arb["auto_inject"] is False

    occupancy_label = {
        "thesis": (
            "Market rallies when repo rates are low AND equity risk appetite "
            "is falling"
        ),
        "signal_definition": "AND(repo_3m_down, eq_ar_falling) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"],
        "gates": ["repo_3m_down", "eq_ar_falling"],
    }
    bad_ol = review_proposal_row(occupancy_label)
    assert bad_ol["ok"] is False
    assert "occupancy_label_only" in bad_ol["reasons"]
    assert bad_ol["auto_inject"] is False

    occ_ok = dict(occupancy_label)
    occ_ok["thesis"] = (
        "PEAD when 3m repo rate is down AND EqAR fell versus the last prior print"
    )
    # Same 2-AND is already catalog after 23t YAML; clone still fail-closes.
    occ_review = review_proposal_row(occ_ok)
    assert occ_review["auto_inject"] is False
    assert occ_review["go"] is False
    if occ_review["ok"]:
        assert "occupancy_label_only" not in occ_review["reasons"]
    else:
        assert "gate_set_already_catalog" in occ_review["reasons"]


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
    posted: dict[str, object] = {}

    def _post(*, url: str, body: bytes, headers: dict[str, str]) -> dict:
        posted["body"] = body
        posted["headers"] = headers
        from research.cf_propose_thesis import stub_propose_thesis_result

        return stub_propose_thesis_result(n=1)

    invoke_cf_propose_thesis(n=1, http_post=_post)
    blob = posted["body"].decode("utf-8")
    assert "why_avoid" in blob
    assert "+" in blob
    hdrs = posted["headers"]
    assert "Authorization" not in hdrs or not str(hdrs.get("Authorization", "")).endswith(
        "+"
    )


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
