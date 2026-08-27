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
EXPECTED_CANONICAL_SOURCE_DIGEST = (
    "sha256:1f72a99e049e9519827fb045db50c56863835c0b0183f52989f42d7c378b9f92"
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
    installed_root = expected_prefix.resolve()
    sys.path.insert(0, str(installed_root))

    import data_contracts
    import data_contracts.canonical as canonical_module
    import data_contracts.coverage as coverage_module
    import data_contracts.source_capability as capability_module
    from ingestion.jquants import acquisition_collection as acquisition_module
    import ingestion.runtime_authority as runtime_authority_module
    import storage.coverage_transition as coverage_transition_module
    import storage.receipt_crypto as receipt_crypto_module
    import storage.receipt_policy as receipt_policy_module
    import storage.verified_receipt as verified_receipt_module
    from data_contracts.coverage import coverage_contract_for
    from data_contracts.canonical import all_canonical_datasets
    from data_contracts.source_capability import (
        all_source_capability_contracts,
        derive_collection_coverage_v3,
        specs_dir,
    )

    package_root = Path(data_contracts.__file__).resolve().parent
    capability_module_path = Path(capability_module.__file__).resolve()
    coverage_module_path = Path(coverage_module.__file__).resolve()
    acquisition_module_path = Path(acquisition_module.__file__).resolve()
    runtime_authority_module_path = Path(runtime_authority_module.__file__).resolve()
    coverage_transition_module_path = Path(
        coverage_transition_module.__file__
    ).resolve()
    receipt_crypto_module_path = Path(receipt_crypto_module.__file__).resolve()
    verified_receipt_module_path = Path(verified_receipt_module.__file__).resolve()
    receipt_policy_module_path = Path(receipt_policy_module.__file__).resolve()
    authority_dir = specs_dir().resolve()
    registry_path = package_root / REGISTRY_NAME
    coverage_transition_registry_path = (
        coverage_transition_module._PINNED_REGISTRY_PATH.resolve()
    )
    receipt_schema_path = verified_receipt_module._SCHEMA_PATH.resolve()
    canonical_registry_path = canonical_module.CANONICAL_REGISTRY_PATH.resolve()
    for path, label in (
        (package_root, "data_contracts package"),
        (capability_module_path, "SourceCapability module"),
        (coverage_module_path, "Coverage module"),
        (acquisition_module_path, "J-Quants acquisition module"),
        (runtime_authority_module_path, "ingestion runtime authority module"),
        (coverage_transition_module_path, "Coverage transition module"),
        (receipt_crypto_module_path, "receipt crypto module"),
        (verified_receipt_module_path, "verified Receipt module"),
        (receipt_policy_module_path, "receipt policy module"),
        (authority_dir, "SourceCapability authority"),
        (registry_path, "acquisition registry"),
        (coverage_transition_registry_path, "Coverage transition registry"),
        (receipt_schema_path, "signed Receipt claims schema"),
        (canonical_registry_path, "canonical dataset registry"),
    ):
        _require_under(path, installed_root, label=label)
    if authority_dir.parent != package_root:
        raise AssertionError("SourceCapability authority is not package-owned")
    if acquisition_module._SHARED_REGISTRY_PATH.resolve() != registry_path:
        raise AssertionError("J-Quants acquisition import did not bind wheel registry")
    if "qp_paths" in sys.modules:
        raise AssertionError("installed SourceCapability loading consulted qp_paths")
    for module_name, module in tuple(sys.modules.items()):
        if not module_name.startswith(("data_contracts", "ingestion", "storage")):
            continue
        module_file = getattr(module, "__file__", None)
        if module_file is not None:
            _require_under(
                Path(module_file).resolve(),
                installed_root,
                label=f"loaded first-party module {module_name}",
            )
    if coverage_transition_module.CoverageTransitionPublicKeyRegistry.load_pinned(
        expected_environment="production"
    ).provisioned:
        raise AssertionError("Coverage transition authority unexpectedly active")
    receipt_schema = verified_receipt_module._claims_schema()
    if receipt_schema.get("$id") != "specs/receipts/signed_receipt_claims.schema.json":
        raise AssertionError("installed signed Receipt claims schema identity drift")

    canonical_sources = {
        contract.dataset_id: receipt_policy_module.receipt_source_for_canonical_source(
            contract.source
        )
        for contract in all_canonical_datasets()
    }
    governed_ids = sorted(
        contract.dataset_id
        for contract in all_canonical_datasets()
        if contract.governance_tier == "governed"
    )
    if len(canonical_sources) != 31 or len(governed_ids) != 26:
        raise AssertionError("installed canonical routing inventory count drift")
    if {
        dataset
        for dataset, source in canonical_sources.items()
        if source == "jsda"
    } != {
        "jsda_corporate_bond_transactions",
        "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates",
    }:
        raise AssertionError("installed canonical JSDA routing membership drift")
    if canonical_sources.get("equities_trades") != "jquants":
        raise AssertionError("installed addon routing policy drift")
    if not receipt_policy_module.is_recovered_only_digests({"origin": []}):
        raise AssertionError("malformed recovery sentinel did not fail closed")
    if not receipt_policy_module.is_recovered_only_digests({"origin": None}):
        raise AssertionError("null recovery sentinel did not fail closed")
    canonical_source_digest = _canonical_digest(canonical_sources)
    if canonical_source_digest != EXPECTED_CANONICAL_SOURCE_DIGEST:
        raise AssertionError("installed canonical receipt-source digest drift")

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
    runtime_registry = acquisition_module._target_registry()
    if runtime_registry.digest != registry_digest:
        raise AssertionError("J-Quants acquisition runtime registry digest drift")

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
        runtime_route = runtime_registry.routes.get(dataset_id)
        if (
            runtime_route is None
            or runtime_route.source_capability_digest != source_digest
            or runtime_route.coverage_policy_digest != coverage_digest
        ):
            raise AssertionError(
                f"J-Quants acquisition runtime route digest drift: {dataset_id}"
            )
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
        "canonical_source_digest": canonical_source_digest,
        "route_digests": route_digests,
    }


def _run(command: list[str], *, cwd: Path, capture: bool = False) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.CalledProcessError as exc:
        details = "\n".join(
            part.strip()
            for part in (exc.stdout, exc.stderr)
            if isinstance(part, str) and part.strip()
        )
        suffix = f"\n{details[-8000:]}" if details else ""
        raise RuntimeError(f"wheel verification subprocess failed{suffix}") from exc
    return completed.stdout if capture else ""


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
        installed = temporary / "installed-wheel"
        empty_cwd = temporary / "empty-cwd"
        decoy_cwd = temporary / "malicious-decoy-cwd"
        source.mkdir()
        dist.mkdir()
        installed.mkdir()
        empty_cwd.mkdir()
        _copy_tracked_source(source)
        (decoy_cwd / "tests").mkdir(parents=True)
        (decoy_cwd / "specs" / "source_capability").mkdir(parents=True)
        (decoy_cwd / "specs" / "coverage_transition").mkdir(parents=True)
        (decoy_cwd / "specs" / "receipts").mkdir(parents=True)
        (decoy_cwd / "packages" / "data_plane" / "data_contracts" /
         "source_capability_contracts").mkdir(parents=True)
        (decoy_cwd / "pyproject.toml").write_text(
            "[project]\nname='malicious-decoy'\nversion='0'\n",
            encoding="utf-8",
        )
        for decoy in (
            decoy_cwd / "specs" / "source_capability" / "equities_bars_daily.json",
            decoy_cwd / "specs" / "coverage_transition" / "public_keys.json",
            decoy_cwd / "specs" / "receipts" / "signed_receipt_claims.schema.json",
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
            [
                str(uv),
                "pip",
                "install",
                "--quiet",
                "--python",
                str(python),
                "--target",
                str(installed),
                "--no-deps",
                "--no-index",
                str(wheels[0]),
            ],
            cwd=temporary,
        )
        empty_result = _probe_subprocess(
            installed_python=python,
            cwd=empty_cwd,
            expected_prefix=installed,
        )
        decoy_result = _probe_subprocess(
            installed_python=python,
            cwd=decoy_cwd,
            expected_prefix=installed,
        )
        if empty_result != decoy_result:
            raise AssertionError("malicious CWD changed installed authority loading")
        print(
            "Installed-wheel acquisition and contract authorities: "
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
    _verify_wheel(
        uv=Path(os.path.abspath(args.uv)),
        python=Path(os.path.abspath(args.python)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
