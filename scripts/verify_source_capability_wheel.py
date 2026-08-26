#!/usr/bin/env python3
"""Build and behaviorally verify the installed SourceCapability authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_ROUTES = frozenset(
    {
        "equities_bars_daily",
        "fins_details",
        "fins_dividend",
        "fins_earnings_date",
        "fins_summary",
        "indices_bars_daily_topix",
        "markets_calendar",
    }
)
EXPECTED_CONTRACT_FILES = frozenset(
    {
        "equities_bars_daily.json",
        "equities_bars_daily_am.json",
        "equities_earnings_calendar.json",
        "equities_master.json",
        "fins_details.json",
        "fins_dividend.json",
        "fins_earnings_date.json",
        "fins_summary.json",
        "indices_bars_daily_topix.json",
        "jsda_otc_bond_reference_prices.json",
        "markets_calendar.json",
    }
)
REGISTRY_NAME = "jquants_acquisition_target_registry.generated.json"
REGISTRY_SOURCE_LOCATOR = (
    "packages/data_plane/data_contracts/source_capability_contracts"
)


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _require_under(path: Path, parent: Path, *, label: str) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise AssertionError(f"{label} escaped installed wheel: {path}") from exc


def _installed_probe(expected_prefix: Path) -> dict[str, Any]:
    import data_contracts
    import data_contracts.coverage as coverage_module
    import data_contracts.source_capability as capability_module
    from data_contracts.coverage import coverage_contract_for
    from data_contracts.source_capability import (
        all_source_capability_contracts,
        derive_collection_coverage_v3,
        specs_dir,
    )

    installed_root = expected_prefix.resolve()
    package_root = Path(data_contracts.__file__).resolve().parent
    capability_module_path = Path(capability_module.__file__).resolve()
    coverage_module_path = Path(coverage_module.__file__).resolve()
    authority_dir = specs_dir().resolve()
    registry_path = package_root / REGISTRY_NAME
    for path, label in (
        (package_root, "data_contracts package"),
        (capability_module_path, "SourceCapability module"),
        (coverage_module_path, "Coverage module"),
        (authority_dir, "SourceCapability authority"),
        (registry_path, "acquisition registry"),
    ):
        _require_under(path, installed_root, label=label)
    if authority_dir.parent != package_root:
        raise AssertionError("SourceCapability authority is not package-owned")
    if "qp_paths" in sys.modules:
        raise AssertionError("installed SourceCapability loading consulted qp_paths")

    files = frozenset(path.name for path in authority_dir.glob("*.json"))
    if files != EXPECTED_CONTRACT_FILES:
        raise AssertionError(
            "installed SourceCapability file inventory mismatch: "
            f"missing={sorted(EXPECTED_CONTRACT_FILES - files)}, "
            f"extra={sorted(files - EXPECTED_CONTRACT_FILES)}"
        )
    contracts = all_source_capability_contracts()
    contract_ids = frozenset(contract.dataset_id for contract in contracts)
    if len(contracts) != 11 or contract_ids != {
        name.removesuffix(".json") for name in EXPECTED_CONTRACT_FILES
    }:
        raise AssertionError("installed SourceCapability registry is not exact-11")

    for contract in contracts:
        derived = derive_collection_coverage_v3(contract)
        coverage = coverage_contract_for(contract.dataset_id)
        for key, value in derived.items():
            if getattr(coverage, key) != value:
                raise AssertionError(
                    f"V3 Coverage parity mismatch: {contract.dataset_id}.{key}"
                )

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry_digest = registry.get("registry_digest")
    registry_body = {
        key: value for key, value in registry.items() if key != "registry_digest"
    }
    if registry_digest != _canonical_digest(registry_body):
        raise AssertionError("installed acquisition registry self-digest drift")
    if (
        registry.get("sources", {}).get("source_capability_directory")
        != REGISTRY_SOURCE_LOCATOR
    ):
        raise AssertionError("installed acquisition registry authority locator drift")

    route_digests: dict[str, dict[str, str]] = {}
    rows = registry.get("datasets")
    if not isinstance(rows, list):
        raise AssertionError("installed acquisition registry lacks routes")
    for row in rows:
        if not isinstance(row, dict):
            raise AssertionError("installed acquisition registry route is malformed")
        canonical = row.get("canonical_dataset")
        source = row.get("source_capability")
        coverage = row.get("coverage_policy")
        if not all(isinstance(value, dict) for value in (canonical, source, coverage)):
            raise AssertionError("installed acquisition registry route contracts are malformed")
        dataset_id = canonical.get("dataset_id")
        if not isinstance(dataset_id, str):
            raise AssertionError("installed acquisition registry route has no dataset id")
        source_path = authority_dir / f"{dataset_id}.json"
        source_document = json.loads(source_path.read_text(encoding="utf-8"))
        installed_coverage = coverage_contract_for(dataset_id).to_dict()
        source_digest = _canonical_digest(source_document)
        registry_source_digest = _canonical_digest(source)
        coverage_digest = _canonical_digest(installed_coverage)
        registry_coverage_digest = _canonical_digest(coverage)
        if source_digest != registry_source_digest:
            raise AssertionError(f"SourceCapability route digest drift: {dataset_id}")
        if coverage_digest != registry_coverage_digest:
            raise AssertionError(f"Coverage route digest drift: {dataset_id}")
        route_digests[dataset_id] = {
            "source_capability_digest": source_digest,
            "coverage_policy_digest": coverage_digest,
        }
    if frozenset(route_digests) != ACTIVE_ROUTES:
        raise AssertionError("installed acquisition registry active routes drift")

    return {
        "package_root": str(package_root),
        "authority_dir": str(authority_dir),
        "contract_count": len(contracts),
        "contract_ids": sorted(contract_ids),
        "registry_digest": registry_digest,
        "route_digests": route_digests,
    }


def _run(command: list[str], *, cwd: Path, capture: bool = False) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return completed.stdout if capture else ""


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _copy_tracked_source(destination: Path) -> None:
    """Copy the current tracked worktree without build caches or ignored files."""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    for encoded in completed.stdout.split(b"\0"):
        if not encoded:
            continue
        relative = Path(os.fsdecode(encoded))
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        elif source.is_file():
            shutil.copy2(source, target)
        else:
            raise AssertionError(f"tracked build input missing: {relative}")


def _probe_subprocess(
    *, installed_python: Path, cwd: Path, expected_prefix: Path
) -> dict[str, Any]:
    output = _run(
        [
            str(installed_python),
            "-I",
            str(Path(__file__).resolve()),
            "--probe-installed",
            "--expected-prefix",
            str(expected_prefix),
        ],
        cwd=cwd,
        capture=True,
    )
    result = json.loads(output)
    if not isinstance(result, dict):
        raise AssertionError("installed SourceCapability probe returned no object")
    return result


def _verify_wheel(*, uv: Path, python: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="quant-platform-source-capability-") as raw:
        temporary = Path(raw)
        source = temporary / "source"
        dist = temporary / "dist"
        venv = temporary / "venv"
        empty_cwd = temporary / "empty-cwd"
        decoy_cwd = temporary / "malicious-decoy-cwd"
        source.mkdir()
        dist.mkdir()
        empty_cwd.mkdir()
        _copy_tracked_source(source)
        (decoy_cwd / "tests").mkdir(parents=True)
        (decoy_cwd / "specs" / "source_capability").mkdir(parents=True)
        (decoy_cwd / "packages" / "data_plane" / "data_contracts" /
         "source_capability_contracts").mkdir(parents=True)
        (decoy_cwd / "pyproject.toml").write_text(
            "[project]\nname='malicious-decoy'\nversion='0'\n",
            encoding="utf-8",
        )
        for decoy in (
            decoy_cwd / "specs" / "source_capability" / "equities_bars_daily.json",
            decoy_cwd / "packages" / "data_plane" / "data_contracts" /
            "source_capability_contracts" / "equities_bars_daily.json",
        ):
            decoy.write_text('{"dataset_id":"cwd-decoy"}\n', encoding="utf-8")

        _run(
            [
                str(uv),
                "build",
                "--wheel",
                "--quiet",
                "--no-build-logs",
                "--no-create-gitignore",
                "--out-dir",
                str(dist),
                "--python",
                str(python),
                str(source),
            ],
            cwd=source,
        )
        wheels = tuple(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise AssertionError(f"expected one built wheel, found {len(wheels)}")
        _run(
            [str(python), "-m", "venv", "--without-pip", str(venv)],
            cwd=temporary,
        )
        installed_python = _venv_python(venv)
        _run(
            [
                str(uv),
                "pip",
                "install",
                "--quiet",
                "--python",
                str(installed_python),
                "--no-deps",
                "--no-index",
                str(wheels[0]),
            ],
            cwd=temporary,
        )
        empty_result = _probe_subprocess(
            installed_python=installed_python,
            cwd=empty_cwd,
            expected_prefix=venv,
        )
        decoy_result = _probe_subprocess(
            installed_python=installed_python,
            cwd=decoy_cwd,
            expected_prefix=venv,
        )
        if empty_result != decoy_result:
            raise AssertionError("malicious CWD changed installed authority loading")
        print(
            "SourceCapability installed-wheel authority: "
            f"ok ({empty_result['contract_count']} contracts, "
            f"{len(empty_result['route_digests'])} active route digests)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--probe-installed", action="store_true")
    parser.add_argument("--expected-prefix", type=Path)
    args = parser.parse_args(argv)
    if args.probe_installed:
        if args.expected_prefix is None:
            parser.error("--probe-installed requires --expected-prefix")
        print(json.dumps(_installed_probe(args.expected_prefix), sort_keys=True))
        return 0
    if args.uv is None or args.python is None:
        parser.error("wheel verification requires --uv and --python")
    _verify_wheel(uv=args.uv.resolve(), python=args.python.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
