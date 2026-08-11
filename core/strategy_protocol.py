"""Narrow strategy interface for the core backtest engine.

A :class:`Strategy` is a black-box callback the engine invokes once per
trading day. It receives a :class:`BarContext` — a **deliberately small** view
of the world — and returns a list of :class:`OrderIntent` (desired target
weights). The strategy never touches the database, never imports :mod:`pit`
or :mod:`storage`, and never sees a data handle. Direct facts are loaded by
the engine via the PIT Data API; derived values are requested through
``ctx.feature(...)``, whose trusted runtime accessor binds the decision
instant's ``as_of`` and database location.

This is the structural enforcement of the data boundary: facts enter the
engine only through ``pit.get_*`` (see :mod:`core.engine`), and reach the
strategy only via this narrow context. Look-ahead is prevented twice — once
by PIT (``available_at <= as_of``) and once by execution (a signal on day *D*
cannot fill on day *D* under ``next_close``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class Bar:
    """One PIT-visible daily OHLCV bar handed to a strategy.

    All fields are values the engine already read via PIT for the decision
    ``as_of``; the strategy cannot reach behind them.
    """

    code: str
    date: str  # YYYY-MM-DD (session date)
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    adjustment_close: float | None = None


@dataclass(frozen=True)
class Position:
    """An open position the engine currently holds."""

    code: str
    shares: float
    avg_cost: float | None = None


@dataclass(frozen=True)
class OrderIntent:
    """A strategy's desired exposure for one code, as a portfolio fraction.

    ``target_weight`` is the fraction of total equity (mark-to-market at the
    decision ``as_of``) the strategy wants held in ``code``:

    * ``1.0``  -> 100% of equity in this one code
    * ``0.0``  -> flat / exit
    * negative -> short (the minimal engine will reject / clip to flat; full
      shorting is out of scope)

    The engine converts weights to target shares using the last PIT-visible
    close at the decision ``as_of`` and trades the delta. Codes the strategy
    omits from a given ``on_bar`` response are **left untouched** (a buy & hold
    strategy therefore returns intents once and ``[]`` thereafter).
    """

    code: str
    target_weight: float
    note: str | None = None


@dataclass(frozen=True)
class EquityMaster:
    """Latest-known-as-of equity master snapshot for one code."""

    code: str
    snapshot_date: str
    company_name: str | None
    sector_17_code: str | None
    sector_33_code: str | None
    market_code: str | None
    scale_category: str | None


@dataclass(frozen=True)
class BarContext:
    """Everything a strategy may consult at one decision point.

    Intentionally carries **no** database path/handle and **no** ``pit``
    reference. Values were loaded by the engine through PIT at :attr:`as_of`
    (the decision instant); versioned derived values are available only via
    :meth:`feature`, which has the same scope injected by the runtime.
    Strategies must not read facts themselves.

    Attributes:
        as_of: The PIT decision instant (canonical JST ISO). Every fact on the
            context satisfies ``available_at <= as_of``.
        date: The decision trading date (``YYYY-MM-DD``).
        universe: TradablE codes as-of ``as_of`` (anti-survivorship: only
            names whose master was visible by the decision instant).
        positions: Currently held positions, by code.
        cash: Cash balance before this decision's fills.
        equity: Total equity (cash + positions carried at the last PIT-safe
            exact-session mark when the current session has no bar).
        prices: Last PIT-visible RAW close inside the signal lookback window
            (``None`` if a code has no visible bar in that window).
        bars: Signal-lookback PIT-visible daily bars per universe code, oldest
            first. Valuation marks are maintained independently.
        master: Latest-known-as-of master snapshot per universe code.
        feature: PIT-scoped versioned feature computation. Persisted
            declarative strategies supply an exact feature version plus its
            declared inputs; hand-written local strategies may follow latest.
    """

    as_of: str
    date: str
    universe: tuple[str, ...]
    positions: Mapping[str, Position]
    cash: float
    equity: float
    prices: Mapping[str, float | None]
    bars: Mapping[str, tuple[Bar, ...]]
    master: Mapping[str, EquityMaster]

    def feature(
        self,
        feature_id: str,
        /,
        *,
        version: str | None = None,
        **inputs: Any,
    ) -> Any:
        """Compute a feature through the engine's PIT-scoped runtime accessor.

        The engine binds this accessor for each decision bar.  It injects this
        context's :attr:`as_of` and the runtime-owned database location, so a
        strategy supplies only the feature identity and its declared inputs.
        ``StrategySpec`` calls must pass an exact ``version``; omitting it is
        retained only for hand-written local strategies that deliberately
        track the registry's latest version. The database location is
        deliberately not a context field.
        """
        reserved = {"as_of", "db_path"}.intersection(inputs)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise TypeError(f"ctx.feature owns runtime-scoped argument(s): {names}")
        accessor = getattr(self, "_feature_accessor", None)
        if accessor is None:
            raise RuntimeError(
                "BarContext feature accessor is not bound; contexts must be "
                "created by the trusted core runtime"
            )
        return accessor(feature_id, version=version, **inputs)

    def compute_feature(
        self,
        feature_id: str,
        /,
        *,
        version: str | None = None,
        **inputs: Any,
    ) -> Any:
        """Explicit alias for :meth:`feature`."""
        return self.feature(feature_id, version=version, **inputs)


class Strategy(Protocol):
    """The narrow protocol every strategy implements.

    A strategy is stateful by construction (it decides what to do given the
    current context). Implementations should be deterministic functions of
    ``(self state, ctx)`` so a backtest is reproducible.
    """

    def on_bar(self, ctx: BarContext) -> list[OrderIntent]:  # pragma: no cover
        """Return the desired target weights for this decision point."""
        ...


# Optional, well-defined hooks a strategy may expose for reproducibility
# metadata. Both default gracefully (see :func:`core.engine.describe_strategy`).
class DescribedStrategy(Protocol):  # pragma: no cover - structural typing
    """Optional interface for reproducible strategy identification."""

    strategy_id: str
    params: dict
