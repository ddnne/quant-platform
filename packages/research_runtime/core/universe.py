"""As-of tradable universe, built only from the PIT equity master.

This is the first anti-survivorship step: at each decision instant we ask PIT
"which equities existed and were listed as of now?" and trade only those. We
do **not** consult any delisting table or look forward — membership is taken
from the latest complete master snapshot visible at the decision instant.

The master can carry multiple full-market snapshots (keyed by
``snapshot_date``).  We select the latest applicable snapshot first and only
then build its code mapping, so a code absent after delisting does not survive
forever through an older per-code row. Richer filters (sector, scale, explicit
listing-status flags in the raw payload, liquidity screens) are deliberately
out of scope for the minimal engine.

A caller-injected fixed universe is only a candidate allowlist.  It never
proves membership: the engine intersects the candidates with
:func:`load_master` at every decision instant.  An :class:`EquityMasterMap`
produced by :func:`load_master` / :func:`membership_at` is the normal input.
A raw code list is rejected unless ``QP_ALLOW_FIXED_UNIVERSE=1``.  That env
only admits offline candidate codes; it cannot bypass the daily PIT gate and
is not a Mass, READY, or GO path.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import date
from types import MappingProxyType
from typing import Any

import pit

from .strategy_protocol import EquityMaster

FIXED_UNIVERSE_ENV = "QP_ALLOW_FIXED_UNIVERSE"

_WRAPPER_KEYS = frozenset({"pit_as_of", "membership_proof", "codes", "membership"})


class RawFixedUniverseError(ValueError):
    """Raw code list injected without PIT ``as_of`` / ``membership_proof``."""


class ResolvedDailyUniverse:
    """Immutable date-indexed candidates from a governed snapshot resolver.

    Product policy owns the rule.  The core copies its closed result and still
    intersects every day's candidates with that day's PIT master.  A missing
    decision date therefore fails closed instead of falling back to a static
    list.
    """

    __slots__ = (
        "membership_by_date",
        "membership_proof",
        "resolved_membership_digest",
        "rule_digest",
    )

    def __init__(self, universe: Any) -> None:
        raw = getattr(universe, "membership_by_date", None)
        resolved_digest = _nonempty_str(
            getattr(universe, "resolved_membership_digest", None)
        )
        rule_id = _nonempty_str(getattr(universe, "rule_id", None))
        rule_version = _nonempty_str(getattr(universe, "rule_version", None))
        rule_digest = _nonempty_str(getattr(universe, "rule_digest", None))
        period_start = _iso_date(getattr(universe, "period_start", None))
        period_end = _iso_date(getattr(universe, "period_end", None))
        proof = _nonempty_str(getattr(universe, "membership_proof", None))
        if (
            not isinstance(raw, Mapping)
            or not rule_id
            or not rule_version
            or not _is_sha256_digest(rule_digest)
            or not period_start
            or not period_end
            or period_start > period_end
        ):
            raise RawFixedUniverseError(
                "daily resolved universe requires a governed rule, period, and digest"
            )
        copied: dict[str, tuple[str, ...]] = {}
        for day, values in raw.items():
            if isinstance(values, (str, bytes)):
                raise RawFixedUniverseError(
                    "daily resolved universe codes must be a sequence"
                )
            codes = tuple(sorted({str(code).strip() for code in values}))
            normalized_day = _iso_date(day)
            if (
                not normalized_day
                or normalized_day < period_start
                or normalized_day > period_end
                or not codes
                or any(not code for code in codes)
                or normalized_day in copied
            ):
                raise RawFixedUniverseError(
                    "daily resolved universe has an invalid date or membership"
                )
            copied[normalized_day] = codes
        if not copied:
            raise RawFixedUniverseError("daily resolved universe is empty")
        canonical = {
            "rule_id": rule_id,
            "rule_version": rule_version,
            "rule_digest": rule_digest,
            "period_start": period_start,
            "period_end": period_end,
            "decision_memberships": [
                {"decision_date": day, "codes": list(copied[day])}
                for day in sorted(copied)
            ],
        }
        expected_digest = _canonical_digest(canonical)
        if (
            resolved_digest != expected_digest
            or proof != "controlled-resolved-universe:" + expected_digest
        ):
            raise RawFixedUniverseError(
                "daily resolved universe membership digest does not match its map"
            )
        self.membership_by_date = MappingProxyType(copied)
        self.resolved_membership_digest = expected_digest
        self.rule_digest = rule_digest
        self.membership_proof = proof

    def codes_for(self, decision_date: str) -> tuple[str, ...]:
        try:
            return self.membership_by_date[str(decision_date)]
        except KeyError as exc:
            raise RawFixedUniverseError(
                f"daily resolved universe has no membership for {decision_date}"
            ) from exc


class EquityMasterMap(dict[str, EquityMaster]):
    """``{code: EquityMaster}`` produced by :func:`load_master` (``as_of``).

    Always carries ``pit_as_of`` and ``membership_proof``. This is the
    injectable fixed-universe type; a raw set of codes is not.
    """

    def __init__(
        self,
        mapping: Mapping[str, EquityMaster],
        *,
        pit_as_of: Any,
    ) -> None:
        as_of = _nonempty_str(pit_as_of)
        if not as_of:
            raise ValueError(
                "equity-master membership requires pit_as_of; "
                "load_master(as_of) cannot skip PIT as_of"
            )
        super().__init__(mapping)
        self.pit_as_of = as_of
        self.membership_proof = f"pit_equity_master:{as_of}"

    def copy(self) -> EquityMasterMap:
        return EquityMasterMap(dict(self), pit_as_of=self.pit_as_of)


def fixed_universe_allowed() -> bool:
    """True only when ``QP_ALLOW_FIXED_UNIVERSE=1`` (research-only, not GO)."""
    return os.environ.get(FIXED_UNIVERSE_ENV, "").strip() == "1"


def _nonempty_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _is_sha256_digest(value: str) -> bool:
    if not value.startswith("sha256:") or len(value) != 71:
        return False
    return all(character in "0123456789abcdef" for character in value[7:])


def _iso_date(value: Any) -> str:
    text = _nonempty_str(value)
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return ""
    return text if parsed.isoformat() == text else ""


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _proof_of(obj: Any) -> str:
    for attr in ("pit_as_of", "membership_proof"):
        found = _nonempty_str(getattr(obj, attr, None))
        if found:
            return found
    if isinstance(obj, Mapping):
        for key in ("pit_as_of", "membership_proof"):
            found = _nonempty_str(obj.get(key))
            if found:
                return found
    return ""


def _sorted_codes(codes: Any) -> tuple[str, ...]:
    return tuple(sorted(str(c) for c in codes))


def _reject_raw() -> None:
    raise RawFixedUniverseError(
        "run_backtest(universe=...) rejects a raw code list without "
        "pit_as_of / membership_proof; pass load_master(as_of) or "
        f"membership_at(as_of), or set {FIXED_UNIVERSE_ENV}=1 "
        "(research-only; not a Mass / READY / GO path)"
    )


def resolve_injected_universe(
    universe: Any, *, db_path: Any = None
) -> tuple[str, ...] | ResolvedDailyUniverse | None:
    """Candidate allowlist codes, or ``None`` for all PIT members per day.

    Accepts :class:`EquityMasterMap` (from :func:`load_master`) or a mapping /
    object that carries a non-empty ``pit_as_of`` / ``membership_proof``.
    A ``codes`` + ``pit_as_of`` payload is re-checked via :func:`membership_at`.
    Raw sequences of codes are rejected unless ``QP_ALLOW_FIXED_UNIVERSE=1``.
    The returned codes are not a membership proof; callers must intersect
    them with :func:`load_master` at the decision instant.
    """
    if universe is None:
        return None
    if isinstance(universe, (str, bytes)):
        raise TypeError(
            f"unsupported universe injection type: {type(universe)!r}"
        )

    if hasattr(universe, "membership_by_date"):
        return ResolvedDailyUniverse(universe)

    proof = _proof_of(universe)
    as_of = _nonempty_str(getattr(universe, "pit_as_of", None))
    if isinstance(universe, Mapping) and not as_of:
        as_of = _nonempty_str(universe.get("pit_as_of"))
    membership = getattr(universe, "membership", None)
    if proof and isinstance(membership, Mapping):
        if as_of:
            return tuple(
                membership_at(as_of, db_path=db_path, codes=membership.keys()).keys()
            )
        return _sorted_codes(membership.keys())

    if isinstance(universe, Mapping):
        if proof:
            if "codes" in universe:
                if not as_of:
                    _reject_raw()
                return tuple(
                    membership_at(
                        as_of, db_path=db_path, codes=universe["codes"]
                    ).keys()
                )
            inner = universe.get("membership")
            if isinstance(inner, Mapping):
                if as_of:
                    return tuple(
                        membership_at(
                            as_of, db_path=db_path, codes=inner.keys()
                        ).keys()
                    )
                return _sorted_codes(inner.keys())
            return _sorted_codes(
                k for k in universe.keys() if k not in _WRAPPER_KEYS
            )
        if not fixed_universe_allowed():
            _reject_raw()
        return _sorted_codes(universe.keys())

    if isinstance(universe, Sequence) or isinstance(universe, (set, frozenset)):
        if not fixed_universe_allowed():
            _reject_raw()
        return _sorted_codes(universe)

    raise TypeError(
        f"unsupported universe injection type: {type(universe)!r}"
    )


def load_master(as_of: Any, *, db_path: Any = None) -> EquityMasterMap:
    """Latest-known-as-of equity master per code, read through PIT.

    Returns an :class:`EquityMasterMap` (``{code: EquityMaster}`` plus
    ``pit_as_of``) for the newest complete master snapshot whose rows are
    visible at ``as_of``.  Selecting one snapshot date prevents missing
    (delisted) codes from leaking in via older snapshots.
    """
    if not _nonempty_str(as_of):
        raise ValueError("load_master requires as_of")
    result = pit.get_equity_master(
        as_of=as_of,
        latest_snapshot=True,
        db_path=db_path,
    )
    latest_snapshot = max(
        (row.get("snapshot_date") or "" for row in result.rows), default=""
    )
    latest: dict[str, EquityMaster] = {}
    for row in result.rows:
        if (row.get("snapshot_date") or "") != latest_snapshot:
            continue
        code = row.get("code")
        if not code:
            continue
        latest[code] = EquityMaster(
            code=code,
            snapshot_date=row.get("snapshot_date") or "",
            company_name=row.get("company_name"),
            sector_17_code=row.get("sector_17_code"),
            sector_33_code=row.get("sector_33_code"),
            market_code=row.get("market_code"),
            scale_category=row.get("scale_category"),
        )
    return EquityMasterMap(latest, pit_as_of=as_of)


def membership_at(
    as_of: Any,
    *,
    db_path: Any = None,
    codes: Sequence[str] | None = None,
) -> EquityMasterMap:
    """PIT-proven membership at ``as_of``, optionally restricted to ``codes``.

    Codes not present in :func:`load_master` at ``as_of`` fail closed.
    """
    master = load_master(as_of, db_path=db_path)
    if codes is None:
        return master
    wanted = tuple(str(c) for c in codes)
    missing = sorted({c for c in wanted if c not in master})
    if missing:
        raise ValueError(
            f"codes not in PIT equity master at as_of={master.pit_as_of}: "
            f"{missing}"
        )
    return EquityMasterMap(
        {c: master[c] for c in wanted},
        pit_as_of=master.pit_as_of,
    )


def build_universe(as_of: Any, *, db_path: Any = None) -> tuple[str, ...]:
    """As-of tradable codes from the PIT equity master, sorted ascending.

    Every code in the latest full master snapshot visible by ``as_of`` is
    included. This excludes both not-yet-listed names and names omitted after
    delisting without consulting future snapshots.
    """
    return tuple(sorted(load_master(as_of=as_of, db_path=db_path).keys()))
