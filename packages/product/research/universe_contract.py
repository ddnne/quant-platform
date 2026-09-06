"""Immutable exact-four universe rule and snapshot-bound resolution.

``tse_prime_with_fins`` is a rule, never a caller supplied list of codes.  For
each controlled-pilot decision date the resolver intersects the latest
PIT-visible Prime-market master snapshot with issuers that already have a
PIT-visible ``fins_summary`` disclosure.  The complete date-to-membership map
is content addressed and later re-derived from the immutable READY artifact.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from core.execution import morning_close_as_of
from data_contracts.membership_runs import (
    MembershipRun,
    RunLengthMembershipMap,
    coalesce_daily_memberships,
    codes_for_runs,
    iter_run_days,
    stream_membership_digest,
    validate_membership_runs,
)
from pit.universe_pit import UniverseDaySlice
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
        "decision_clock": "tse_morning_close_jst",
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
    membership_runs: tuple[MembershipRun, ...] = ()

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
        interned: dict[tuple[str, ...], tuple[str, ...]] = {}
        normalized: list[tuple[str, tuple[str, ...]]] = []
        if self.decision_memberships:
            seen: set[str] = set()
            for decision_date, raw_codes in self.decision_memberships:
                day = str(decision_date)
                codes = tuple(sorted({str(code).strip() for code in raw_codes}))
                codes = interned.setdefault(codes, codes)
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
        try:
            if self.membership_runs:
                runs = validate_membership_runs(
                    self.membership_runs,
                    period_start=self.period_start,
                    period_end=self.period_end,
                )
                if normalized:
                    from_daily = validate_membership_runs(
                        coalesce_daily_memberships(normalized),
                        period_start=self.period_start,
                        period_end=self.period_end,
                    )
                    if from_daily != runs:
                        raise MassResearchDisabledError(
                            "resolved universe membership runs disagree with daily memberships"
                        )
            else:
                if not normalized:
                    raise MassResearchDisabledError("resolved universe is empty")
                runs = validate_membership_runs(
                    coalesce_daily_memberships(normalized),
                    period_start=self.period_start,
                    period_end=self.period_end,
                )
        except ValueError as exc:
            raise MassResearchDisabledError(str(exc)) from exc
        if not runs:
            raise MassResearchDisabledError("resolved universe is empty")
        object.__setattr__(self, "membership_runs", runs)
        object.__setattr__(self, "decision_memberships", tuple(iter_run_days(runs)))
        expected = stream_membership_digest(
            rule_id=self.rule_id,
            rule_version=self.rule_version,
            rule_digest=self.rule_digest,
            period_start=self.period_start,
            period_end=self.period_end,
            runs=runs,
        )
        declared = str(self.resolved_membership_digest or "")
        if declared and declared != expected:
            raise MassResearchDisabledError(
                "resolved universe membership digest mismatch"
            )
        object.__setattr__(self, "resolved_membership_digest", expected)

    @property
    def membership_by_date(self) -> Mapping[str, tuple[str, ...]]:
        return RunLengthMembershipMap(self.membership_runs)

    @property
    def membership_proof(self) -> str:
        return "controlled-resolved-universe:" + self.resolved_membership_digest

    def codes_for(self, decision_date: str) -> tuple[str, ...]:
        try:
            return codes_for_runs(self.membership_runs, str(decision_date))
        except (KeyError, ValueError) as exc:
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
            "membership_runs": [
                {"start": run.start, "end": run.end, "codes": list(run.codes)}
                for run in self.membership_runs
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.to_canonical_dict(),
            "resolved_membership_digest": self.resolved_membership_digest,
        }


def _calendar_dates(start: str, end: str) -> tuple[str, ...]:
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    values: list[str] = []
    while cursor <= stop:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


def _map_universe_pit_error(exc: BaseException) -> MassResearchDisabledError:
    message = str(exc)
    if "universe has no trading dates" in message:
        return MassResearchDisabledError("controlled universe has no trading dates")
    if "universe snapshot is missing" in message:
        return MassResearchDisabledError(
            message.replace("universe snapshot is missing", "controlled universe snapshot is missing")
        )
    if "universe requires canonical jquants_records" in message:
        return MassResearchDisabledError(
            "controlled universe requires the canonical jquants_records schema"
        )
    if "universe requires canonical" in message:
        return MassResearchDisabledError(
            message.replace("universe requires canonical", "controlled universe requires canonical")
        )
    if "universe snapshot query failed" in message:
        return MassResearchDisabledError(
            "controlled universe snapshot query failed closed"
        )
    return MassResearchDisabledError(str(exc))


def resolve_tse_prime_with_fins(
    slices: Sequence[UniverseDaySlice],
    *,
    period_start: str,
    period_end: str,
) -> ResolvedUniverseMembership:
    """Resolve the governed exact-four universe from closed PIT day slices."""
    membership, _evidence = resolve_tse_prime_with_fins_evidence(
        slices,
        period_start=period_start,
        period_end=period_end,
    )
    return membership


def resolve_tse_prime_with_fins_evidence(
    slices: Sequence[UniverseDaySlice],
    *,
    period_start: str,
    period_end: str,
) -> tuple[ResolvedUniverseMembership, dict[str, Any]]:
    """Resolve membership and report observed, non-authoritative breadth.

    The evidence only describes rows visible in the supplied closed slices.
    It deliberately makes no upstream-completeness claim and applies no pass
    threshold. Product never opens a database Path.
    """
    if isinstance(slices, (str, bytes)) or type(slices).__name__ in {"PosixPath", "WindowsPath", "Path"}:
        raise MassResearchDisabledError(
            "controlled universe requires closed PIT slices, not a storage path"
        )
    memberships: list[tuple[str, tuple[str, ...]]] = []
    interned_codes: dict[tuple[str, ...], tuple[str, ...]] = {}
    daily_observations: list[dict[str, Any]] = []
    for day_slice in slices:
        prime_codes = [
            member.code
            for member in day_slice.members
            if member.market_code == TSE_PRIME_MARKET_CODE
        ]
        resolved = tuple(
            sorted(code for code in prime_codes if code in day_slice.fins_codes)
        )
        if not resolved:
            raise MassResearchDisabledError(
                f"tse_prime_with_fins resolves empty at {day_slice.decision_date}"
            )
        resolved = interned_codes.setdefault(resolved, resolved)
        memberships.append((day_slice.decision_date, resolved))
        daily_observations.append(
            {
                "decision_date": day_slice.decision_date,
                "prime_master_count": len(prime_codes),
                "resolved_fins_intersection_count": len(resolved),
                "resolved_fins_intersection_ratio": (
                    len(resolved) / len(prime_codes)
                ),
            }
        )
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


def _resolve_tse_prime_with_fins_from_pinned_connection(
    connection: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    observed_through: str,
) -> ResolvedUniverseMembership:
    """Internal Controlled resolver; it cannot reopen a snapshot pathname."""

    from pit.read_clock import (
        SNAPSHOT_OBSERVATION_LABEL,
        PitReadClock,
        install_read_clock,
    )
    from pit.universe_pit import _universe_day_slices_from_connection

    as_of_for_day = {
        day: morning_close_as_of(day)
        for day in _calendar_dates(period_start, period_end)
    }
    proof_clock = PitReadClock(
        decision_at=morning_close_as_of(period_end),
        observed_through=observed_through,
        observation_label=SNAPSHOT_OBSERVATION_LABEL,
        promotable=True,
    )
    with install_read_clock(proof_clock):
        slices = _universe_day_slices_from_connection(
            connection,
            period_start=period_start,
            period_end=period_end,
            as_of_for_day=as_of_for_day,
        )
    return resolve_tse_prime_with_fins(
        slices,
        period_start=period_start,
        period_end=period_end,
    )



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
