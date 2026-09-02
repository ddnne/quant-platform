"""Trusted READY publication service. Product receives closed evidence only."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

from core.execution import (
    close_as_of,
    morning_close_as_of,
    operational_usable_by_as_of,
)
from data_contracts import coverage_contract_for
from data_contracts.identity import natural_key as contract_natural_key
from pit import PitError
from pit.governed_am_view import am_product_row_matches_session
from pit.read_clock import (
    PitReadClock,
    SNAPSHOT_OBSERVATION_LABEL,
    install_read_clock,
    visibility_predicates,
)
from research.universe_contract import (
    EXACT_FOUR_UNIVERSE_RULE_DIGEST,
    resolve_tse_prime_with_fins,
)
from selection.budget_ledger import MassResearchDisabledError
from paper_runtime.readiness_attestation import EXACT_FOUR_DATASET_IDS
from storage.receipt_crypto import (
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
)
from storage.coverage_ledger import CollectionReceipt
from storage.schema import CATALOG_CODE_SQL
from ops.receipt_product import (
    product_artifact_body_digest,
    product_artifact_digest_ordered,
)
from storage.verified_receipt import require_verified_collection_closure


def _calendar_dates(start: str, end: str) -> tuple[str, ...]:
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    values: list[str] = []
    while cursor <= stop:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


def canonical_digest(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _closed_applied_mirror_identity(
    identity: Mapping[str, object],
) -> dict[str, Any]:
    """Copy the sealed identity. Callers cannot inject or omit fields."""

    if type(identity) is not MappingProxyType:
        raise PitError("READY publication identity is not authority-frozen")
    closed: dict[str, Any] = {}
    for key, value in identity.items():
        if isinstance(value, Mapping):
            closed[str(key)] = dict(value)
        else:
            closed[str(key)] = value
    return json.loads(
        json.dumps(closed, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )


@dataclass(frozen=True, slots=True)
class VerifiedPublicationEvidence:
    """Closed READY publication result. Not a storage or SQL capability."""

    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class ReadyPublicationService:
    """Governed READY publication. Pre-READY scans stay closure-local."""

    def request_verified_publication(
        self,
        applied_mirror: object,
        binding: Any,
    ) -> VerifiedPublicationEvidence:
        """Publish request: closed evidence only. Not a catalog enumerator."""

        if isinstance(applied_mirror, (str, Path)):
            raise TypeError(
                "ReadyPublicationService does not accept a filesystem path"
            )
        from scripts.sync_d1_to_sqlite import (
            _consume_authenticated_applied_mirror_for_ready_publication,
        )

        return _consume_authenticated_applied_mirror_for_ready_publication(
            applied_mirror, binding
        )


def verify_controlled_publication_evidence(
    applied_mirror: object,
    binding: Any,
) -> VerifiedPublicationEvidence:
    """Consume one sealed applied-mirror handle through READY verification."""

    return ReadyPublicationService().request_verified_publication(
        applied_mirror, binding
    )


def _verify_publication_on_authenticated_mirror(
    conn: sqlite3.Connection,
    identity: Mapping[str, object],
    binding: Any,
) -> VerifiedPublicationEvidence:
    """Prove the exact natural-key closure consumed by the controlled pilot.

    A single historical row cannot prove a period.  This gate derives the
    versioned daily universe from the candidate snapshot, enumerates every
    calendar/master/bar/TOPIX/financials key needed by that universe and its
    longest lookback, enforces ``available_at <= decision as_of``, and then
    requires every selected key to belong to a current v4 signed collection
    closure whose structured digest reproduces from the local database.
    Catalog and product scans are closure-local: they never accept a caller
    clock, token, or path, and they never escape as rows or connections.
    """
    periods = {
        (str(profile.period_start), str(profile.period_end))
        for profile in binding.profiles
    }
    if len(periods) != 1:
        raise MassResearchDisabledError(
            "exact-four plans must share one governed universe period"
        )
    period_start, period_end = next(iter(periods))
    max_lookback = max(
        int(scope["required_lookback_trading_days"])
        for profile in binding.profiles
        for scope in profile.dataset_scopes
    )
    required_datasets = tuple(binding.required_datasets)
    expected_exact = frozenset(EXACT_FOUR_DATASET_IDS)
    if set(required_datasets) != expected_exact:
        raise MassResearchDisabledError(
            "exact-four PIT verifier dataset closure drifted"
        )

    calendar_start = (
        date.fromisoformat(period_start)
        - timedelta(days=max(int(max_lookback) * 3, 14))
    ).isoformat()
    from scripts.sync_d1_to_sqlite import (
        _authenticated_applied_mirror_connection_identity,
        _canonical_applied_mirror_identity_json,
        _require_canonical_applied_mirror_exported_at,
    )

    if type(conn) is not sqlite3.Connection:
        raise MassResearchDisabledError(
            "READY publication requires the pinned applied-mirror connection"
        )
    registered = _authenticated_applied_mirror_connection_identity(conn)
    if registered is None:
        raise MassResearchDisabledError(
            "READY publication connection is not the authenticated applied mirror"
        )
    try:
        closed_identity = _closed_applied_mirror_identity(identity)
        _canonical_applied_mirror_identity_json(dict(closed_identity))
        exported_at = _require_canonical_applied_mirror_exported_at(
            closed_identity.get("exported_at")
        )
        if closed_identity["exported_at"] != exported_at:
            raise PitError("READY publication identity is not canonical")
        physical_digest = registered.digest
        conn.row_factory = sqlite3.Row
        with nullcontext(conn) as conn:
            class _OwnedUniverseVerifier:
                """Purpose-specific universe capability. Not a SQL/path/row API."""

                def resolve_day_slices(
                    self,
                    *,
                    period_start: str,
                    period_end: str,
                    as_of_for_day: Mapping[str, str],
                ):
                    from pit.universe_pit import _universe_day_slices_from_connection

                    return _universe_day_slices_from_connection(
                        conn,
                        period_start=period_start,
                        period_end=period_end,
                        as_of_for_day=as_of_for_day,
                    )

            verifier = _OwnedUniverseVerifier()

            if _authenticated_applied_mirror_connection_identity(conn) is not registered:
                raise PitError("READY publication connection identity swapped")
            stamped = exported_at
            proof_clock = PitReadClock(
                decision_at=close_as_of(period_end),
                observed_through=stamped,
                observation_label=SNAPSHOT_OBSERVATION_LABEL,
                promotable=True,
            )
            catalog_required = {
                "source",
                "dataset",
                "natural_key",
                "event_time",
                "available_at",
                "ingested_at",
                "payload",
                "raw_payload",
            }
            receipt_required = {
                "source",
                "dataset",
                "segment_id",
                "segment_start",
                "segment_end",
                "expected_scope",
                "expected_items",
                "observed_items",
                "raw_page_count",
                "raw_row_count",
                "structured_row_count",
                "pagination_exhausted",
                "digests_json",
                "run_id",
                "status",
                "error",
                "checked_at",
            }
            product_required = {
                "operation_id",
                "run_id",
                "source",
                "dataset",
                "segment_id",
                "artifact_key",
                "artifact_digest",
                "artifact_body",
                "row_count",
                "byte_count",
                "manifest_key",
                "manifest_digest",
                "raw_manifest_key",
                "raw_manifest_digest",
                "raw_page_count",
                "raw_row_count",
                "raw_bytes",
                "committed_at",
            }
            product_row_fields = (
                "source",
                "dataset",
                "natural_key",
                "event_time",
                "available_at",
                "ingested_at",
                "payload",
                "raw_payload",
            )
            market_datasets = frozenset(
                {"markets_calendar", "indices_bars_daily_topix"}
            )

            def table_columns(table: str) -> set[str]:
                return {
                    str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")
                }

            def load_receipt_scope(
                datasets: Sequence[str],
            ) -> tuple[
                tuple[dict[str, Any], ...],
                tuple[dict[str, Any], ...],
                tuple[dict[str, Any], ...],
                tuple[dict[str, Any], ...],
            ]:
                columns = table_columns("jquants_records")
                if not catalog_required <= columns:
                    raise PitError(
                        "PIT dependency scope requires canonical jquants_records columns"
                    )
                placeholders = ",".join("?" for _ in datasets)
                if not receipt_required <= table_columns("collection_receipts"):
                    raise PitError(
                        "PIT dependency scope requires signed collection receipt columns"
                    )
                if not product_required <= table_columns(
                    "receipt_product_materializations"
                ):
                    raise PitError(
                        "PIT dependency scope requires receipt product materializations"
                    )
                if "authority_operation_id" not in table_columns("ingestion_run_log"):
                    raise PitError(
                        "PIT dependency scope requires authority-bound ingestion runs"
                    )
                collection_receipts = tuple(
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM collection_receipts WHERE source='jquants' "
                        f"AND dataset IN ({placeholders}) ORDER BY checked_at,run_id",
                        tuple(datasets),
                    )
                )
                run_ids = tuple(
                    dict.fromkeys(
                        int(row["run_id"])
                        for row in collection_receipts
                        if row.get("run_id") is not None
                    )
                )
                if not run_ids:
                    return collection_receipts, (), (), ()
                run_placeholders = ",".join("?" for _ in run_ids)
                bound = tuple(datasets) + run_ids
                product_materializations = tuple(
                    dict(row)
                    for row in conn.execute(
                        "SELECT operation_id,run_id,source,dataset,segment_id,"
                        "artifact_key,artifact_digest,artifact_body,row_count,"
                        "byte_count,manifest_key,manifest_digest,raw_manifest_key,"
                        "raw_manifest_digest,raw_page_count,raw_row_count,"
                        "raw_bytes,committed_at FROM receipt_product_materializations "
                        "WHERE source='jquants' "
                        f"AND dataset IN ({placeholders}) "
                        f"AND run_id IN ({run_placeholders})",
                        bound,
                    )
                )
                ingestion_runs = tuple(
                    dict(row)
                    for row in conn.execute(
                        "SELECT id,source,runtime,status,authority_operation_id "
                        f"FROM ingestion_run_log WHERE id IN ({run_placeholders})",
                        run_ids,
                    )
                )
                raw_retention_manifests = tuple(
                    dict(row)
                    for row in conn.execute(
                        "SELECT dataset,run_id,manifest_key,page_count,row_count,"
                        "raw_bytes,data_digest FROM raw_retention_manifests "
                        f"WHERE dataset IN ({placeholders}) "
                        f"AND run_id IN ({run_placeholders})",
                        bound,
                    )
                )
                return (
                    collection_receipts,
                    product_materializations,
                    ingestion_runs,
                    raw_retention_manifests,
                )

            def iter_catalog_product_rows(
                dataset: str,
                event_start: str,
                event_end: str,
                codes: Sequence[str] = (),
            ) -> Iterator[dict[str, str]]:
                vis_sql, vis_bound = visibility_predicates(proof_clock)
                wanted = [str(code).strip() for code in codes if str(code).strip()]
                fields = ",".join(product_row_fields)
                sql = (
                    f"SELECT {fields} FROM jquants_records "
                    "WHERE source='jquants' AND dataset=? "
                    "AND substr(event_time, 1, 10) >= ? "
                    "AND substr(event_time, 1, 10) <= ? AND "
                    + " AND ".join(vis_sql)
                )
                params: list[Any] = [
                    dataset,
                    str(event_start)[:10],
                    str(event_end)[:10],
                    *vis_bound,
                ]
                if wanted and dataset not in market_datasets:
                    placeholders = ",".join("?" for _ in wanted)
                    sql += f" AND {CATALOG_CODE_SQL} IN ({placeholders})"
                    params.extend(wanted)
                sql += " ORDER BY source, dataset, natural_key"
                for raw in conn.execute(sql, params):
                    row = {field: raw[field] for field in product_row_fields}
                    if any(type(value) is not str for value in row.values()):
                        raise PitError(
                            f"{dataset} product row fields must be exact text"
                        )
                    if (
                        row["event_time"] > proof_clock.decision_at
                        or row["available_at"] > proof_clock.decision_at
                        or row["ingested_at"] > proof_clock.observed_through
                    ):
                        continue
                    yield row

            def iter_catalog_fact_pages(
                dataset: str,
                event_start: str,
                event_end: str,
                codes: Sequence[str] = (),
                page_size: int = 64,
            ) -> Iterator[tuple[dict[str, Any], ...]]:
                if not isinstance(page_size, int) or page_size < 1:
                    raise PitError("READY catalog page size is invalid")
                page: list[dict[str, Any]] = []
                for row in iter_catalog_product_rows(
                    dataset,
                    event_start,
                    event_end,
                    codes,
                ):
                    payload_raw: Any = row["payload"]
                    try:
                        payload = json.loads(payload_raw) if payload_raw else None
                    except json.JSONDecodeError as exc:
                        raise PitError(f"{dataset} payload is not JSON") from exc
                    if not isinstance(payload, Mapping):
                        raise PitError(f"{dataset} payload is missing")
                    page.append(
                        {
                            "natural_key": row["natural_key"],
                            "event_date": str(row["event_time"])[:10],
                            "event_time": row["event_time"],
                            "available_at": row["available_at"],
                            "ingested_at": row["ingested_at"],
                            "payload": {
                                str(key): value for key, value in payload.items()
                            },
                        }
                    )
                    if len(page) >= page_size:
                        yield tuple(page)
                        page.clear()
                if page:
                    yield tuple(page)

            as_of_for_day = {
                day: morning_close_as_of(day)
                for day in _calendar_dates(period_start, period_end)
            }
            with install_read_clock(proof_clock):
                slices = verifier.resolve_day_slices(
                    period_start=period_start,
                    period_end=period_end,
                    as_of_for_day=as_of_for_day,
                )
            resolved_universe = resolve_tse_prime_with_fins(
                slices,
                period_start=period_start,
                period_end=period_end,
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
            (
                collection_receipts,
                product_materializations,
                ingestion_runs,
                raw_retention_manifests,
            ) = load_receipt_scope(required_datasets)

            def _as_datetime(value: Any, label: str) -> datetime:
                try:
                    parsed = datetime.fromisoformat(
                        str(value).replace("Z", "+00:00")
                    )
                except (TypeError, ValueError) as exc:
                    raise MassResearchDisabledError(
                        f"PIT dependency scope {label} is malformed"
                    ) from exc
                if parsed.tzinfo is None:
                    raise MassResearchDisabledError(
                        f"PIT dependency scope {label} lacks timezone"
                    )
                return parsed

            def _payload_value(payload: Mapping[str, Any], *names: str) -> str:
                for name in names:
                    value = payload.get(name)
                    if value is not None and str(value).strip():
                        return str(value).strip()
                return ""

            def _row_code(row: Mapping[str, Any]) -> str:
                return _payload_value(row["payload"], "Code", "code")

            def _compact_fact(dataset_id: str, fact: Mapping[str, Any]) -> dict[str, Any]:
                payload = fact["payload"]
                expected_key = contract_natural_key(payload, dataset_id)
                if (
                    expected_key.startswith("hash:sha256:")
                    or fact.get("natural_key") != expected_key
                ):
                    raise MassResearchDisabledError(
                        f"{dataset_id} natural key is noncanonical"
                    )
                ingested = str(fact.get("ingested_at") or "")
                if not ingested or ingested > proof_clock.observed_through:
                    raise MassResearchDisabledError(
                        f"{dataset_id} fact ingested after snapshot observed_through"
                    )
                return {
                    "payload": payload,
                    "natural_key": str(fact["natural_key"]),
                    "event_date": str(fact["event_date"])[:10],
                    "event_at": _as_datetime(
                        fact["event_time"], f"{dataset_id}.event_time"
                    ),
                    "available_at": _as_datetime(
                        fact["available_at"], f"{dataset_id}.available_at"
                    ),
                    "ingested_at": ingested,
                }

            def _iter_dataset_facts(dataset_id: str, *, codes: Sequence[str] = ()):
                try:
                    for page in iter_catalog_fact_pages(
                        dataset_id,
                        calendar_start,
                        period_end,
                        codes,
                    ):
                        for fact in page:
                            yield _compact_fact(dataset_id, fact)
                except PitError as exc:
                    raise MassResearchDisabledError(str(exc)) from exc

            calendar_by_date: dict[str, dict[str, Any]] = {}
            for row in _iter_dataset_facts("markets_calendar"):
                day = row["event_date"]
                if day in calendar_by_date:
                    raise MassResearchDisabledError(
                        f"markets_calendar duplicates natural date {day}"
                    )
                calendar_by_date[day] = row

            start_clock = _as_datetime(
                morning_close_as_of(period_start), "period_start"
            )
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
                raise MassResearchDisabledError(
                    "PIT dependency scope lacks the exact calendar lookback: "
                    f"visible={len(prior_trading)}, required={max_lookback}"
                )
            lookback_dates = tuple(prior_trading[-max_lookback:])
            scope_start = lookback_dates[0] if lookback_dates else period_start

            cursor = datetime.fromisoformat(scope_start).date()
            end_date = datetime.fromisoformat(period_end).date()
            calendar_dates: list[str] = []
            while cursor <= end_date:
                calendar_dates.append(cursor.isoformat())
                cursor = cursor.fromordinal(cursor.toordinal() + 1)
            selected_keys: dict[str, set[str]] = {
                dataset_id: set() for dataset_id in required_datasets
            }
            selected_event_dates: dict[str, dict[str, str]] = {
                dataset_id: {} for dataset_id in required_datasets
            }
            trading_dates: list[str] = []
            for day in calendar_dates:
                row = calendar_by_date.get(day)
                if row is None:
                    raise MassResearchDisabledError(
                        f"markets_calendar missing exact scope date {day}"
                    )
                if row["available_at"] > _as_datetime(
                    morning_close_as_of(day), day
                ):
                    raise MassResearchDisabledError(
                        f"markets_calendar {day} is late at decision time"
                    )
                selected_keys["markets_calendar"].add(row["natural_key"])
                selected_event_dates["markets_calendar"][row["natural_key"]] = row[
                    "event_date"
                ]
                if _payload_value(
                    row["payload"], "HolidayDivision", "HolDiv", "holiday_division"
                ) == "1":
                    trading_dates.append(day)
            in_period_trading = tuple(
                day for day in trading_dates if period_start <= day <= period_end
            )
            if tuple(resolved_universe.membership_by_date) != in_period_trading:
                raise MassResearchDisabledError(
                    "resolved universe decision dates do not equal the exact calendar"
                )
            first_membership = resolved_universe.codes_for(in_period_trading[0])

            master_by_date: dict[str, dict[str, dict[str, Any]]] = {}
            for row in _iter_dataset_facts("equities_master", codes=member_codes):
                code = _row_code(row)
                if code:
                    master_by_date.setdefault(row["event_date"], {})[code] = row
            fins_by_code: dict[str, list[dict[str, Any]]] = {}
            for row in _iter_dataset_facts("fins_summary", codes=member_codes):
                code = _row_code(row)
                if code:
                    fins_by_code.setdefault(code, []).append(row)
            bars_by_day_code: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for row in _iter_dataset_facts("equities_bars_daily", codes=member_codes):
                code = _row_code(row)
                if code:
                    bars_by_day_code.setdefault((row["event_date"], code), []).append(row)
            am_by_day_code: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for row in _iter_dataset_facts(
                "equities_bars_daily_am", codes=member_codes
            ):
                code = _row_code(row)
                if code:
                    am_by_day_code.setdefault((row["event_date"], code), []).append(
                        row
                    )
            topix_by_day: dict[str, list[dict[str, Any]]] = {}
            for row in _iter_dataset_facts("indices_bars_daily_topix"):
                topix_by_day.setdefault(row["event_date"], []).append(row)

            for day in in_period_trading:
                decision_clock = _as_datetime(morning_close_as_of(day), day)
                members = resolved_universe.codes_for(day)
                visible_dates = [stamp for stamp in master_by_date if stamp <= day]
                if not visible_dates:
                    raise MassResearchDisabledError(
                        f"equities_master missing daily PIT snapshot for {day}"
                    )
                latest_snapshot = max(visible_dates)
                master_by_code = {
                    code: row
                    for code, row in master_by_date[latest_snapshot].items()
                    if row["event_at"] <= decision_clock
                    and row["available_at"] <= decision_clock
                }
                missing_master = sorted(set(members) - set(master_by_code))
                if missing_master:
                    raise MassResearchDisabledError(
                        f"equities_master missing resolved members at {day}: "
                        f"{missing_master[:5]}"
                    )
                for code in members:
                    selected_keys["equities_master"].add(
                        master_by_code[code]["natural_key"]
                    )
                    selected_event_dates["equities_master"][
                        master_by_code[code]["natural_key"]
                    ] = master_by_code[code]["event_date"]
                    fins = [
                        row
                        for row in fins_by_code.get(code, ())
                        if row["event_at"] <= decision_clock
                        and row["available_at"] <= decision_clock
                    ]
                    if not fins:
                        raise MassResearchDisabledError(
                            f"fins_summary missing or late for {code} at {day}"
                        )
                    latest_fins = max(
                        fins,
                        key=lambda row: (
                            row["event_at"],
                            row["available_at"],
                            row["natural_key"],
                        ),
                    )
                    selected_keys["fins_summary"].add(latest_fins["natural_key"])
                    selected_event_dates["fins_summary"][latest_fins["natural_key"]] = (
                        latest_fins["event_date"]
                    )
                    am_matches = [
                        row
                        for row in am_by_day_code.get((day, code), ())
                        if am_product_row_matches_session(
                            event_time=row["event_at"].isoformat(),
                            available_at=row["available_at"].isoformat(),
                            ingested_at=row["ingested_at"],
                            session_date=day,
                        )
                    ]
                    if len(am_matches) != 1:
                        raise MassResearchDisabledError(
                            "equities_bars_daily_am same-day operational closure "
                            f"missing/late for {code}/{day}: rows={len(am_matches)}; "
                            f"usable_by={operational_usable_by_as_of(day)}"
                        )
                    selected_keys["equities_bars_daily_am"].add(
                        am_matches[0]["natural_key"]
                    )
                    selected_event_dates["equities_bars_daily_am"][
                        am_matches[0]["natural_key"]
                    ] = am_matches[0]["event_date"]

            for day in trading_dates:
                decision_clock = _as_datetime(close_as_of(day), day)
                members = (
                    resolved_universe.codes_for(day)
                    if day >= period_start
                    else first_membership
                )
                for code in members:
                    matches = [
                        row
                        for row in bars_by_day_code.get((day, code), ())
                        if row["event_at"] <= decision_clock
                        and row["available_at"] <= decision_clock
                    ]
                    if len(matches) != 1:
                        raise MassResearchDisabledError(
                            "equities_bars_daily natural-key closure missing/late for "
                            f"{code}/{day}: rows={len(matches)}"
                        )
                    selected_keys["equities_bars_daily"].add(
                        matches[0]["natural_key"]
                    )
                    selected_event_dates["equities_bars_daily"][
                        matches[0]["natural_key"]
                    ] = matches[0]["event_date"]
                topix = [
                    row
                    for row in topix_by_day.get(day, ())
                    if row["event_at"] <= decision_clock
                    and row["available_at"] <= decision_clock
                ]
                if len(topix) != 1:
                    raise MassResearchDisabledError(
                        "indices_bars_daily_topix exact trading-date closure "
                        f"missing/late for {day}: rows={len(topix)}"
                    )
                selected_keys["indices_bars_daily_topix"].add(
                    topix[0]["natural_key"]
                )
                selected_event_dates["indices_bars_daily_topix"][
                    topix[0]["natural_key"]
                ] = topix[0]["event_date"]

            verified_segments: dict[
                str, list[tuple[str, str, str, str]]
            ] = {
                dataset_id: [] for dataset_id in required_datasets
            }
            for raw in collection_receipts:
                stored = dict(raw)
                dataset_id = str(stored["dataset"])
                try:
                    expected_scope = json.loads(str(stored["expected_scope"]))
                    digests = json.loads(str(stored["digests_json"]))
                    receipt = CollectionReceipt(
                        source=str(stored["source"]),
                        dataset=dataset_id,
                        segment_id=str(stored["segment_id"]),
                        segment_start=str(stored["segment_start"]),
                        segment_end=str(stored["segment_end"]),
                        expected_scope=expected_scope,
                        expected_items=(
                            None
                            if stored["expected_items"] is None
                            else int(stored["expected_items"])
                        ),
                        observed_items=int(stored["observed_items"]),
                        raw_page_count=int(stored["raw_page_count"]),
                        raw_row_count=int(stored["raw_row_count"]),
                        structured_row_count=int(stored["structured_row_count"]),
                        pagination_exhausted=bool(stored["pagination_exhausted"]),
                        digests=digests,
                        run_id=int(stored["run_id"]),
                        status=str(stored["status"]),
                        error=(
                            None if stored["error"] is None else str(stored["error"])
                        ),
                        checked_at=str(stored["checked_at"]),
                    )
                    closure = require_verified_collection_closure(
                        receipt,
                        expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                        expected_authority_instance_digest=(
                            PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                        ),
                        expected_policy_version=coverage_contract_for(
                            dataset_id
                        ).policy_version,
                    )
                    product_rows = [
                        row
                        for row in product_materializations
                        if row.get("source") == closure.source
                        and row.get("dataset") == closure.dataset
                        and row.get("segment_id") == closure.segment_id
                        and row.get("run_id") == closure.run_id
                    ]
                    if len(product_rows) != 1:
                        continue
                    product = dict(product_rows[0])
                    run_rows = [
                        row
                        for row in ingestion_runs
                        if row.get("id") == closure.run_id
                    ]
                    raw_manifests = [
                        row
                        for row in raw_retention_manifests
                        if row.get("dataset") == closure.dataset
                        and row.get("run_id") == closure.run_id
                    ]
                    # A receipt attests the complete governed source segment,
                    # not the smaller set of natural keys selected by this
                    # plan's PIT universe.  Reconstruct and verify that full
                    # artifact here; universe filtering belongs only to the
                    # dependency-key selection above.
                    observed_count, observed_product_digest, observed_bytes = (
                        product_artifact_digest_ordered(
                            iter_catalog_product_rows(
                                dataset_id,
                                closure.segment_start[:10],
                                closure.segment_end[:10],
                            )
                        )
                    )
                    if (
                        closure.status != "SUCCESS"
                        or not closure.pagination_exhausted
                        or not closure.discovery_exhausted
                        or observed_count != closure.structured_row_count
                        or observed_product_digest != closure.structured_digest
                        or product["artifact_digest"] != observed_product_digest
                        or product_artifact_body_digest(product["artifact_body"])
                        != observed_product_digest
                        or len(product["artifact_body"].encode("utf-8"))
                        != product["byte_count"]
                        or int(product["byte_count"]) != observed_bytes
                        or product["row_count"] != closure.structured_row_count
                        or product["raw_manifest_digest"]
                        != closure.raw_manifest_digest
                        or product["raw_page_count"] != closure.raw_page_count
                        or product["raw_row_count"] != closure.raw_row_count
                        or len(run_rows) != 1
                        or run_rows[0]["id"] != closure.run_id
                        or run_rows[0]["source"] != closure.source
                        or run_rows[0]["runtime"] != "receipt-evidence-authority"
                        or run_rows[0]["status"] != "SUCCESS"
                        or run_rows[0]["authority_operation_id"]
                        != product["operation_id"]
                        or len(raw_manifests) != 1
                        or raw_manifests[0]["manifest_key"]
                        != product["raw_manifest_key"]
                        or raw_manifests[0]["page_count"]
                        != closure.raw_page_count
                        or raw_manifests[0]["row_count"]
                        != closure.raw_row_count
                        or raw_manifests[0]["raw_bytes"] != product["raw_bytes"]
                        or raw_manifests[0]["data_digest"]
                        != closure.raw_manifest_digest
                    ):
                        continue
                except Exception:
                    continue
                verified_segments[dataset_id].append(
                    (
                        closure.segment_start[:10],
                        closure.segment_end[:10],
                        closure.receipt_digest,
                        closure.structured_digest,
                    )
                )

            entries: list[dict[str, Any]] = []
            for dataset_id in required_datasets:
                selected = selected_keys[dataset_id]
                if not selected:
                    raise MassResearchDisabledError(
                        f"PIT dependency scope selected no keys for {dataset_id}"
                    )
                used_receipts: set[str] = set()
                used_products: set[str] = set()
                for natural_key in selected:
                    event_date = selected_event_dates[dataset_id][natural_key]
                    matches = [
                        (receipt_digest, product_digest)
                        for segment_start, segment_end, receipt_digest, product_digest
                        in verified_segments[dataset_id]
                        if segment_start <= event_date <= segment_end
                    ]
                    if not matches:
                        raise MassResearchDisabledError(
                            "PIT dependency scope natural key is not bound to a "
                            f"current signed receipt: {dataset_id}/{natural_key}"
                        )
                    receipt_digest, product_digest = sorted(matches)[-1]
                    used_receipts.add(receipt_digest)
                    used_products.add(product_digest)
                entries.append(
                    {
                        "dataset_id": dataset_id,
                        "natural_key_count": len(selected),
                        "natural_key_digest": canonical_digest(sorted(selected)),
                        "receipt_digests": sorted(used_receipts),
                        "receipt_set_digest": canonical_digest(
                            sorted(used_receipts)
                        ),
                        "product_artifact_digests": sorted(used_products),
                        "product_artifact_set_digest": canonical_digest(
                            sorted(used_products)
                        ),
                    }
                )
            final_registered = _authenticated_applied_mirror_connection_identity(
                conn
            )
            if (
                final_registered is not registered
                or final_registered.digest != physical_digest
            ):
                raise PitError(
                    "physical DB digest does not match the prepared snapshot"
                )
            body = {
                "format": "pit-dependency-scope-proof/v1",
                "status": "PASS",
                "applied_mirror_identity": closed_identity,
                "environment": closed_identity["environment"],
                "resource_identity": closed_identity["resource_identity"],
                "audit_digest": closed_identity["audit_digest"],
                "issuer_key_id": closed_identity["issuer_key_id"],
                "export_digest": closed_identity["export_digest"],
                "source_change_seq": closed_identity["source_change_seq"],
                "applied_change_seq": closed_identity["applied_change_seq"],
                "export_cursor": closed_identity["source_change_seq"],
                "applied_cursor": closed_identity["applied_change_seq"],
                "source_content_digest": closed_identity["source_content_digest"],
                "local_content_digest": closed_identity["local_content_digest"],
                "source_schema_digest": closed_identity["source_schema_digest"],
                "schema_digest": closed_identity["schema_digest"],
                "table_counts": closed_identity["table_counts"],
                "exported_at": exported_at,
                "observed_through": exported_at,
                "physical_db_digest": physical_digest,
                "physical_db_identity": {
                    "digest": registered.digest,
                    "size": registered.size,
                },
                "profile_digest": binding.profile_digest,
                "plan_set_digest": binding.plan_set_digest,
                "dependency_closure_digest": binding.closure_set_digest,
                "universe_rule_digest": EXACT_FOUR_UNIVERSE_RULE_DIGEST,
                "resolved_universe_digest": (
                    resolved_universe.resolved_membership_digest
                ),
                "universe_daily_summary": [
                    {
                        "decision_date": day,
                        "member_count": len(codes),
                        "membership_digest": canonical_digest(list(codes)),
                    }
                    for day, codes in resolved_universe.decision_memberships
                ],
                "period_start": period_start,
                "period_end": period_end,
                "lookback_trading_days": max_lookback,
                "entries": entries,
                "product_materialization_digest": canonical_digest(
                    [
                        {
                            "dataset_id": entry["dataset_id"],
                            "product_artifact_digests": entry[
                                "product_artifact_digests"
                            ],
                        }
                        for entry in entries
                    ]
                ),
            }
            return VerifiedPublicationEvidence({**body, "proof_digest": canonical_digest(body)})
    except PitError as exc:
        raise MassResearchDisabledError(str(exc)) from exc
    except sqlite3.Error as exc:
        raise MassResearchDisabledError(
            "PIT dependency scope query failed closed"
        ) from exc


__all__ = [
    "ReadyPublicationService",
    "VerifiedPublicationEvidence",
    "canonical_digest",
    "verify_controlled_publication_evidence",
]
