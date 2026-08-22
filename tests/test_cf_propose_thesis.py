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


def test_worker_index_contains_propose_thesis_route() -> None:
    src = (
        _WORKER_INDEX.read_text(encoding="utf-8")
        + "\n"
        + _WORKER_PROPOSE.read_text(encoding="utf-8")
    )
    assert "/v1/propose-thesis" in src
    assert "stub_not_catalog" in src
    assert "not_injected: true" in src
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
    assert "stubProposals" in src
    assert "equities_bars_daily" in src
    assert "fins_summary" in src
    assert "PROPOSE_ALLOWED_GATES" in src
    assert "Do not invent datasets" in src or "do not invent datasets" in src.lower()
    assert "Title polarity MUST match gates" in src or "title polarity" in src.lower()
    assert "occupancy sentence" in src.lower()
    assert "slice(0, 24)" in src or "slice(0,24)" in src
    assert "weekday-only" in src or "No weekday" in src
    assert "2+" in src or "AND-cross" in src or "2 or 3" in src
    assert "Liquidity × Fundamentals" in src or "direction labels" in src
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


def test_catalog_gate_set_avoid_is_existing_crosses() -> None:
    from research.cf_propose_thesis import catalog_gate_set_avoid
    from research.unique_logic.constants import PROPOSE_CALENDAR_GATES

    tokens = catalog_gate_set_avoid(limit=8)
    assert 1 <= len(tokens) <= 8
    full = catalog_gate_set_avoid()
    assert len(full) == PROPOSE_WHY_AVOID_LIMIT
    assert PROPOSE_WHY_AVOID_LIMIT == 24
    assert all("+" in t for t in tokens)
    blob = " ".join(tokens)
    assert "skip_monday" not in blob
    assert "friday_skip" not in blob
    assert PROPOSE_CALENDAR_GATES.isdisjoint(
        {p for t in tokens for p in t.split("+")}
    )
    assert all(len(t.split("+")) == 2 for t in tokens) or tokens[0].count("+") == 1
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
