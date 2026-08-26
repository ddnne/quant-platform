"""Behavioral attacks against the sole finding-ledger release gate."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from scripts import finding_ledger_gate as gate


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "phase633_finding_ledger.json"
MARKDOWN_LEDGER = ROOT / "docs" / "phase633_finding_ledger.md"

EXPECTED_FINDING_IDS = frozenset(
    {
        "D1", "D2", "D3", "D4", "D5", "D6", "D7",
        "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9",
        "R10", "R11", "R12",
        "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9",
        "C10", "C11", "C12", "C13", "C14", "C15",
        "A1", "A2", "A3", "A4", "A5", "A6", "A7",
    }
)
EXPECTED_P0_FINDING_IDS = frozenset(
    {
        "D1", "D2", "D3", "D4", "D7",
        "R1", "R2", "R3", "R4", "R5", "R6", "R10", "R11",
        "C1", "C2", "C3", "C4", "C9", "C10", "C11", "C13", "C14",
        "A1", "A2", "A7",
    }
)
EXPECTED_P1_FINDING_IDS = frozenset(
    {
        "D5", "D6",
        "R7", "R8", "R9", "R12",
        "C5", "C6", "C7", "C8", "C12", "C15",
        "A3", "A4", "A5", "A6",
    }
)
EXPECTED_NEW_FINDINGS = {
    "D7": ("data_pit_receipt", "P0", "FIXED"),
    "R12": ("ready_plan_execution", "P1", "FIXED"),
    "C11": ("cloudflare_ops_ci", "P0", "FIXED"),
    "C12": ("cloudflare_ops_ci", "P1", "FIXED"),
    "C13": ("cloudflare_ops_ci", "P0", "FIXED"),
    "C14": ("cloudflare_ops_ci", "P0", "FIXED"),
    "C15": ("cloudflare_ops_ci", "P1", "FIXED"),
}
MARKDOWN_AREAS = {
    "Data / PIT / Receipt": "data_pit_receipt",
    "READY / Plan / Execution": "ready_plan_execution",
    "Cloudflare / Ops / CI": "cloudflare_ops_ci",
    "Architecture / Test / Operations": "architecture_test_operations",
}
MARKDOWN_FINDING_ID = re.compile(r"^[A-Z][0-9]+$")
MARKDOWN_STATUSES = frozenset({"OPEN", "FIXED", "DEFERRED", "HOLD"})


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


def _markdown_structure(
    markdown: str | None = None,
) -> dict[str, tuple[str, str, str]]:
    area: str | None = None
    severity: str | None = None
    rows: dict[str, tuple[str, str, str]] = {}
    seen_ids: set[str] = set()
    rendered_markdown = (
        MARKDOWN_LEDGER.read_text(encoding="utf-8")
        if markdown is None
        else markdown
    )
    for line in rendered_markdown.splitlines():
        if line.startswith("## "):
            area = MARKDOWN_AREAS.get(line.removeprefix("## ").strip())
            severity = None
            continue
        if line.startswith("### "):
            candidate = line.removeprefix("### ").strip()
            severity = candidate if candidate in {"P0", "P1"} else None
            continue
        rendered = line.strip()
        if not rendered.startswith("|"):
            continue
        first_cell = rendered.removeprefix("|").split("|", 1)[0].strip()
        if MARKDOWN_FINDING_ID.fullmatch(first_cell) is None:
            continue
        finding_id = first_cell
        assert finding_id not in seen_ids, (
            f"duplicate Markdown finding id: {finding_id}"
        )
        seen_ids.add(finding_id)

        body = rendered.removeprefix("|")
        if body.endswith("|"):
            body = body.removesuffix("|")
        cells = tuple(cell.strip() for cell in body.split("|"))
        assert len(cells) == 4, (
            f"Markdown finding {finding_id} must have exactly four table cells"
        )
        row_id, finding, status, evidence = cells
        assert row_id == finding_id
        assert finding, f"Markdown finding {finding_id} must have finding text"
        assert status in MARKDOWN_STATUSES, (
            f"Markdown finding {finding_id} has invalid status {status!r}"
        )
        assert evidence, f"Markdown finding {finding_id} must have evidence text"
        assert area is not None, f"finding row outside a pinned area: {line}"
        assert severity is not None, f"finding row outside P0/P1: {line}"
        rows[finding_id] = (area, severity, status)
    return rows


def _replace_markdown_finding_row(finding_id: str, replacement: str) -> str:
    lines = MARKDOWN_LEDGER.read_text(encoding="utf-8").splitlines()
    indexes = [
        index
        for index, line in enumerate(lines)
        if line.startswith(f"| {finding_id} |")
    ]
    assert len(indexes) == 1
    lines[indexes[0]] = replacement
    return "\n".join(lines) + "\n"


def test_pinned_inventory_and_severity_oracles_are_exact() -> None:
    assert len(EXPECTED_FINDING_IDS) == 41
    assert len(EXPECTED_P0_FINDING_IDS) == 25
    assert len(EXPECTED_P1_FINDING_IDS) == 16
    assert EXPECTED_P0_FINDING_IDS.isdisjoint(EXPECTED_P1_FINDING_IDS)
    assert EXPECTED_P0_FINDING_IDS | EXPECTED_P1_FINDING_IDS == EXPECTED_FINDING_IDS
    assert gate._PINNED_FINDING_IDS == EXPECTED_FINDING_IDS
    assert gate._PINNED_P0_FINDING_IDS == EXPECTED_P0_FINDING_IDS

    document = _document()
    rows = document["findings"]  # type: ignore[index]
    assert {row["id"] for row in rows} == EXPECTED_FINDING_IDS
    assert {row["id"] for row in rows if row["severity"] == "P0"} == (
        EXPECTED_P0_FINDING_IDS
    )
    assert {row["id"] for row in rows if row["severity"] == "P1"} == (
        EXPECTED_P1_FINDING_IDS
    )
    observed = {
        row["id"]: (row["area"], row["severity"], row["status"])
        for row in rows
    }
    assert {
        finding_id: observed[finding_id] for finding_id in EXPECTED_NEW_FINDINGS
    } == EXPECTED_NEW_FINDINGS
    assert {
        status: sum(row["status"] == status for row in rows)
        for status in ("FIXED", "OPEN", "HOLD", "DEFERRED")
    } == {"FIXED": 27, "OPEN": 10, "HOLD": 2, "DEFERRED": 2}


@pytest.mark.parametrize("finding_id", sorted(EXPECTED_FINDING_IDS))
def test_every_pinned_finding_severity_is_immutable(finding_id: str) -> None:
    document = _closed_document()
    row = next(
        row for row in document["findings"] if row["id"] == finding_id  # type: ignore[index]
    )
    row["severity"] = "P1" if finding_id in EXPECTED_P0_FINDING_IDS else "P0"
    with pytest.raises(
        gate.FindingLedgerError,
        match="severity does not match its pinned finding id",
    ):
        gate._evaluate_ledger_bytes(_render(document))


def test_markdown_and_json_ledgers_have_exact_structural_parity() -> None:
    document = _document()
    json_rows: dict[str, tuple[str, str, str]] = {}
    for row in document["findings"]:  # type: ignore[index]
        finding_id = row["id"]
        assert finding_id not in json_rows, f"duplicate JSON finding id: {finding_id}"
        json_rows[finding_id] = (row["area"], row["severity"], row["status"])
    assert len(json_rows) == 41
    assert set(json_rows) == EXPECTED_FINDING_IDS
    assert _markdown_structure() == json_rows


def test_markdown_row_cannot_search_a_later_allowed_status() -> None:
    attacked = _replace_markdown_finding_row(
        "D2",
        "| D2 | forged | CLOSED | OPEN | evidence |",
    )
    with pytest.raises(AssertionError, match="exactly four table cells"):
        _markdown_structure(attacked)


def test_markdown_duplicate_id_is_rejected_even_when_row_is_malformed() -> None:
    attacked = (
        MARKDOWN_LEDGER.read_text(encoding="utf-8").rstrip()
        + "\n| D7 | contradictory | CLOSED | bogus |\n"
    )
    with pytest.raises(AssertionError, match="duplicate Markdown finding id: D7"):
        _markdown_structure(attacked)


def test_markdown_status_must_be_exactly_allowed() -> None:
    attacked = _replace_markdown_finding_row(
        "D7",
        "| D7 | contradictory | CLOSED | bogus |",
    )
    with pytest.raises(AssertionError, match="has invalid status 'CLOSED'"):
        _markdown_structure(attacked)


@pytest.mark.parametrize(
    "replacement",
    [
        "| D7 | finding | FIXED | evidence | extra |",
        "| D7 | finding | FIXED |",
    ],
)
def test_markdown_finding_rows_require_exactly_four_cells(
    replacement: str,
) -> None:
    attacked = _replace_markdown_finding_row("D7", replacement)
    with pytest.raises(AssertionError, match="exactly four table cells"):
        _markdown_structure(attacked)


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
