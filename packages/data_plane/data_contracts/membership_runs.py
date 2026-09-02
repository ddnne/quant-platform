"""Run-length membership for long PIT universes.

Stores state-change runs instead of a per-day × per-code Cartesian map.
A streaming digest never materializes the expanded JSON. Iteration yields the
current interned code tuple plus the decision date.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


def _iso_date(value: Any) -> str:
    text = str(value or "").strip()
    parsed = date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise ValueError("membership date is not ISO")
    return text


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _next_day(value: str) -> str:
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat()


def canonical_run_codes(codes: Sequence[str]) -> tuple[str, ...]:
    if (
        isinstance(codes, tuple)
        and codes
        and all(isinstance(code, str) and code and code.strip() == code for code in codes)
        and len(set(codes)) == len(codes)
        and tuple(sorted(codes)) == codes
    ):
        return codes
    items = tuple(str(code).strip() for code in codes)
    if not items or any(not code for code in items):
        raise ValueError("membership run codes are empty")
    if len(set(items)) != len(items):
        raise ValueError("membership run codes are not unique")
    if tuple(sorted(items)) != items:
        raise ValueError("membership run codes are not sorted")
    return items


def validate_membership_runs(
    runs: Sequence[MembershipRun],
    *,
    period_start: str,
    period_end: str,
    require_coalesced: bool = True,
) -> tuple[MembershipRun, ...]:
    """Reject malformed, overlapping, out-of-order, or out-of-period runs."""

    start = _iso_date(period_start)
    end = _iso_date(period_end)
    if start > end:
        raise ValueError("membership period is reversed")
    validated: list[MembershipRun] = []
    previous: MembershipRun | None = None
    for raw in runs:
        run = raw if isinstance(raw, MembershipRun) else MembershipRun(
            start=getattr(raw, "start"),
            end=getattr(raw, "end"),
            codes=tuple(getattr(raw, "codes")),
        )
        if run.start < start or run.end > end:
            raise ValueError("membership run is outside its period")
        if previous is not None:
            if run.start <= previous.end:
                raise ValueError("membership runs overlap or are out of order")
            if (
                require_coalesced
                and previous.codes == run.codes
                and _next_day(previous.end) == run.start
            ):
                merged = MembershipRun(
                    start=previous.start, end=run.end, codes=previous.codes
                )
                validated[-1] = merged
                previous = merged
                continue
        validated.append(run)
        previous = run
    if not validated:
        raise ValueError("membership runs are empty")
    return tuple(validated)


@dataclass(frozen=True, slots=True)
class MembershipRun:
    start: str
    end: str
    codes: tuple[str, ...]

    def __post_init__(self) -> None:
        start = _iso_date(self.start)
        end = _iso_date(self.end)
        if start > end:
            raise ValueError("membership run is reversed")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "codes", canonical_run_codes(self.codes))

    def contains(self, day: str) -> bool:
        return self.start <= day <= self.end


def coalesce_daily_memberships(
    pairs: Sequence[tuple[str, tuple[str, ...]]],
) -> tuple[MembershipRun, ...]:
    """Compress interned daily memberships into inclusive runs."""

    runs: list[MembershipRun] = []
    interned: dict[tuple[str, ...], tuple[str, ...]] = {}
    for raw_day, raw_codes in pairs:
        day = _iso_date(raw_day)
        codes = interned.setdefault(
            canonical_run_codes(raw_codes), canonical_run_codes(raw_codes)
        )
        if runs and runs[-1].codes is codes and _next_day(runs[-1].end) == day:
            last = runs[-1]
            runs[-1] = MembershipRun(start=last.start, end=day, codes=codes)
        else:
            runs.append(MembershipRun(start=day, end=day, codes=codes))
    return tuple(runs)


def codes_for_runs(runs: Sequence[MembershipRun], decision_date: str) -> tuple[str, ...]:
    day = _iso_date(decision_date)
    lo = 0
    hi = len(runs) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        run = runs[mid]
        if day < run.start:
            hi = mid - 1
        elif day > run.end:
            lo = mid + 1
        else:
            return run.codes
    raise KeyError(day)


def iter_run_days(
    runs: Sequence[MembershipRun],
) -> Iterator[tuple[str, tuple[str, ...]]]:
    for run in runs:
        cursor = date.fromisoformat(run.start)
        stop = date.fromisoformat(run.end)
        while cursor <= stop:
            yield cursor.isoformat(), run.codes
            cursor += timedelta(days=1)


def decision_dates(runs: Sequence[MembershipRun]) -> tuple[str, ...]:
    return tuple(day for day, _codes in iter_run_days(runs))


def _json_string(value: str) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")


def stream_membership_digest(
    *,
    rule_id: str,
    rule_version: str,
    rule_digest: str,
    period_start: str,
    period_end: str,
    runs: Sequence[MembershipRun],
) -> str:
    """SHA-256 of the run-length canonical form. Does not expand per-day codes.

    The hasher is updated with the exact canonical JSON object whose sorted
    keys are membership_runs, period_end, period_start, rule_digest, rule_id,
    rule_version. Each run is encoded independently so peak memory is one run.
    """

    digest = hashlib.sha256()
    digest.update(b'{"membership_runs":[')
    first = True
    for run in runs:
        if not first:
            digest.update(b",")
        first = False
        digest.update(
            _canonical_bytes(
                {
                    "codes": list(run.codes),
                    "end": run.end,
                    "start": run.start,
                }
            )
        )
    digest.update(b'],"period_end":')
    digest.update(_json_string(period_end))
    digest.update(b',"period_start":')
    digest.update(_json_string(period_start))
    digest.update(b',"rule_digest":')
    digest.update(_json_string(rule_digest))
    digest.update(b',"rule_id":')
    digest.update(_json_string(rule_id))
    digest.update(b',"rule_version":')
    digest.update(_json_string(rule_version))
    digest.update(b"}")
    return "sha256:" + digest.hexdigest()


class RunLengthMembershipMap(Mapping[str, tuple[str, ...]]):
    """Date lookup over interned runs. ``dict(map)`` copies pointers, not codes."""

    __slots__ = ("_runs", "_dates")

    def __init__(self, runs: Sequence[MembershipRun]) -> None:
        self._runs = tuple(runs)
        self._dates = decision_dates(self._runs)

    def __getitem__(self, key: str) -> tuple[str, ...]:
        try:
            return codes_for_runs(self._runs, str(key))
        except (KeyError, ValueError) as exc:
            raise KeyError(key) from exc

    def __iter__(self) -> Iterator[str]:
        return iter(self._dates)

    def __len__(self) -> int:
        return len(self._dates)


__all__ = [
    "MembershipRun",
    "RunLengthMembershipMap",
    "canonical_run_codes",
    "coalesce_daily_memberships",
    "codes_for_runs",
    "decision_dates",
    "iter_run_days",
    "stream_membership_digest",
    "validate_membership_runs",
]
