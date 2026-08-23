"""CF /v1/propose-thesis contract. Does not write catalog. Does not GO."""
from __future__ import annotations

from pathlib import Path

from research.cf_propose_thesis import (
    PROPOSE_ALLOWED_DATASETS,
    PROPOSE_WHY_AVOID_LIMIT,
    invoke_cf_propose_thesis,
    reject_window_tweak,
    review_proposal_row,
)
from tests.cf_propose_stub import stub_propose_thesis_result
from research.unique_logic.constants import PROPOSE_ALLOWED_GATES

_WORKER_PROPOSE = (
    Path(__file__).resolve().parents[1]
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "src"
    / "propose_thesis.ts"
)


def _fresh_ok_proposal() -> dict:
    """3-AND not in catalog that review_proposal_row accepts. Avoids clone stale pins."""
    from itertools import combinations

    from research.unique_logic.catalog import combo_thesis_records
    from research.unique_logic.constants import (
        PRI_FLOW_GATES,
        PRI_RATE_GATES,
        PRI_VOL_GATES,
        SPARSE_GATE_COMBOS,
    )
    from research.unique_logic.propose_review_tables import (
        PROPOSE_CONTRADICTORY_GATE_PAIRS,
    )

    catalog_sets = {
        frozenset(str(x) for x in (row.get("gates") or []) if str(x).strip())
        for row in combo_thesis_records()
    }
    pri = sorted((PRI_VOL_GATES | PRI_FLOW_GATES | PRI_RATE_GATES) & PROPOSE_ALLOWED_GATES)
    for combo in combinations(pri, 3):
        s = frozenset(combo)
        if s in catalog_sets:
            continue
        if any(pair <= s for pair, _ in SPARSE_GATE_COMBOS):
            continue
        if any(contra <= s for contra in PROPOSE_CONTRADICTORY_GATE_PAIRS):
            continue
        prop = {
            "thesis": (
                f"PEAD when {combo[0].replace('_', ' ')} and "
                f"{combo[1].replace('_', ' ')} while "
                f"{combo[2].replace('_', ' ')} hold names skip missing PIT prints"
            ),
            "signal_definition": f"AND({', '.join(combo)}) PIT skip missing",
            "position_rule": "event-hold surprise sign",
            "datasets": [
                "equities_bars_daily",
                "fins_summary",
                "markets_margin_interest",
                "jsda_tokyo_repo_rates",
            ],
            "gates": list(combo),
        }
        if review_proposal_row(prop)["ok"]:
            return prop
    raise AssertionError("no fresh review-ok 3-AND remains")


def test_propose_eval_pack_never_writes_catalog() -> None:
    from research.cf_propose_thesis import propose_eval_pack

    pack = propose_eval_pack(
        {
            "ok": False,
            "error": "llm_failed",
            "n_adoptable": 0,
            "proposals": [],
            "reviews": [],
        },
        occupancy_by_track={"mid_n_explore": {}, "liq_large": {}},
        job_id="eval-cf-propose-test24em",
    )
    assert pack["written"] is False
    assert pack["catalog_written"] is False
    assert pack["auto_inject"] is False
    assert pack["llm_failed_not_soup"] is True
    assert pack["go"] is False


def test_local_catalog_write_block_reasons_do_not_inject() -> None:
    from research.cf_propose_thesis import local_catalog_write_block_reasons

    empty = {"mid_n_explore": {}, "liq_large": {}}
    assert local_catalog_write_block_reasons(
        {"gates": ["rich_iv", "uncrowded_margin", "easing"]},
        {"ok": False},
        occupancy_by_track=empty,
    ) == ["review_not_ok"]
    n_pri = local_catalog_write_block_reasons(
        {"gates": ["afterclose", "large_surprise"]},
        {"ok": True},
        occupancy_by_track=empty,
    )
    assert "n_pri<2" in n_pri
    missing = local_catalog_write_block_reasons(
        {"gates": ["rich_iv", "uncrowded_margin", "easing"]},
        {"ok": True},
        occupancy_by_track=empty,
    )
    assert "missing_2and_parents" in missing or "parent_lo<=0.22" in missing


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


def test_review_proposal_row_rejects_invent_and_weekday() -> None:
    good = _fresh_ok_proposal()
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
    from tests.cf_propose_phrase_cases import REVIEW_PHRASE_CASES

    ds = ["equities_bars_daily", "fins_summary", "jsda_tokyo_repo_rates"]
    assert len(REVIEW_PHRASE_CASES) >= 40
    for bad_thesis, gates, reason, good_thesis in REVIEW_PHRASE_CASES:
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
    from research.cf_propose_thesis import (
        CATALOG_GATE_SET_AVOID_LIMIT,
        assemble_why_avoid,
        catalog_prefer_pair_avoid,
        catalog_prefer_triple_avoid,
        sparse_gate_set_avoid,
        sparse_prefer_subset_avoid,
    )
    from research.unique_logic.propose_review_tables import propose_prompt_good

    full = catalog_gate_set_avoid()
    assert len(full) == CATALOG_GATE_SET_AVOID_LIMIT
    assert any(t.count("+") == 2 for t in full)
    assert any(t.count("+") == 1 for t in full)
    n3 = sum(1 for t in full if t.count("+") == 2)
    n2 = sum(1 for t in full if t.count("+") == 1)
    assert n3 >= CATALOG_GATE_SET_AVOID_LIMIT // 3
    assert n2 >= CATALOG_GATE_SET_AVOID_LIMIT // 3
    prefer_pairs = catalog_prefer_pair_avoid()
    good_tok = "+".join(sorted(str(g) for g in propose_prompt_good()["gates"]))
    assert good_tok not in prefer_pairs
    assembled = assemble_why_avoid()
    assert len(assembled) <= PROPOSE_WHY_AVOID_LIMIT
    from research.cf_propose_thesis import PROPOSE_BLOCKED_GATE_SETS

    for tok in PROPOSE_BLOCKED_GATE_SETS:
        assert tok in assembled
    for tok in prefer_pairs:
        assert tok in assembled
    triples = catalog_prefer_triple_avoid()
    assert good_tok not in assembled
    if len(propose_prompt_good()["gates"]) == 3:
        adopted_tok = "+".join(sorted(str(g) for g in propose_prompt_good()["gates"]))
        assert adopted_tok not in triples
    prefer_sparse = sparse_prefer_subset_avoid()
    assert "curve_flatten+overnight_p10+pb_rising" in sparse_gate_set_avoid()
    assert "curve_flatten+overnight_p10+pb_rising" in prefer_sparse
    for tok in prefer_sparse:
        assert tok in assembled
    assert all("+" in t for t in tokens)
    blob = " ".join(tokens)
    assert "skip_monday" not in blob
    assert "friday_skip" not in blob
    assert PROPOSE_CALENDAR_GATES.isdisjoint(
        {p for t in tokens for p in t.split("+")}
    )


def test_sparse_gate_set_avoid_is_in_why_avoid() -> None:
    import json

    from research.cf_propose_thesis import (
        sparse_gate_set_avoid,
        sparse_prefer_subset_avoid,
    )

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
    # Remaining SPARSE may truncate; prefer-subset SPARSE is reserved.
    for tok in sparse_prefer_subset_avoid():
        assert tok in avoid
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
        fresh = _fresh_ok_proposal()
        return {
            "ok": True,
            "workers_ai_used": True,
            "proposals": [
                {
                    **fresh,
                    "status": "llm_not_catalog",
                }
            ],
        }

    out = invoke_cf_propose_thesis(n=1, job_id="test-clone-retry", http_post=_post)
    assert len(calls) == 2
    assert "eq_ar_high+liq_high" in calls[1]["why_avoid"]
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
