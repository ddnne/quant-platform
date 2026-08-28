"""Immutable exact-four universe rule and snapshot-bound resolution.

``tse_prime_with_fins`` is a rule, never a caller supplied list of codes.  For
each controlled-pilot decision date the resolver intersects the latest
PIT-visible Prime-market master snapshot with issuers that already have a
PIT-visible ``fins_summary`` disclosure.  The complete date-to-membership map
is content addressed and later re-derived from the immutable READY artifact.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from core.execution import close_as_of
from data_contracts.identity import natural_key as contract_natural_key
from selection.budget_ledger import MassResearchDisabledError


EXACT_FOUR_UNIVERSE_RULE_ID = "tse_prime_with_fins"
EXACT_FOUR_UNIVERSE_RULE_VERSION = "tse-prime-with-fins/v1"
TSE_PRIME_MARKET_CODE = "0111"
UNIVERSE_BREADTH_EVIDENCE_FORMAT = (
    "observed-tse-prime-with-fins-breadth/v1"
)
_VersionIdentity = tuple[str, str, str]


def _canonical_digest(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


EXACT_FOUR_UNIVERSE_RULE_DOCUMENT: Mapping[str, Any] = MappingProxyType(
    {
        "rule_id": EXACT_FOUR_UNIVERSE_RULE_ID,
        "rule_version": EXACT_FOUR_UNIVERSE_RULE_VERSION,
        "decision_clock": "tse_session_close_jst",
        "master_rule": {
            "dataset": "equities_master",
            "latest_snapshot_visible_at_decision": True,
            "market_code": TSE_PRIME_MARKET_CODE,
        },
        "financials_rule": {
            "dataset": "fins_summary",
            "at_least_one_disclosure_visible_at_decision": True,
        },
        "runtime_rule": "resolved_membership_intersect_daily_pit_master",
    }
)
EXACT_FOUR_UNIVERSE_RULE_DIGEST = _canonical_digest(
    dict(EXACT_FOUR_UNIVERSE_RULE_DOCUMENT)
)


@dataclass(frozen=True, slots=True)
class ResolvedUniverseMembership:
    """Content-addressed daily membership derived from one immutable DB."""

    period_start: str
    period_end: str
    decision_memberships: tuple[tuple[str, tuple[str, ...]], ...]
    rule_id: str = EXACT_FOUR_UNIVERSE_RULE_ID
    rule_version: str = EXACT_FOUR_UNIVERSE_RULE_VERSION
    rule_digest: str = EXACT_FOUR_UNIVERSE_RULE_DIGEST
    resolved_membership_digest: str = ""

    def __post_init__(self) -> None:
        if (
            self.rule_id != EXACT_FOUR_UNIVERSE_RULE_ID
            or self.rule_version != EXACT_FOUR_UNIVERSE_RULE_VERSION
            or self.rule_digest != EXACT_FOUR_UNIVERSE_RULE_DIGEST
        ):
            raise MassResearchDisabledError(
                "controlled universe rule identity is not canonical"
            )
        if not self.period_start or self.period_start > self.period_end:
            raise MassResearchDisabledError("controlled universe period is invalid")
        normalized: list[tuple[str, tuple[str, ...]]] = []
        seen: set[str] = set()
        for decision_date, raw_codes in self.decision_memberships:
            day = str(decision_date)
            codes = tuple(sorted({str(code).strip() for code in raw_codes}))
            if (
                not day
                or day in seen
                or not codes
                or any(not code for code in codes)
            ):
                raise MassResearchDisabledError(
                    "resolved universe requires unique non-empty daily memberships"
                )
            if day < self.period_start or day > self.period_end:
                raise MassResearchDisabledError(
                    "resolved universe decision date is outside its period"
                )
            seen.add(day)
            normalized.append((day, codes))
        normalized.sort(key=lambda item: item[0])
        if not normalized:
            raise MassResearchDisabledError("resolved universe is empty")
        object.__setattr__(self, "decision_memberships", tuple(normalized))
        expected = _canonical_digest(self.to_canonical_dict())
        declared = str(self.resolved_membership_digest or "")
        if declared and declared != expected:
            raise MassResearchDisabledError(
                "resolved universe membership digest mismatch"
            )
        object.__setattr__(self, "resolved_membership_digest", expected)

    @property
    def membership_by_date(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType(dict(self.decision_memberships))

    @property
    def membership_proof(self) -> str:
        return "controlled-resolved-universe:" + self.resolved_membership_digest

    def codes_for(self, decision_date: str) -> tuple[str, ...]:
        try:
            return self.membership_by_date[str(decision_date)]
        except KeyError as exc:
            raise MassResearchDisabledError(
                f"resolved universe has no decision membership for {decision_date}"
            ) from exc

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "rule_digest": self.rule_digest,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "decision_memberships": [
                {"decision_date": day, "codes": list(codes)}
                for day, codes in self.decision_memberships
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.to_canonical_dict(),
            "resolved_membership_digest": self.resolved_membership_digest,
        }


def _parse_datetime(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MassResearchDisabledError(f"{label} is not an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise MassResearchDisabledError(f"{label} must include a timezone")
    return parsed


def _decode_payload(row: Mapping[str, Any], dataset_id: str) -> dict[str, Any]:
    payload: Any = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MassResearchDisabledError(
                f"{dataset_id} payload is not canonical JSON"
            ) from exc
    if not isinstance(payload, Mapping):
        raise MassResearchDisabledError(f"{dataset_id} payload is missing")
    document = {str(key): value for key, value in payload.items()}
    expected_key = contract_natural_key(document, dataset_id)
    if expected_key.startswith("hash:sha256:") or row.get("natural_key") != expected_key:
        raise MassResearchDisabledError(
            f"{dataset_id} natural key is missing or noncanonical"
        )
    return document


def _pick(payload: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _calendar_dates(start: str, end: str) -> tuple[str, ...]:
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    values: list[str] = []
    while cursor <= stop:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


def _load_governed_rows(
    db_path: str | Path, dataset_ids: Sequence[str]
) -> dict[str, tuple[dict[str, Any], ...]]:
    source = Path(db_path).resolve()
    if not source.is_file():
        raise MassResearchDisabledError(
            f"controlled universe snapshot is missing: {source}"
        )
    uri = "file:" + quote(str(source)) + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        required = {
            "source",
            "dataset",
            "natural_key",
            "event_time",
            "available_at",
            "ingested_at",
            "payload",
            "raw_payload",
        }
        placeholders = ",".join("?" for _ in dataset_ids)
        rows: list[sqlite3.Row] = []
        for table in ("jquants_records", "jquants_records_revisions"):
            columns = {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({table})")
            }
            if not columns:
                if table == "jquants_records":
                    raise MassResearchDisabledError(
                        "controlled universe requires the canonical "
                        "jquants_records schema"
                    )
                continue
            if not required <= columns:
                raise MassResearchDisabledError(
                    f"controlled universe requires canonical {table} schema"
                )
            rows.extend(
                conn.execute(
                    "SELECT source,dataset,natural_key,event_time,available_at,"
                    f"ingested_at,payload,raw_payload FROM {table} "
                    f"WHERE source='jquants' AND dataset IN ({placeholders}) "
                    "ORDER BY dataset,event_time,natural_key,available_at,"
                    "ingested_at",
                    tuple(dataset_ids),
                ).fetchall()
            )
    except sqlite3.Error as exc:
        raise MassResearchDisabledError(
            "controlled universe snapshot query failed closed"
        ) from exc
    finally:
        if "conn" in locals():
            conn.close()
    grouped: dict[str, list[dict[str, Any]]] = {
        str(dataset_id): [] for dataset_id in dataset_ids
    }
    for raw in rows:
        row = dict(raw)
        dataset_id = str(row["dataset"])
        row["_payload"] = _decode_payload(row, dataset_id)
        row["_available"] = _parse_datetime(
            row.get("available_at"), label=f"{dataset_id}.available_at"
        )
        row["_event"] = _parse_datetime(
            row.get("event_time"), label=f"{dataset_id}.event_time"
        )
        row["_ingested"] = _parse_datetime(
            row.get("ingested_at"), label=f"{dataset_id}.ingested_at"
        )
        grouped[dataset_id].append(row)
    return {key: tuple(value) for key, value in grouped.items()}


def resolve_tse_prime_with_fins(
    db_path: str | Path,
    *,
    period_start: str,
    period_end: str,
) -> ResolvedUniverseMembership:
    """Resolve the governed exact-four universe from an immutable PIT DB."""
    membership, _evidence = resolve_tse_prime_with_fins_evidence(
        db_path,
        period_start=period_start,
        period_end=period_end,
    )
    return membership


def resolve_tse_prime_with_fins_evidence(
    db_path: str | Path,
    *,
    period_start: str,
    period_end: str,
) -> tuple[ResolvedUniverseMembership, dict[str, Any]]:
    """Resolve membership and report observed, non-authoritative breadth.

    The evidence only describes rows visible in the supplied immutable DB.  It
    deliberately makes no upstream-completeness claim and applies no pass
    threshold.
    """
    rows = _load_governed_rows(
        db_path, ("markets_calendar", "equities_master", "fins_summary")
    )
    activation_events: list[
        tuple[datetime, str, str, datetime, datetime, int, dict[str, Any]]
    ] = []
    calendar_candidate_days: set[str] = set()
    insertion_order = 0
    for dataset_rows in rows.values():
        for row in dataset_rows:
            dataset_id = str(row["dataset"])
            if dataset_id == "markets_calendar":
                calendar_candidate_days.add(str(row["event_time"])[:10])
            activation_events.append(
                (
                    max(row["_event"], row["_available"]),
                    dataset_id,
                    str(row["natural_key"]),
                    row["_available"],
                    row["_ingested"],
                    insertion_order,
                    row,
                )
            )
            insertion_order += 1
    activation_events.sort(key=lambda item: item[:-1])

    requested_days = _calendar_dates(period_start, period_end)
    for day in requested_days:
        if day not in calendar_candidate_days:
            raise MassResearchDisabledError(
                f"markets_calendar is missing required date {day}"
            )

    latest_versions: dict[_VersionIdentity, dict[str, Any]] = {}
    calendar_by_day: dict[
        str, dict[_VersionIdentity, dict[str, Any]]
    ] = {}
    master_by_snapshot: dict[
        str, dict[_VersionIdentity, dict[str, Any]]
    ] = {}
    master_day_heap: list[tuple[int, str]] = []
    fins_code_counts: dict[str, int] = {}

    def remove_active(
        identity: _VersionIdentity, row: dict[str, Any]
    ) -> None:
        dataset_id = str(row["dataset"])
        if dataset_id == "markets_calendar":
            day = str(row["event_time"])[:10]
            bucket = calendar_by_day.get(day)
            if bucket is not None:
                bucket.pop(identity, None)
                if not bucket:
                    del calendar_by_day[day]
        elif dataset_id == "equities_master":
            day = str(row["event_time"])[:10]
            bucket = master_by_snapshot.get(day)
            if bucket is not None:
                bucket.pop(identity, None)
                if not bucket:
                    del master_by_snapshot[day]
        elif dataset_id == "fins_summary":
            code = _pick(row["_payload"], "Code", "code")
            if code:
                remaining = fins_code_counts.get(code, 0) - 1
                if remaining > 0:
                    fins_code_counts[code] = remaining
                else:
                    fins_code_counts.pop(code, None)

    def add_active(identity: _VersionIdentity, row: dict[str, Any]) -> None:
        dataset_id = str(row["dataset"])
        if dataset_id == "markets_calendar":
            day = str(row["event_time"])[:10]
            calendar_by_day.setdefault(day, {})[identity] = row
        elif dataset_id == "equities_master":
            day = str(row["event_time"])[:10]
            if day not in master_by_snapshot:
                master_by_snapshot[day] = {}
                heapq.heappush(
                    master_day_heap,
                    (-date.fromisoformat(day).toordinal(), day),
                )
            master_by_snapshot[day][identity] = row
        elif dataset_id == "fins_summary":
            code = _pick(row["_payload"], "Code", "code")
            if code:
                fins_code_counts[code] = fins_code_counts.get(code, 0) + 1

    def activate(row: dict[str, Any]) -> None:
        identity: _VersionIdentity = (
            str(row["source"]),
            str(row["dataset"]),
            str(row["natural_key"]),
        )
        previous = latest_versions.get(identity)
        version = (row["_available"], row["_ingested"])
        if previous is not None and version <= (
            previous["_available"],
            previous["_ingested"],
        ):
            return
        if previous is not None:
            remove_active(identity, previous)
        latest_versions[identity] = row
        add_active(identity, row)

    memberships: list[tuple[str, tuple[str, ...]]] = []
    daily_observations: list[dict[str, Any]] = []
    event_index = 0
    saw_trading_day = False
    for day in requested_days:
        as_of = _parse_datetime(close_as_of(day), label="decision_as_of")
        while (
            event_index < len(activation_events)
            and activation_events[event_index][0] <= as_of
        ):
            activate(activation_events[event_index][-1])
            event_index += 1

        visible_calendar = calendar_by_day.get(day)
        if not visible_calendar:
            raise MassResearchDisabledError(
                f"markets_calendar row for {day} is not PIT-visible"
            )
        if len(visible_calendar) != 1:
            raise MassResearchDisabledError(
                f"markets_calendar has duplicate natural keys for {day}"
            )
        calendar_row = next(iter(visible_calendar.values()))
        holiday = _pick(
            calendar_row["_payload"],
            "HolidayDivision",
            "HolDiv",
            "holiday_division",
        )
        if holiday != "1":
            continue
        saw_trading_day = True

        while master_day_heap and master_day_heap[0][1] not in master_by_snapshot:
            heapq.heappop(master_day_heap)
        if not master_day_heap:
            raise MassResearchDisabledError(
                f"equities_master has no PIT-visible snapshot for {day}"
            )
        latest_snapshot = master_day_heap[0][1]
        prime_codes: set[str] = set()
        seen_master: set[str] = set()
        for row in master_by_snapshot[latest_snapshot].values():
            payload = row["_payload"]
            code = _pick(payload, "Code", "code")
            if not code or code in seen_master:
                raise MassResearchDisabledError(
                    f"equities_master snapshot {latest_snapshot} has invalid code identity"
                )
            seen_master.add(code)
            market_code = _pick(payload, "MarketCode", "MktCode", "Mkt")
            if market_code == TSE_PRIME_MARKET_CODE:
                prime_codes.add(code)

        resolved = tuple(
            sorted(code for code in prime_codes if fins_code_counts.get(code, 0) > 0)
        )
        if not resolved:
            raise MassResearchDisabledError(
                f"tse_prime_with_fins resolves empty at {day}"
            )
        memberships.append((day, resolved))
        daily_observations.append(
            {
                "decision_date": day,
                "prime_master_count": len(prime_codes),
                "resolved_fins_intersection_count": len(resolved),
                "resolved_fins_intersection_ratio": (
                    len(resolved) / len(prime_codes)
                ),
            }
        )

    if not saw_trading_day:
        raise MassResearchDisabledError("controlled universe has no trading dates")

    membership = ResolvedUniverseMembership(
        period_start=period_start,
        period_end=period_end,
        decision_memberships=tuple(memberships),
    )
    total_prime = sum(
        int(item["prime_master_count"]) for item in daily_observations
    )
    total_resolved = sum(
        int(item["resolved_fins_intersection_count"])
        for item in daily_observations
    )
    minimum_daily_ratio = min(
        float(item["resolved_fins_intersection_ratio"])
        for item in daily_observations
    )
    worst_days = [
        str(item["decision_date"])
        for item in daily_observations
        if float(item["resolved_fins_intersection_ratio"])
        == minimum_daily_ratio
    ]
    evidence = {
        "format": UNIVERSE_BREADTH_EVIDENCE_FORMAT,
        "evidence_kind": "OBSERVED",
        "rule_id": EXACT_FOUR_UNIVERSE_RULE_ID,
        "rule_version": EXACT_FOUR_UNIVERSE_RULE_VERSION,
        "period_start": period_start,
        "period_end": period_end,
        "daily_observations": daily_observations,
        "total_prime_master_observations": total_prime,
        "total_resolved_fins_intersection_observations": total_resolved,
        "overall_ratio": total_resolved / total_prime,
        "minimum_daily_ratio": minimum_daily_ratio,
        "worst_days": worst_days,
        "source_complete_claim": False,
    }
    return membership, evidence


__all__ = [
    "EXACT_FOUR_UNIVERSE_RULE_DIGEST",
    "EXACT_FOUR_UNIVERSE_RULE_DOCUMENT",
    "EXACT_FOUR_UNIVERSE_RULE_ID",
    "EXACT_FOUR_UNIVERSE_RULE_VERSION",
    "ResolvedUniverseMembership",
    "TSE_PRIME_MARKET_CODE",
    "UNIVERSE_BREADTH_EVIDENCE_FORMAT",
    "resolve_tse_prime_with_fins",
    "resolve_tse_prime_with_fins_evidence",
]
