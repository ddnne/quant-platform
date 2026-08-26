"""Behavioral attacks against the sole finding-ledger release gate."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import finding_ledger_gate as gate


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "phase633_finding_ledger.json"


def _document() -> dict[str, object]:
    value = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _render(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _closed_document() -> dict[str, object]:
    value = _document()
    for finding in value["findings"]:  # type: ignore[index]
        if finding["severity"] == "P0":
            finding["status"] = "FIXED"
    return value


def test_current_pinned_ledger_blocks_with_exact_open_p0_inventory() -> None:
    snapshot = gate.load_pinned_finding_ledger()
    assert snapshot.open_p0_ids == (
        "A2",
        "C10",
        "C4",
        "D2",
        "D3",
        "R10",
        "R11",
        "R5",
    )
    assert not snapshot.release_allowed
    with pytest.raises(gate.FindingLedgerError, match="release gate blocked"):
        gate.require_pinned_finding_ledger_gate()


def test_closed_fixture_is_the_only_success_shape() -> None:
    snapshot = gate._evaluate_ledger_bytes(_render(_closed_document()))
    assert snapshot.open_p0_ids == ()
    assert snapshot.independent_review_unresolved_p0 == 0
    assert snapshot.release_allowed
    assert snapshot.evidence_payload() == {
        "ledger_digest": snapshot.digest,
        "open_p0_ids": [],
    }


@pytest.mark.parametrize("level", ["root", "policy", "finding"])
def test_nonfinite_json_is_rejected_at_every_object_level(level: str) -> None:
    document = _closed_document()
    if level == "root":
        document["updated_at"] = float("nan")
    elif level == "policy":
        document["merge_policy"]["independent_review_unresolved_p0"] = float(  # type: ignore[index]
            "inf"
        )
    else:
        document["findings"][0]["summary"] = float("-inf")  # type: ignore[index]
    with pytest.raises(gate.FindingLedgerError, match="non-finite"):
        gate._evaluate_ledger_bytes(_render(document))


@pytest.mark.parametrize(
    "needle,replacement",
    [
        ('"schema_version":', '"schema_version":"duplicate","schema_version":'),
        (
            '"required_p0_status":"FIXED"',
            '"required_p0_status":"FIXED","required_p0_status":"FIXED"',
        ),
        ('"id":"D1"', '"id":"D1","id":"D1"'),
    ],
)
def test_duplicate_json_keys_are_rejected_at_every_object_level(
    needle: str, replacement: str
) -> None:
    raw = _render(_closed_document()).decode("utf-8")
    assert needle in raw
    attacked = raw.replace(needle, replacement, 1)
    with pytest.raises(gate.FindingLedgerError, match="duplicate object key"):
        gate._evaluate_ledger_bytes(attacked.encode("utf-8"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda doc: doc["findings"].clear(), "non-empty array"),
        (
            lambda doc: doc.__setitem__(
                "findings",
                [row for row in doc["findings"] if row["severity"] != "P0"],
            ),
            "id inventory drift",
        ),
        (
            lambda doc: doc["findings"].append(deepcopy(doc["findings"][0])),
            "duplicate finding id",
        ),
        (lambda doc: doc["findings"].pop(), "id inventory drift"),
        (
            lambda doc: doc["findings"].append(
                {
                    "id": "Z99",
                    "area": "architecture_test_operations",
                    "severity": "P1",
                    "status": "FIXED",
                    "summary": "invented",
                    "evidence": "invented",
                }
            ),
            "id inventory drift",
        ),
    ],
)
def test_finding_inventory_cannot_vacuously_pass(mutation, message: str) -> None:
    document = _closed_document()
    mutation(document)
    with pytest.raises(gate.FindingLedgerError, match=message):
        gate._evaluate_ledger_bytes(_render(document))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda doc: doc["merge_policy"].__setitem__(
                "independent_review_unresolved_p0", True
            ),
            "non-negative integer",
        ),
        (
            lambda doc: doc["merge_policy"].__setitem__(
                "independent_review_unresolved_p0", 1
            ),
            "release gate blocked",
        ),
        (
            lambda doc: doc["merge_policy"].__setitem__(
                "required_p0_status", "OPEN"
            ),
            "must be FIXED",
        ),
        (
            lambda doc: doc["findings"][0].__setitem__("severity", "P2"),
            "severity is invalid",
        ),
        (
            lambda doc: doc["findings"][0].__setitem__("status", "CLOSED"),
            "status is invalid",
        ),
        (
            lambda doc: next(
                row for row in doc["findings"] if row["id"] == "A2"
            ).__setitem__("severity", "P1"),
            "severity does not match its pinned finding id",
        ),
        (
            lambda doc: doc["findings"][0].__setitem__(
                "area", "ready_plan_execution"
            ),
            "area does not match its pinned finding id",
        ),
    ],
)
def test_policy_and_vocabulary_attacks_fail_closed(mutate, message: str) -> None:
    document = _closed_document()
    mutate(document)
    snapshot_or_error = None
    if message == "release gate blocked":
        snapshot_or_error = gate._evaluate_ledger_bytes(_render(document))
        assert not snapshot_or_error.release_allowed
        return
    with pytest.raises(gate.FindingLedgerError, match=message):
        gate._evaluate_ledger_bytes(_render(document))


@pytest.mark.parametrize("level", ["root", "policy", "finding"])
def test_closed_schema_rejects_unknown_fields_at_every_level(level: str) -> None:
    document = _closed_document()
    if level == "root":
        document["release_allowed"] = True
    elif level == "policy":
        document["merge_policy"]["release_allowed"] = True  # type: ignore[index]
    else:
        document["findings"][0]["release_allowed"] = True  # type: ignore[index]
    with pytest.raises(gate.FindingLedgerError, match="schema drift"):
        gate._evaluate_ledger_bytes(_render(document))


def test_nonzero_independent_review_count_blocks_even_with_all_p0_fixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _closed_document()
    document["merge_policy"]["independent_review_unresolved_p0"] = 1  # type: ignore[index]
    snapshot = gate._evaluate_ledger_bytes(_render(document))
    assert not snapshot.release_allowed
    monkeypatch.setattr(gate, "load_pinned_finding_ledger", lambda: snapshot)
    with pytest.raises(gate.FindingLedgerError, match="release gate blocked"):
        gate.require_pinned_finding_ledger_gate()


def test_production_cli_accepts_no_caller_ledger_path() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "finding_ledger_gate.py"), str(LEDGER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "accepts no caller path" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        [sys.executable, "scripts/finding_ledger_gate.py"],
        ["bash", "scripts/verify_ci.sh"],
        ["bash", "scripts/verify_cloudflare_deployment_acceptance.sh"],
        [
            sys.executable,
            "scripts/build_release_evidence.py",
            "does-not-exist.json",
            "--output-dir",
            "does-not-exist-output",
        ],
    ],
)
def test_every_release_entrypoint_stops_on_the_current_open_ledger(
    command: list[str],
) -> None:
    env = {"PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "finding ledger release gate blocked" in result.stderr
    assert not (ROOT / "does-not-exist-output").exists()
