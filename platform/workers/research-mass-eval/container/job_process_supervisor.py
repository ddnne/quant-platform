"""Bounded one-job child process-group supervision for the Container runtime."""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import signal
import stat
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

RESULT_MAX_BYTES = 64 * 1024
START_GRACE_SECONDS = 2.0
TERM_GRACE_SECONDS = 0.5
KILL_GRACE_SECONDS = 2.0

Runner = Callable[[Any], dict[str, Any]]


def _safe_detail(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:500]


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_result(path: Path, envelope: Mapping[str, Any]) -> None:
    if set(envelope) not in ({"status", "result"}, {"status", "error"}):
        raise RuntimeError("supervised result envelope is not closed")
    body = _canonical_bytes(envelope)
    if not 0 < len(body) <= RESULT_MAX_BYTES:
        raise RuntimeError("supervised result exceeds the fixed size bound")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _child_main(
    runner: Runner,
    spec: Any,
    result_path: Path,
    ready_connection: Any,
) -> None:
    try:
        os.setsid()
        ready_connection.send_bytes(b"1")
    except BaseException:
        os._exit(70)
    finally:
        ready_connection.close()
    try:
        result = runner(spec)
        if not isinstance(result, dict):
            raise RuntimeError("job runner returned a non-object result")
        try:
            _write_result(result_path, {"status": "ok", "result": result})
        except RuntimeError as error:
            _write_result(
                result_path,
                {"status": "error", "error": _safe_detail(error)},
            )
    except BaseException as error:
        try:
            _write_result(
                result_path,
                {"status": "error", "error": _safe_detail(error)},
            )
        except BaseException:
            os._exit(74)


@dataclass(frozen=True, slots=True)
class SupervisedJobOutcome:
    quiescent: bool
    result: dict[str, Any] | None = None
    error: str | None = None


class JobProcessSupervisor:
    """Own one POSIX session and report a result only after it is quiescent."""

    def __init__(
        self,
        runner: Runner,
        spec: Any,
        *,
        work_root: Path,
        start_grace_seconds: float = START_GRACE_SECONDS,
        term_grace_seconds: float = TERM_GRACE_SECONDS,
        kill_grace_seconds: float = KILL_GRACE_SECONDS,
        process_context: multiprocessing.context.BaseContext | None = None,
    ) -> None:
        if min(start_grace_seconds, term_grace_seconds, kill_grace_seconds) <= 0:
            raise ValueError("process supervision grace periods must be positive")
        self._runner = runner
        self._spec = spec
        self._work_root = work_root
        self._start_grace_seconds = start_grace_seconds
        self._term_grace_seconds = term_grace_seconds
        self._kill_grace_seconds = kill_grace_seconds
        self._process_context = process_context or multiprocessing.get_context("spawn")
        self._process: Any | None = None
        self._process_started = False
        self._group_id: int | None = None
        self._identity_confirmed = False
        self._result_root: Path | None = None
        self._result_path: Path | None = None
        self._start_error: str | None = None
        self._quiescent = False
        self._stop_lock = threading.Lock()
        self._closed = False

    @property
    def pid(self) -> int | None:
        process = self._process
        return int(process.pid) if process is not None and process.pid else None

    @property
    def group_id(self) -> int | None:
        return self._group_id if self._identity_confirmed else None

    def start(self) -> None:
        self._work_root.mkdir(parents=True, exist_ok=True)
        self._result_root = Path(
            tempfile.mkdtemp(prefix=".job-supervisor-", dir=self._work_root)
        )
        os.chmod(self._result_root, 0o700)
        self._result_path = self._result_root / "result.json"
        ready_reader, ready_writer = self._process_context.Pipe(duplex=False)
        try:
            process = self._process_context.Process(
                target=_child_main,
                args=(self._runner, self._spec, self._result_path, ready_writer),
                name=f"qp-job-{self._spec.job_id}",
                daemon=False,
            )
            self._process = process
            process.start()
            self._process_started = True
            self._group_id = int(process.pid) if process.pid else None
            ready_writer.close()
            if (
                not ready_reader.poll(self._start_grace_seconds)
                or ready_reader.recv_bytes(1) != b"1"
            ):
                self._start_error = "job process group identity was not confirmed"
                self.stop()
                return
            self._identity_confirmed = self._group_id is not None
            if not self._identity_confirmed:
                self._start_error = "job process pid is unavailable"
                self.stop()
        except BaseException as error:
            self._start_error = _safe_detail(error)
            if not self._process_started:
                self._quiescent = True
                self._group_id = None
            else:
                self.stop()
        finally:
            ready_writer.close()
            ready_reader.close()

    def _process_state(self) -> str:
        if self._process is None or not self._process_started:
            return "dead"
        try:
            return "alive" if self._process.is_alive() else "dead"
        except (AssertionError, OSError, ValueError):
            return "unknown"

    def _group_state(self) -> str:
        if self._group_id is None:
            return "unknown" if self._process is not None else "dead"
        try:
            os.killpg(self._group_id, 0)
        except ProcessLookupError:
            return "dead"
        except (PermissionError, OSError):
            return "unknown"
        return "alive"

    def _reap_leader(self, timeout: float = 0.0) -> None:
        if self._process is None:
            return
        try:
            self._process.join(timeout)
        except (AssertionError, OSError, ValueError):
            pass

    def _wait_quiescent(self, seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self._reap_leader()
            process_state = self._process_state()
            if process_state == "dead":
                while self._group_id is not None:
                    try:
                        pid, _status = os.waitpid(-self._group_id, os.WNOHANG)
                    except (ChildProcessError, OSError):
                        break
                    if pid <= 0:
                        break
            if process_state == "dead" and self._group_state() == "dead":
                self._quiescent = self._identity_confirmed or self._process is None
                return self._quiescent
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))

    def _signal_group(self, value: signal.Signals) -> None:
        if not self._identity_confirmed or self._group_id is None:
            return
        try:
            os.killpg(self._group_id, value)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def stop(self) -> bool:
        """TERM, bounded wait, KILL, bounded wait, then require quiescence."""

        with self._stop_lock:
            if self._quiescent or self._wait_quiescent(0):
                return self._quiescent
            self._signal_group(signal.SIGTERM)
            if self._wait_quiescent(self._term_grace_seconds):
                return True
            self._signal_group(signal.SIGKILL)
            if (
                not self._identity_confirmed
                and self._process is not None
                and self._process_started
            ):
                try:
                    self._process.kill()
                except (AssertionError, OSError, ValueError):
                    pass
            return self._wait_quiescent(self._kill_grace_seconds)

    def _read_result(self) -> SupervisedJobOutcome:
        try:
            if self._result_path is None:
                raise RuntimeError("job result path is unavailable")
            metadata = self._result_path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError("job result is not a regular file")
            if not 0 < metadata.st_size <= RESULT_MAX_BYTES:
                raise RuntimeError("job result size is outside the fixed bound")
            with self._result_path.open("rb") as handle:
                raw = handle.read(RESULT_MAX_BYTES + 1)
            if len(raw) != metadata.st_size or len(raw) > RESULT_MAX_BYTES:
                raise RuntimeError("job result exceeded the fixed read bound")
            parsed: Any = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise RuntimeError("job result envelope is not an object")
            if set(parsed) == {"status", "result"} and parsed["status"] == "ok":
                if not isinstance(parsed["result"], dict):
                    raise RuntimeError("job result terminal is not an object")
                return SupervisedJobOutcome(True, result=dict(parsed["result"]))
            if set(parsed) == {"status", "error"} and parsed["status"] == "error":
                if not isinstance(parsed["error"], str) or not parsed["error"]:
                    raise RuntimeError("job error envelope is invalid")
                return SupervisedJobOutcome(True, error=parsed["error"][:500])
            raise RuntimeError("job result envelope is not closed")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as error:
            exitcode = None if self._process is None else self._process.exitcode
            suffix = "" if exitcode in {None, 0} else f" (exitcode {exitcode})"
            return SupervisedJobOutcome(
                True,
                error=f"{_safe_detail(error)}{suffix}"[:500],
            )

    def wait(self) -> SupervisedJobOutcome:
        if self._start_error is not None:
            outcome = SupervisedJobOutcome(self._quiescent, error=self._start_error)
            self.close()
            return outcome
        while self._process_state() == "alive":
            self._reap_leader(0.05)
        if not self._wait_quiescent(0) and not self.stop():
            return SupervisedJobOutcome(
                False,
                error="job process group liveness is unknown",
            )
        outcome = self._read_result()
        self.close()
        return outcome

    def close(self) -> None:
        if self._closed or not self._quiescent:
            return
        self._closed = True
        if self._process is not None:
            try:
                self._process.close()
            except ValueError:
                pass
        if self._result_root is not None:
            shutil.rmtree(self._result_root, ignore_errors=True)
