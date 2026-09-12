"""Private DataPlane owner for bound-decision-visible AM research reads.

Prior catalog versions are ranked by ``_iter_query_rows`` under the decision
availability/event wall. Same-day retrospective daily rows are ranked under
observed-through, then projected to the existing AM allowlist. This module is
not a public handle, Connection, or product enumerator. PM valuation, period-end
calendar proof, complete-master membership, and AM marks stay on their existing
owners.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from data_contracts.read_scopes import DatasetReadRequirement, DatasetReadScope
from ops.receipt_product import (
    iter_product_artifact_body_rows,
    product_row_digest,
)
from storage.schema import CATALOG_CODE_SQL

from .errors import PitError
from .financial_observations import (
    FinancialCatalogState,
    _owned_selection_from_raw_rows,
    _product_digest_from_raw,
)
from .personal_retrospective_session import _synthetic_d_am_signal_row
from .query import _iter_query_rows, normalize_as_of
from .read_clock import resolve_read_clock


THROUGH_BOUND_DECISION_VISIBLE_VIEW = "bound_decision_visible_view"
_BARS_DATASET = "equities_bars_daily"
_FINS_DATASET = "fins_summary"
_MASTER_DATASET = "equities_master"
_PAGE_ASC = "event_time, natural_key, source"
_PAGE_DESC = "event_time DESC, natural_key DESC, source DESC"
_OWNER_TOKEN = object()
_AM_ALIASES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "close": ("MC", "MorningClose", "morning_close"),
        "adjustment_close": (
            "MAdjC",
            "MorningAdjustmentClose",
            "morning_adjustment_close",
        ),
        "adjustment_volume": (
            "MorningAdjustmentVolume",
            "MAdjVo",
            "morning_adjustment_volume",
        ),
        "date": ("Date", "date"),
        "code": ("Code", "code"),
    }
)
_DAILY_ALIASES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "close": ("Close", "C"),
        "adjustment_close": ("AdjustmentClose", "AdjClose", "AdjC"),
        "volume": ("Volume", "Vo"),
        "adjustment_volume": ("AdjustmentVolume", "AdjVolume", "AdjVo"),
        "date": ("Date", "date"),
        "code": ("Code", "code"),
    }
)


class ScopedSelectionError(PitError):
    """Declared-scope selection failed closed."""


def _require_active_sqlite_transaction(conn: sqlite3.Connection) -> None:
    """Refuse use outside an open SQLite transaction.

    ``Connection.in_transaction`` is not proof of ``connect_readonly``,
    verifier-owned pinning, or READY/runtime integration.
    """
    if type(conn) is not sqlite3.Connection:
        raise ScopedSelectionError("scoped selection requires sqlite3.Connection")
    if not conn.in_transaction:
        raise ScopedSelectionError(
            "scoped selection requires an active SQLite transaction"
        )


@dataclass(frozen=True, slots=True)
class ScopedBarView:
    """AM research bar. Original clocks; no full-day/PM source payload."""

    code: str
    date: str
    natural_key: str
    event_time: str
    available_at: str
    ingested_at: str
    close: float | None
    adjustment_close: float | None
    volume: float | None
    adjustment_volume: float | None
    field_evidence: Mapping[str, str]
    contemporaneous_observation_unproven: bool
    product_row_digest: str
    same_day_am: bool


@dataclass(frozen=True, slots=True)
class ScopedFinancialView:
    """Compact financial owner output. No raw-row or payload array."""

    state: FinancialCatalogState
    selected_natural_key: str | None
    selected_product_digest: str | None
    field_evidence: Mapping[str, str]
    split_safety_anchor: str | None


def _row_text(row: Any, key: str) -> str:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return ""
    if value is None:
        return ""
    return str(value)


def _payload_dict(row: Any) -> dict[str, Any] | None:
    try:
        raw = row["payload"]
    except (KeyError, IndexError, TypeError):
        return None
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw:
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def _row_code(payload: Mapping[str, Any] | None, row: Any) -> str:
    if payload:
        for key in ("Code", "code"):
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    natural_key = _row_text(row, "natural_key")
    if natural_key:
        try:
            mapped = json.loads(natural_key)
        except (TypeError, ValueError):
            mapped = None
        if isinstance(mapped, dict):
            for key in ("Code", "code"):
                value = mapped.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
    return ""


def _row_event_date(payload: Mapping[str, Any] | None, row: Any) -> str:
    if payload:
        for key in ("Date", "date"):
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()[:10]
    return _row_text(row, "event_time")[:10]


def alias_field_evidence(
    payload: Mapping[str, Any] | None, aliases: Sequence[str]
) -> str:
    if not isinstance(payload, dict):
        return "missing"
    present = False
    saw_value = False
    for alias in aliases:
        if alias not in payload:
            continue
        present = True
        if payload[alias] is not None:
            saw_value = True
            break
    if not present:
        return "missing"
    return "present_value" if saw_value else "present_null"


def _bar_field_evidence(
    scope: DatasetReadScope, payload: Mapping[str, Any] | None, *, same_day_am: bool
) -> dict[str, str]:
    aliases = _AM_ALIASES if same_day_am else _DAILY_ALIASES
    evidence: dict[str, str] = {}
    for field in tuple(scope.fields) + tuple(scope.optional_fields):
        if same_day_am and field == "volume":
            evidence[field] = "absent_am_allowlist"
            continue
        evidence[field] = alias_field_evidence(payload, aliases.get(field, (field,)))
    return evidence


def _missing_required(
    scope: DatasetReadScope, evidence: Mapping[str, str], *, natural_key: str
) -> tuple[str, str, str] | None:
    for field in scope.fields:
        status = evidence.get(field)
        if status in {"missing", "absent_am_allowlist"}:
            return (natural_key, field, status or "missing")
    return None


def _require_am_requirement(requirement: DatasetReadRequirement) -> None:
    if requirement.clock == "same_trading_date_pm_close":
        raise ScopedSelectionError("PM valuation is a separate operation")
    if requirement.consumer_kind == "fill_am_mark":
        raise ScopedSelectionError("AM marks are a separate operation")
    if requirement.clock == "period_end_session_close":
        raise ScopedSelectionError(
            "period-end calendar proof is a separate operation"
        )
    if requirement.clock == "unconsumed_policy_membership":
        raise ScopedSelectionError("unconsumed membership cannot declare a read")
    if requirement.clock != THROUGH_BOUND_DECISION_VISIBLE_VIEW:
        raise ScopedSelectionError(
            "scoped AM research uses the bound decision-visible view"
        )
    if requirement.scope.unconsumed_membership:
        raise ScopedSelectionError("unconsumed membership cannot declare a read")
    if (
        requirement.scope.dataset_id == _MASTER_DATASET
        and requirement.scope.initial_visible_state
        == "latest_complete_snapshot_plus_updates"
    ):
        raise ScopedSelectionError(
            "equities_master latest_complete_snapshot_plus_updates requires "
            "the complete-master owner"
        )


def _iter_catalog_versions(
    conn: sqlite3.Connection,
    *,
    dataset_id: str,
    as_of: str,
    codes: Sequence[str] | None,
    extra_where: str | None = None,
    params: Sequence[Any] | None = None,
    order_by: str = _PAGE_ASC,
) -> Iterator[Any]:
    where = ["dataset = ?"]
    bound: list[Any] = [dataset_id]
    if extra_where:
        where.append(f"({extra_where})")
    if params:
        bound.extend(params)
    wanted = [str(code).strip() for code in (codes or ()) if str(code).strip()]
    if wanted:
        placeholders = ",".join("?" for _ in wanted)
        where.append(f"({CATALOG_CODE_SQL}) IN ({placeholders})")
        bound.extend(wanted)
    yield from _iter_query_rows(
        conn,
        as_of=as_of,
        table="jquants_records",
        dataset_id=dataset_id,
        extra_where=" AND ".join(where),
        params=bound,
        order_by=order_by,
    )


def _index_product_digests(product_artifact_bodies: Sequence[str]) -> frozenset[str]:
    """One full-segment parse per owner batch. Compact digest witness only."""

    if not product_artifact_bodies:
        raise ScopedSelectionError(
            "selected catalog version requires verified full-segment product backing"
        )
    digests: set[str] = set()
    for body in product_artifact_bodies:
        for row in iter_product_artifact_body_rows(body):
            digests.add(product_row_digest(row))
    return frozenset(digests)


def _require_product_backing(digest: str | None, witness: frozenset[str]) -> None:
    if digest is None or digest not in witness:
        raise ScopedSelectionError(
            "selected catalog version is not backed by its verified "
            "full-segment product generation"
        )


def _backed_catalog_rows(
    raw_rows: Iterator[Any], witness: frozenset[str]
) -> Iterator[Any]:
    """Every contributing catalog version must match the batch witness."""

    try:
        for raw in raw_rows:
            _require_product_backing(_product_digest_from_raw(raw), witness)
            yield raw
    finally:
        close = getattr(raw_rows, "close", None)
        if close is not None:
            close()


def _public_bar_view(
    raw: Any,
    *,
    scope: DatasetReadScope,
    decision_day: str,
    witness: frozenset[str],
) -> ScopedBarView:
    from .governed_am_view import _sealed_catalog_daily_bar

    payload = _payload_dict(raw)
    code = _row_code(payload, raw)
    day = _row_event_date(payload, raw)
    same_day = day == decision_day
    if not code or len(day) != 10:
        raise ScopedSelectionError("catalog bar is missing code or date")
    digest = _product_digest_from_raw(raw)
    _require_product_backing(digest, witness)
    source_bar = _sealed_catalog_daily_bar(
        raw, payload or {}, code=code, day=day
    )
    if same_day:
        projected = _synthetic_d_am_signal_row(
            source_bar, include_morning_turnover_history=False
        )
        close = projected.get("close")
        adjustment_close = projected.get("adjustment_close")
        adjustment_volume = projected.get("adjustment_volume")
        volume = None
    else:
        close = source_bar.get("close")
        adjustment_close = source_bar.get("adjustment_close")
        volume = source_bar.get("volume")
        adjustment_volume = source_bar.get("adjustment_volume")
    evidence = _bar_field_evidence(scope, payload, same_day_am=same_day)
    missing = _missing_required(scope, evidence, natural_key=_row_text(raw, "natural_key"))
    if missing:
        raise ScopedSelectionError(
            f"required field {missing[1]!r} is {missing[2]} on "
            f"{_BARS_DATASET}/{missing[0]}"
        )
    return ScopedBarView(
        code=code,
        date=day,
        natural_key=_row_text(raw, "natural_key"),
        event_time=_row_text(raw, "event_time"),
        available_at=_row_text(raw, "available_at"),
        ingested_at=_row_text(raw, "ingested_at"),
        close=None if close is None else close,
        adjustment_close=None if adjustment_close is None else adjustment_close,
        volume=volume,
        adjustment_volume=adjustment_volume,
        field_evidence=MappingProxyType(evidence),
        contemporaneous_observation_unproven=same_day,
        product_row_digest=digest,
        same_day_am=same_day,
    )


def _select_same_day_bars(
    conn: sqlite3.Connection,
    *,
    scope: DatasetReadScope,
    decision_as_of: str,
    observed_through: str,
    codes: Sequence[str],
    witness: frozenset[str],
) -> dict[str, ScopedBarView]:
    decision_day = decision_as_of[:10]
    found: dict[str, ScopedBarView] = {}
    for raw in _iter_catalog_versions(
        conn,
        dataset_id=_BARS_DATASET,
        as_of=observed_through,
        codes=codes,
        extra_where="substr(event_time, 1, 10) = ?",
        params=(decision_day,),
        order_by=_PAGE_ASC,
    ):
        view = _public_bar_view(
            raw,
            scope=scope,
            decision_day=decision_day,
            witness=witness,
        )
        found[view.code] = view
    return found


def _select_prior_bars(
    conn: sqlite3.Connection,
    *,
    scope: DatasetReadScope,
    decision_as_of: str,
    codes: Sequence[str],
    from_day: str | None,
    per_code_limit: Mapping[str, int] | None,
    witness: frozenset[str],
) -> dict[str, list[ScopedBarView]]:
    decision_day = decision_as_of[:10]
    wanted = {str(code) for code in codes}
    remaining = None if per_code_limit is None else dict(per_code_limit)
    collected: dict[str, list[ScopedBarView]] = {code: [] for code in wanted}
    collect_all = remaining is None and from_day is None
    if (
        remaining is not None
        and all(value <= 0 for value in remaining.values())
        and from_day is None
    ):
        return collected
    extra = ["substr(event_time, 1, 10) < ?"]
    params: list[Any] = [decision_day]
    need_older_than_window = remaining is not None and any(
        value > 0 for value in remaining.values()
    )
    if from_day is not None and not need_older_than_window:
        extra.insert(0, "substr(event_time, 1, 10) >= ?")
        params.insert(0, from_day)
    for raw in _iter_catalog_versions(
        conn,
        dataset_id=_BARS_DATASET,
        as_of=decision_as_of,
        codes=codes,
        extra_where=" AND ".join(extra),
        params=params,
        order_by=_PAGE_DESC,
    ):
        payload = _payload_dict(raw)
        code = _row_code(payload, raw)
        if code not in wanted:
            continue
        day = _row_event_date(payload, raw)
        need_latest = remaining is not None and remaining.get(code, 0) > 0
        need_window = from_day is not None and day >= from_day
        if not collect_all and not need_latest and not need_window:
            if (
                remaining is not None
                and all(value <= 0 for value in remaining.values())
                and (from_day is None or day < from_day)
            ):
                break
            continue
        view = _public_bar_view(
            raw,
            scope=scope,
            decision_day=decision_day,
            witness=witness,
        )
        collected[code].append(view)
        if remaining is not None and remaining.get(code, 0) > 0:
            remaining[code] = remaining[code] - 1
        if (
            remaining is not None
            and all(value <= 0 for value in remaining.values())
            and from_day is None
        ):
            break
    for code in collected:
        collected[code].reverse()
    return collected


def _select_bars(
    conn: sqlite3.Connection,
    *,
    requirement: DatasetReadRequirement,
    decision_as_of: str,
    observed_through: str,
    codes: Sequence[str],
    witness: frozenset[str],
    split_anchor: str | None = None,
) -> tuple[ScopedBarView, ...]:
    scope = requirement.scope
    count = scope.observation_count
    latest_n = None if count is None else count.value
    if latest_n is not None and (type(latest_n) is not int or latest_n < 1):
        raise ScopedSelectionError("latest_n must be a positive integer")
    if not codes:
        return ()
    same_day = _select_same_day_bars(
        conn,
        scope=scope,
        decision_as_of=decision_as_of,
        observed_through=observed_through,
        codes=codes,
        witness=witness,
    )
    interval_start = None
    if scope.split_safety_anchor_interval and split_anchor:
        text = str(split_anchor).strip()
        if text:
            try:
                interval_start = (
                    date.fromisoformat(text) - timedelta(days=31)
                ).isoformat()
            except ValueError:
                interval_start = None
    prior_limit = None
    if latest_n is not None:
        prior_limit = {
            str(code): latest_n - (1 if str(code) in same_day else 0)
            for code in codes
        }
        prior_limit = {
            code: max(0, limit) for code, limit in prior_limit.items()
        }
    prior = _select_prior_bars(
        conn,
        scope=scope,
        decision_as_of=decision_as_of,
        codes=codes,
        from_day=interval_start,
        per_code_limit=prior_limit,
        witness=witness,
    )
    selected: list[ScopedBarView] = []
    for code in codes:
        rows = list(prior.get(code, ()))
        d_row = same_day.get(code)
        if d_row is not None:
            rows.append(d_row)
        if latest_n is not None:
            latest = rows[-latest_n:]
        else:
            latest = rows
        if interval_start is not None:
            latest_date = latest[-1].date if latest else None
            window_rows = [
                row
                for row in rows
                if latest_date is not None
                and interval_start <= row.date <= latest_date
            ]
            by_digest: dict[str, ScopedBarView] = {}
            for row in (*window_rows, *latest):
                by_digest[row.product_row_digest] = row
            latest = sorted(
                by_digest.values(),
                key=lambda item: (item.date, item.natural_key),
            )
        selected.extend(latest)
    return tuple(selected)


def _select_financial(
    conn: sqlite3.Connection,
    *,
    requirement: DatasetReadRequirement,
    decision_as_of: str,
    code: str,
    witness: frozenset[str],
) -> ScopedFinancialView:
    scope = requirement.scope
    state_name = scope.initial_visible_state
    if state_name is None:
        raise ScopedSelectionError("financial scope requires initial_visible_state")
    raw_rows = _backed_catalog_rows(
        _iter_catalog_versions(
            conn,
            dataset_id=_FINS_DATASET,
            as_of=decision_as_of,
            codes=(code,),
            order_by=_PAGE_ASC,
        ),
        witness,
    )
    owned = _owned_selection_from_raw_rows(
        raw_rows,
        dataset=_FINS_DATASET,
        code=code,
        initial_visible_state=state_name,
    )
    column_evidence = dict(owned.payload_column_evidence or {})
    evidence: dict[str, str] = {}
    for field in scope.fields:
        if field in {"payload", "raw_payload"}:
            evidence[field] = column_evidence.get(field, "missing")
    observation = owned.state.observation
    anchor = None if observation is None else observation.get("split_safety_anchor")
    return ScopedFinancialView(
        state=owned.state,
        selected_natural_key=owned.evidence.selected_natural_key,
        selected_product_digest=owned.selected_product_digest,
        field_evidence=MappingProxyType(evidence),
        split_safety_anchor=None if anchor is None else str(anchor),
    )


class _OwnedScopedResearchOwner:
    """Private AM research owner. Full-product digest witness is built once.

    Selected catalog versions still match that witness in
    ``_public_bar_view`` / ``_backed_catalog_rows``. An active SQLite
    transaction is required; that check is not readonly ownership or
    verified-runtime integration. This is not receipt verification, READY
    minting, or a same-DB authenticity proof. Authenticated full-segment
    reconciliation stays on its existing owner.
    """

    __slots__ = ("_conn", "_witness")

    def __init__(
        self,
        token: object,
        *,
        conn: sqlite3.Connection,
        witness: frozenset[str],
    ) -> None:
        if token is not _OWNER_TOKEN:
            raise ScopedSelectionError(
                "scoped research owner is privately constructed"
            )
        _require_active_sqlite_transaction(conn)
        self._conn = conn
        self._witness = witness

    def select_am_research_scope(
        self,
        *,
        requirement: DatasetReadRequirement,
        decision_as_of: str,
        observed_through: str,
        codes: Sequence[str],
        split_anchor: str | None = None,
    ) -> ScopedBarView | ScopedFinancialView | tuple[ScopedBarView, ...]:
        _require_active_sqlite_transaction(self._conn)
        _require_am_requirement(requirement)
        decision = normalize_as_of(decision_as_of)
        supplied_observed = normalize_as_of(observed_through)
        clock = resolve_read_clock(decision, conn=self._conn)
        if supplied_observed != clock.observed_through:
            raise ScopedSelectionError(
                "supplied observed_through does not match the snapshot "
                "observation clock"
            )
        observed = clock.observed_through
        if decision > observed:
            raise ScopedSelectionError(
                "AM decision as_of is after snapshot observed_through"
            )
        dataset_id = requirement.scope.dataset_id
        if dataset_id == _FINS_DATASET:
            if len(tuple(codes)) != 1:
                raise ScopedSelectionError("financial scope requires one code")
            return _select_financial(
                self._conn,
                requirement=requirement,
                decision_as_of=decision,
                code=str(codes[0]),
                witness=self._witness,
            )
        if dataset_id == _BARS_DATASET:
            return _select_bars(
                self._conn,
                requirement=requirement,
                decision_as_of=decision,
                observed_through=observed,
                codes=tuple(str(code) for code in codes),
                witness=self._witness,
                split_anchor=split_anchor,
            )
        raise ScopedSelectionError(
            f"no AM research owner for dataset {dataset_id!r}"
        )


def _owned_scoped_research_owner(
    conn: sqlite3.Connection,
    *,
    product_artifact_bodies: Sequence[str],
) -> _OwnedScopedResearchOwner:
    """Pin full-product row digests once while this connection is in a transaction.

    The transaction check does not prove readonly ownership or verified
    publication/runtime pinning.
    """

    _require_active_sqlite_transaction(conn)
    return _OwnedScopedResearchOwner(
        _OWNER_TOKEN,
        conn=conn,
        witness=_index_product_digests(product_artifact_bodies),
    )


def sqlite_row_event_date(row: Any) -> str:
    """Event-date helper for actual sqlite3.Row values. No Mapping.get."""

    return _row_event_date(_payload_dict(row), row)


def sqlite_row_code(row: Any) -> str:
    """Code helper for actual sqlite3.Row values. No Mapping.get."""

    return _row_code(_payload_dict(row), row)


__all__ = [
    "ScopedBarView",
    "ScopedFinancialView",
    "ScopedSelectionError",
    "alias_field_evidence",
    "sqlite_row_code",
    "sqlite_row_event_date",
]
