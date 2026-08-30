"""Feature compute runtime — pure, PIT-only, ``as_of``-required.

:func:`compute` is the single entry point. It:

1. Resolves the feature definition from the registry.
2. Validates that ``as_of`` was supplied (hard requirement — no default).
3. Validates required inputs are present.
4. Builds a :class:`FeatureContext` whose PIT getters are scoped to ``as_of``.
5. Calls ``feature.compute(ctx)`` and augments the returned metadata.

The compute function sees only the context; it has no ``db_path`` or input
mapping attribute, no connection, and no wall-clock time. Facts and declared
inputs enter only via scoped getters. The runtime keeps its database location
inside a private reader closure.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

import pit
from pit.query import resolve_db_path

from . import registry as _registry
from .dataset_guard import master_pit_history_start, require_feature_dataset
from .types import FeatureDefinition, FeatureOutput

FEATURES_RUNTIME_VERSION = "0.8.0"


class AsOfRequired(ValueError):
    """Raised when a feature compute call omits ``as_of``."""


class MissingInput(KeyError):
    """Raised when a required input is missing on a compute call."""


_NO_DEFAULT = object()
_RUNTIME_SCOPE_FIELDS = frozenset({"as_of", "db_path"})


class _BoundDailyBarsReader(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class _DailyBarsReaderCapability:
    """Engine-only: daily-bar reads locked to one as_of and db scope."""

    as_of: str
    db_path: str
    reader: _BoundDailyBarsReader


def bind_personal_retrospective_am_session_daily_bars(
    *, as_of: Any, db_path: Any
) -> _DailyBarsReaderCapability:
    """Positive capability for engine-created AM signal contexts.

    Ordinary ``compute`` callers cannot inject this reader, a later ``as_of``,
    or a different database scope. Other feature resources stay ordinary PIT
    reads at the bound 11:30 instant.
    """
    from pit.personal_retrospective_session import (
        get_personal_retrospective_am_signal_equity_bars_daily,
    )

    as_of_iso = _require_as_of(as_of)
    resolved_db = resolve_db_path(db_path)

    def reader(**kwargs: Any):
        reserved = sorted(_RUNTIME_SCOPE_FIELDS.intersection(kwargs))
        if reserved:
            raise TypeError(
                f"AM session daily-bar reader owns runtime-scoped argument(s): "
                f"{reserved}"
            )
        return get_personal_retrospective_am_signal_equity_bars_daily(
            as_of=as_of_iso, db_path=resolved_db, **kwargs
        )

    return _DailyBarsReaderCapability(
        as_of=as_of_iso, db_path=str(resolved_db), reader=reader
    )


@dataclass(frozen=True, slots=True)
class FeatureContext:
    """Read-only PIT-scoped context handed to a feature's ``compute``.

    The ``get_equity_bars_daily`` / ``get_equity_master`` /
    ``get_market_calendar`` shortcuts already inject ``as_of`` and the
    runtime-owned database scope. Feature inputs are available only through
    :meth:`get_input`. There is no database-path attribute, connection
    handle, HTTP client, or wall clock.
    """

    as_of: str
    _input_values: Mapping[str, Any]
    _pit_reader: Callable[[str, Mapping[str, Any]], Any]

    def get_input(self, name: str, default: Any = _NO_DEFAULT) -> Any:
        """Return one declared input without exposing the complete mapping."""
        if name in self._input_values:
            return self._input_values[name]
        if default is not _NO_DEFAULT:
            return default
        raise KeyError(f"feature input not supplied: {name!r}")

    def _read(self, resource: str, kwargs: Mapping[str, Any]):
        reserved = sorted(_RUNTIME_SCOPE_FIELDS.intersection(kwargs))
        if reserved:
            raise TypeError(
                f"FeatureContext owns runtime-scoped argument(s): {reserved}"
            )
        return self._pit_reader(resource, kwargs)

    def get_equity_bars_daily(self, **kwargs: Any):
        """PIT daily bars with the context's trusted scope injected.

        Maps to COMPLETE dataset ``equities_bars_daily`` (history-eligible).
        """
        require_feature_dataset(
            "equities_bars_daily", context="FeatureContext.get_equity_bars_daily"
        )
        return self._read("equity_bars_daily", kwargs)

    def _read_equity_master_official_island(self, kwargs: Mapping[str, Any]):
        """PIT master from official listed-info start; pre-2008-05-07 is empty.

        Not Dataset COMPLETE. Remaining PARTIAL after the official start stays
        PD-D2-MASTER. ``as_of`` is this context's trusted scope.
        """
        official_start = master_pit_history_start()
        if str(self.as_of)[:10] < official_start:
            return pit.PitResult(
                rows=[],
                metadata={
                    "as_of": self.as_of,
                    "table": "jquants_listed_info",
                    "count": 0,
                    "pit_api_version": pit.PIT_API_VERSION,
                    "source": "jquants",
                    "official_start": official_start,
                    "pd_id": "PD-D2-MASTER",
                },
            )
        return self._read("equity_master", kwargs)

    def get_equity_master(self, **kwargs: Any):
        """PIT equity master from official listed-info start 2008-05-07.

        ``equities_master`` remains PD-D2-MASTER (not Dataset COMPLETE) for
        remaining PARTIAL gaps after the official start. Features read the
        official island through PIT with this context's ``as_of``. as_of or
        snapshots before 2008-05-07 are empty / fail-closed. Tip-only AM,
        earnings calendar, and JSDA OTC stay permanent DEFER.
        """
        return self._read_equity_master_official_island(kwargs)

    def get_market_calendar(self, **kwargs: Any):
        """PIT market calendar with the context's trusted scope injected.

        Maps to COMPLETE dataset ``markets_calendar`` (history-eligible).
        """
        require_feature_dataset(
            "markets_calendar", context="FeatureContext.get_market_calendar"
        )
        return self._read("market_calendar", kwargs)

    def get_jquants_records(self, dataset: str, **kwargs: Any):
        """PIT generic catalog records with trusted scope injected.

        ``equities_master`` uses the same official-island path as
        :meth:`get_equity_master` (pre-2008-05-07 empty; on/after PIT with
        ``as_of``). Remaining PARTIAL stays PD-D2-MASTER; not Dataset
        COMPLETE. Tip-only AM, earnings calendar, and JSDA OTC stay
        permanent DEFER. Other DEFER ids fail closed before the PIT read.
        """
        if str(dataset).strip() == "equities_master":
            return self._read_equity_master_official_island(kwargs)
        eligible = require_feature_dataset(
            dataset, context="FeatureContext.get_jquants_records"
        )
        return self._read("jquants_records", {"dataset": eligible, **kwargs})

    def get_jsda_repo_rates(self, **kwargs: Any):
        """PIT JSDA Tokyo repo rates with the context's trusted scope injected.

        Maps to COMPLETE dataset ``jsda_tokyo_repo_rates`` (history-eligible).
        Permanent DEFER ids are fail-closed before the PIT read.
        """
        require_feature_dataset(
            "jsda_tokyo_repo_rates",
            context="FeatureContext.get_jsda_repo_rates",
        )
        return self._read("jsda_repo_rates", kwargs)


def _require_as_of(as_of: Any) -> str:
    if as_of is None:
        raise AsOfRequired(
            "features.compute requires an explicit `as_of` (PIT hard gate)"
        )
    # Pass through pit's normalizer (raises on invalid input).
    from pit.query import normalize_as_of
    return normalize_as_of(as_of)


def _validate_inputs(feature: FeatureDefinition, inputs: Mapping[str, Any]) -> None:
    missing = [
        k for k in feature.inputs.required_kwargs
        if k not in inputs or inputs[k] is None
    ]
    if missing:
        raise MissingInput(
            f"feature {feature.id!r} missing required inputs: {missing}"
        )


def _compute(
    feature,
    *,
    as_of: Any,
    db_path: Any = None,
    daily_bars_capability: _DailyBarsReaderCapability | None = None,
    **inputs: Any,
) -> FeatureOutput:
    if isinstance(feature, str):
        feature = _registry.get(feature)
    as_of_iso = _require_as_of(as_of)
    _validate_inputs(feature, inputs)

    resolved_db = resolve_db_path(db_path)
    if daily_bars_capability is not None:
        if not isinstance(daily_bars_capability, _DailyBarsReaderCapability):
            raise TypeError("daily_bars_capability is not a bound engine capability")
        if daily_bars_capability.as_of != as_of_iso:
            raise ValueError(
                "bound daily-bar capability as_of does not match compute as_of"
            )
        if daily_bars_capability.db_path != str(resolved_db):
            raise ValueError(
                "bound daily-bar capability db_path does not match compute db_path"
            )

    def _read_pit(resource: str, kwargs: Mapping[str, Any]):
        if resource == "equity_bars_daily" and daily_bars_capability is not None:
            return daily_bars_capability.reader(**dict(kwargs))
        readers = {
            "equity_bars_daily": pit.get_equity_bars_daily,
            "equity_master": pit.get_equity_master,
            "market_calendar": pit.get_market_calendar,
            "jquants_records": pit.get_jquants_records,
            "jsda_repo_rates": pit.get_jsda_repo_rates,
        }
        try:
            reader = readers[resource]
        except KeyError as exc:  # pragma: no cover - context methods are closed
            raise RuntimeError(f"unknown FeatureContext resource: {resource!r}") from exc
        return reader(as_of=as_of_iso, db_path=resolved_db, **dict(kwargs))

    ctx = FeatureContext(
        as_of=as_of_iso,
        _input_values=MappingProxyType(dict(inputs)),
        _pit_reader=_read_pit,
    )
    out = feature.compute(ctx)
    if not isinstance(out, FeatureOutput):
        raise TypeError(
            f"feature {feature.id!r} returned {type(out).__name__}; expected FeatureOutput"
        )
    md = dict(out.metadata)
    md.update({
        "feature_id": feature.id,
        "feature_version": str(feature.version),
        "as_of": as_of_iso,
        "pit_api_version": pit.PIT_API_VERSION,
        "features_runtime_version": FEATURES_RUNTIME_VERSION,
        "db_path": str(resolved_db),
    })
    if feature.price_basis is not None:
        md["price_basis"] = feature.price_basis
    return FeatureOutput(value=out.value, metadata=md)


def compute(
    feature,
    *,
    as_of: Any,
    db_path: Any = None,
    **inputs: Any,
) -> FeatureOutput:
    """Compute one feature at ``as_of`` with PIT-scoped reads.

    Parameters
    ----------
    feature : FeatureDefinition | str
        Either a registered :class:`~features.types.FeatureDefinition` or its
        registry id (e.g. ``"return_1d"``). When a str, the latest version is
        used; pin a version by passing the resolved definition.
    as_of : str
        **Required.** PIT decision instant. Anything accepted by
        ``pit.query.normalize_as_of`` (canonical JST ISO).
    db_path : Any, optional
        SQLite DB path (resolved via ``pit.query.resolve_db_path``).
    **inputs :
        Per-feature inputs. Required kwargs are validated against
        ``feature.inputs.required_kwargs``.

    Returns
    -------
    FeatureOutput
        The feature value with provenance metadata: ``feature_id``,
        ``feature_version``, ``as_of``, ``pit_api_version``,
        ``features_runtime_version``, ``rows_seen``, ``db_path``.
    """
    return _compute(feature, as_of=as_of, db_path=db_path, **inputs)


def compute_with_engine_daily_bars_capability(
    feature,
    *,
    as_of: Any,
    db_path: Any = None,
    daily_bars_capability: _DailyBarsReaderCapability,
    **inputs: Any,
) -> FeatureOutput:
    """Engine-only compute: AM session-masked daily bars, ordinary other PIT."""
    return _compute(
        feature,
        as_of=as_of,
        db_path=db_path,
        daily_bars_capability=daily_bars_capability,
        **inputs,
    )


def compute_many(
    feature_ids: list[str],
    *,
    as_of: Any,
    db_path: Any = None,
    **shared_inputs: Any,
) -> dict[str, FeatureOutput]:
    """Compute many features at the same ``as_of`` with shared inputs.

    Each feature still receives only its declared required inputs (extras are
    ignored). Useful for building a feature vector at a decision instant.
    """
    out: dict[str, FeatureOutput] = {}
    for fid in feature_ids:
        feat = _registry.get(fid)
        # Restrict inputs to those the feature declares (required + optional).
        accepted = set(feat.inputs.required_kwargs) | set(feat.inputs.optional_kwargs)
        kwargs = {k: v for k, v in shared_inputs.items() if k in accepted}
        out[fid] = compute(feat, as_of=as_of, db_path=db_path, **kwargs)
    return out
