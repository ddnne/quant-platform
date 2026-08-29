"""Closed, PIT-resolved TOPIX universes for personal DRAFT research.

This module is intentionally separate from ``research.universe_contract``.
The latter is the immutable controlled exact-four Prime authority; these
selectors are unsigned personal exploration inputs and can never mint READY,
Pilot, Mass, promotion, or trading authority.
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
from data_contracts.personal_universe import (
    TOPIX_CORE30,
    TOPIX_LARGE70,
    TOPIX_MID400,
    TOPIX_SCALE_CATEGORIES,
    TOPIX_SMALL_1,
    TOPIX_SMALL_2,
    canonical_topix_scale_category,
)


PERSONAL_UNIVERSE_RULE_VERSION = "personal-topix-scale-with-fins/v1"
PERSONAL_UNIVERSE_BREADTH_FORMAT = "personal-topix-with-fins-breadth/v1"
DEFAULT_PERSONAL_UNIVERSE_ID = "topix_all"
_VersionIdentity = tuple[str, str, str]


class PersonalUniverseError(ValueError):
    """The selector, snapshot, or PIT membership is invalid for DRAFT use."""


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PersonalUniverseSelector:
    selector_id: str
    scale_categories: tuple[str, ...]

    def __post_init__(self) -> None:
        categories = tuple(dict.fromkeys(self.scale_categories))
        if (
            not self.selector_id
            or not categories
            or any(category not in TOPIX_SCALE_CATEGORIES for category in categories)
        ):
            raise PersonalUniverseError("personal universe selector is invalid")
        object.__setattr__(self, "scale_categories", categories)

    @property
    def rule_id(self) -> str:
        return f"{self.selector_id}_with_fins"

    @property
    def rule_version(self) -> str:
        return PERSONAL_UNIVERSE_RULE_VERSION

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "decision_clock": "tse_session_close_jst",
            "master_rule": {
                "dataset": "equities_master",
                "latest_snapshot_visible_at_decision": True,
                "selector_id": self.selector_id,
                "scale_categories": list(self.scale_categories),
            },
            "financials_rule": {
                "dataset": "fins_summary",
                "at_least_one_disclosure_visible_at_decision": True,
            },
            "research_state": "PERSONAL_DRAFT",
            "controlled_live_eligibility": "FORBIDDEN",
        }

    @property
    def rule_digest(self) -> str:
        return _canonical_digest(self.to_canonical_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_dict(), "rule_digest": self.rule_digest}


_SELECTORS: Mapping[str, PersonalUniverseSelector] = MappingProxyType(
    {
        "topix_all": PersonalUniverseSelector(
            "topix_all", TOPIX_SCALE_CATEGORIES
        ),
        "topix_core30": PersonalUniverseSelector(
            "topix_core30", (TOPIX_CORE30,)
        ),
        "topix_large70": PersonalUniverseSelector(
            "topix_large70", (TOPIX_LARGE70,)
        ),
        "topix_mid400": PersonalUniverseSelector(
            "topix_mid400", (TOPIX_MID400,)
        ),
        "topix_small1": PersonalUniverseSelector(
            "topix_small1", (TOPIX_SMALL_1,)
        ),
        "topix_small2": PersonalUniverseSelector(
            "topix_small2", (TOPIX_SMALL_2,)
        ),
        "topix_small": PersonalUniverseSelector(
            "topix_small", (TOPIX_SMALL_1, TOPIX_SMALL_2)
        ),
        "topix100": PersonalUniverseSelector(
            "topix100", (TOPIX_CORE30, TOPIX_LARGE70)
        ),
        "topix500": PersonalUniverseSelector(
            "topix500", (TOPIX_CORE30, TOPIX_LARGE70, TOPIX_MID400)
        ),
    }
)
PERSONAL_UNIVERSE_IDS: tuple[str, ...] = tuple(_SELECTORS)


def personal_universe_selector(selector_id: str) -> PersonalUniverseSelector:
    try:
        return _SELECTORS[str(selector_id)]
    except KeyError as exc:
        raise PersonalUniverseError(
            f"universe_id must be one of {list(PERSONAL_UNIVERSE_IDS)}"
        ) from exc


@dataclass(frozen=True, slots=True)
class PersonalResolvedUniverseMembership:
    """Content-addressed daily membership with core-compatible shape."""

    period_start: str
    period_end: str
    decision_memberships: tuple[tuple[str, tuple[str, ...]], ...]
    rule_id: str
    rule_version: str
    rule_digest: str
    resolved_membership_digest: str = ""

    def __post_init__(self) -> None:
        if (
            not self.rule_id
            or self.rule_version != PERSONAL_UNIVERSE_RULE_VERSION
            or not self.rule_digest.startswith("sha256:")
            or not self.period_start
            or self.period_start > self.period_end
        ):
            raise PersonalUniverseError(
                "personal resolved universe identity is invalid"
            )
        normalized: list[tuple[str, tuple[str, ...]]] = []
        seen: set[str] = set()
        for raw_day, raw_codes in self.decision_memberships:
            day = str(raw_day)
            codes = tuple(sorted({str(code).strip() for code in raw_codes}))
            if (
                day in seen
                or day < self.period_start
                or day > self.period_end
                or not codes
                or any(not code for code in codes)
            ):
                raise PersonalUniverseError(
                    "personal resolved universe has invalid daily membership"
                )
            seen.add(day)
            normalized.append((day, codes))
        normalized.sort(key=lambda item: item[0])
        if not normalized:
            raise PersonalUniverseError("personal resolved universe is empty")
        object.__setattr__(self, "decision_memberships", tuple(normalized))
        expected = _canonical_digest(self.to_canonical_dict())
        declared = str(self.resolved_membership_digest or "")
        if declared and declared != expected:
            raise PersonalUniverseError(
                "personal resolved universe membership digest mismatch"
            )
        object.__setattr__(self, "resolved_membership_digest", expected)

    @property
    def membership_by_date(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType(dict(self.decision_memberships))

    @property
    def membership_proof(self) -> str:
        # ``core.universe.ResolvedDailyUniverse`` currently uses this envelope
        # for every governed daily map.  The embedded rule explicitly remains
        # PERSONAL_DRAFT/FORBIDDEN and conveys no controlled authority.
        return "controlled-resolved-universe:" + self.resolved_membership_digest

    def codes_for(self, decision_date: str) -> tuple[str, ...]:
        try:
            return self.membership_by_date[str(decision_date)]
        except KeyError as exc:
            raise PersonalUniverseError(
                f"personal universe has no membership for {decision_date}"
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
            "research_state": "PERSONAL_DRAFT",
            "controlled_live_eligibility": "FORBIDDEN",
        }


def _parse_datetime(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PersonalUniverseError(f"{label} is not an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise PersonalUniverseError(f"{label} must include a timezone")
    return parsed


def _decode_payload(row: Mapping[str, Any], dataset_id: str) -> dict[str, Any]:
    payload: Any = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PersonalUniverseError(
                f"{dataset_id} payload is not canonical JSON"
            ) from exc
    if not isinstance(payload, Mapping):
        raise PersonalUniverseError(f"{dataset_id} payload is missing")
    document = {str(key): value for key, value in payload.items()}
    expected_key = contract_natural_key(document, dataset_id)
    if (
        expected_key.startswith("hash:sha256:")
        or row.get("natural_key") != expected_key
    ):
        raise PersonalUniverseError(
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
    try:
        cursor = date.fromisoformat(start)
        stop = date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise PersonalUniverseError(
            "personal universe period must use ISO dates"
        ) from exc
    if cursor > stop:
        raise PersonalUniverseError("personal universe period is reversed")
    values: list[str] = []
    while cursor <= stop:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


def _load_rows(
    db_path: str | Path, dataset_ids: Sequence[str]
) -> dict[str, tuple[dict[str, Any], ...]]:
    source = Path(db_path).resolve()
    if not source.is_file():
        raise PersonalUniverseError(f"personal universe snapshot is missing: {source}")
    uri = "file:" + quote(str(source)) + "?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
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
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if not columns:
                if table == "jquants_records":
                    raise PersonalUniverseError(
                        "personal universe requires canonical jquants_records"
                    )
                continue
            if not required <= columns:
                raise PersonalUniverseError(
                    f"personal universe requires canonical {table} schema"
                )
            rows.extend(
                connection.execute(
                    "SELECT source,dataset,natural_key,event_time,available_at,"
                    f"ingested_at,payload,raw_payload FROM {table} "
                    f"WHERE source='jquants' AND dataset IN ({placeholders}) "
                    "ORDER BY dataset,event_time,natural_key,available_at,ingested_at",
                    tuple(dataset_ids),
                ).fetchall()
            )
    except sqlite3.Error as exc:
        raise PersonalUniverseError("personal universe snapshot query failed") from exc
    finally:
        if connection is not None:
            connection.close()
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


def resolve_personal_universe_with_evidence(
    db_path: str | Path,
    *,
    period_start: str,
    period_end: str,
    universe_id: str = DEFAULT_PERSONAL_UNIVERSE_ID,
) -> tuple[PersonalResolvedUniverseMembership, dict[str, Any]]:
    """Resolve one closed selector from the latest PIT-visible dated master."""

    selector = personal_universe_selector(universe_id)
    rows = _load_rows(
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
            raise PersonalUniverseError(
                f"markets_calendar is missing required date {day}"
            )

    latest_versions: dict[_VersionIdentity, dict[str, Any]] = {}
    calendar_by_day: dict[str, dict[_VersionIdentity, dict[str, Any]]] = {}
    master_by_snapshot: dict[str, dict[_VersionIdentity, dict[str, Any]]] = {}
    master_day_heap: list[tuple[int, str]] = []
    fins_code_counts: dict[str, int] = {}

    def remove_active(identity: _VersionIdentity, row: dict[str, Any]) -> None:
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
                    master_day_heap, (-date.fromisoformat(day).toordinal(), day)
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

    allowed = frozenset(selector.scale_categories)
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
            raise PersonalUniverseError(
                f"markets_calendar row for {day} is not PIT-visible"
            )
        if len(visible_calendar) != 1:
            raise PersonalUniverseError(
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
            raise PersonalUniverseError(
                f"equities_master has no PIT-visible snapshot for {day}"
            )
        latest_snapshot = master_day_heap[0][1]
        selected_codes: set[str] = set()
        seen_master: set[str] = set()
        for row in master_by_snapshot[latest_snapshot].values():
            payload = row["_payload"]
            code = _pick(payload, "Code", "code")
            if not code or code in seen_master:
                raise PersonalUniverseError(
                    "equities_master snapshot "
                    f"{latest_snapshot} has invalid code identity"
                )
            seen_master.add(code)
            category = canonical_topix_scale_category(
                _pick(
                    payload,
                    "CanonicalScaleCategory",
                    "ScaleCategory",
                    "ScaleCat",
                    "scale_category",
                )
            )
            if category in allowed:
                selected_codes.add(code)

        if not selected_codes:
            raise PersonalUniverseError(
                f"{selector.selector_id} resolves no master members at {day}"
            )
        resolved = tuple(
            sorted(
                code for code in selected_codes if fins_code_counts.get(code, 0) > 0
            )
        )
        if not resolved:
            raise PersonalUniverseError(
                f"{selector.rule_id} resolves empty at {day}"
            )
        memberships.append((day, resolved))
        daily_observations.append(
            {
                "decision_date": day,
                "selector_master_count": len(selected_codes),
                "resolved_fins_intersection_count": len(resolved),
                "resolved_fins_intersection_ratio": len(resolved)
                / len(selected_codes),
            }
        )

    if not saw_trading_day:
        raise PersonalUniverseError("personal universe has no trading dates")

    membership = PersonalResolvedUniverseMembership(
        period_start=period_start,
        period_end=period_end,
        decision_memberships=tuple(memberships),
        rule_id=selector.rule_id,
        rule_version=selector.rule_version,
        rule_digest=selector.rule_digest,
    )
    total_master = sum(
        int(item["selector_master_count"]) for item in daily_observations
    )
    total_resolved = sum(
        int(item["resolved_fins_intersection_count"])
        for item in daily_observations
    )
    minimum_daily_ratio = min(
        float(item["resolved_fins_intersection_ratio"])
        for item in daily_observations
    )
    evidence = {
        "format": PERSONAL_UNIVERSE_BREADTH_FORMAT,
        "evidence_kind": "OBSERVED",
        "selector": selector.to_dict(),
        "period_start": period_start,
        "period_end": period_end,
        "daily_observations": daily_observations,
        "total_selector_master_observations": total_master,
        "total_resolved_fins_intersection_observations": total_resolved,
        "overall_ratio": total_resolved / total_master,
        "minimum_daily_ratio": minimum_daily_ratio,
        "worst_days": [
            str(item["decision_date"])
            for item in daily_observations
            if float(item["resolved_fins_intersection_ratio"])
            == minimum_daily_ratio
        ],
        "source_complete_claim": False,
        "research_state": "PERSONAL_DRAFT",
        "controlled_live_eligibility": "FORBIDDEN",
    }
    return membership, evidence


def resolve_personal_universe(
    db_path: str | Path,
    *,
    period_start: str,
    period_end: str,
    universe_id: str = DEFAULT_PERSONAL_UNIVERSE_ID,
) -> PersonalResolvedUniverseMembership:
    membership, _evidence = resolve_personal_universe_with_evidence(
        db_path,
        period_start=period_start,
        period_end=period_end,
        universe_id=universe_id,
    )
    return membership


__all__ = [
    "DEFAULT_PERSONAL_UNIVERSE_ID",
    "PERSONAL_UNIVERSE_BREADTH_FORMAT",
    "PERSONAL_UNIVERSE_IDS",
    "PERSONAL_UNIVERSE_RULE_VERSION",
    "PersonalResolvedUniverseMembership",
    "PersonalUniverseError",
    "PersonalUniverseSelector",
    "personal_universe_selector",
    "resolve_personal_universe",
    "resolve_personal_universe_with_evidence",
]
