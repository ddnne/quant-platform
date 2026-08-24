"""Glob production *.py: extra_digests= callers use partition_extra_digests."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS = (REPO / "packages", REPO / "scripts")

# Lane B issue/verify path plus helper definition may attach envelope fields.
ISSUE_VERIFY_OR_HELPER = frozenset(
    {
        "coverage_receipts.py",
        "receipt_crypto.py",
        "trusted_receipt.py",
        "verified_receipt.py",
    }
)
EXTRA_DIGESTS_CALLS = frozenset(
    {
        "build_collection_receipt",
        "build_signed_digest_fields",
        "emit_segment_receipt",
        "issue",
    }
)


def _production_py() -> list[Path]:
    files: list[Path] = []
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if path.name.startswith("test_"):
                continue
            files.append(path)
    return files


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_partition_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node) == "partition_extra_digests"


def test_production_extra_digests_callers_use_partition_extra_digests() -> None:
    helper = REPO / "packages" / "data_plane" / "storage" / "receipt_crypto.py"
    assert "def partition_extra_digests" in helper.read_text(encoding="utf-8")

    offenders: list[str] = []
    found_caller = False
    for path in _production_py():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if path.name in ISSUE_VERIFY_OR_HELPER:
            continue
        rel = path.relative_to(REPO)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            extra = next((kw for kw in node.keywords if kw.arg == "extra_digests"), None)
            if extra is None:
                continue
            if _call_name(node) not in EXTRA_DIGESTS_CALLS:
                continue
            found_caller = True
            if not _is_partition_call(extra.value):
                offenders.append(f"{rel}:{node.lineno}")
    assert found_caller
    assert not offenders, (
        "extra_digests= callers must pass partition_extra_digests(...): "
        + ", ".join(offenders)
    )
