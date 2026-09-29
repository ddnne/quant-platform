"""Eval tracks / universe. ADV-ranked, never head-N. Not GO."""
from __future__ import annotations

def test_rank_eval_codes_is_not_head_n_and_skips_missing() -> None:
    from research.eval_universe import rank_eval_codes

    scored = [
        {"code": "AAAAA", "adv": 10.0, "n_bars": 50, "n_ta": 1, "n_eqar": 1},
        {"code": "BBBBB", "adv": 100.0, "n_bars": 50, "n_ta": 1, "n_eqar": 1},
        {"code": "CCCCC", "adv": 90.0, "n_bars": 10, "n_ta": 1, "n_eqar": 1},
        {"code": "DDDDD", "adv": 80.0, "n_bars": 50, "n_ta": 0, "n_eqar": 1},
        {"code": "EEEEE", "adv": 70.0, "n_bars": 50, "n_ta": 1, "n_eqar": 0},
        {"code": "FFFFF", "adv": 60.0, "n_bars": 50, "n_ta": 1, "n_eqar": 1},
    ]
    ranked = rank_eval_codes(scored, max_codes=10)
    assert ranked[0] == "BBBBB"
    assert ranked != [row["code"] for row in scored][: len(ranked)]
    assert "CCCCC" not in ranked
    assert "DDDDD" not in ranked
    assert "EEEEE" not in ranked
    assert "AAAAA" in ranked


def test_empty_pool_does_not_fall_back_to_head_n() -> None:
    from research.eval_universe import EVAL_UNIVERSE_POOL, select_eval_universe

    out = select_eval_universe(max_codes=10, pool=())
    assert out == []
    assert out != list(EVAL_UNIVERSE_POOL)[:10]
