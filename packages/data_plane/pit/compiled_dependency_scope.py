"""Compiled V3 dependency-scope selection on an owned DataPlane connection.

READY publication and the pinned Controlled opener share this owner. It does
not mint COMPLETE, clip signed artifacts, or import the product compiler.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from data_contracts.identity import natural_key as contract_natural_key
from data_contracts.read_scopes import DatasetReadRequirement
from ops.receipt_product import PRODUCT_ARTIFACT_FIELDS, product_row_digest
from storage.schema import CATALOG_CODE_SQL

from .errors import PitError
from .read_clock import (
    SNAPSHOT_OBSERVATION_LABEL,
    PitReadClock,
    install_read_clock,
)
from .scoped_selection import (
    ScopedBarView,
    ScopedFinancialView,
)
from .universe_pit import _calendar_dates


_SESSION_DATASETS = (
    "equities_bars_daily",
    "equities_master",
    "fins_summary",
    "indices_bars_daily_topix",
    "markets_calendar",
)
_MARKET_DATASETS = frozenset({"markets_calendar", "indices_bars_daily_topix"})


@dataclass(frozen=True, slots=True)
class CompiledControlledSelection:
    """Trusted compiled period/lookback/feature-consumer metadata."""

    period_start: str
    period_end: str
    lookback_trading_days: int
    profile_digest: str
    feature_consumers: tuple[Mapping[str, tuple[Any, ...]], ...]

    def __post_init__(self) -> None:
        if type(self.period_start) is not str or type(self.period_end) is not str:
            raise PitError("compiled universe period is missing")
        if (
            isinstance(self.lookback_trading_days, bool)
            or type(self.lookback_trading_days) is not int
            or self.lookback_trading_days < 0
        ):
            raise PitError("compiled lookback is missing")
        if (
            type(self.profile_digest) is not str
            or len(self.profile_digest) != 71
            or not self.profile_digest.startswith("sha256:")
        ):
            raise PitError("compiled profile digest is invalid")
        if not self.feature_consumers:
            raise PitError("compiled feature consumers are missing")
        frozen: list[Mapping[str, tuple[Any, ...]]] = []
        for consumers in self.feature_consumers:
            if not isinstance(consumers, Mapping) or not consumers:
                raise PitError("compiled feature consumers are missing")
            packed: dict[str, tuple[Any, ...]] = {}
            for consumer_id, items in consumers.items():
                if type(consumer_id) is not str or not consumer_id.strip():
                    raise PitError("compiled feature consumer_id is missing")
                requirements = tuple(items)
                if not requirements or any(
                    type(item) is not DatasetReadRequirement for item in requirements
                ):
                    raise PitError(
                        "compiled feature consumers require DatasetReadRequirement values"
                    )
                packed[consumer_id] = requirements
            frozen.append(MappingProxyType(packed))
        object.__setattr__(self, "feature_consumers", tuple(frozen))


@dataclass(frozen=True, slots=True)
class _CompiledDependencyScopeHits:
    selected_keys: Mapping[str, frozenset[str]]
    selected_versions: Mapping[str, frozenset[str]]


def _require_aware(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PitError(f"PIT dependency scope {label} is malformed") from exc
    if parsed.tzinfo is None:
        raise PitError(f"PIT dependency scope {label} lacks timezone")
    return parsed


def _payload_value(payload: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _payload_session_price(
    payload: Mapping[str, Any], keys: tuple[str, ...]
) -> float | None:
    for key in keys:
        value = payload.get(key)
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price == price and price not in (float("inf"), float("-inf")) and price > 0.0:
            return price
    return None


def _row_code(row: Mapping[str, Any]) -> str:
    return _payload_value(row["payload"], "Code", "code")


def _compact_fact(dataset_id: str, fact: Mapping[str, Any]) -> dict[str, Any]:
    payload = fact["payload"]
    expected_key = contract_natural_key(payload, dataset_id)
    if expected_key.startswith("hash:sha256:") or fact.get("natural_key") != expected_key:
        raise PitError(f"{dataset_id} natural key is noncanonical")
    ingested = str(fact.get("ingested_at") or "")
    if not ingested:
        raise PitError(
            f"{dataset_id} fact ingested after snapshot observed_through"
        )
    digest = fact.get("product_row_digest")
    if type(digest) is not str or not digest:
        raise PitError(
            f"{dataset_id} selected fact is missing product row digest"
        )
    return {
        "payload": payload,
        "natural_key": str(fact["natural_key"]),
        "event_date": str(fact["event_date"])[:10],
        "event_at": _require_aware(fact["event_time"], f"{dataset_id}.event_time"),
        "available_at": _require_aware(
            fact["available_at"], f"{dataset_id}.available_at"
        ),
        "ingested_at": ingested,
        "product_row_digest": digest,
    }


def _iter_catalog_facts(
    conn: sqlite3.Connection,
    dataset_id: str,
    *,
    period_end: str,
    catalog_decision_at: str,
    observed_through: str,
    codes: Sequence[str] = (),
    available_at_cutoff: str | None = None,
    event_start: str | None = None,
) -> Iterator[dict[str, Any]]:
    wanted = [str(code).strip() for code in codes if str(code).strip()]
    fields = ",".join(PRODUCT_ARTIFACT_FIELDS)
    sql = (
        f"SELECT {fields} FROM jquants_records "
        "WHERE source='jquants' AND dataset=? "
    )
    params: list[Any] = [dataset_id]
    if event_start is not None:
        sql += "AND substr(event_time, 1, 10) >= ? "
        params.append(str(event_start)[:10])
    sql += (
        "AND substr(event_time, 1, 10) <= ? AND event_time IS NOT NULL AND "
        "available_at IS NOT NULL AND ingested_at IS NOT NULL"
    )
    params.append(str(period_end)[:10])
    if wanted and dataset_id not in _MARKET_DATASETS:
        placeholders = ",".join("?" for _ in wanted)
        sql += f" AND {CATALOG_CODE_SQL} IN ({placeholders})"
        params.extend(wanted)
    sql += " ORDER BY source, dataset, natural_key"
    observed = _require_aware(observed_through, "observed_through")
    cutoff = _require_aware(
        available_at_cutoff or catalog_decision_at, "available_at_cutoff"
    )
    decision = _require_aware(catalog_decision_at, "decision_at")
    for raw in conn.execute(sql, params):
        row = {field: raw[field] for field in PRODUCT_ARTIFACT_FIELDS}
        if any(type(value) is not str for value in row.values()):
            raise PitError(f"{dataset_id} product row fields must be exact text")
        event_at = _require_aware(row["event_time"], f"{dataset_id}.event_time")
        available_at = _require_aware(
            row["available_at"], f"{dataset_id}.available_at"
        )
        ingested_at = _require_aware(
            row["ingested_at"], f"{dataset_id}.ingested_at"
        )
        if available_at_cutoff is None:
            if event_at > decision or available_at > decision or ingested_at > observed:
                continue
        elif available_at > cutoff or ingested_at > observed:
            continue
        payload_raw: Any = row["payload"]
        try:
            payload = json.loads(payload_raw) if payload_raw else None
        except json.JSONDecodeError as exc:
            raise PitError(f"{dataset_id} payload is not JSON") from exc
        if not isinstance(payload, Mapping):
            raise PitError(f"{dataset_id} payload is missing")
        yield _compact_fact(
            dataset_id,
            {
                "natural_key": row["natural_key"],
                "event_date": str(row["event_time"])[:10],
                "event_time": row["event_time"],
                "available_at": row["available_at"],
                "ingested_at": row["ingested_at"],
                "payload": {str(key): value for key, value in payload.items()},
                "product_row_digest": product_row_digest(row),
            },
        )


def _select_compiled_dependency_scope(
    conn: sqlite3.Connection,
    *,
    compiled: CompiledControlledSelection,
    observed_through: str,
    slices: Sequence[Any],
    resolved_universe: Any,
    scoped_owner: Any,
) -> _CompiledDependencyScopeHits:
    """Select exact keys and versions from compiled V3 requirements."""

    from .governed_am_view import (
        am_information_cutoff,
        official_afternoon_close_as_of,
    )

    period_start = compiled.period_start
    period_end = compiled.period_end
    max_lookback = compiled.lookback_trading_days
    catalog_decision_at = official_afternoon_close_as_of(period_end)
    proof_clock = PitReadClock(
        decision_at=catalog_decision_at,
        observed_through=observed_through,
        observation_label=SNAPSHOT_OBSERVATION_LABEL,
        promotable=True,
    )
    member_codes = tuple(
        sorted(
            {
                code
                for _day, codes in resolved_universe.decision_memberships
                for code in codes
            }
        )
    )
    selected_keys: dict[str, set[str]] = {
        dataset_id: set() for dataset_id in _SESSION_DATASETS
    }
    selected_digests: dict[str, set[str]] = {
        dataset_id: set() for dataset_id in _SESSION_DATASETS
    }

    def _facts(
        dataset_id: str,
        *,
        codes: Sequence[str] = (),
        available_at_cutoff: str | None = None,
        event_start: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        return _iter_catalog_facts(
            conn,
            dataset_id,
            period_end=period_end,
            catalog_decision_at=catalog_decision_at,
            observed_through=observed_through,
            codes=codes,
            available_at_cutoff=available_at_cutoff,
            event_start=event_start,
        )

    calendar_by_date: dict[str, dict[str, Any]] = {}
    for row in _facts("markets_calendar"):
        day = row["event_date"]
        if day in calendar_by_date:
            raise PitError(f"markets_calendar duplicates natural date {day}")
        ingested = _require_aware(
            row["ingested_at"], "markets_calendar.ingested_at"
        )
        if ingested > _require_aware(observed_through, "observed_through"):
            raise PitError(
                "markets_calendar fact ingested after snapshot observed_through"
            )
        calendar_by_date[day] = row

    start_clock = _require_aware(am_information_cutoff(period_start), "period_start")
    prior_trading = sorted(
        day
        for day, row in calendar_by_date.items()
        if day < period_start
        and row["available_at"] <= start_clock
        and _payload_value(
            row["payload"], "HolidayDivision", "HolDiv", "holiday_division"
        )
        == "1"
    )
    if len(prior_trading) < max_lookback:
        raise PitError(
            "PIT dependency scope lacks the exact calendar lookback: "
            f"visible={len(prior_trading)}, required={max_lookback}"
        )
    lookback_dates = (
        () if max_lookback == 0 else tuple(prior_trading[-max_lookback:])
    )
    scope_start = lookback_dates[0] if lookback_dates else period_start
    window_start = lookback_dates[0] if lookback_dates else period_start
    trading_dates: list[str] = []
    for day in _calendar_dates(scope_start, period_end):
        row = calendar_by_date.get(day)
        if row is None:
            raise PitError(f"markets_calendar missing exact scope date {day}")
        if row["available_at"] > _require_aware(am_information_cutoff(day), day):
            raise PitError(f"markets_calendar {day} is late at decision time")
        selected_keys["markets_calendar"].add(row["natural_key"])
        selected_digests["markets_calendar"].add(row["product_row_digest"])
        if (
            _payload_value(
                row["payload"], "HolidayDivision", "HolDiv", "holiday_division"
            )
            == "1"
        ):
            trading_dates.append(day)
    in_period_trading = tuple(
        day for day in trading_dates if period_start <= day <= period_end
    )
    if tuple(resolved_universe.membership_by_date) != in_period_trading:
        raise PitError(
            "resolved universe decision dates do not equal the exact calendar"
        )
    first_membership = resolved_universe.codes_for(in_period_trading[0])

    authorized_master_dates = {str(item.snapshot_date)[:10] for item in slices}
    if not authorized_master_dates:
        raise PitError("equities_master membership seed snapshot is missing")
    master_by_date: dict[str, dict[str, dict[str, Any]]] = {}
    for row in _facts(
        "equities_master",
        codes=member_codes,
        event_start=min(authorized_master_dates),
    ):
        ingested = _require_aware(row["ingested_at"], "equities_master.ingested_at")
        if ingested > _require_aware(observed_through, "observed_through"):
            raise PitError(
                "equities_master fact ingested after snapshot observed_through"
            )
        if row["event_date"] not in authorized_master_dates:
            continue
        code = _row_code(row)
        if code:
            master_by_date.setdefault(row["event_date"], {})[code] = row
    bars_by_day_code: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in _facts(
        "equities_bars_daily",
        codes=member_codes,
        available_at_cutoff=observed_through,
        event_start=window_start,
    ):
        ingested = _require_aware(
            row["ingested_at"], "equities_bars_daily.ingested_at"
        )
        if ingested > _require_aware(observed_through, "observed_through"):
            raise PitError(
                "equities_bars_daily fact ingested after snapshot observed_through"
            )
        code = _row_code(row)
        if code:
            bars_by_day_code.setdefault((row["event_date"], code), []).append(row)
    topix_by_day: dict[str, list[dict[str, Any]]] = {}
    for row in _facts(
        "indices_bars_daily_topix",
        event_start=window_start,
    ):
        ingested = _require_aware(
            row["ingested_at"], "indices_bars_daily_topix.ingested_at"
        )
        if ingested > _require_aware(observed_through, "observed_through"):
            raise PitError(
                "indices_bars_daily_topix fact ingested after snapshot observed_through"
            )
        topix_by_day.setdefault(row["event_date"], []).append(row)

    for day in in_period_trading:
        decision_clock = _require_aware(am_information_cutoff(day), day)
        members = resolved_universe.codes_for(day)
        visible_dates = [stamp for stamp in master_by_date if stamp <= day]
        if not visible_dates:
            raise PitError(f"equities_master missing daily PIT snapshot for {day}")
        latest_snapshot = max(visible_dates)
        master_by_code = {
            code: row
            for code, row in master_by_date[latest_snapshot].items()
            if row["event_at"] <= decision_clock
            and row["available_at"] <= decision_clock
        }
        missing_master = sorted(set(members) - set(master_by_code))
        if missing_master:
            raise PitError(
                f"equities_master missing resolved members at {day}: "
                f"{missing_master[:5]}"
            )
        for code in members:
            selected_keys["equities_master"].add(master_by_code[code]["natural_key"])
            selected_digests["equities_master"].add(
                master_by_code[code]["product_row_digest"]
            )

    with install_read_clock(proof_clock):
        for day in in_period_trading:
            members = resolved_universe.codes_for(day)
            decision_as_of = am_information_cutoff(day)
            for consumers in compiled.feature_consumers:
                for _consumer_id, requirements in consumers.items():
                    fins_req = None
                    bars_req = None
                    for requirement in requirements:
                        dataset_id = requirement.scope.dataset_id
                        if dataset_id == "fins_summary":
                            fins_req = requirement
                        elif dataset_id == "equities_bars_daily":
                            bars_req = requirement
                    for code in members:
                        split_anchor = None
                        if fins_req is not None:
                            financial = scoped_owner.select_am_research_scope(
                                requirement=fins_req,
                                decision_as_of=decision_as_of,
                                observed_through=observed_through,
                                codes=(code,),
                            )
                            if type(financial) is not ScopedFinancialView:
                                raise PitError(
                                    "READY financial consumer did not return "
                                    "ScopedFinancialView"
                                )
                            split_anchor = financial.split_safety_anchor
                            if financial.selected_natural_key:
                                selected_keys["fins_summary"].add(
                                    financial.selected_natural_key
                                )
                            for natural_key, _event_day in financial.visible_identities:
                                selected_keys["fins_summary"].add(natural_key)
                            if financial.state.visible_row_count != len(
                                financial.visible_product_digests
                            ):
                                raise PitError(
                                    "fins_summary visible product digests "
                                    "do not match counted observations"
                                )
                            for digest in financial.visible_product_digests:
                                if type(digest) is not str or not digest:
                                    raise PitError(
                                        "fins_summary visible observation "
                                        "is missing its product row digest"
                                    )
                                selected_digests["fins_summary"].add(digest)
                            if (
                                financial.state.visible_row_count < 1
                                and not financial.visible_identities
                            ):
                                raise PitError(
                                    f"fins_summary missing or late for {code} at {day}"
                                )
                        if bars_req is not None:
                            bars = scoped_owner.select_am_research_scope(
                                requirement=bars_req,
                                decision_as_of=decision_as_of,
                                observed_through=observed_through,
                                codes=(code,),
                                split_anchor=split_anchor,
                            )
                            if type(bars) is not tuple:
                                raise PitError(
                                    "READY bar consumer did not return scoped bars"
                                )
                            for bar in bars:
                                if type(bar) is not ScopedBarView:
                                    raise PitError(
                                        "READY bar consumer is not ScopedBarView"
                                    )
                                selected_keys["equities_bars_daily"].add(
                                    bar.natural_key
                                )
                                selected_digests["equities_bars_daily"].add(
                                    bar.product_row_digest
                                )

    observed_clock = _require_aware(observed_through, "observed_through")
    for day in trading_dates:
        decision_clock = _require_aware(
            official_afternoon_close_as_of(day), day
        )
        members = (
            resolved_universe.codes_for(day)
            if day >= period_start
            else first_membership
        )
        for code in members:
            matches = [
                row
                for row in bars_by_day_code.get((day, code), ())
                if row["available_at"] <= observed_clock
                and _require_aware(
                    row["ingested_at"], "equities_bars_daily.ingested_at"
                )
                <= observed_clock
                and _payload_session_price(
                    row["payload"],
                    ("MAdjC", "MorningAdjustmentClose", "morning_adjustment_close"),
                )
                is not None
                and _payload_session_price(
                    row["payload"],
                    (
                        "AAdjC",
                        "AfternoonAdjustmentClose",
                        "afternoon_adjustment_close",
                    ),
                )
                is not None
            ]
            if len(matches) != 1:
                raise PitError(
                    "equities_bars_daily historical MAdjC/AAdjC closure "
                    f"missing for {code}/{day}: rows={len(matches)}"
                )
            selected_keys["equities_bars_daily"].add(matches[0]["natural_key"])
            selected_digests["equities_bars_daily"].add(
                matches[0]["product_row_digest"]
            )
        topix = [
            row
            for row in topix_by_day.get(day, ())
            if row["event_at"] <= decision_clock
            and row["available_at"] <= decision_clock
        ]
        if len(topix) != 1:
            raise PitError(
                "indices_bars_daily_topix exact trading-date closure "
                f"missing/late for {day}: rows={len(topix)}"
            )
        selected_keys["indices_bars_daily_topix"].add(topix[0]["natural_key"])
        selected_digests["indices_bars_daily_topix"].add(
            topix[0]["product_row_digest"]
        )

    return _CompiledDependencyScopeHits(
        selected_keys=MappingProxyType(
            {key: frozenset(value) for key, value in selected_keys.items()}
        ),
        selected_versions=MappingProxyType(
            {key: frozenset(value) for key, value in selected_digests.items()}
        ),
    )
