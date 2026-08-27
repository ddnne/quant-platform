"""Adversarial tests for the root-owned READY-to-Controlled install."""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import execution.controlled_ready_custody_v2 as custody
import execution.controlled_execution_activation_v2 as activation
from execution.exact_four_codec import _canonical_bytes
from execution.exact_four_codec import ExactFourAuthorityPending
from scripts import install_controlled_ready_custody as install_command


_CONTROLLED_GENERATED_UID = "11111111-2222-3333-4444-555555555555"


def _patch_controlled_reader_directory_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    service_uid: int = 503,
) -> None:
    from scripts import local_authority_bootstrap_common as bootstrap_common

    account = _service_account("qp_controlled", service_uid, 20)
    monkeypatch.setattr(bootstrap_common.pwd, "getpwall", lambda: [account])
    attributes = {
        ("Users", "qp_controlled", "GeneratedUID"): (
            _CONTROLLED_GENERATED_UID,
        ),
        ("Users", "qp_controlled", "UniqueID"): (str(service_uid),),
        (
            "Groups",
            "qp_staging_controlled_execution_readers",
            "GroupMembership",
        ): ("qp_controlled",),
        (
            "Groups",
            "qp_staging_controlled_execution_readers",
            "GroupMembers",
        ): (_CONTROLLED_GENERATED_UID,),
        (
            "Groups",
            "qp_staging_controlled_execution_readers",
            "NestedGroups",
        ): (),
    }
    monkeypatch.setattr(
        bootstrap_common,
        "_directory_service_attribute_values",
        lambda kind, name, attribute, **_kwargs: attributes[
            (kind, name, attribute)
        ],
    )


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], SimpleNamespace]:
    ready_root = tmp_path / "ready"
    projection_root = tmp_path / "projection"
    controlled_root = tmp_path / "controlled-root"
    for path, mode in (
        (ready_root, 0o700),
        (projection_root, 0o700),
        (controlled_root, 0o750),
    ):
        path.mkdir(mode=mode)
        path.chmod(mode)
    snapshot_id = "sha256:" + "1" * 64
    ready_manifest_digest = "sha256:" + "2" * 64
    snapshot = ready_root / ("sha256_" + "1" * 64 + ".sqlite")
    connection = sqlite3.connect(snapshot)
    connection.execute(
        "CREATE TABLE local_snapshot_manifests ("
        "snapshot_id TEXT PRIMARY KEY,format TEXT,manifest_json TEXT)"
    )
    embedded = {
        "format": "research-snapshot-manifest/v2",
        "state": "READY",
        "snapshot_id": snapshot_id,
        "ready_manifest": {
            "snapshot_id": snapshot_id,
            "manifest_digest": ready_manifest_digest,
        },
    }
    connection.execute(
        "INSERT INTO local_snapshot_manifests VALUES (?,?,?)",
        (
            snapshot_id,
            "research-snapshot-manifest/v2",
            _canonical_bytes(embedded).decode("utf-8"),
        ),
    )
    connection.commit()
    connection.close()
    snapshot.chmod(0o400)
    projection = projection_root / "projection.json"
    projection.write_bytes(b'{"signed":"projection"}')
    projection.chmod(0o400)
    projection_digest = _digest(projection.read_bytes())
    attestation = _canonical_bytes(
        {"signed_projection_document_digest": projection_digest}
    )
    response = _canonical_bytes(
        {
            "result": {
                "attestation_base64": base64.b64encode(attestation).decode(
                    "ascii"
                )
            }
        }
    )
    subject = SimpleNamespace(
        ready_authority_instance_id="ready-authority/staging/v1",
        ready_authority_resource_digest="sha256:" + "3" * 64,
        readiness_attestation_id="sha256:" + "4" * 64,
        snapshot_id=snapshot_id,
        ready_manifest_digest=ready_manifest_digest,
        immutable_snapshot_digest=_digest(snapshot.read_bytes()),
        exact_four_binding_digest="sha256:" + "5" * 64,
        controlled_pilot_policy_digest="sha256:" + "6" * 64,
    )
    evidence = SimpleNamespace(
        subject=subject,
        response_digest=_digest(response),
    )
    monkeypatch.setattr(
        custody,
        "verify_ready_authority_response_v2",
        lambda raw, *, expected_environment: evidence,
    )
    import research.ready_manifest as ready_manifest

    monkeypatch.setattr(
        ready_manifest,
        "load_exact_four_pilot_ready_binding",
        lambda: SimpleNamespace(required_datasets=("equities_bars_daily",)),
    )
    monkeypatch.setattr(
        ready_manifest,
        "_verified_projection_evidence",
        lambda raw, datasets, *, expected_environment: SimpleNamespace(
            signed_document_digest=_digest(raw)
        ),
    )
    arguments: dict[str, object] = {
        "environment": "staging",
        "ready_response": response,
        "ready_snapshot_root": ready_root.resolve(),
        "signed_projection_path": projection.resolve(),
        "controlled_root": controlled_root.resolve(),
        "expected_ready_uid": os.geteuid(),
        "expected_projection_uid": os.geteuid(),
        "controlled_owner_uid": os.geteuid(),
        "controlled_reader_gid": os.getegid(),
    }
    return arguments, evidence


def _install(arguments: dict[str, object]) -> custody.InstalledControlledReadyCustodyV2:
    return custody._install_controlled_ready_custody_v2(**arguments)  # type: ignore[arg-type]


def test_install_is_content_addressed_create_only_and_retry_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    first = _install(arguments)
    before = {
        path: (path.read_bytes(), path.stat().st_ino)
        for path in (first.snapshot_path, first.projection_path, first.manifest_path)
    }
    second = _install(arguments)
    assert second == first
    for path, (raw, inode) in before.items():
        observed = path.stat()
        assert path.read_bytes() == raw
        assert observed.st_ino == inode
        assert observed.st_uid == os.geteuid()
        assert observed.st_gid == os.getegid()
        assert observed.st_mode & 0o777 == 0o440
        assert observed.st_nlink == 1
    assert not list(Path(arguments["controlled_root"]).glob("*.partial"))


def test_partial_install_has_no_commit_manifest_and_retry_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    original = custody._write_create_only_bytes

    def fail_manifest(*args: object, **kwargs: object) -> None:
        raise OSError("simulated manifest fsync failure")

    monkeypatch.setattr(custody, "_write_create_only_bytes", fail_manifest)
    with pytest.raises(OSError, match="simulated"):
        _install(arguments)
    root = Path(arguments["controlled_root"])
    assert list(root.glob("snapshot-*.sqlite3"))
    assert list(root.glob("projection-*.json"))
    assert list(root.glob("custody-*.json")) == []
    assert list(root.glob("*.partial")) == []
    monkeypatch.setattr(custody, "_write_create_only_bytes", original)
    installed = _install(arguments)
    assert installed.manifest_path.is_file()


def test_crash_between_create_only_link_and_partial_unlink_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    original_unlink = custody.os.unlink
    interrupted = False

    class SimulatedProcessCrash(BaseException):
        pass

    def crash_after_link(
        name: str | bytes | Path,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal interrupted
        if not interrupted and str(name).endswith(".partial"):
            interrupted = True
            raise SimulatedProcessCrash
        original_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(custody.os, "unlink", crash_after_link)
    with pytest.raises(SimulatedProcessCrash):
        _install(arguments)
    root = Path(arguments["controlled_root"])
    committed = list(root.glob("snapshot-*.sqlite3"))
    partials = list(root.glob(".*.partial"))
    assert len(committed) == 1
    assert len(partials) == 1
    assert committed[0].stat().st_ino == partials[0].stat().st_ino
    assert committed[0].stat().st_nlink == 2
    assert list(root.glob("custody-*.json")) == []

    monkeypatch.setattr(custody.os, "unlink", original_unlink)
    installed = _install(arguments)
    assert installed.manifest_path.is_file()
    assert installed.snapshot_path.stat().st_nlink == 1
    assert list(root.glob(".*.partial")) == []


def test_source_path_swap_cannot_commit_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    snapshot = Path(arguments["ready_snapshot_root"]) / (
        "sha256_" + "1" * 64 + ".sqlite"
    )
    displaced = snapshot.with_name("displaced.sqlite")
    original = custody._copy_fd_to_create_only_file
    swapped = False

    def swap_then_copy(*args: object, **kwargs: object) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            snapshot.rename(displaced)
            snapshot.write_bytes(b"attacker replacement")
            snapshot.chmod(0o400)
        original(*args, **kwargs)

    monkeypatch.setattr(custody, "_copy_fd_to_create_only_file", swap_then_copy)
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="changed during custody copy",
    ):
        _install(arguments)
    root = Path(arguments["controlled_root"])
    assert list(root.glob("custody-*.json")) == []


def test_pinned_source_directories_survive_ancestor_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, evidence = _fixture(tmp_path, monkeypatch)
    ready_root = Path(arguments["ready_snapshot_root"])
    projection_path = Path(arguments["signed_projection_path"])
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    ready_fd = os.open(ready_root, directory_flags)
    projection_fd = os.open(projection_path.parent, directory_flags)
    try:
        moved_ready = ready_root.with_name("pinned-ready")
        moved_projection = projection_path.parent.with_name("pinned-projection")
        ready_root.rename(moved_ready)
        projection_path.parent.rename(moved_projection)
        ready_root.mkdir(mode=0o700)
        projection_path.parent.mkdir(mode=0o700)
        replacement_snapshot = ready_root / (
            "sha256_" + "1" * 64 + ".sqlite"
        )
        replacement_snapshot.write_bytes(b"attacker snapshot")
        replacement_snapshot.chmod(0o400)
        replacement_projection = projection_path.parent / projection_path.name
        replacement_projection.write_bytes(b'{"signed":"attacker"}')
        replacement_projection.chmod(0o400)

        installed = custody._install_controlled_ready_custody_v2(
            **arguments,  # type: ignore[arg-type]
            ready_snapshot_root_fd=ready_fd,
            signed_projection_parent_fd=projection_fd,
        )
    finally:
        os.close(projection_fd)
        os.close(ready_fd)
    assert installed.snapshot_digest == evidence.subject.immutable_snapshot_digest
    assert installed.projection_digest == _digest(b'{"signed":"projection"}')


def test_existing_conflicting_content_address_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, evidence = _fixture(tmp_path, monkeypatch)
    target = Path(arguments["controlled_root"]) / (
        "snapshot-" + evidence.subject.immutable_snapshot_digest[7:] + ".sqlite3"
    )
    target.write_bytes(b"conflicting preexisting file")
    target.chmod(0o440)
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="differs",
    ):
        _install(arguments)
    assert list(Path(arguments["controlled_root"]).glob("custody-*.json")) == []


def test_loader_reverifies_manifest_response_and_both_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    installed = _install(arguments)
    monkeypatch.setattr(
        custody,
        "read_pinned_authority_file_v2",
        lambda path, **_kwargs: path.read_bytes(),
    )
    loaded = custody.load_controlled_ready_custody_v2(
        installed.manifest_path,
        expected_environment="staging",
        expected_owner_uid=os.geteuid(),
        expected_reader_gid=os.getegid(),
    )
    assert loaded == installed
    installed.projection_path.chmod(0o640)
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="not one protected immutable regular file|identity or content differs",
    ):
        custody.load_controlled_ready_custody_v2(
            installed.manifest_path,
            expected_environment="staging",
            expected_owner_uid=os.geteuid(),
            expected_reader_gid=os.getegid(),
        )


def test_loader_replays_current_projection_verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    installed = _install(arguments)
    monkeypatch.setattr(
        custody,
        "read_pinned_authority_file_v2",
        lambda path, **_kwargs: path.read_bytes(),
    )
    import research.ready_manifest as ready_manifest

    def revoked_projection(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("projection signer is no longer authorized")

    monkeypatch.setattr(
        ready_manifest,
        "_verified_projection_evidence",
        revoked_projection,
    )
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="current verification",
    ):
        custody.load_controlled_ready_custody_v2(
            installed.manifest_path,
            expected_environment="staging",
            expected_owner_uid=os.geteuid(),
            expected_reader_gid=os.getegid(),
        )


def test_install_rejects_projection_not_bound_by_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    attestation = _canonical_bytes(
        {"signed_projection_document_digest": "sha256:" + "9" * 64}
    )
    arguments["ready_response"] = _canonical_bytes(
        {
            "result": {
                "attestation_base64": base64.b64encode(attestation).decode(
                    "ascii"
                )
            }
        }
    )
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="differ from READY authority evidence",
    ):
        _install(arguments)
    assert not list(Path(arguments["controlled_root"]).glob("custody-*.json"))


@pytest.mark.parametrize(
    "ready_response",
    (bytearray(b"{}"), b"", b"x" * (custody._MAX_READY_RESPONSE_BYTES + 1)),
)
def test_internal_install_rejects_unbounded_or_nonexact_response_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ready_response: object,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    arguments["ready_response"] = ready_response
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="bounded exact non-empty bytes",
    ):
        _install(arguments)


def test_public_install_bounds_response_before_path_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(custody.os, "geteuid", lambda: 0)
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="bounded exact non-empty bytes",
    ):
        custody.install_controlled_ready_custody_v2(
            environment="staging",
            ready_response=bytearray(b"{}"),  # type: ignore[arg-type]
            ready_snapshot_root=Path("/not-inspected"),
            signed_projection_path=Path("/not-inspected/projection.json"),
            controlled_root=Path("/not-inspected"),
            expected_ready_uid=501,
            expected_projection_uid=502,
            controlled_reader_gid=503,
        )


def test_manifest_bound_includes_ready_response_base64_overhead() -> None:
    encoded_bound = ((custody._MAX_READY_RESPONSE_BYTES + 2) // 3) * 4
    assert custody._MAX_MANIFEST_BYTES >= encoded_bound + 64 * 1024


def test_embedded_ready_manifest_is_bounded_before_json_decode(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "oversized.sqlite"
    connection = sqlite3.connect(snapshot)
    connection.execute(
        "CREATE TABLE local_snapshot_manifests ("
        "snapshot_id TEXT PRIMARY KEY,format TEXT,manifest_json TEXT)"
    )
    snapshot_id = "sha256:" + "1" * 64
    connection.execute(
        "INSERT INTO local_snapshot_manifests VALUES (?,?,?)",
        (
            snapshot_id,
            "research-snapshot-manifest/v2",
            "x" * (custody._MAX_EMBEDDED_READY_MANIFEST_BYTES + 1),
        ),
    )
    connection.commit()
    connection.close()
    descriptor = os.open(snapshot, os.O_RDONLY)
    try:
        with pytest.raises(
            custody.ControlledReadyCustodyV2Error,
            match="metadata is invalid",
        ):
            custody._verify_embedded_ready_manifest(
                descriptor,
                snapshot_id=snapshot_id,
                expected_ready_manifest_digest="sha256:" + "2" * 64,
                deadline_monotonic=time.monotonic() + 60,
            )
    finally:
        os.close(descriptor)


def test_copy_capacity_fails_closed_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    monkeypatch.setattr(
        custody.os,
        "fstatvfs",
        lambda _fd: SimpleNamespace(
            f_frsize=4096,
            f_bsize=4096,
            f_bavail=1,
        ),
    )
    try:
        with pytest.raises(
            custody.ControlledReadyCustodyV2Error,
            match="insufficient free space",
        ):
            custody._require_copy_capacity(root_fd, (("snapshot.sqlite3", 1),))
    finally:
        os.close(root_fd)
    assert not list(tmp_path.glob("snapshot.sqlite3"))


def test_internal_install_rejects_root_reader_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    arguments["controlled_reader_gid"] = 0
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="must not be the root group",
    ):
        _install(arguments)


def test_public_installer_cannot_downgrade_root_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arguments, _evidence = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(custody.os, "geteuid", lambda: 501)
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="human-authorized root",
    ):
        custody.install_controlled_ready_custody_v2(
            environment="staging",
            ready_response=arguments["ready_response"],  # type: ignore[arg-type]
            ready_snapshot_root=arguments["ready_snapshot_root"],  # type: ignore[arg-type]
            signed_projection_path=arguments["signed_projection_path"],  # type: ignore[arg-type]
            controlled_root=arguments["controlled_root"],  # type: ignore[arg-type]
            expected_ready_uid=501,
            expected_projection_uid=501,
            controlled_reader_gid=20,
        )


def _service_account(name: str, uid: int, gid: int) -> SimpleNamespace:
    return SimpleNamespace(
        pw_name=name,
        pw_uid=uid,
        pw_gid=gid,
        pw_dir="/var/empty",
        pw_shell="/usr/bin/false",
    )


def test_install_command_uses_exact_controlled_custody_reader_group(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_controlled_reader_directory_service(monkeypatch)
    service_gid = 20
    accounts = {
        "qp_ready": _service_account("qp_ready", 501, service_gid),
        "qp_projection": _service_account("qp_projection", 502, service_gid),
        "qp_controlled": _service_account("qp_controlled", 503, service_gid),
    }
    manifest = {
        "principals": {
            "ready": {"deployments": {"staging": {"service_user": "qp_ready"}}},
            "ops_projection": {
                "deployments": {"staging": {"service_user": "qp_projection"}}
            },
            "controlled_execution": {
                "deployments": {"staging": {"service_user": "qp_controlled"}}
            },
        }
    }
    groups = {
        "quant_platform_authorities": SimpleNamespace(
            gr_name="quant_platform_authorities",
            gr_gid=service_gid,
            gr_mem=[],
        ),
        "qp_staging_controlled_execution_callers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_callers",
            gr_gid=30,
            gr_mem=["qp_controlled", "qp_trader"],
        ),
        "qp_staging_controlled_execution_readers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_readers",
            gr_gid=40,
            gr_mem=["qp_controlled"],
        ),
    }
    monkeypatch.setattr(install_command.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        install_command,
        "load_and_validate_manifest",
        lambda: manifest,
    )
    monkeypatch.setattr(
        install_command,
        "_deployments",
        lambda environment: [
            {
                "environment": environment,
                "authority_id": "controlled_execution",
                "service_user": "qp_controlled",
                "caller_group": "qp_staging_controlled_execution_callers",
                "custody_reader_group": (
                    "qp_staging_controlled_execution_readers"
                ),
            }
        ],
    )
    monkeypatch.setattr(
        install_command.pwd,
        "getpwnam",
        lambda name: accounts[name],
    )
    monkeypatch.setattr(
        install_command.grp,
        "getgrnam",
        lambda name: groups[name],
    )
    monkeypatch.setattr(
        install_command.grp,
        "getgrgid",
        lambda gid: next(group for group in groups.values() if group.gr_gid == gid),
    )
    monkeypatch.setattr(
        install_command,
        "read_root_owned_controlled_ready_input_v2",
        lambda _path: b"verified-ready-response",
    )
    observed: dict[str, object] = {}

    def install(**kwargs: object) -> SimpleNamespace:
        observed.update(kwargs)
        return SimpleNamespace(
            manifest_path=Path("/protected/custody.json"),
            manifest_digest="sha256:" + "1" * 64,
            snapshot_id="sha256:" + "2" * 64,
            snapshot_digest="sha256:" + "3" * 64,
            projection_digest="sha256:" + "4" * 64,
            ready_authority_resource_digest="sha256:" + "5" * 64,
        )

    monkeypatch.setattr(
        install_command,
        "install_controlled_ready_custody_v2",
        install,
    )
    assert install_command.main(
        [
            "--environment",
            "staging",
            "--ready-response-file",
            "/protected/ready.json",
            "--ready-snapshot-root",
            "/protected/ready",
            "--signed-projection-file",
            "/protected/projection.json",
            "--controlled-root",
            "/protected/controlled",
        ]
    ) == 0
    assert observed["controlled_reader_gid"] == 40
    output = capsys.readouterr().out
    assert '"controlled_reader_gid":40' in output
    assert (
        '"controlled_reader_group":"qp_staging_controlled_execution_readers"'
        in output
    )


def test_install_command_rejects_shared_service_group_as_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounts = (
        _service_account("qp_ready", 501, 20),
        _service_account("qp_projection", 502, 20),
        _service_account("qp_controlled", 503, 20),
    )
    monkeypatch.setattr(
        install_command,
        "_deployments",
        lambda environment: [
            {
                "environment": environment,
                "authority_id": "controlled_execution",
                "service_user": "qp_controlled",
                "caller_group": "qp_staging_controlled_execution_callers",
                "custody_reader_group": (
                    "qp_staging_controlled_execution_readers"
                ),
            }
        ],
    )
    groups = {
        "quant_platform_authorities": SimpleNamespace(
            gr_name="quant_platform_authorities", gr_gid=20, gr_mem=[]
        ),
        "qp_staging_controlled_execution_callers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_callers",
            gr_gid=30,
            gr_mem=["qp_controlled", "qp_trader"],
        ),
        "qp_staging_controlled_execution_readers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_readers",
            gr_gid=20,
            gr_mem=["qp_controlled"],
        ),
    }
    monkeypatch.setattr(
        install_command.grp,
        "getgrnam",
        lambda name: groups[name],
    )
    with pytest.raises(
        install_command.ControlledReadyInstallCommandError,
        match="safely provisioned",
    ):
        install_command._controlled_reader_group(
            environment="staging",
            ready=accounts[0],  # type: ignore[arg-type]
            projection=accounts[1],  # type: ignore[arg-type]
            controlled=accounts[2],  # type: ignore[arg-type]
        )


def test_install_command_rejects_reused_authority_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_controlled_reader_directory_service(monkeypatch)
    accounts = (
        _service_account("qp_ready", 501, 20),
        _service_account("qp_projection", 501, 20),
        _service_account("qp_controlled", 503, 20),
    )
    monkeypatch.setattr(
        install_command,
        "_deployments",
        lambda environment: [
            {
                "environment": environment,
                "authority_id": "controlled_execution",
                "service_user": "qp_controlled",
                "caller_group": "qp_staging_controlled_execution_callers",
                "custody_reader_group": (
                    "qp_staging_controlled_execution_readers"
                ),
            }
        ],
    )
    groups = {
        "quant_platform_authorities": SimpleNamespace(
            gr_name="quant_platform_authorities", gr_gid=20, gr_mem=[]
        ),
        "qp_staging_controlled_execution_callers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_callers",
            gr_gid=30,
            gr_mem=["qp_controlled", "qp_trader"],
        ),
        "qp_staging_controlled_execution_readers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_readers",
            gr_gid=40,
            gr_mem=["qp_controlled"],
        ),
    }
    monkeypatch.setattr(
        install_command.grp,
        "getgrnam",
        lambda name: groups[name],
    )
    monkeypatch.setattr(
        install_command.grp,
        "getgrgid",
        lambda gid: next(group for group in groups.values() if group.gr_gid == gid),
    )
    with pytest.raises(
        install_command.ControlledReadyInstallCommandError,
        match="principals are not distinct",
    ):
        install_command._controlled_reader_group(
            environment="staging",
            ready=accounts[0],  # type: ignore[arg-type]
            projection=accounts[1],  # type: ignore[arg-type]
            controlled=accounts[2],  # type: ignore[arg-type]
        )


def test_install_command_rejects_trader_in_custody_reader_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounts = (
        _service_account("qp_ready", 501, 20),
        _service_account("qp_projection", 502, 20),
        _service_account("qp_controlled", 503, 20),
    )
    monkeypatch.setattr(
        install_command,
        "_deployments",
        lambda environment: [
            {
                "environment": environment,
                "authority_id": "controlled_execution",
                "service_user": "qp_controlled",
                "caller_group": "qp_staging_controlled_execution_callers",
                "custody_reader_group": (
                    "qp_staging_controlled_execution_readers"
                ),
            }
        ],
    )
    groups = {
        "quant_platform_authorities": SimpleNamespace(
            gr_name="quant_platform_authorities", gr_gid=20, gr_mem=[]
        ),
        "qp_staging_controlled_execution_callers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_callers",
            gr_gid=30,
            gr_mem=["qp_controlled", "qp_trader"],
        ),
        "qp_staging_controlled_execution_readers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_readers",
            gr_gid=40,
            gr_mem=["qp_controlled", "qp_trader"],
        ),
    }
    monkeypatch.setattr(install_command.grp, "getgrnam", lambda name: groups[name])
    with pytest.raises(
        install_command.ControlledReadyInstallCommandError,
        match="safely provisioned",
    ):
        install_command._controlled_reader_group(
            environment="staging",
            ready=accounts[0],  # type: ignore[arg-type]
            projection=accounts[1],  # type: ignore[arg-type]
            controlled=accounts[2],  # type: ignore[arg-type]
        )


def test_pinned_install_input_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "ready-response.fifo"
    os.mkfifo(fifo, 0o400)
    started = time.monotonic()
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="immutable regular file",
    ):
        custody._require_pinned_source(
            fifo.resolve(),
            expected_uid=os.geteuid(),
            maximum_bytes=1024,
            label="READY response",
        )
    assert time.monotonic() - started < 1.0


def test_pinned_install_input_rejects_symlink_and_oversize(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    target.chmod(0o400)
    link = tmp_path / "response.json"
    link.symlink_to(target)
    with pytest.raises(custody.ControlledReadyCustodyV2Error, match="opened"):
        custody._require_pinned_source(
            link.absolute(),
            expected_uid=os.geteuid(),
            maximum_bytes=1024,
            label="READY response",
        )
    large = tmp_path / "large.json"
    large.write_bytes(b"x" * 1025)
    large.chmod(0o400)
    with pytest.raises(
        custody.ControlledReadyCustodyV2Error,
        match="immutable regular file",
    ):
        custody._require_pinned_source(
            large.resolve(),
            expected_uid=os.geteuid(),
            maximum_bytes=1024,
            label="READY response",
        )


def _activation_document() -> dict[str, object]:
    return {
        "format": "exact-four-controlled-execution-activation/v3",
        "environment": "staging",
        "service_uid": os.geteuid(),
        "trader_uid": os.geteuid() + 1,
        "store_path": "/protected/controlled.sqlite3",
        "signer_key_id": "controlled-test-v1",
        "private_key_path": "/protected/controlled.key",
        "budget_id": "controlled-test-budget",
        "budget_ledger_path": "/protected/budget.sqlite3",
        "ready_custody_manifest_path": "/protected/custody.json",
        "ready_custody_manifest_digest": "sha256:" + "7" * 64,
        "controlled_reader_gid": os.getegid(),
        "provider_socket_path": "/protected/provider.sock",
        "provider_uid": os.geteuid() + 2,
        "provider_timeout_seconds": 30,
        "protected_store_observed": True,
        "protected_signing_key_observed": True,
        "rp_registry": {},
        "credential_registry": {},
    }


def test_activation_v3_rejects_independent_snapshot_projection_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _activation_document()
    document["format"] = "exact-four-controlled-execution-activation/v2"
    document["immutable_snapshot_path"] = "/attacker/snapshot.sqlite3"
    document["signed_projection_path"] = "/attacker/projection.json"
    monkeypatch.setattr(
        activation,
        "read_pinned_authority_file_v2",
        lambda *_args, **_kwargs: _canonical_bytes(document),
    )
    with pytest.raises(ExactFourAuthorityPending, match="fields or format"):
        activation._load_root_owned_activation()


def test_activation_loader_rechecks_canonical_reader_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _activation_document()
    document["service_uid"] = 501
    document["controlled_reader_gid"] = 30
    monkeypatch.setattr(
        activation,
        "read_pinned_authority_file_v2",
        lambda *_args, **_kwargs: _canonical_bytes(document),
    )
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        activation,
        "_require_controlled_reader_group_v2",
        lambda **kwargs: observed.update(kwargs),
    )
    assert activation._load_root_owned_activation() == document
    assert observed == {
        "environment": "staging",
        "service_uid": 501,
        "claimed_gid": 30,
    }


def test_runtime_requires_exact_custody_manifest_before_opening_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _activation_document()
    monkeypatch.setattr(activation, "_load_root_owned_activation", lambda: document)
    monkeypatch.setattr(
        activation,
        "_require_controlled_reader_group_v2",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        activation,
        "load_controlled_ready_custody_v2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            custody.ControlledReadyCustodyV2Error("absent")
        ),
    )
    with pytest.raises(ExactFourAuthorityPending, match="custody transition"):
        activation._load_live_controlled_execution_runtime_v2()


def test_activation_binds_reader_gid_to_controlled_only_supplementary_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import local_authority_bootstrap_common as bootstrap_common

    _patch_controlled_reader_directory_service(monkeypatch)

    monkeypatch.setattr(
        bootstrap_common,
        "_deployments",
        lambda environment: [
            {
                "environment": environment,
                "authority_id": "controlled_execution",
                "service_user": "qp_controlled",
                "caller_group": "qp_staging_controlled_execution_callers",
                "custody_reader_group": (
                    "qp_staging_controlled_execution_readers"
                ),
            }
        ],
    )
    monkeypatch.setattr(
        activation.pwd,
        "getpwuid",
        lambda uid: _service_account("qp_controlled", uid, 20),
    )
    groups_by_name = {
        bootstrap_common.SERVICE_GROUP: SimpleNamespace(
            gr_name=bootstrap_common.SERVICE_GROUP,
            gr_gid=20,
            gr_mem=[],
        ),
        "qp_staging_controlled_execution_callers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_callers",
            gr_gid=30,
            gr_mem=["qp_controlled", "qp_trader"],
        ),
        "qp_staging_controlled_execution_readers": SimpleNamespace(
            gr_name="qp_staging_controlled_execution_readers",
            gr_gid=40,
            gr_mem=["qp_controlled"],
        ),
    }
    monkeypatch.setattr(
        bootstrap_common.grp,
        "getgrnam",
        lambda name: groups_by_name[name],
    )
    monkeypatch.setattr(
        bootstrap_common.grp,
        "getgrgid",
        lambda gid: next(
            group for group in groups_by_name.values() if group.gr_gid == gid
        ),
    )
    monkeypatch.setattr(activation.os, "getegid", lambda: 30)
    monkeypatch.setattr(activation.os, "getgroups", lambda: [20, 30, 40])
    activation._require_controlled_reader_group_v2(
        environment="staging",
        service_uid=503,
        claimed_gid=40,
    )
    with pytest.raises(ExactFourAuthorityPending, match="drifts"):
        activation._require_controlled_reader_group_v2(
            environment="staging",
            service_uid=503,
            claimed_gid=20,
        )
    monkeypatch.setattr(activation.os, "getgroups", lambda: [20, 30])
    with pytest.raises(ExactFourAuthorityPending, match="drifts"):
        activation._require_controlled_reader_group_v2(
            environment="staging",
            service_uid=503,
            claimed_gid=40,
        )
