"""Public result and configuration types for deterministic paper runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from core import BacktestResult


PAPER_RESULT_SCHEMA_VERSION = "paper-result/v1"


class Lifecycle(str, Enum):
    """Minimal strategy lifecycle used in Phase 5."""

    DRAFT = "Draft"
    PAPER = "Paper"

    @classmethod
    def parse(cls, value: "Lifecycle | str") -> "Lifecycle":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower()
        for member in cls:
            if member.value.lower() == normalized:
                return member
        raise ValueError(
            f"unknown lifecycle {value!r}; choose one of "
            f"{[member.value for member in cls]}"
        )


@dataclass(frozen=True)
class PaperRunConfig:
    """Inputs to one backtest-backed paper run.

    ``db_path`` identifies an already-ingested structured database.  It is
    passed only to the trusted ``core`` engine and to versioned feature
    computes; strategies never receive a SQL connection or PIT handle.
    """

    start: str
    end: str
    db_path: str | Path | None = None
    universe: tuple[str, ...] | list[str] | None = None
    execution_mode: str = "next_close"
    cost_bps: float = 5.0
    starting_capital: float = 1_000_000.0
    lookback_days: int = 30
    lifecycle: Lifecycle | str = Lifecycle.PAPER
    calendar_as_of: str | None = None

    def __post_init__(self) -> None:
        if not self.start or not self.end or self.start > self.end:
            raise ValueError("paper period requires start <= end")
        if self.execution_mode not in {"next_close", "same_day_close"}:
            raise ValueError(
                "execution_mode must be 'next_close' or 'same_day_close'"
            )
        if float(self.cost_bps) < 0:
            raise ValueError("cost_bps must be >= 0")
        if float(self.starting_capital) <= 0:
            raise ValueError("starting_capital must be > 0")
        if int(self.lookback_days) < 1:
            raise ValueError("lookback_days must be >= 1")

        object.__setattr__(self, "lifecycle", Lifecycle.parse(self.lifecycle))
        if self.universe is not None:
            normalized = tuple(
                sorted({str(code).strip() for code in self.universe if str(code).strip()})
            )
            if not normalized:
                raise ValueError("universe cannot be empty when supplied")
            object.__setattr__(self, "universe", normalized)


@dataclass(frozen=True)
class PaperRunResult:
    """One completed paper result plus its reproduction manifest."""

    run_id: str
    lifecycle: Lifecycle
    backtest: BacktestResult
    reproducibility: dict[str, Any]

    @property
    def metrics(self) -> dict[str, Any]:
        return self.backtest.metrics

    @property
    def trades(self) -> list[dict[str, Any]]:
        return self.backtest.trades

    @property
    def equity_curve(self) -> list[dict[str, Any]]:
        return self.backtest.equity_curve

    @property
    def metadata(self) -> dict[str, Any]:
        """Alias used by result consumers expecting a metadata block."""
        return self.reproducibility

    @property
    def strategy_id(self) -> str:
        return str(self.reproducibility["strategy_id"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAPER_RESULT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "lifecycle": self.lifecycle.value,
            "reproducibility": dict(self.reproducibility),
            "backtest": {
                "equity_curve": list(self.backtest.equity_curve),
                "trades": list(self.backtest.trades),
                "metrics": dict(self.backtest.metrics),
                "metadata": dict(self.backtest.metadata),
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PaperRunResult":
        schema = payload.get("schema_version")
        if schema != PAPER_RESULT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported paper result schema {schema!r}; "
                f"expected {PAPER_RESULT_SCHEMA_VERSION!r}"
            )
        bt = payload.get("backtest")
        if not isinstance(bt, dict):
            raise ValueError("paper result is missing its backtest block")
        reproduction = payload.get("reproducibility")
        if not isinstance(reproduction, dict):
            raise ValueError("paper result is missing its reproducibility block")
        return cls(
            run_id=str(payload["run_id"]),
            lifecycle=Lifecycle.parse(payload["lifecycle"]),
            backtest=BacktestResult(
                equity_curve=list(bt.get("equity_curve", [])),
                trades=list(bt.get("trades", [])),
                metrics=dict(bt.get("metrics", {})),
                metadata=dict(bt.get("metadata", {})),
            ),
            reproducibility=dict(reproduction),
        )
