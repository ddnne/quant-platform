#!/usr/bin/env python3
"""Thin CLI for inactive bootstrap and strict-gated local authority activation."""

# Compatibility exports remain available while the implementation is split by
# responsibility. Tests and existing operators import these names directly.
# ruff: noqa: F401

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

from scripts.authority_principal_manifest import load_and_validate_manifest
from scripts.finding_ledger_gate import (
    FindingLedgerError,
    require_pinned_finding_ledger_gate,
)
from scripts.local_authority_activation import ActivationStateError
from scripts.local_authority_bootstrap_common import (
    _ACTIONS,
    _ROOT,
    _RUNNABLE_AUTHORITIES,
    BOOTSTRAP_ONLY_ACTIONS,
    LAUNCHD_INSTALL_ROOT,
    LAUNCHD_RENDER_ROOT,
    LAUNCHD_TEMPLATE,
    POSITIVE_ACTIVATION_ACTIONS,
    PROTECTED_ROOT,
    PUBLIC_METADATA_NAME,
    REGISTRY_PROPOSAL_PATH,
    RUN_ROOT,
    RUNTIME_BUNDLE_MANIFEST_PATH,
    RUNTIME_BUNDLES_ROOT,
    SERVICE_GROUP,
    BootstrapError,
    _caller_service_user,
    _deployments,
    _ensure_directory,
    _environments,
    _local_peer_rows,
    _run,
    _safe_file_state,
    _write_exclusive,
    _write_root_owned_file,
    build_plan,
)
from scripts.local_authority_bootstrap_common import (
    _require_human_root as _require_human_root_common,
)
from scripts.local_authority_bootstrap_state import activate_state, audit_state
from scripts.local_authority_provisioning import (
    _dscl_create,
    _dscl_values,
    _ensure_caller_group,
    _ensure_group,
    _ensure_user,
    _generate_or_validate_key_material,
    _key_id,
    _launchd_loaded,
    _load_public_metadata,
    _next_id,
    _public_metadata_document,
    _record_exists,
    _registry_proposal_rows,
    _render_plist,
    _run_key_generation_as_service_user,
    _runtime_config_template,
    _set_exact_caller_group_members,
    _used_ids,
    apply_plan,
    generate_keys,
    install_plists,
    install_runtime_configs,
    load_plists,
    registry_proposals,
    render_plists,
)
from scripts.local_authority_runtime_bundle import (
    _load_runtime_bundle_manifest,
    _protect_runtime_tree,
    _require_root_owned_executable,
    _runtime_python_acquisition_plan,
    _validate_root_python_dependencies,
    install_runtime_bundle,
)


def _require_human_root() -> None:
    """Compatibility facade over the split bootstrap root-presence check."""

    _require_human_root_common()


def _require_positive_activation():
    """Apply the positive gate using this CLI module's injectable boundary."""

    _require_human_root()
    try:
        return require_pinned_finding_ledger_gate()
    except FindingLedgerError as exc:
        raise BootstrapError(
            f"strict finding-ledger release gate rejected apply: {exc}"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=_ACTIONS, default="plan")
    parser.add_argument(
        "--environment",
        choices=("staging", "production", "all"),
        default="all",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "perform the selected mutation; bootstrap-only actions require sudo, "
            "load/activate additionally require the strict all-P0 gate"
        ),
    )
    parser.add_argument(
        "--config-source-root",
        type=Path,
        help=(
            "reviewed runtime configs rooted as <environment>/<authority>.json; "
            "required only for install-runtime-configs --apply"
        ),
    )
    parser.add_argument(
        "--expected-source-sha",
        help="reviewed exact Git SHA required for install-runtime-bundle --apply",
    )
    parser.add_argument(
        "--root-python",
        type=Path,
        help=(
            "root-owned Python 3.11+ interpreter with root-owned "
            "cryptography/jsonschema; required for install-runtime-bundle --apply"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action in {"plan", "audit"} and args.apply:
        print(
            f"{args.action} is read-only and does not accept --apply", file=sys.stderr
        )
        return 2
    try:
        if args.action == "plan":
            result = build_plan(args.environment)
        elif args.action == "audit":
            result = audit_state(args.environment)
        elif args.action == "prepare-users":
            result = (
                apply_plan(args.environment)
                if args.apply
                else build_plan(args.environment)
            )
        elif args.action == "generate-keys":
            result = generate_keys(args.environment, apply=args.apply)
        elif args.action == "install-runtime-configs":
            result = install_runtime_configs(
                args.environment,
                apply=args.apply,
                source_root=args.config_source_root,
            )
        elif args.action == "install-runtime-bundle":
            result = install_runtime_bundle(
                apply=args.apply,
                expected_source_sha=args.expected_source_sha,
                root_python=args.root_python,
            )
        elif args.action == "render-plists":
            result = render_plists(args.environment, apply=args.apply)
        elif args.action == "install-plists":
            result = install_plists(args.environment, apply=args.apply)
        elif args.action == "load-plists":
            result = load_plists(args.environment, apply=args.apply)
        elif args.action == "registry-proposals":
            result = registry_proposals(args.environment, apply=args.apply)
        elif args.action == "activate":
            result = activate_state(args.environment, apply=args.apply)
        else:
            raise BootstrapError("unsupported bootstrap action")
    except (BootstrapError, ActivationStateError, FindingLedgerError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
