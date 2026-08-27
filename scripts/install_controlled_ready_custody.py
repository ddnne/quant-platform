#!/usr/bin/env python3
"""Install one signed READY generation into root-owned Controlled custody.

This command never creates users, groups, directories, keys, activation state,
or launchd jobs.  Those resources must already exist under the reviewed local
authority bootstrap.  The command only performs the create-only immutable
copy and returns the exact manifest identity for a later root-owned activation
document.
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
from pathlib import Path
from typing import Any

from execution.controlled_ready_custody_v2 import (
    ControlledReadyCustodyV2Error,
    install_controlled_ready_custody_v2,
    read_root_owned_controlled_ready_input_v2,
)
from scripts.local_authority_bootstrap_common import (
    BootstrapError,
    _deployments,
    load_and_validate_manifest,
    require_controlled_custody_reader_group,
)


class ControlledReadyInstallCommandError(RuntimeError):
    """The administrator-facing install command failed closed."""


def _service_account(
    manifest: dict[str, Any], *, authority_id: str, environment: str
) -> pwd.struct_passwd:
    try:
        username = manifest["principals"][authority_id]["deployments"][environment][
            "service_user"
        ]
        account = pwd.getpwnam(username)
    except (KeyError, TypeError) as exc:
        raise ControlledReadyInstallCommandError(
            f"{authority_id} service identity is not declared"
        ) from exc
    if (
        account.pw_uid <= 0
        or account.pw_gid <= 0
        or account.pw_dir != "/var/empty"
        or account.pw_shell != "/usr/bin/false"
    ):
        raise ControlledReadyInstallCommandError(
            f"{authority_id} service identity is not a disabled dedicated user"
        )
    return account


def _controlled_reader_group(
    *,
    environment: str,
    ready: pwd.struct_passwd,
    projection: pwd.struct_passwd,
    controlled: pwd.struct_passwd,
) -> grp.struct_group:
    """Resolve the Controlled-only custody capability group."""

    rows = [
        row
        for row in _deployments(environment)
        if row["authority_id"] == "controlled_execution"
    ]
    if (
        len(rows) != 1
        or rows[0].get("environment") != environment
        or rows[0].get("service_user") != controlled.pw_name
        or type(rows[0].get("caller_group")) is not str
        or type(rows[0].get("custody_reader_group")) is not str
    ):
        raise ControlledReadyInstallCommandError(
            "Controlled custody reader group is not uniquely declared"
        )
    try:
        service_group, _caller_group, reader_group = (
            require_controlled_custody_reader_group(
                row=rows[0],
                service_account=controlled,
            )
        )
    except BootstrapError as exc:
        raise ControlledReadyInstallCommandError(
            "Controlled-only custody reader group is not safely provisioned"
        ) from exc
    accounts = (ready, projection, controlled)
    if (
        type(service_group.gr_gid) is not int
        or service_group.gr_gid <= 0
        or any(account.pw_gid != service_group.gr_gid for account in accounts)
    ):
        raise ControlledReadyInstallCommandError(
            "authority service primary groups drift from the shared service group"
        )
    if len({account.pw_uid for account in accounts}) != len(accounts):
        raise ControlledReadyInstallCommandError(
            "READY, Ops Projection, and Controlled service principals are not distinct"
        )
    return reader_group


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="create-only READY to Controlled custody install"
    )
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--ready-response-file", type=Path, required=True)
    parser.add_argument("--ready-snapshot-root", type=Path, required=True)
    parser.add_argument("--signed-projection-file", type=Path, required=True)
    parser.add_argument("--controlled-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if os.geteuid() != 0:
        raise ControlledReadyInstallCommandError(
            "run only after an administrator has explicitly authorized sudo"
        )
    manifest = load_and_validate_manifest()
    ready = _service_account(
        manifest,
        authority_id="ready",
        environment=arguments.environment,
    )
    projection = _service_account(
        manifest,
        authority_id="ops_projection",
        environment=arguments.environment,
    )
    controlled = _service_account(
        manifest,
        authority_id="controlled_execution",
        environment=arguments.environment,
    )
    reader_group = _controlled_reader_group(
        environment=arguments.environment,
        ready=ready,
        projection=projection,
        controlled=controlled,
    )
    try:
        ready_response = read_root_owned_controlled_ready_input_v2(
            arguments.ready_response_file
        )
    except (ControlledReadyCustodyV2Error, OSError) as exc:
        raise ControlledReadyInstallCommandError(
            "READY response must be a bounded root-owned protected regular file"
        ) from exc
    try:
        installed = install_controlled_ready_custody_v2(
            environment=arguments.environment,
            ready_response=ready_response,
            ready_snapshot_root=arguments.ready_snapshot_root,
            signed_projection_path=arguments.signed_projection_file,
            controlled_root=arguments.controlled_root,
            expected_ready_uid=ready.pw_uid,
            expected_projection_uid=projection.pw_uid,
            controlled_reader_gid=reader_group.gr_gid,
        )
    except (ControlledReadyCustodyV2Error, OSError) as exc:
        raise ControlledReadyInstallCommandError(
            "READY-to-Controlled custody install rejected"
        ) from exc
    print(
        json.dumps(
            {
                "status": "INSTALLED_INACTIVE",
                "environment": arguments.environment,
                "manifest_path": str(installed.manifest_path),
                "manifest_digest": installed.manifest_digest,
                "snapshot_id": installed.snapshot_id,
                "snapshot_digest": installed.snapshot_digest,
                "projection_digest": installed.projection_digest,
                "controlled_reader_group": reader_group.gr_name,
                "controlled_reader_gid": reader_group.gr_gid,
                "ready_authority_resource_digest": (
                    installed.ready_authority_resource_digest
                ),
                "research_execution_started": False,
                "activation_modified": False,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
