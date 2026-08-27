#!/usr/bin/env python3
"""Fail-closed release gate for the pinned Phase 6.3.1 finding ledger.

The production entrypoint intentionally accepts no path argument.  Tests may
exercise the private bytes evaluator, but release callers can only evaluate the
ledger tracked at ``docs/phase633_finding_ledger.json`` in this checkout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, NoReturn


SCHEMA_VERSION = "phase631-finding-ledger/v1"
_ROOT = Path(__file__).resolve().parents[1]
_PINNED_LEDGER_PATH = _ROOT / "docs" / "phase633_finding_ledger.json"
_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "updated_at", "merge_policy", "findings"}
)
_MERGE_POLICY_KEYS = frozenset(
    {
        "required_p0_status",
        "independent_review_unresolved_p0",
        "candidate_patch_is_not_closure",
    }
)
_FINDING_REQUIRED_KEYS = frozenset(
    {"id", "area", "severity", "status", "summary"}
)
_FINDING_OPTIONAL_KEYS = frozenset({"evidence", "closure"})
_AREAS = frozenset(
    {
        "data_pit_receipt",
        "ready_plan_execution",
        "cloudflare_ops_ci",
        "architecture_test_operations",
    }
)
_SEVERITIES = frozenset({"P0", "P1"})
_STATUSES = frozenset({"OPEN", "FIXED", "DEFERRED", "HOLD"})
_FINDING_ID = re.compile(r"^[A-Z][0-9]+$")
_PINNED_FINDING_IDS = frozenset(
    {
        "D1",
        "D2",
        "D3",
        "D4",
        "D5",
        "D6",
        "D7",
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "R6",
        "R7",
        "R8",
        "R9",
        "R10",
        "R11",
        "R12",
        "C1",
        "C2",
        "C3",
        "C4",
        "C5",
        "C6",
        "C7",
        "C8",
        "C9",
        "C10",
        "C11",
        "C12",
        "C13",
        "C14",
        "C15",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
    }
)
_PINNED_P0_FINDING_IDS = frozenset(
    {
        "D1",
        "D2",
        "D3",
        "D4",
        "D7",
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "R6",
        "R10",
        "R11",
        "C1",
        "C2",
        "C3",
        "C4",
        "C9",
        "C10",
        "C11",
        "C13",
        "C14",
        "A1",
        "A2",
        "A7",
    }
)
_AREA_BY_ID_PREFIX = {
    "D": "data_pit_receipt",
    "R": "ready_plan_execution",
    "C": "cloudflare_ops_ci",
    "A": "architecture_test_operations",
}


class FindingLedgerError(RuntimeError):
    """The pinned ledger is malformed or its release policy is unsatisfied."""


@dataclass(frozen=True)
class FindingLedgerSnapshot:
    """Immutable, validated facts used by every release boundary."""

    digest: str
    open_p0_ids: tuple[str, ...]
    required_p0_status: str
    independent_review_unresolved_p0: int

    @property
    def release_allowed(self) -> bool:
        return (
            not self.open_p0_ids
            and self.required_p0_status == "FIXED"
            and self.independent_review_unresolved_p0 == 0
        )

    def evidence_payload(self) -> dict[str, Any]:
        return {
            "ledger_digest": self.digest,
            "open_p0_ids": list(self.open_p0_ids),
        }


def _reject_constant(value: str) -> NoReturn:
    raise FindingLedgerError(
        f"finding ledger contains non-finite JSON constant {value!r}"
    )


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FindingLedgerError(
                f"finding ledger contains duplicate object key {key!r}"
            )
        result[key] = value
    return result


def _strict_json_loads(raw: bytes) -> Mapping[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FindingLedgerError("finding ledger must be UTF-8 JSON") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except FindingLedgerError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FindingLedgerError("finding ledger is not strict JSON") from exc
    if not isinstance(value, Mapping):
        raise FindingLedgerError("finding ledger root must be an object")
    return value


def _exact_keys(value: Any, *, expected: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FindingLedgerError(f"{label} must be an object")
    observed = frozenset(value)
    if observed != expected:
        raise FindingLedgerError(
            f"{label} schema drift: missing={sorted(expected - observed)}, "
            f"extra={sorted(observed - expected)}"
        )
    return value


def _nonempty_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FindingLedgerError(f"{label} must be a non-empty string")
    return value


def _validate_updated_at(value: Any) -> None:
    rendered = _nonempty_string(value, label="finding ledger updated_at")
    try:
        observed = datetime.fromisoformat(rendered)
    except ValueError as exc:
        raise FindingLedgerError(
            "finding ledger updated_at must be an RFC3339 timestamp"
        ) from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise FindingLedgerError(
            "finding ledger updated_at must include an explicit timezone"
        )


def _validate_finding(raw: Any, *, index: int) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise FindingLedgerError(f"findings[{index}] must be an object")
    keys = frozenset(raw)
    allowed = _FINDING_REQUIRED_KEYS | _FINDING_OPTIONAL_KEYS
    missing = _FINDING_REQUIRED_KEYS - keys
    extra = keys - allowed
    if missing or extra:
        raise FindingLedgerError(
            f"findings[{index}] schema drift: missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    finding_id = _nonempty_string(raw["id"], label=f"findings[{index}].id")
    if _FINDING_ID.fullmatch(finding_id) is None:
        raise FindingLedgerError(f"findings[{index}].id is invalid")
    area = _nonempty_string(raw["area"], label=f"findings[{index}].area")
    if area not in _AREAS:
        raise FindingLedgerError(f"findings[{index}].area is invalid")
    expected_area = _AREA_BY_ID_PREFIX.get(finding_id[0])
    if expected_area is not None and area != expected_area:
        raise FindingLedgerError(
            f"findings[{index}].area does not match its pinned finding id"
        )
    severity = _nonempty_string(
        raw["severity"], label=f"findings[{index}].severity"
    )
    if severity not in _SEVERITIES:
        raise FindingLedgerError(f"findings[{index}].severity is invalid")
    expected_severity = "P0" if finding_id in _PINNED_P0_FINDING_IDS else "P1"
    if finding_id in _PINNED_FINDING_IDS and severity != expected_severity:
        raise FindingLedgerError(
            f"findings[{index}].severity does not match its pinned finding id"
        )
    status = _nonempty_string(raw["status"], label=f"findings[{index}].status")
    if status not in _STATUSES:
        raise FindingLedgerError(f"findings[{index}].status is invalid")
    _nonempty_string(raw["summary"], label=f"findings[{index}].summary")
    if status == "FIXED":
        _nonempty_string(raw.get("evidence"), label=f"findings[{index}].evidence")
    else:
        _nonempty_string(raw.get("closure"), label=f"findings[{index}].closure")
    if "evidence" in raw:
        _nonempty_string(raw["evidence"], label=f"findings[{index}].evidence")
    if "closure" in raw:
        _nonempty_string(raw["closure"], label=f"findings[{index}].closure")
    return raw


def _evaluate_ledger_bytes(raw: bytes) -> FindingLedgerSnapshot:
    """Private test seam: validate exact bytes without changing the pinned path."""

    document = _exact_keys(
        _strict_json_loads(raw), expected=_TOP_LEVEL_KEYS, label="finding ledger"
    )
    if document["schema_version"] != SCHEMA_VERSION:
        raise FindingLedgerError("finding ledger schema_version is invalid")
    _validate_updated_at(document["updated_at"])
    policy = _exact_keys(
        document["merge_policy"],
        expected=_MERGE_POLICY_KEYS,
        label="finding ledger merge_policy",
    )
    required_status = policy["required_p0_status"]
    if required_status != "FIXED":
        raise FindingLedgerError(
            "finding ledger required_p0_status must be FIXED"
        )
    unresolved_review = policy["independent_review_unresolved_p0"]
    if type(unresolved_review) is not int or unresolved_review < 0:
        raise FindingLedgerError(
            "finding ledger independent_review_unresolved_p0 must be a "
            "non-negative integer"
        )
    if policy["candidate_patch_is_not_closure"] is not True:
        raise FindingLedgerError(
            "finding ledger candidate_patch_is_not_closure must be true"
        )
    findings = document["findings"]
    if not isinstance(findings, list) or not findings:
        raise FindingLedgerError("finding ledger findings must be a non-empty array")
    ids: set[str] = set()
    p0_rows: list[Mapping[str, Any]] = []
    for index, raw_finding in enumerate(findings):
        finding = _validate_finding(raw_finding, index=index)
        finding_id = str(finding["id"])
        if finding_id in ids:
            raise FindingLedgerError(
                f"finding ledger contains duplicate finding id {finding_id!r}"
            )
        ids.add(finding_id)
        if finding["severity"] == "P0":
            p0_rows.append(finding)
    if ids != _PINNED_FINDING_IDS:
        raise FindingLedgerError(
            "finding ledger id inventory drift: "
            f"missing={sorted(_PINNED_FINDING_IDS - ids)}, "
            f"extra={sorted(ids - _PINNED_FINDING_IDS)}"
        )
    if not p0_rows:
        raise FindingLedgerError("finding ledger must contain at least one P0 row")
    open_p0_ids = tuple(
        sorted(
            str(finding["id"])
            for finding in p0_rows
            if finding["status"] != required_status
        )
    )
    return FindingLedgerSnapshot(
        digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        open_p0_ids=open_p0_ids,
        required_p0_status=required_status,
        independent_review_unresolved_p0=unresolved_review,
    )


def load_pinned_finding_ledger() -> FindingLedgerSnapshot:
    """Load only the repository-pinned production ledger."""

    try:
        raw = _PINNED_LEDGER_PATH.read_bytes()
    except OSError as exc:
        raise FindingLedgerError("pinned finding ledger cannot be read") from exc
    return _evaluate_ledger_bytes(raw)


def require_pinned_finding_ledger_gate() -> FindingLedgerSnapshot:
    """Return the pinned snapshot only when release policy is fully closed."""

    snapshot = load_pinned_finding_ledger()
    if snapshot.open_p0_ids or snapshot.independent_review_unresolved_p0 != 0:
        raise FindingLedgerError(
            "finding ledger release gate blocked: "
            f"open_p0_ids={list(snapshot.open_p0_ids)}, "
            "independent_review_unresolved_p0="
            f"{snapshot.independent_review_unresolved_p0}"
        )
    if not snapshot.release_allowed:
        raise FindingLedgerError("finding ledger release gate blocked")
    return snapshot


def main() -> int:
    # No argv/path parser by design: production always reads the pinned ledger.
    if len(sys.argv) != 1:
        print("finding ledger gate accepts no caller path or arguments", file=sys.stderr)
        return 2
    try:
        snapshot = require_pinned_finding_ledger_gate()
    except FindingLedgerError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"finding ledger release gate: ok ({snapshot.digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
