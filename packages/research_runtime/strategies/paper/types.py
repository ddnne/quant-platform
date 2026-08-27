"""Public result and configuration types for deterministic paper runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from core import BacktestResult
from price_basis import RAW, require_supported_price_basis


PAPER_RESULT_SCHEMA_VERSION = "paper-result/v2"
_PAPER_RESULT_V1_SCHEMA_VERSION = "paper-result/v1"


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


@dataclass(frozen=True, slots=True)
class PaperRunConfig:
    """Inputs to one backtest-backed paper run.

    ``db_path`` identifies an already-ingested structured database.  It is
    passed only to the trusted runtime, which binds it into the engine and the
    context feature accessor; strategies never receive a path, SQL connection,
    or PIT handle.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("PaperRunConfig is final")

    start: str
    end: str
    db_path: str | Path | None = None
    universe: tuple[str, ...] | list[str] | Mapping[str, Any] | None = None
    execution_mode: str = "next_close"
    cost_bps: float = 5.0
    starting_capital: float = 1_000_000.0
    lookback_days: int = 30
    price_basis: str = RAW
    # The importable low-level runtime is an offline fixture/backtest surface.
    # ``Lifecycle.PAPER`` remains a stable serialization label, but run_paper
    # and JsonPaperStore reject it.  Only a future OS-isolated authority may
    # issue controlled PAPER artifacts.
    lifecycle: Lifecycle | str = Lifecycle.DRAFT
    calendar_as_of: str | None = None
    # W85 / w0816t — short-leg financing = f(repo[t] + fixed spread).
    # Default **off** preserves long-only / legacy paper numerics. Enable
    # for CS L-S paper trials (short notional × (repo+spread)/days).
    short_financing_enabled: bool = False
    short_financing_sensitivity: str = "mid"  # low / mid / high → 25/50/150
    short_financing_spread_bp: float | None = None
    # Optional date→repo_pct (JSDA percent). Gaps → no invent charge.
    short_financing_repo_rates: dict[str, float] | None = None
    # Fixed repo annual bp when no series (disclosed placeholder; default 0).
    short_financing_fallback_repo_annual_bp: float = 0.0
    # W86 / w0816u — when financing enabled and rates not supplied, load daily
    # repo series from the paper DB via PIT (core helper). Default mid spread
    # + repo when series present; gaps disclosed only (no invent).
    short_financing_auto_load_repo: bool = True
    # Leverage financing = f(repo[t]) on excess gross above 1× (repo only —
    # never re-applies short spread). None → follow short_financing_enabled.
    leverage_financing_enabled: bool | None = None
    leverage_financing_repo_rates: dict[str, float] | None = None
    leverage_financing_fallback_repo_annual_bp: float = 0.0
    leverage_financing_auto_load_repo: bool = True

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
        sens = str(self.short_financing_sensitivity or "mid").strip().lower()
        if sens not in {"low", "mid", "high"}:
            raise ValueError(
                "short_financing_sensitivity must be one of low|mid|high"
            )
        object.__setattr__(self, "short_financing_sensitivity", sens)
        if self.leverage_financing_enabled is not None:
            object.__setattr__(
                self,
                "leverage_financing_enabled",
                bool(self.leverage_financing_enabled),
            )

        object.__setattr__(self, "lifecycle", Lifecycle.parse(self.lifecycle))
        object.__setattr__(
            self, "price_basis", require_supported_price_basis(self.price_basis)
        )
        if self.universe is not None:
            if getattr(self.universe, "membership_by_date", None) is not None:
                if not self.universe.membership_by_date:
                    raise ValueError("resolved daily universe cannot be empty")
            elif getattr(self.universe, "membership_proof", None):
                if not tuple(self.universe):
                    raise ValueError("PIT-proven universe cannot be empty")
            else:
                normalized = tuple(
                    sorted(
                        {
                            str(code).strip()
                            for code in self.universe
                            if str(code).strip()
                        }
                    )
                )
                if not normalized:
                    raise ValueError("universe cannot be empty when supplied")
                object.__setattr__(self, "universe", normalized)


@dataclass(frozen=True, slots=True)
class PaperRunResult:
    """One completed paper result plus its reproduction manifest."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("PaperRunResult is final")

    experiment_id: str
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
            "experiment_id": self.experiment_id,
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
        if schema not in {
            PAPER_RESULT_SCHEMA_VERSION,
            _PAPER_RESULT_V1_SCHEMA_VERSION,
        }:
            raise ValueError(
                f"unsupported paper result schema {schema!r}; "
                f"expected {PAPER_RESULT_SCHEMA_VERSION!r} or "
                f"{_PAPER_RESULT_V1_SCHEMA_VERSION!r}"
            )
        bt = payload.get("backtest")
        if not isinstance(bt, dict):
            raise ValueError("paper result is missing its backtest block")
        reproduction = payload.get("reproducibility")
        if not isinstance(reproduction, dict):
            raise ValueError("paper result is missing its reproducibility block")
        run_id = str(payload["run_id"])
        if schema == PAPER_RESULT_SCHEMA_VERSION:
            experiment_id = str(payload.get("experiment_id", "")).strip()
            if not experiment_id:
                raise ValueError("paper-result/v2 is missing experiment_id")
        else:
            # V1 used its lifecycle-sensitive run id as the only identity.  It
            # cannot be losslessly upgraded to a lifecycle-neutral experiment
            # id, so preserve that stable legacy identity when loading it.
            experiment_id = str(
                payload.get("experiment_id")
                or reproduction.get("experiment_id")
                or run_id
            )
        return cls(
            experiment_id=experiment_id,
            run_id=run_id,
            lifecycle=Lifecycle.parse(payload["lifecycle"]),
            backtest=BacktestResult(
                equity_curve=list(bt.get("equity_curve", [])),
                trades=list(bt.get("trades", [])),
                metrics=dict(bt.get("metrics", {})),
                metadata=dict(bt.get("metadata", {})),
            ),
            reproducibility=dict(reproduction),
        )
