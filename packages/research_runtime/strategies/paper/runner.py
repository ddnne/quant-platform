"""Backtest-backed Phase 5 paper run entry point."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import features
from core import (
    BacktestResult,
    leverage_financing,
    load_repo_rates_by_date_for_paper,
    run_backtest,
    short_financing,
    standard_cost,
)
from paper_runtime import (
    DATA_SNAPSHOT_FORMAT,
    data_snapshot_id,
    feature_definition_hashes,
    git_commit,
    strategy_definition_hash,
)

from .store import JsonPaperStore
from .types import PaperRunConfig, PaperRunResult


# 0.6.0 — Phase 5 paper runner baseline
# 0.6.1 — W85 optional short financing via PaperRunConfig
# 0.7.0 — W86 daily repo auto-load + leverage financing (mid + repo default)
PAPER_RUNNER_VERSION = "0.7.0"


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


def _resolve_repo_rates(
    config: PaperRunConfig,
    *,
    explicit: dict[str, float] | None,
    auto_load: bool,
    db_path: Path,
) -> tuple[dict[str, float] | None, dict[str, Any] | None]:
    """Resolve date→repo_pct for financing.

    Prefer explicit config rates; else auto-load from the paper DB via the
    core PIT helper when ``auto_load`` is True. Empty DB → ``None`` (fixed
    placeholder path). Never invents gap fills.
    """
    if explicit is not None:
        rates = {str(k)[:10]: float(v) for k, v in explicit.items()}
        return rates, {
            "load_path": "config_explicit",
            "series_present": bool(rates),
            "n_obs": len(rates),
            "gap_policy": "disclose_only_no_ffill_no_invent",
            "ffill_applied": False,
            "invent_fill": False,
        }
    if not auto_load:
        return None, {
            "load_path": "disabled",
            "series_present": False,
            "n_obs": 0,
            "gap_policy": "disclose_only_no_ffill_no_invent",
            "ffill_applied": False,
            "invent_fill": False,
        }
    try:
        pack = load_repo_rates_by_date_for_paper(
            db_path=db_path,
            start=config.start,
            end=config.end,
        )
    except Exception as exc:  # pragma: no cover - disclosed failure path
        return None, {
            "load_path": "pit.get_jsda_repo_rates",
            "series_present": False,
            "n_obs": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "gap_policy": "disclose_only_no_ffill_no_invent",
            "ffill_applied": False,
            "invent_fill": False,
            "note": "Repo auto-load failed; falling back to fixed placeholder.",
        }
    rates = dict(pack.get("rates_by_date") or {})
    if not rates:
        return None, pack
    return rates, pack


def _build_financing_models(
    config: PaperRunConfig,
    *,
    db_path: Path,
) -> tuple[Any, Any, dict[str, Any]]:
    """Build short + leverage financing models for one paper run.

    Defaults when enabled: **mid** short spread + date-matched repo when the
    series is present. Leverage uses the same repo series with **no** short
    spread (no double-count).
    """
    load_meta: dict[str, Any] = {
        "short_financing_enabled": bool(config.short_financing_enabled),
        "default_sensitivity": "mid",
        "double_count_policy": (
            "short = repo + spread; leverage = repo only on excess gross"
        ),
    }

    short_enabled = bool(config.short_financing_enabled)
    lev_flag = config.leverage_financing_enabled
    lev_enabled = bool(short_enabled if lev_flag is None else lev_flag)

    shared_rates: dict[str, float] | None = None
    shared_meta: dict[str, Any] | None = None

    sf_model = None
    if short_enabled:
        rates, meta = _resolve_repo_rates(
            config,
            explicit=config.short_financing_repo_rates,
            auto_load=bool(config.short_financing_auto_load_repo),
            db_path=db_path,
        )
        shared_rates, shared_meta = rates, meta
        load_meta["short_repo_load"] = meta
        sf_model = short_financing(
            sensitivity=str(config.short_financing_sensitivity or "mid"),
            spread_bp=config.short_financing_spread_bp,
            repo_rates_by_date=rates,
            fallback_repo_annual_bp=float(
                config.short_financing_fallback_repo_annual_bp or 0.0
            ),
            enabled=True,
        )

    lev_model = None
    if lev_enabled:
        if config.leverage_financing_repo_rates is not None:
            rates, meta = _resolve_repo_rates(
                config,
                explicit=config.leverage_financing_repo_rates,
                auto_load=False,
                db_path=db_path,
            )
        elif shared_rates is not None or shared_meta is not None:
            # Reuse short-leg series when both enabled (single load).
            rates, meta = shared_rates, shared_meta or {
                "load_path": "shared_with_short",
                "series_present": bool(shared_rates),
                "n_obs": len(shared_rates or {}),
            }
        else:
            rates, meta = _resolve_repo_rates(
                config,
                explicit=None,
                auto_load=bool(config.leverage_financing_auto_load_repo),
                db_path=db_path,
            )
        load_meta["leverage_repo_load"] = meta
        lev_model = leverage_financing(
            repo_rates_by_date=rates,
            fallback_repo_annual_bp=float(
                config.leverage_financing_fallback_repo_annual_bp or 0.0
            ),
            enabled=True,
        )

    load_meta["leverage_financing_enabled"] = lev_enabled
    load_meta["short_has_repo_series"] = bool(
        sf_model is not None and sf_model.has_repo_series
    )
    load_meta["leverage_has_repo_series"] = bool(
        lev_model is not None and lev_model.has_repo_series
    )
    return sf_model, lev_model, load_meta


def _reproducibility(
    result: BacktestResult,
    *,
    config: PaperRunConfig,
    snapshot_id: str,
    feature_versions: dict[str, str],
    feature_hashes: dict[str, str],
    strategy_hash: str,
    commit: str,
    financing_load: dict[str, Any] | None = None,
) -> dict[str, Any]:
    core_md = result.metadata
    return {
        "paper_runner_version": PAPER_RUNNER_VERSION,
        "core_engine_version": core_md["core_engine_version"],
        "pit_api_version": core_md["pit_api_version"],
        "features_runtime_version": features.__version__,
        "feature_versions": feature_versions,
        "feature_definition_hashes": feature_hashes,
        "period": {"start": config.start, "end": config.end},
        "execution_mode": core_md["execution_mode"],
        "as_of_rule": core_md["as_of_rule"],
        "cost_model": dict(core_md["cost_model"]),
        "short_financing": core_md.get("short_financing"),
        "short_financing_applied": core_md.get("short_financing_applied"),
        "leverage_financing": core_md.get("leverage_financing"),
        "leverage_financing_applied": core_md.get("leverage_financing_applied"),
        "repo_financing_load": financing_load,
        "universe": list(config.universe) if config.universe is not None else None,
        "universe_rule": core_md["universe_rule"],
        "lookback_days": core_md["lookback_days"],
        "price_basis": core_md["price_basis"],
        "starting_capital": core_md["starting_capital"],
        "strategy_id": core_md["strategy_id"],
        "params": dict(core_md["strategy_params"]),
        "strategy_params": dict(core_md["strategy_params"]),
        "strategy_params_hash": core_md["strategy_params_hash"],
        "strategy_definition_hash": strategy_hash,
        "git_commit": commit,
        "db_path": core_md["db_path"],
        "data_snapshot_format": DATA_SNAPSHOT_FORMAT,
        "data_snapshot_id": snapshot_id,
        "calendar_as_of": config.calendar_as_of,
        "trading_days": core_md["trading_days"],
    }


def _experiment_id(reproduction: dict[str, Any]) -> str:
    """Lifecycle-neutral deterministic identity of one experiment design."""
    payload = {
        "strategy_id": reproduction["strategy_id"],
        "strategy_params": reproduction["strategy_params"],
        "strategy_definition_hash": reproduction["strategy_definition_hash"],
        "feature_versions": reproduction["feature_versions"],
        "feature_definition_hashes": reproduction["feature_definition_hashes"],
        "data_snapshot_id": reproduction["data_snapshot_id"],
        "runtime_versions": {
            "paper_runner": reproduction["paper_runner_version"],
            "core_engine": reproduction["core_engine_version"],
            "pit_api": reproduction["pit_api_version"],
            "features_runtime": reproduction["features_runtime_version"],
        },
        "engine_config": {
            "period": reproduction["period"],
            "execution_mode": reproduction["execution_mode"],
            "as_of_rule": reproduction["as_of_rule"],
            "cost_model": reproduction["cost_model"],
            "short_financing": reproduction.get("short_financing"),
            "leverage_financing": reproduction.get("leverage_financing"),
            "universe": reproduction["universe"],
            "universe_rule": reproduction["universe_rule"],
            "lookback_days": reproduction["lookback_days"],
            "price_basis": reproduction["price_basis"],
            "starting_capital": reproduction["starting_capital"],
            "calendar_as_of": reproduction["calendar_as_of"],
        },
    }
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_paper(
    strategy: Any,
    config: PaperRunConfig,
    *,
    store: JsonPaperStore | None = None,
) -> PaperRunResult:
    """Run ``strategy`` through ``core.run_backtest`` and optionally persist it.

    A cheap control-plane snapshot id is computed before and after the run. A
    concurrent mutation fails closed rather than emitting reproduction
    metadata for a mixed snapshot.  For this deterministic pure-backtest
    runner, ``run_id == experiment_id`` by policy.

    W86 financing defaults (when enabled): mid short spread + daily repo
    series auto-loaded from the paper DB when present; leverage financing
    uses the same repo without re-applying short spread.
    """
    configured_path = Path(config.db_path or "data/structured/ingestion.sqlite")
    feature_versions = _feature_versions(strategy)
    feature_hashes = feature_definition_hashes(feature_versions)
    strategy_hash = strategy_definition_hash(strategy)
    commit = git_commit()
    # Resolve financing (may open DB via PIT for repo auto-load) **before**
    # the mutation-guard snapshot so a read-side WAL open is not mistaken for
    # concurrent data mutation during the backtest.
    sf_model, lev_model, financing_load = _build_financing_models(
        config, db_path=configured_path
    )
    before = data_snapshot_id(configured_path)
    backtest = run_backtest(
        strategy,
        config.start,
        config.end,
        db_path=config.db_path,
        execution_mode=config.execution_mode,
        cost_model=standard_cost(config.cost_bps),
        short_financing=sf_model,
        leverage_financing=lev_model,
        universe=config.universe,
        starting_capital=config.starting_capital,
        lookback_days=config.lookback_days,
        price_basis=config.price_basis,
        calendar_as_of=config.calendar_as_of,
    )
    after = data_snapshot_id(configured_path)
    if before != after:
        raise RuntimeError(
            "paper database changed during the run; retry against a stable "
            "ingestion snapshot so the result is reproducible"
        )

    reproduction = _reproducibility(
        backtest,
        config=config,
        snapshot_id=before,
        feature_versions=feature_versions,
        feature_hashes=feature_hashes,
        strategy_hash=strategy_hash,
        commit=commit,
        financing_load=financing_load,
    )
    experiment_id = _experiment_id(reproduction)
    result = PaperRunResult(
        experiment_id=experiment_id,
        run_id=experiment_id,
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
            f"Experiment: {result.experiment_id}",
            f"Strategy: {md['strategy_id']}",
            f"Period: {md['period']['start']} .. {md['period']['end']}",
            f"Return (post-cost): {float(metrics.get('total_return_post_cost', 0.0)):.6%}",
            f"Max drawdown: {float(metrics.get('max_drawdown', 0.0)):.6%}",
            f"Trades: {int(metrics.get('num_trades', len(result.trades)))}",
            f"Data snapshot: {md['data_snapshot_id']}",
        ]
    )
