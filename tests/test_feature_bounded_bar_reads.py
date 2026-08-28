"""Feature hot paths bound PIT reads without changing null-tail semantics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from features.complete21_min_compute import _fundamental_value_score
from features.v0 import _momentum_n


class _TailContext:
    def __init__(
        self,
        *,
        bars: list[dict],
        inputs: dict,
        fins: list[dict] | None = None,
    ) -> None:
        self._bars = bars
        self._inputs = inputs
        self._fins = fins or []
        self.bar_limits: list[int | None] = []

    def get_input(self, name: str, default=None):
        return self._inputs.get(name, default)

    def get_equity_bars_daily(self, *, code: str, latest_n: int | None = None):
        assert code == self._inputs["code"]
        self.bar_limits.append(latest_n)
        rows = self._bars if latest_n is None else self._bars[-latest_n:]
        return SimpleNamespace(rows=rows)

    def get_jquants_records(self, *, dataset: str, code: str):
        assert dataset == "fins_summary"
        assert code == self._inputs["code"]
        return SimpleNamespace(rows=self._fins)


def _close(day: int, value: float | None) -> dict:
    return {"date": f"2025-04-{day:02d}", "close": value}


def test_momentum_common_path_reads_only_required_tail() -> None:
    ctx = _TailContext(
        bars=[_close(day, float(100 + day)) for day in range(1, 9)],
        inputs={"code": "8697", "n": 3},
    )

    result = _momentum_n(ctx)

    assert ctx.bar_limits == [4]
    assert result.metadata["rows_seen"] == 4
    assert result.value == pytest.approx((108.0 - 105.0) / 105.0)


def test_momentum_null_tail_falls_back_to_unbounded_legacy_selection() -> None:
    ctx = _TailContext(
        bars=[
            _close(1, 100.0),
            _close(2, 110.0),
            _close(3, 120.0),
            _close(4, None),
            _close(5, 130.0),
        ],
        inputs={"code": "8697", "n": 2},
    )

    result = _momentum_n(ctx)

    assert ctx.bar_limits == [3, None]
    assert result.metadata["rows_seen"] == 4
    assert result.value == pytest.approx((130.0 - 110.0) / 110.0)


def test_fundamental_null_latest_close_falls_back_to_last_valid_close() -> None:
    ctx = _TailContext(
        bars=[_close(1, 100.0), _close(2, None)],
        inputs={"code": "8697"},
        fins=[{"payload": {"DiscDate": "2025-04-01", "BPS": 50.0}}],
    )

    result = _fundamental_value_score(ctx)

    assert ctx.bar_limits == [1, None]
    assert result.value == pytest.approx(0.5)
    assert result.metadata["last_date"] == "2025-04-01"
