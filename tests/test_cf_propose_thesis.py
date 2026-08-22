"""CF /v1/propose-thesis contract. Does not write catalog. Does not GO."""
from __future__ import annotations

from pathlib import Path

from research.cf_propose_thesis import (
    invoke_cf_propose_thesis,
    reject_window_tweak,
    stub_propose_thesis_result,
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


def test_worker_index_contains_propose_thesis_route() -> None:
    src = _WORKER_INDEX.read_text(encoding="utf-8")
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
    assert "stubProposals" in src
    assert "auto_inject: false" in src
