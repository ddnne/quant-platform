"""Closed, PIT-resolved TOPIX universes for personal DRAFT research.

This module is intentionally separate from ``research.universe_contract``.
The latter is the immutable controlled exact-four Prime authority. Personal
research is not Prime-limited: default ``topix_all`` and the listed
Core30/Large70/Mid400/Small/TOPIX100/500 selectors are PIT-resolved and
intersected with financials at the execution decision cutoff. Default AM
cohorts use 11:30 information and same-day PM close. These selectors are
unsigned personal exploration inputs and can never mint READY, Pilot, Mass,
promotion, or trading authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Literal, Mapping

from core.execution import close_as_of, morning_close_as_of
from data_contracts.membership_runs import (
    MembershipRun,
    RunLengthMembershipMap,
    coalesce_daily_memberships,
    codes_for_runs,
    iter_run_days,
    stream_membership_digest,
    validate_membership_runs,
)
from data_contracts.personal_universe import (
    TOPIX_CORE30,
    TOPIX_LARGE70,
    TOPIX_MID400,
    TOPIX_SCALE_CATEGORIES,
    TOPIX_SMALL_1,
    TOPIX_SMALL_2,
    canonical_topix_scale_category,
)
from pit import DatabaseNotFound, PitError
from pit.personal_research_view import PersonalResearchDataView
from pit.universe_pit import UniverseDaySlice


PERSONAL_UNIVERSE_RULE_VERSION = "personal-topix-scale-with-fins/v1"
PERSONAL_UNIVERSE_BREADTH_FORMAT = "personal-topix-with-fins-breadth/v1"
DEFAULT_PERSONAL_UNIVERSE_ID = "topix_all"
PersonalUniverseDecisionCutoff = Literal["session_close", "morning_close"]
PERSONAL_UNIVERSE_DECISION_CUTOFFS: tuple[str, ...] = (
    "session_close",
    "morning_close",
)
DEFAULT_PERSONAL_UNIVERSE_DECISION_CUTOFF: PersonalUniverseDecisionCutoff = (
    "morning_close"
)
_DECISION_CUTOFF_AS_OF = {
    "session_close": close_as_of,
    "morning_close": morning_close_as_of,
}
_DECISION_CUTOFF_CLOCK_IDS = {
    "session_close": "tse_session_close_jst",
    "morning_close": "tse_morning_close_jst",
}
_VersionIdentity = tuple[str, str, str]


def _require_decision_cutoff(value: str) -> PersonalUniverseDecisionCutoff:
    cutoff = str(value)
    if cutoff not in _DECISION_CUTOFF_AS_OF:
        raise PersonalUniverseError(
            "personal universe decision_cutoff must be one of "
            f"{list(PERSONAL_UNIVERSE_DECISION_CUTOFFS)}"
        )
    return cutoff  # type: ignore[return-value]


def personal_research_universe_decision_cutoff(
    *, am_pm: bool
) -> PersonalUniverseDecisionCutoff:
    """AM-signal/PM-close cohorts resolve membership at morning close."""

    return "morning_close" if am_pm else "session_close"


def personal_research_universe_rule_digest(
    universe_id: str, *, am_pm: bool
) -> str:
    """Rule digest for one closed universe at the cohort execution cutoff."""

    return personal_universe_selector(
        universe_id,
        decision_cutoff=personal_research_universe_decision_cutoff(am_pm=am_pm),
    ).rule_digest


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
    decision_cutoff: str = DEFAULT_PERSONAL_UNIVERSE_DECISION_CUTOFF

    def __post_init__(self) -> None:
        categories = tuple(dict.fromkeys(self.scale_categories))
        if (
            not self.selector_id
            or not categories
            or any(category not in TOPIX_SCALE_CATEGORIES for category in categories)
        ):
            raise PersonalUniverseError("personal universe selector is invalid")
        object.__setattr__(self, "scale_categories", categories)
        object.__setattr__(
            self, "decision_cutoff", _require_decision_cutoff(self.decision_cutoff)
        )

    @property
    def rule_id(self) -> str:
        return f"{self.selector_id}_with_fins"

    @property
    def rule_version(self) -> str:
        return PERSONAL_UNIVERSE_RULE_VERSION

    def with_decision_cutoff(self, decision_cutoff: str) -> PersonalUniverseSelector:
        cutoff = _require_decision_cutoff(decision_cutoff)
        if cutoff == self.decision_cutoff:
            return self
        return replace(self, decision_cutoff=cutoff)

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "decision_clock": _DECISION_CUTOFF_CLOCK_IDS[self.decision_cutoff],
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


def personal_universe_selector(
    selector_id: str,
    *,
    decision_cutoff: str = DEFAULT_PERSONAL_UNIVERSE_DECISION_CUTOFF,
) -> PersonalUniverseSelector:
    try:
        selector = _SELECTORS[str(selector_id)]
    except KeyError as exc:
        raise PersonalUniverseError(
            f"universe_id must be one of {list(PERSONAL_UNIVERSE_IDS)}"
        ) from exc
    return selector.with_decision_cutoff(decision_cutoff)


@dataclass(frozen=True, slots=True)
class PersonalResolvedUniverseMembership:
    """Content-addressed membership stored as run-length state changes."""

    period_start: str
    period_end: str
    decision_memberships: tuple[tuple[str, tuple[str, ...]], ...]
    rule_id: str
    rule_version: str
    rule_digest: str
    resolved_membership_digest: str = ""
    membership_runs: tuple[MembershipRun, ...] = ()

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
        interned: dict[tuple[str, ...], tuple[str, ...]] = {}
        normalized: list[tuple[str, tuple[str, ...]]] = []
        if self.decision_memberships:
            seen: set[str] = set()
            for raw_day, raw_codes in self.decision_memberships:
                day = str(raw_day)
                codes = tuple(sorted({str(code).strip() for code in raw_codes}))
                codes = interned.setdefault(codes, codes)
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
                        raise PersonalUniverseError(
                            "personal resolved universe membership runs disagree with daily memberships"
                        )
            else:
                if not normalized:
                    raise PersonalUniverseError("personal resolved universe is empty")
                runs = validate_membership_runs(
                    coalesce_daily_memberships(normalized),
                    period_start=self.period_start,
                    period_end=self.period_end,
                )
        except ValueError as exc:
            raise PersonalUniverseError(str(exc)) from exc
        if not runs:
            raise PersonalUniverseError("personal resolved universe is empty")
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
            raise PersonalUniverseError(
                "personal resolved universe membership digest mismatch"
            )
        object.__setattr__(self, "resolved_membership_digest", expected)

    @property
    def membership_by_date(self) -> Mapping[str, tuple[str, ...]]:
        return RunLengthMembershipMap(self.membership_runs)

    @property
    def membership_proof(self) -> str:
        # Distinct from Controlled ``controlled-resolved-universe:``. The core
        # engine only uses this as a digest envelope for a daily map; rule_id
        # remains PERSONAL_DRAFT/FORBIDDEN and cannot mint READY or Pilot.
        return "personal-draft-resolved-universe:" + self.resolved_membership_digest

    def codes_for(self, decision_date: str) -> tuple[str, ...]:
        try:
            return codes_for_runs(self.membership_runs, str(decision_date))
        except (KeyError, ValueError) as exc:
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
            "membership_runs": [
                {"start": run.start, "end": run.end, "codes": list(run.codes)}
                for run in self.membership_runs
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.to_canonical_dict(),
            "resolved_membership_digest": self.resolved_membership_digest,
            "research_state": "PERSONAL_DRAFT",
            "controlled_live_eligibility": "FORBIDDEN",
        }


def _map_universe_pit_error(exc: BaseException) -> PersonalUniverseError:
    message = str(exc)
    if isinstance(exc, DatabaseNotFound) or "structured DB not found" in message:
        return PersonalUniverseError(message)
    if (
        "rebuild as personal-draft-history/v8" in message
        or "compact v7 marker or schema is invalid" in message
        or "wire-incompatible" in message
    ):
        return PersonalUniverseError(
            "personal universe compact schema is invalid; "
            "rebuild as personal-draft-history/v8"
        )
    if "cannot mix compact" in message:
        return PersonalUniverseError(
            "personal universe cannot mix compact master with "
            "generic or revision equities_master"
        )
    if "requires canonical jquants_records" in message:
        return PersonalUniverseError(
            "personal universe requires canonical jquants_records"
        )
    if "universe has no trading dates" in message:
        return PersonalUniverseError("personal universe has no trading dates")
    return PersonalUniverseError(str(exc) if str(exc) else "personal universe snapshot query failed")


def _apply_personal_selector(
    slices: tuple[UniverseDaySlice, ...],
    selector: PersonalUniverseSelector,
    *,
    period_start: str,
    period_end: str,
) -> tuple[PersonalResolvedUniverseMembership, dict[str, Any]]:
    allowed = frozenset(selector.scale_categories)
    memberships: list[tuple[str, tuple[str, ...]]] = []
    interned_codes: dict[tuple[str, ...], tuple[str, ...]] = {}
    daily_observations: list[dict[str, Any]] = []
    for slice in slices:
        selected = []
        seen: set[str] = set()
        for member in slice.members:
            if member.code in seen:
                raise PersonalUniverseError(
                    "equities_master snapshot "
                    f"{slice.snapshot_date} has invalid code identity"
                )
            seen.add(member.code)
            category = canonical_topix_scale_category(member.scale_category)
            if category in allowed:
                selected.append(member.code)
        if not selected:
            raise PersonalUniverseError(
                f"{selector.selector_id} resolves no master members at {slice.decision_date}"
            )
        resolved = tuple(
            sorted(code for code in selected if code in slice.fins_codes)
        )
        if not resolved:
            raise PersonalUniverseError(
                f"{selector.rule_id} resolves empty at {slice.decision_date}"
            )
        resolved = interned_codes.setdefault(resolved, resolved)
        if memberships and memberships[-1][1] == resolved:
            resolved = memberships[-1][1]
        memberships.append((slice.decision_date, resolved))
        daily_observations.append(
            {
                "decision_date": slice.decision_date,
                "selector_master_count": len(selected),
                "resolved_fins_intersection_count": len(resolved),
                "resolved_fins_intersection_ratio": len(resolved) / len(selected),
            }
        )
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
        "decision_cutoff": selector.decision_cutoff,
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
        "research_state": "PERSONAL_DRAFT",
        "controlled_live_eligibility": "FORBIDDEN",
    }
    return membership, evidence


def resolve_personal_universe_with_evidence(
    view: PersonalResearchDataView,
    *,
    period_start: str,
    period_end: str,
    universe_id: str = DEFAULT_PERSONAL_UNIVERSE_ID,
    decision_cutoff: str | None = None,
) -> tuple[PersonalResolvedUniverseMembership, dict[str, Any]]:
    """Resolve one closed selector from the latest PIT-visible dated master."""
    if not isinstance(view, PersonalResearchDataView):
        raise PersonalUniverseError("personal universe requires a typed research data view")
    cutoff = str(decision_cutoff or view.decision_cutoff)
    selector = personal_universe_selector(universe_id, decision_cutoff=cutoff)
    if selector.decision_cutoff != view.decision_cutoff:
        raise PersonalUniverseError(
            "personal universe decision_cutoff must match the research view"
        )
    try:
        slices = view.universe_slices(
            period_start=period_start, period_end=period_end
        )
    except PitError as exc:
        raise _map_universe_pit_error(exc) from exc
    return _apply_personal_selector(
        slices,
        selector,
        period_start=period_start,
        period_end=period_end,
    )


def resolve_personal_universe(
    view: PersonalResearchDataView,
    *,
    period_start: str,
    period_end: str,
    universe_id: str = DEFAULT_PERSONAL_UNIVERSE_ID,
    decision_cutoff: str | None = None,
) -> PersonalResolvedUniverseMembership:
    membership, _evidence = resolve_personal_universe_with_evidence(
        view,
        period_start=period_start,
        period_end=period_end,
        universe_id=universe_id,
        decision_cutoff=decision_cutoff,
    )
    return membership


__all__ = [
    "DEFAULT_PERSONAL_UNIVERSE_DECISION_CUTOFF",
    "DEFAULT_PERSONAL_UNIVERSE_ID",
    "PERSONAL_UNIVERSE_BREADTH_FORMAT",
    "PERSONAL_UNIVERSE_DECISION_CUTOFFS",
    "PERSONAL_UNIVERSE_IDS",
    "PERSONAL_UNIVERSE_RULE_VERSION",
    "PersonalResolvedUniverseMembership",
    "PersonalUniverseError",
    "PersonalUniverseSelector",
    "personal_research_universe_decision_cutoff",
    "personal_research_universe_rule_digest",
    "personal_universe_selector",
    "resolve_personal_universe",
    "resolve_personal_universe_with_evidence",
]
