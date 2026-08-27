"""Real SQLite/process checks for the Controlled writer quiescence boundary."""

from __future__ import annotations

import multiprocessing
import os
import sqlite3
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from execution import controlled_execution_quiescence_v2 as quiescence
from scripts import run_local_authority as runner


def _provision_wal_store(path: Path) -> None:
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    path.touch(mode=0o600)
    path.chmod(0o600)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("CREATE TABLE evidence(value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence VALUES ('preserved')")
        connection.commit()
    finally:
        connection.close()
    assert path.read_bytes()[18:20] == b"\x02\x02"


def _identity(path: Path) -> quiescence._ControlledStoreIdentityV2:
    return quiescence._ControlledStoreIdentityV2(
        environment="staging",
        service_uid=os.geteuid(),
        store_path=path,
    )


def _spawn_lock_attempt(path_text: str, result: multiprocessing.Queue[str]) -> None:
    path = Path(path_text)
    try:
        lease = quiescence._acquire_lifecycle_lock(
            _identity(path), require_marker_absent=True
        )
    except quiescence.ControlledExecutionQuiescenceV2Error:
        result.put("BLOCKED")
    else:
        lease.close()
        result.put("ACQUIRED")


def _attempt_inherited_lease(
    lease: quiescence.ControlledWriterLifecycleLeaseV2,
    result: multiprocessing.Queue[str],
) -> None:
    try:
        lease._require_held()
    except quiescence.ControlledExecutionQuiescenceV2Error:
        lease.close()
        try:
            os.fstat(lease._descriptor)
        except OSError:
            result.put("REJECTED_AND_CHILD_DESCRIPTOR_CLOSED")
        else:
            result.put("REJECTED_BUT_CHILD_DESCRIPTOR_OPEN")
    else:
        result.put("INHERITED_LEASE_REUSED")


def _hold_lifecycle_lock(
    path_text: str,
    ready: multiprocessing.Queue[str],
    release: multiprocessing.Queue[str],
) -> None:
    path = Path(path_text)
    try:
        lease = quiescence._acquire_lifecycle_lock(
            _identity(path), require_marker_absent=True
        )
    except quiescence.ControlledExecutionQuiescenceV2Error:
        ready.put("FAILED")
        return
    ready.put("HELD")
    try:
        release.get(timeout=15)
    finally:
        lease.close()


def test_real_transition_is_same_inode_delete_sidecar_free_and_resume_blocked(
    tmp_path: Path,
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    before = store.lstat()

    session = quiescence._begin_transition(_identity(store.resolve()))
    marker = quiescence._transition_paths(store.resolve())[1]
    assert session.store_identity == (before.st_dev, before.st_ino)
    assert store.lstat().st_ino == before.st_ino
    assert store.read_bytes()[18:20] == b"\x01\x01"
    assert marker.is_file()
    quiescence._require_no_sidecars(store)
    connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("SELECT value FROM evidence").fetchone() == (
            "preserved",
        )
    finally:
        connection.close()

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="externally anchored completion verifier",
    ):
        session.restore_wal_after_bounded_canary()
    session.close()

    assert store.lstat().st_ino == before.st_ino
    assert store.read_bytes()[18:20] == b"\x01\x01"
    assert marker.exists()


def test_lifecycle_lock_is_mutually_exclusive_across_processes(tmp_path: Path) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    lease = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    process = context.Process(
        target=_spawn_lock_attempt, args=(str(store.resolve()), result)
    )
    process.start()
    process.join(timeout=15)
    try:
        assert process.exitcode == 0
        assert result.get(timeout=2) == "BLOCKED"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        lease.close()

    second = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    second.close()


def test_forked_child_cannot_reuse_or_unlock_parent_lifecycle(
    tmp_path: Path,
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork start method is unavailable")
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    lease = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    fork_context = multiprocessing.get_context("fork")
    inherited_result = fork_context.Queue()
    child = fork_context.Process(
        target=_attempt_inherited_lease,
        args=(lease, inherited_result),
    )
    child.start()
    child.join(timeout=15)
    contender: multiprocessing.Process | None = None
    try:
        assert child.exitcode == 0
        assert inherited_result.get(timeout=2) == (
            "REJECTED_AND_CHILD_DESCRIPTOR_CLOSED"
        )
        lease._require_held()

        spawn_context = multiprocessing.get_context("spawn")
        contender_result = spawn_context.Queue()
        contender = spawn_context.Process(
            target=_spawn_lock_attempt,
            args=(str(store.resolve()), contender_result),
        )
        contender.start()
        contender.join(timeout=15)
        assert contender.exitcode == 0
        assert contender_result.get(timeout=2) == "BLOCKED"
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        if contender is not None and contender.is_alive():
            contender.terminate()
            contender.join(timeout=5)
        lease.close()

    replacement = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    replacement.close()


def test_exact_type_fake_lease_cannot_bypass_another_process_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from execution import controlled_execution_activation_v2 as activation

    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    identity = _identity(store.resolve())
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    release = context.Queue()
    holder = context.Process(
        target=_hold_lifecycle_lock,
        args=(str(store.resolve()), ready, release),
    )
    holder.start()
    fake: quiescence.ControlledWriterLifecycleLeaseV2 | None = None
    try:
        assert ready.get(timeout=15) == "HELD"
        lock_path, _marker_path = quiescence._transition_paths(store.resolve())
        descriptor = os.open(
            lock_path,
            os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        observed = os.fstat(descriptor)
        fake = quiescence.ControlledWriterLifecycleLeaseV2(
            identity=identity,
            descriptor=descriptor,
            lock_path=lock_path,
            lock_identity=(observed.st_dev, observed.st_ino),
            require_marker_absent=True,
            _token=quiescence._SESSION_TOKEN,
        )
        reached: list[str] = []
        monkeypatch.setattr(
            activation,
            "_load_live_controlled_execution_writer_material_v2",
            lambda: reached.append("material"),
        )
        monkeypatch.setattr(
            activation,
            "SQLiteControlledExecutionWriterV2",
            lambda *_args, **_kwargs: reached.append("sqlite"),
        )

        with pytest.raises(
            quiescence.ControlledExecutionQuiescenceV2Error,
            match="does not own the lock",
        ):
            quiescence.require_held_controlled_writer_lifecycle_v2(
                fake,
                expected_environment="staging",
                expected_store_path=store.resolve(),
            )
        with pytest.raises(
            quiescence.ControlledExecutionQuiescenceV2Error,
            match="does not own the lock",
        ):
            activation._load_live_controlled_execution_writer_v2(
                server_bound=True,
                lifecycle=fake,
            )
        assert reached == []
    finally:
        if fake is not None:
            fake.close()
        release.put("RELEASE")
        holder.join(timeout=15)
        if holder.is_alive():
            holder.terminate()
            holder.join(timeout=5)
    assert holder.exitcode == 0


def test_closed_lifecycle_fd_number_reuse_is_rejected(tmp_path: Path) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    lease = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    reused_descriptor = lease._descriptor
    lock_path, _marker_path = quiescence._transition_paths(store.resolve())
    os.close(reused_descriptor)
    opened: list[int] = []
    for _attempt in range(64):
        replacement_descriptor = os.open(
            lock_path,
            os.O_RDWR
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened.append(replacement_descriptor)
        if replacement_descriptor == reused_descriptor:
            break
    assert opened[-1] == reused_descriptor
    try:
        with pytest.raises(
            quiescence.ControlledExecutionQuiescenceV2Error,
            match="closed or replaced",
        ):
            lease._require_held()
    finally:
        try:
            lease.close()
        finally:
            for descriptor in opened[:-1]:
                os.close(descriptor)

    replacement = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    replacement.close()


def test_both_closed_lifecycle_fd_numbers_cannot_resurrect_stale_lease(
    tmp_path: Path,
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    lease = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    descriptor = lease._descriptor
    guard = lease._descriptor_guard
    lock_path, _marker_path = quiescence._transition_paths(store.resolve())
    os.close(descriptor)
    os.close(guard)

    fresh = os.open(
        lock_path,
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    if fresh == descriptor:
        os.dup2(fresh, guard)
    elif fresh == guard:
        os.dup2(fresh, descriptor)
    else:
        os.dup2(fresh, descriptor)
        os.dup2(fresh, guard)
    try:
        with pytest.raises(
            quiescence.ControlledExecutionQuiescenceV2Error,
            match="closed or replaced",
        ):
            lease._require_held()
    finally:
        lease.close()
        if fresh not in {descriptor, guard}:
            os.close(fresh)

    replacement = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    replacement.close()


def test_open_writer_forces_transition_failure_and_durable_restart_hold(
    tmp_path: Path,
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    writer = sqlite3.connect(store, isolation_level=None)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO evidence VALUES ('uncommitted')")
    try:
        with pytest.raises(
            quiescence.ControlledExecutionQuiescenceV2Error,
            match="exclusive WAL-to-DELETE transition failed",
        ):
            quiescence._begin_transition(_identity(store.resolve()))
    finally:
        writer.rollback()
        writer.close()

    marker = quiescence._transition_paths(store.resolve())[1]
    assert marker.is_file()
    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="resume is forbidden",
    ):
        quiescence._acquire_lifecycle_lock(
            _identity(store.resolve()), require_marker_absent=True
        )
    assert store.read_bytes()[18:20] == b"\x02\x02"


def test_session_release_without_completion_never_removes_restart_hold(
    tmp_path: Path,
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    session = quiescence._begin_transition(_identity(store.resolve()))
    marker = quiescence._transition_paths(store.resolve())[1]
    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="externally anchored completion verifier",
    ):
        session.restore_wal_after_bounded_canary()
    session.close()

    assert marker.is_file()
    assert store.read_bytes()[18:20] == b"\x01\x01"
    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="resume is forbidden",
    ):
        quiescence._acquire_lifecycle_lock(
            _identity(store.resolve()), require_marker_absent=True
        )


def test_marker_append_is_detected_before_any_resume_attempt(tmp_path: Path) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    session = quiescence._begin_transition(_identity(store.resolve()))
    marker = quiescence._transition_paths(store.resolve())[1]
    with marker.open("ab") as stream:
        stream.write(b"\nattacker-appended")
        stream.flush()
        os.fsync(stream.fileno())

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="marker changed",
    ):
        session.restore_wal_after_bounded_canary()
    session.close()

    assert marker.is_file()
    assert store.read_bytes()[18:20] == b"\x01\x01"


def test_zero_progress_marker_write_fails_closed_and_blocks_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    monkeypatch.setattr(quiescence, "_os_write", lambda *_args: 0)

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="marker cannot be created durably",
    ):
        quiescence._begin_transition(_identity(store.resolve()))

    marker = quiescence._transition_paths(store.resolve())[1]
    assert marker.is_file()
    assert marker.stat().st_size == 0
    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="resume is forbidden",
    ):
        quiescence._acquire_lifecycle_lock(
            _identity(store.resolve()), require_marker_absent=True
        )


@pytest.mark.parametrize("unsafe_kind", ("symlink", "fifo", "hardlink", "mode"))
def test_unsafe_store_identity_is_rejected_before_transition_marker(
    tmp_path: Path, unsafe_kind: str
) -> None:
    store = tmp_path / "controlled.sqlite3"
    target = tmp_path / "target.sqlite3"
    _provision_wal_store(target)
    if unsafe_kind == "symlink":
        store.symlink_to(target)
    elif unsafe_kind == "fifo":
        os.mkfifo(store, 0o600)
    elif unsafe_kind == "hardlink":
        os.link(target, store)
    else:
        store.write_bytes(target.read_bytes())
        store.chmod(0o640)

    with pytest.raises(quiescence.ControlledExecutionQuiescenceV2Error):
        quiescence._begin_transition(_identity(store.absolute()))
    assert not quiescence._transition_paths(store.absolute())[1].exists()


@pytest.mark.parametrize("unsafe_kind", ("symlink", "fifo", "hardlink", "mode"))
def test_unsafe_lifecycle_lock_identity_is_rejected(
    tmp_path: Path, unsafe_kind: str
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    lock, marker = quiescence._transition_paths(store.resolve())
    target = tmp_path / "unsafe-lock-target"
    target.write_bytes(b"not-a-lock")
    target.chmod(0o600)
    if unsafe_kind == "symlink":
        lock.symlink_to(target)
    elif unsafe_kind == "fifo":
        os.mkfifo(lock, 0o600)
    elif unsafe_kind == "hardlink":
        os.link(target, lock)
    else:
        lock.write_bytes(b"wrong mode")
        lock.chmod(0o640)

    with pytest.raises(quiescence.ControlledExecutionQuiescenceV2Error):
        quiescence._acquire_lifecycle_lock(
            _identity(store.resolve()), require_marker_absent=True
        )
    assert not marker.exists()


def test_path_swap_during_sqlite_open_is_detected_and_blocks_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "controlled.sqlite3"
    displaced = tmp_path / "displaced.sqlite3"
    _provision_wal_store(store)
    original_open = quiescence._open_exclusive_connection

    def swap_then_open(path: Path) -> sqlite3.Connection:
        path.rename(displaced)
        path.write_bytes(displaced.read_bytes())
        path.chmod(0o600)
        return original_open(path)

    monkeypatch.setattr(quiescence, "_open_exclusive_connection", swap_then_open)
    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="Controlled store changed",
    ):
        quiescence._begin_transition(_identity(store.resolve()))

    assert quiescence._transition_paths(store.resolve())[1].is_file()
    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="resume is forbidden",
    ):
        quiescence._acquire_lifecycle_lock(
            _identity(store.resolve()), require_marker_absent=True
        )


def test_persistent_sqlite_sidecar_fails_closed_without_manual_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    original_open = quiescence._open_exclusive_connection

    class PersistentSidecarConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def execute(self, statement: str):
            return self.connection.execute(statement)

        def close(self) -> None:
            self.connection.close()
            sidecar = Path(f"{store}-shm")
            sidecar.write_bytes(b"sqlite-owned-persistent-sidecar")
            sidecar.chmod(0o600)

    monkeypatch.setattr(
        quiescence,
        "_open_exclusive_connection",
        lambda path: PersistentSidecarConnection(original_open(path)),
    )
    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="retained a SQLite sidecar",
    ):
        quiescence._begin_transition(_identity(store.resolve()))

    assert Path(f"{store}-shm").is_file()
    assert quiescence._transition_paths(store.resolve())[1].is_file()


def test_controlled_daemon_acquires_lifecycle_before_build_and_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    calls: list[str] = []
    real_lease = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )

    def acquire(*, expected_environment: str):
        assert expected_environment == "staging"
        calls.append("lock")
        return real_lease

    writer = SimpleNamespace(_path=store.resolve(), environment="staging")
    handler = SimpleNamespace(writer=writer)
    service = SimpleNamespace(
        handlers={runner.CONTROLLED_TRADER_HANDOFF_OPERATION: handler}
    )

    def build_service(
        *,
        authority_id: str,
        environment: str,
        lifecycle: quiescence.ControlledWriterLifecycleLeaseV2,
    ):
        assert lifecycle is real_lease
        real_lease._require_held()
        assert (authority_id, environment) == ("controlled_execution", "staging")
        calls.append("build")
        return service

    class StopServer(RuntimeError):
        pass

    class Server:
        def __init__(self, observed: object) -> None:
            assert observed is service

        def serve(self, _listener: object) -> None:
            real_lease._require_held()
            calls.append("serve")
            raise StopServer

    monkeypatch.setattr(runner, "acquire_live_controlled_writer_lifecycle_v2", acquire)
    monkeypatch.setattr(runner, "build_service", build_service)
    monkeypatch.setattr(
        runner,
        "load_and_validate_manifest",
        lambda: {
            "principals": {
                "controlled_execution": {
                    "deployments": {"staging": {"socket_path": "/fixed.sock"}}
                }
            }
        },
    )
    monkeypatch.setattr(
        runner, "launchd_listener", lambda *, expected_socket_path: object()
    )
    monkeypatch.setattr(runner, "UnixAuthorityConnectionServer", Server)

    with pytest.raises(StopServer):
        runner.serve_forever(
            authority_id="controlled_execution", environment="staging"
        )
    assert calls == ["lock", "build", "serve"]
    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error, match="already closed"
    ):
        real_lease._require_held()


def test_transition_session_rejects_post_transition_sidecar(tmp_path: Path) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    session = quiescence._begin_transition(_identity(store.resolve()))
    sidecar = Path(f"{store}-shm")
    sidecar.write_bytes(b"post-transition-sidecar")
    sidecar.chmod(0o600)

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="retained a SQLite sidecar",
    ):
        session.restore_wal_after_bounded_canary()
    session.close()

    assert sidecar.is_file()
    assert quiescence._transition_paths(store.resolve())[1].is_file()


def test_transition_session_revalidates_parent_directory_mode(
    tmp_path: Path,
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    session = quiescence._begin_transition(_identity(store.resolve()))
    tmp_path.chmod(0o750)

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="store directory changed",
    ):
        session.restore_wal_after_bounded_canary()
    session.close()

    assert quiescence._transition_paths(store.resolve())[1].is_file()


def test_transition_session_rejects_parent_directory_path_swap(
    tmp_path: Path,
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    session = quiescence._begin_transition(_identity(store.resolve()))
    displaced = tmp_path.with_name(f"{tmp_path.name}-displaced")
    tmp_path.rename(displaced)
    tmp_path.mkdir(mode=0o700)
    lock_name = quiescence._transition_paths(store)[0].name
    (displaced / lock_name).rename(tmp_path / lock_name)

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="store directory changed",
    ):
        session.restore_wal_after_bounded_canary()
    session.close()

    displaced_store = displaced / store.name
    assert quiescence._transition_paths(displaced_store)[1].is_file()


def test_public_and_server_openers_without_lifecycle_never_reach_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from execution import controlled_execution_activation_v2 as activation
    from execution import controlled_execution_writer_v2 as facade

    reached: list[str] = []
    monkeypatch.setattr(
        activation,
        "_load_live_controlled_execution_writer_material_v2",
        lambda: reached.append("material"),
    )
    monkeypatch.setattr(
        activation,
        "SQLiteControlledExecutionWriterV2",
        lambda *_args, **_kwargs: reached.append("sqlite"),
    )

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="exact lifecycle lease",
    ):
        activation._load_live_controlled_execution_writer_v2(
            server_bound=True,
        )
    with pytest.raises(Exception, match="PENDING_PROTECTED"):
        facade.open_live_controlled_execution_writer_v2()
    assert reached == []


def test_handler_without_lifecycle_rejects_before_server_openers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import execution_authority_entrypoints as entrypoints

    reached: list[str] = []
    monkeypatch.setattr(
        entrypoints,
        "_open_server_bound_controlled_execution_writer_v2",
        lambda **_kwargs: reached.append("writer"),
    )
    monkeypatch.setattr(
        entrypoints,
        "_open_server_bound_controlled_execution_runtime_v2",
        lambda **_kwargs: reached.append("runtime"),
    )

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="exact lifecycle lease",
    ):
        entrypoints.open_live_controlled_execution_handler_v2()
    assert reached == []


def test_daemon_lease_detects_marker_created_after_acquisition(
    tmp_path: Path,
) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    lease = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()),
        require_marker_absent=True,
    )
    marker = quiescence._transition_paths(store.resolve())[1]
    marker.write_bytes(b"unexpected-transition")
    marker.chmod(0o600)
    try:
        with pytest.raises(
            quiescence.ControlledExecutionQuiescenceV2Error,
            match="resume is forbidden",
        ):
            quiescence.require_held_controlled_writer_lifecycle_v2(
                lease,
                expected_environment="staging",
                expected_store_path=store.resolve(),
            )
    finally:
        lease.close()


def test_build_service_without_lifecycle_rejects_before_manifest_or_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached: list[str] = []
    monkeypatch.setattr(
        runner,
        "load_and_validate_manifest",
        lambda: reached.append("manifest"),
    )
    monkeypatch.setattr(
        runner,
        "SQLiteAuthorityEventLedger",
        lambda *_args, **_kwargs: reached.append("sqlite"),
    )

    with pytest.raises(
        quiescence.ControlledExecutionQuiescenceV2Error,
        match="exact lifecycle lease",
    ):
        runner.build_service(
            authority_id="controlled_execution",
            environment="staging",
        )
    assert reached == []


def test_lifecycle_files_are_private_single_link_regular_files(tmp_path: Path) -> None:
    store = tmp_path / "controlled.sqlite3"
    _provision_wal_store(store)
    lease = quiescence._acquire_lifecycle_lock(
        _identity(store.resolve()), require_marker_absent=True
    )
    lock, marker = quiescence._transition_paths(store.resolve())
    try:
        info = lock.lstat()
        assert stat.S_ISREG(info.st_mode)
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert info.st_uid == os.geteuid()
        assert info.st_nlink == 1
        assert not marker.exists()
    finally:
        lease.close()
