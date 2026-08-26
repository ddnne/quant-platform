"""One-observation contract inputs for the Ops Projection renderer.

The projection authority must not hash package files in one observation and
then render policy or inventory from module-import caches populated by another
observation.  ``ProjectionContractSnapshot.capture`` retains every governing
file byte string once and derives all projection-facing contract facts from
those exact bytes.

This is an unsigned renderer input, not a signing or publication capability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"projection contract contains non-finite JSON value {value!r}")


def _decode_object(raw: bytes, *, origin: str) -> dict[str, Any]:
    """Decode one exact UTF-8 JSON object and reject duplicate keys."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError(
                    f"projection contract {origin} contains duplicate key {key!r}"
                )
            document[key] = value
        return document

    try:
        document = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=_reject_nonfinite,
        )
    except UnicodeDecodeError as exc:
        raise ValueError(f"projection contract {origin} is not UTF-8") from exc
    if type(document) is not dict:
        raise ValueError(f"projection contract {origin} must be a JSON object")
    return document


def _read_retained_contract_file(path: Path) -> bytes:
    """Read one contract file exactly once for one snapshot observation."""

    try:
        return path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"projection contract file is unavailable: {path}") from exc


def _digest_retained_files(
    retained_files: Mapping[str, bytes],
    relative_paths: tuple[str, ...],
) -> str:
    digest = hashlib.sha256()
    if not relative_paths:
        raise RuntimeError("projection contract digest has no source files")
    for relative_path in sorted(relative_paths):
        try:
            raw = retained_files[relative_path]
        except KeyError as exc:
            raise RuntimeError(
                f"projection contract snapshot omitted {relative_path}"
            ) from exc
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update(raw)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _policy_digest(contract: Any) -> str:
    raw = json.dumps(
        contract.to_dict(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _freeze_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(row))


@dataclass(frozen=True, slots=True)
class ProjectionContractSnapshot:
    """Immutable projection facts derived from one retained-byte observation."""

    contract_digest: str
    registry_digest: str
    retained_files: Mapping[str, bytes]
    coverage_contracts: tuple[Any, ...]
    source_inventory: tuple[Mapping[str, Any], ...]
    _coverage_by_id: Mapping[str, Any]
    _policy_bindings: Mapping[str, Mapping[str, str]]

    @property
    def coverage_dataset_ids(self) -> tuple[str, ...]:
        return tuple(self._coverage_by_id)

    def coverage_policy_binding(self, dataset_id: str) -> Mapping[str, str]:
        try:
            return self._policy_bindings[dataset_id]
        except KeyError as exc:
            raise KeyError(f"unknown coverage contract: {dataset_id!r}") from exc

    def coverage_policy_set_binding(
        self, dataset_ids: tuple[str, ...] | list[str]
    ) -> Mapping[str, Any]:
        normalized = tuple(sorted(str(item) for item in dataset_ids))
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("coverage policy set requires unique dataset ids")
        rows = [dict(self.coverage_policy_binding(dataset_id)) for dataset_id in normalized]
        raw = json.dumps(
            rows,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        versions = sorted({row["policy_version"] for row in rows})
        effective_version = versions[0] if len(versions) == 1 else "mixed:" + digest
        return MappingProxyType(
            {
                "policy_version": effective_version,
                "policy_digest": digest,
                "datasets": tuple(MappingProxyType(row) for row in rows),
            }
        )

    @classmethod
    def capture(cls, repo_root: Path) -> "ProjectionContractSnapshot":
        """Capture package authority files once, then parse only retained bytes."""

        root = Path(repo_root)
        package = root / "packages" / "data_plane" / "data_contracts"
        storage_package = root / "packages" / "data_plane" / "storage"
        capability_dir = package / "source_capability_contracts"
        capability_paths = tuple(sorted(capability_dir.glob("*.json"), key=str))
        if not capability_paths:
            raise RuntimeError("projection SourceCapability authority is unavailable")

        registry_path = package / "canonical_datasets.json"
        coverage_path = package / "collection_coverage.json"
        contract_paths = (
            coverage_path,
            *capability_paths,
            storage_package
            / "authorities"
            / "receipts"
            / "signed_receipt_claims.schema.json",
            root / "specs" / "ops_projection" / "signed_envelope.schema.json",
        )
        all_paths = (registry_path, *contract_paths)
        retained: dict[str, bytes] = {}
        for path in all_paths:
            try:
                relative_path = path.relative_to(root).as_posix()
            except ValueError as exc:
                raise RuntimeError(
                    "projection contract file escaped the repository authority root"
                ) from exc
            if relative_path in retained:
                raise RuntimeError(
                    f"duplicate projection contract source path: {relative_path}"
                )
            retained[relative_path] = _read_retained_contract_file(path)

        # A concurrent directory membership rotation cannot silently produce a
        # partial capability inventory. File contents are never reopened.
        final_capability_names = tuple(
            path.name for path in sorted(capability_dir.glob("*.json"), key=str)
        )
        if final_capability_names != tuple(path.name for path in capability_paths):
            raise RuntimeError(
                "projection SourceCapability authority changed during capture"
            )

        relative_registry = registry_path.relative_to(root).as_posix()
        relative_contracts = tuple(
            path.relative_to(root).as_posix() for path in contract_paths
        )
        registry_digest = _digest_retained_files(retained, (relative_registry,))
        contract_digest = _digest_retained_files(retained, relative_contracts)

        canonical_document = _decode_object(
            retained[relative_registry], origin=relative_registry
        )
        coverage_relative = coverage_path.relative_to(root).as_posix()
        coverage_document = _decode_object(
            retained[coverage_relative], origin=coverage_relative
        )

        # These parser types validate the retained documents. Their package
        # module caches are deliberately never consulted for projection facts.
        from data_contracts.canonical import CanonicalDatasetContract
        from data_contracts.coverage import CollectionCoverageContract
        from data_contracts.source_capability import (
            derive_collection_coverage_v3,
            parse_source_capability_document,
        )

        if canonical_document.get("schema_version") != 1:
            raise ValueError("canonical dataset registry schema_version must be 1")
        registry_version = canonical_document.get("registry_version")
        if type(registry_version) is not str or not registry_version.strip():
            raise ValueError("canonical dataset registry_version must be non-empty")
        canonical_rows = canonical_document.get("datasets")
        if type(canonical_rows) is not list or not canonical_rows:
            raise ValueError("canonical registry datasets must be a non-empty array")
        canonical_contracts: list[Any] = []
        raw_by_id: dict[str, dict[str, Any]] = {}
        for raw in canonical_rows:
            if type(raw) is not dict:
                raise ValueError("each canonical dataset contract must be an object")
            contract = CanonicalDatasetContract.from_dict(raw)
            if contract.dataset_id in raw_by_id:
                raise ValueError(
                    f"duplicate dataset_id in canonical registry: {contract.dataset_id}"
                )
            canonical_contracts.append(contract)
            raw_by_id[contract.dataset_id] = raw
        governed_ids = {
            contract.dataset_id
            for contract in canonical_contracts
            if contract.governance_tier == "governed"
        }
        if len(governed_ids) != 26 or len(canonical_contracts) < 26:
            raise ValueError(
                "canonical registry must contain exactly 26 governed datasets"
            )

        if coverage_document.get("schema_version") != 2:
            raise ValueError("collection coverage schema_version must be 2")
        root_policy_version = coverage_document.get("policy_version")
        defaults = coverage_document.get("defaults")
        coverage_rows = coverage_document.get("datasets")
        if type(root_policy_version) is not str or not root_policy_version:
            raise ValueError("collection coverage policy_version must be non-empty")
        if type(defaults) is not dict or type(coverage_rows) is not dict:
            raise ValueError("coverage defaults and datasets must be objects")
        if set(coverage_rows) != governed_ids:
            raise ValueError(
                "coverage datasets must exactly match canonical governed membership: "
                f"missing={sorted(governed_ids - set(coverage_rows))}, "
                f"extra={sorted(set(coverage_rows) - governed_ids)}"
            )
        coverage_contracts: list[Any] = []
        coverage_by_id: dict[str, Any] = {}
        for dataset_id, overrides in coverage_rows.items():
            if type(overrides) is not dict:
                raise ValueError(f"coverage contract {dataset_id!r} must be an object")
            contract = CollectionCoverageContract.from_dict(
                dataset_id,
                {**defaults, "policy_version": root_policy_version, **overrides},
            )
            coverage_contracts.append(contract)
            coverage_by_id[dataset_id] = contract

        capabilities: dict[str, Any] = {}
        for path in capability_paths:
            relative_path = path.relative_to(root).as_posix()
            document = _decode_object(retained[relative_path], origin=relative_path)
            for capability in parse_source_capability_document(
                document, origin=relative_path
            ):
                if capability.dataset_id in capabilities:
                    raise ValueError(
                        "duplicate SourceCapabilityContract dataset_id: "
                        f"{capability.dataset_id!r}"
                    )
                capabilities[capability.dataset_id] = capability
        v3_ids = {
            dataset_id
            for dataset_id, contract in coverage_by_id.items()
            if contract.policy_version == "collection-coverage/v3"
        }
        if set(capabilities) != v3_ids:
            raise ValueError(
                "SourceCapability inventory must exactly match Coverage V3 membership: "
                f"missing={sorted(v3_ids - set(capabilities))}, "
                f"extra={sorted(set(capabilities) - v3_ids)}"
            )
        for dataset_id, capability in capabilities.items():
            expected = derive_collection_coverage_v3(capability)
            observed = coverage_by_id[dataset_id]
            drift = {
                field: (getattr(observed, field), value)
                for field, value in expected.items()
                if getattr(observed, field) != value
            }
            if drift:
                raise ValueError(
                    f"Coverage V3/SourceCapability drift for {dataset_id}: {drift}"
                )

        policy_bindings = {
            dataset_id: MappingProxyType(
                {
                    "policy_id": dataset_id,
                    "policy_version": contract.policy_version,
                    "policy_digest": _policy_digest(contract),
                }
            )
            for dataset_id, contract in coverage_by_id.items()
        }
        if any(
            type(binding["policy_version"]) is not str
            or not binding["policy_version"]
            for binding in policy_bindings.values()
        ):
            raise ValueError("coverage policy version is missing")

        inventory: list[Mapping[str, Any]] = []
        for contract in canonical_contracts:
            raw = raw_by_id[contract.dataset_id]
            coverage = coverage_by_id.get(contract.dataset_id)
            capability = capabilities.get(contract.dataset_id)
            sla = dict(raw.get("sla") or {})
            upstream = None
            collection_window = None
            available_at_json = None
            historical_start = raw.get("historical_start")
            expected_frequency = raw.get("expected_frequency") or "unknown"
            coverage_granularity = (
                raw.get("coverage_segment_granularity") or "none"
            )
            research_eligible = False
            if coverage is not None:
                historical_start = coverage.history_target_start
                expected_frequency = coverage.expected_frequency
                coverage_granularity = coverage.segment_granularity
            inventory_status = raw.get(
                "inventory_status",
                "GOVERNED"
                if contract.governance_tier == "governed"
                else "EXPERIMENTAL",
            )
            if capability is None or coverage is None:
                inventory_status = "UNVERIFIED_ENDPOINT"
            if capability is not None:
                upstream = capability.upstream_locator
                collection_window = capability.collection_window.grain
                historical_start = capability.earliest_official_availability
                research_eligible = bool(capability.historical_research_eligible)
                sla.update(
                    {
                        "expected_after": capability.freshness_sla.expected_after,
                        "usable_by": capability.freshness_sla.usable_by,
                        "timezone": capability.freshness_sla.timezone,
                        "freshness_policy": capability.freshness_sla.rule,
                        "official_evidence_url": capability.official_evidence_url,
                    }
                )
                available_at_json = json.dumps(
                    asdict(capability.available_at),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            inventory.append(
                _freeze_row(
                    {
                        "dataset_id": contract.dataset_id,
                        "display_name": contract.display_name,
                        "source": contract.source,
                        "governance_tier": contract.governance_tier,
                        "inventory_status": inventory_status,
                        "upstream_locator": upstream,
                        "collection_window": collection_window,
                        "expected_frequency": expected_frequency,
                        "coverage_segment_granularity": coverage_granularity,
                        "research_eligible": research_eligible,
                        "enabled": bool(raw.get("enabled", True)),
                        "sla": json.dumps(
                            sla, sort_keys=True, separators=(",", ":")
                        ),
                        "historical_start": historical_start,
                        "available_at_json": available_at_json,
                    }
                )
            )

        return cls(
            contract_digest=contract_digest,
            registry_digest=registry_digest,
            retained_files=MappingProxyType(dict(retained)),
            coverage_contracts=tuple(coverage_contracts),
            source_inventory=tuple(inventory),
            _coverage_by_id=MappingProxyType(dict(coverage_by_id)),
            _policy_bindings=MappingProxyType(dict(policy_bindings)),
        )


__all__ = ["ProjectionContractSnapshot"]
