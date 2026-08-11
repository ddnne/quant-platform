"""Backtest-backed Phase 5 paper run entry point."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import features
from core import BacktestResult, run_backtest, standard_cost

from .store import JsonPaperStore
from .types import Lifecycle, PaperRunConfig, PaperRunResult


PAPER_RUNNER_VERSION = "0.5.0"


def fingerprint_db(db_path: str | Path) -> str:
    """Content fingerprint the SQLite main file and an active WAL, if any."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"paper database does not exist: {path}")
    components = [("main", path)]
    wal = path.with_name(path.name + "-wal")
    # SQLite may create an empty ``-wal`` sidecar while opening a read-only
    # fixture.  It contains no database state, so do not let its mere presence
    # make an otherwise stable run appear mutated.
    if wal.is_file() and wal.stat().st_size > 0:
        components.append(("wal", wal))

    digest = hashlib.sha256()
    for label, component in components:
        digest.update(label.encode("ascii"))
        digest.update(b"\0")
        with component.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _feature_versions(strategy: Any) -> dict[str, str]:
    explicit = getattr(strategy, "feature_versions", None)
    if isinstance(explicit, dict):
        return {str(k): str(v) for k, v in sorted(explicit.items())}
    ids = getattr(strategy, "feature_ids", ())
    return {
        str(feature_id): str(features.get(str(feature_id)).version)
        for feature_id in sorted(set(ids))
    }


def _reproducibility(
    result: BacktestResult,
    *,
    config: PaperRunConfig,
    db_fingerprint: str,
    feature_versions: dict[str, str],
) -> dict[str, Any]:
    core_md = result.metadata
    return {
        "paper_runner_version": PAPER_RUNNER_VERSION,
        "core_engine_version": core_md["core_engine_version"],
        "pit_api_version": core_md["pit_api_version"],
        "features_runtime_version": features.__version__,
        "feature_versions": feature_versions,
        "period": {"start": config.start, "end": config.end},
        "execution_mode": core_md["execution_mode"],
        "as_of_rule": core_md["as_of_rule"],
        "cost_model": dict(core_md["cost_model"]),
        "universe": list(config.universe) if config.universe is not None else None,
        "universe_rule": core_md["universe_rule"],
        "lookback_days": core_md["lookback_days"],
        "starting_capital": core_md["starting_capital"],
        "strategy_id": core_md["strategy_id"],
        "params": dict(core_md["strategy_params"]),
        "strategy_params": dict(core_md["strategy_params"]),
        "strategy_params_hash": core_md["strategy_params_hash"],
        "db_path": core_md["db_path"],
        "db_fingerprint": db_fingerprint,
        "trading_days": core_md["trading_days"],
    }


def _run_id(
    *,
    lifecycle: Lifecycle,
    reproduction: dict[str, Any],
    backtest: BacktestResult,
) -> str:
    payload = {
        "lifecycle": lifecycle.value,
        "reproducibility": reproduction,
        "metrics": backtest.metrics,
        "trades": backtest.trades,
        "equity_curve": backtest.equity_curve,
    }
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def run_paper(
    strategy: Any,
    config: PaperRunConfig,
    *,
    store: JsonPaperStore | None = None,
) -> PaperRunResult:
    """Run ``strategy`` through ``core.run_backtest`` and optionally persist it.

    The database is fingerprinted before and after the run.  A concurrent
    mutation fails closed rather than emitting misleading reproduction
    metadata for a mixed snapshot.
    """
    configured_path = Path(config.db_path or "data/structured/ingestion.sqlite")
    before = fingerprint_db(configured_path)
    backtest = run_backtest(
        strategy,
        config.start,
        config.end,
        db_path=config.db_path,
        execution_mode=config.execution_mode,
        cost_model=standard_cost(config.cost_bps),
        universe=config.universe,
        starting_capital=config.starting_capital,
        lookback_days=config.lookback_days,
        calendar_as_of=config.calendar_as_of,
    )
    after = fingerprint_db(configured_path)
    if before != after:
        raise RuntimeError(
            "paper database changed during the run; retry against a stable "
            "ingestion snapshot so the result is reproducible"
        )

    reproduction = _reproducibility(
        backtest,
        config=config,
        db_fingerprint=after,
        feature_versions=_feature_versions(strategy),
    )
    result = PaperRunResult(
        run_id=_run_id(
            lifecycle=config.lifecycle,
            reproduction=reproduction,
            backtest=backtest,
        ),
        lifecycle=config.lifecycle,
        backtest=backtest,
        reproducibility=reproduction,
    )
    if store is not None:
        store.save(result)
    return result


def format_paper_report(result: PaperRunResult) -> str:
    """Render a small human-readable report for terminals and logs."""
    metrics = result.metrics
    md = result.reproducibility
    return "\n".join(
        [
            f"Paper run {result.run_id} [{result.lifecycle.value}]",
            f"Strategy: {md['strategy_id']}",
            f"Period: {md['period']['start']} .. {md['period']['end']}",
            f"Return (post-cost): {float(metrics.get('total_return_post_cost', 0.0)):.6%}",
            f"Max drawdown: {float(metrics.get('max_drawdown', 0.0)):.6%}",
            f"Trades: {int(metrics.get('num_trades', len(result.trades)))}",
            f"DB: {md['db_fingerprint']}",
        ]
    )
