"""Sealed Controlled provider runtime with pinned snapshot capabilities."""

from __future__ import annotations

import array
import base64
import fcntl
import hashlib
import os
import socket
import stat
import struct
from abc import ABC, abstractmethod
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from execution.controlled_execution_budget_v2 import (
    ControlledBudgetLedgerV2Error,
    ControlledPersistentBudgetLedgerV2,
    _ControlledBudgetReservationV2,
)
from execution.exact_four_codec import (
    _canonical_bytes,
    _require_digest,
    _strict_json_loads,
    canonical_authority_digest,
)
from execution.controlled_execution_ipc_v2 import _unix_peer_uid
from research.readiness import derive_ready_authority_resource_digest
from execution.secure_authority_files_v2 import open_pinned_authority_file_v2


CONTROLLED_PROVIDER_REQUEST_FORMAT = "controlled-pilot-provider-request/v2"
CONTROLLED_PROVIDER_RESPONSE_FORMAT = "controlled-pilot-provider-response/v2"
CONTROLLED_PROVIDER_USAGE_FORMAT = "controlled-provider-usage/v2"
_RUNTIME_CONSTRUCTION_TOKEN = object()
_SNAPSHOT_CONSTRUCTION_TOKEN = object()
_MAX_PROVIDER_FRAME_BYTES = 32 * 1024 * 1024
_USAGE_COUNTERS = (
    "generations",
    "model_calls",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "paper_runs",
    "compute_time_ms",
    "estimated_cost_micros",
)


class ControlledExecutionRuntimeV2Error(RuntimeError):
    """The sealed runtime, snapshot, budget, or provider failed closed."""


class ControlledProviderTimeoutV2(ControlledExecutionRuntimeV2Error):
    """The fixed Controlled provider exceeded its governed timeout."""


def _sha256_fd(fd: int, *, expected_size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < expected_size:
        block = os.pread(fd, min(1024 * 1024, expected_size - offset), offset)
        if not block:
            raise ControlledExecutionRuntimeV2Error(
                "pinned Controlled resource ended before its measured size"
            )
        digest.update(block)
        offset += len(block)
    return "sha256:" + digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _verified_usage_evidence(
    usage: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    manifest: bytes,
    contents: Mapping[str, bytes],
    reserved_maximums: Mapping[str, int],
) -> bytes:
    expected_fields = {
        "format",
        "environment",
        "budget_id",
        "reservation_id",
        "idempotency_key",
        "snapshot_digest",
        "projection_digest",
        "manifest_digest",
        "contents_digest",
        *_USAGE_COUNTERS,
        "usage_digest",
    }
    if type(usage) is not dict or set(usage) != expected_fields:
        raise ControlledExecutionRuntimeV2Error(
            "Controlled provider usage fields are not closed"
        )
    contents_digest = canonical_authority_digest(
        {key: _sha256_bytes(value) for key, value in contents.items()}
    )
    if (
        usage.get("format") != CONTROLLED_PROVIDER_USAGE_FORMAT
        or usage.get("environment") != context.get("environment")
        or usage.get("budget_id") != context.get("budget_id")
        or usage.get("reservation_id") != context.get("budget_reservation_id")
        or usage.get("idempotency_key") != context.get("idempotency_key")
        or usage.get("snapshot_digest") != context.get(
            "immutable_snapshot_digest"
        )
        or usage.get("projection_digest") != context.get(
            "projection_document_digest"
        )
        or usage.get("manifest_digest") != _sha256_bytes(manifest)
        or usage.get("contents_digest") != contents_digest
    ):
        raise ControlledExecutionRuntimeV2Error(
            "Controlled provider usage is not bound to this exact response"
        )
    try:
        for field in (
            "budget_reservation_id",
            "idempotency_key",
            "immutable_snapshot_digest",
            "projection_document_digest",
        ):
            _require_digest(context[field], f"Controlled provider context {field}")
        for field in ("manifest_digest", "contents_digest", "usage_digest"):
            _require_digest(usage[field], f"Controlled provider usage {field}")
    except Exception as exc:
        raise ControlledExecutionRuntimeV2Error(
            "Controlled provider usage binding digest is invalid"
        ) from exc
    if type(reserved_maximums) is not dict or set(reserved_maximums) != set(
        _USAGE_COUNTERS
    ):
        raise ControlledExecutionRuntimeV2Error(
            "Controlled reservation maximums are invalid"
        )
    for counter in _USAGE_COUNTERS:
        value = usage[counter]
        maximum = reserved_maximums[counter]
        if (
            type(value) is not int
            or type(maximum) is not int
            or value < 0
            or value > maximum
        ):
            raise ControlledExecutionRuntimeV2Error(
                f"Controlled provider {counter} usage exceeds its reservation"
            )
    body = {key: value for key, value in usage.items() if key != "usage_digest"}
    if usage["usage_digest"] != canonical_authority_digest(body):
        raise ControlledExecutionRuntimeV2Error(
            "Controlled provider usage digest does not verify"
        )
    return _canonical_bytes(usage)


class PinnedControlledSnapshotV2:
    """Read-only FD capability for the immutable DB and signed projection."""

    __slots__ = (
        "_snapshot_fd",
        "_projection_fd",
        "_snapshot_identity",
        "_projection_identity",
        "snapshot_digest",
        "projection_digest",
    )

    def __init__(
        self,
        *,
        snapshot_fd: int,
        projection_fd: int,
        _token: object,
    ) -> None:
        if _token is not _SNAPSHOT_CONSTRUCTION_TOKEN:
            raise ControlledExecutionRuntimeV2Error(
                "pinned snapshot requires server-owned descriptors"
            )
        snapshot = self._validate_descriptor(snapshot_fd, "immutable snapshot")
        projection = self._validate_descriptor(projection_fd, "signed projection")
        self._snapshot_fd = snapshot_fd
        self._projection_fd = projection_fd
        self._snapshot_identity = self._identity(snapshot)
        self._projection_identity = self._identity(projection)
        if self._snapshot_identity[:2] == self._projection_identity[:2]:
            raise ControlledExecutionRuntimeV2Error(
                "Controlled snapshot and projection require distinct inodes"
            )
        self.snapshot_digest = _sha256_fd(
            snapshot_fd, expected_size=snapshot.st_size
        )
        self.projection_digest = _sha256_fd(
            projection_fd, expected_size=projection.st_size
        )

    @staticmethod
    def _identity(metadata: os.stat_result) -> tuple[int, ...]:
        return (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            metadata.st_uid,
            stat.S_IMODE(metadata.st_mode),
            metadata.st_nlink,
        )

    @staticmethod
    def _validate_descriptor(fd: int, label: str) -> os.stat_result:
        try:
            metadata = os.fstat(fd)
            status_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        except OSError as exc:
            raise ControlledExecutionRuntimeV2Error(
                f"{label} descriptor cannot be inspected"
            ) from exc
        if (
            status_flags & os.O_ACCMODE != os.O_RDONLY
            or descriptor_flags & fcntl.FD_CLOEXEC == 0
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_nlink != 1
        ):
            raise ControlledExecutionRuntimeV2Error(
                f"{label} must be a single-link non-empty read-only close-on-exec regular FD"
            )
        return metadata

    def verify_context(self, context: Mapping[str, Any]) -> None:
        snapshot = self._validate_descriptor(
            self._snapshot_fd, "immutable snapshot"
        )
        projection = self._validate_descriptor(
            self._projection_fd, "signed projection"
        )
        if (
            self._identity(snapshot) != self._snapshot_identity
            or self._identity(projection) != self._projection_identity
            or _sha256_fd(self._snapshot_fd, expected_size=snapshot.st_size)
            != self.snapshot_digest
            or _sha256_fd(self._projection_fd, expected_size=projection.st_size)
            != self.projection_digest
            or context.get("immutable_snapshot_digest") != self.snapshot_digest
        ):
            raise ControlledExecutionRuntimeV2Error(
                "Controlled immutable snapshot/projection identity drifted"
            )
        expected_resource = derive_ready_authority_resource_digest(
            environment=context["ready_environment"],
            authority_instance_id=context["ready_authority_instance_id"],
            snapshot_id=context["snapshot_id"],
            immutable_db_digest=self.snapshot_digest,
            ready_manifest_digest=context["ready_manifest_digest"],
            signed_projection_document_digest=self.projection_digest,
        )
        if (
            context.get("environment") != context.get("ready_environment")
            or context.get("ready_authority_resource_digest") != expected_resource
        ):
            raise ControlledExecutionRuntimeV2Error(
                "Controlled snapshot does not satisfy READY authority resource binding"
            )

    @property
    def snapshot_fd(self) -> int:
        return self._snapshot_fd

    @property
    def projection_fd(self) -> int:
        return self._projection_fd


def open_pinned_controlled_snapshot_v2(
    *,
    snapshot_path: str,
    projection_path: str,
    expected_uid: int | None = None,
    chain_root: str | None = None,
) -> PinnedControlledSnapshotV2:
    """Open paths once with O_NOFOLLOW and retain the measured descriptors."""

    descriptors: list[int] = []
    try:
        uid = os.geteuid() if expected_uid is None else expected_uid
        for text in (snapshot_path, projection_path):
            if type(text) is not str or not os.path.isabs(text):
                raise ControlledExecutionRuntimeV2Error(
                    "Controlled resource paths must be absolute"
                )
            path = os.path.abspath(text)
            root = (
                os.path.dirname(path)
                if chain_root is None
                else os.path.abspath(chain_root)
            )
            pinned = open_pinned_authority_file_v2(
                Path(path),
                chain_root=Path(root),
                directory_owner_uids={0, uid},
                expected_file_uid=uid,
                allowed_file_modes=frozenset({0o400, 0o440, 0o444}),
            )
            descriptors.append(pinned.fd)
        return PinnedControlledSnapshotV2(
            snapshot_fd=descriptors[0],
            projection_fd=descriptors[1],
            _token=_SNAPSHOT_CONSTRUCTION_TOKEN,
        )
    except Exception:
        for descriptor in descriptors:
            os.close(descriptor)
        raise


class ControlledExecutionProviderV2(ABC):
    """Concrete provider boundary; this is not an authorization capability."""

    @abstractmethod
    def execute_bytes(
        self,
        request: bytes,
        *,
        snapshot_fd: int,
        projection_fd: int,
    ) -> Mapping[str, Any]:
        """Return exact bytes for ``manifest`` and all ten contents."""


class UnixControlledExecutionProviderV2(ControlledExecutionProviderV2):
    """Fixed AF_UNIX provider client authenticated by kernel peer UID."""

    __slots__ = ("_path", "_provider_uid", "_timeout_seconds")

    def __init__(
        self, *, socket_path: str, provider_uid: int, timeout_seconds: float
    ) -> None:
        if (
            type(socket_path) is not str
            or not os.path.isabs(socket_path)
            or type(provider_uid) is not int
            or provider_uid <= 0
            or type(timeout_seconds) not in {int, float}
            or not 0 < float(timeout_seconds) <= 300
        ):
            raise ControlledExecutionRuntimeV2Error(
                "Controlled provider endpoint configuration is invalid"
            )
        self._path = socket_path
        self._provider_uid = provider_uid
        self._timeout_seconds = float(timeout_seconds)

    def execute_bytes(
        self,
        request: bytes,
        *,
        snapshot_fd: int,
        projection_fd: int,
    ) -> Mapping[str, Any]:
        channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        channel.settimeout(self._timeout_seconds)
        try:
            channel.connect(self._path)
            if _unix_peer_uid(channel) != self._provider_uid:
                raise ControlledExecutionRuntimeV2Error(
                    "Controlled provider AF_UNIX peer UID mismatch"
                )
            frame = struct.pack("!I", len(request)) + request
            rights = array.array("i", [snapshot_fd, projection_fd])
            sent = channel.sendmsg(
                [frame],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights.tobytes())],
            )
            if sent != len(frame):
                raise ControlledExecutionRuntimeV2Error(
                    "Controlled provider request frame was not sent atomically"
                )
            header = channel.recv(4, socket.MSG_WAITALL)
            if len(header) != 4:
                raise ControlledExecutionRuntimeV2Error(
                    "Controlled provider response header is incomplete"
                )
            length = struct.unpack("!I", header)[0]
            if length < 2 or length > _MAX_PROVIDER_FRAME_BYTES:
                raise ControlledExecutionRuntimeV2Error(
                    "Controlled provider response length is invalid"
                )
            raw = channel.recv(length, socket.MSG_WAITALL)
            if len(raw) != length:
                raise ControlledExecutionRuntimeV2Error(
                    "Controlled provider response is incomplete"
                )
        except (TimeoutError, socket.timeout) as exc:
            raise ControlledProviderTimeoutV2(
                "Controlled provider timed out"
            ) from exc
        except OSError as exc:
            raise ControlledExecutionRuntimeV2Error(
                "Controlled provider transport failed"
            ) from exc
        finally:
            channel.close()
        response = _strict_json_loads(raw, label="Controlled provider response")
        if (
            set(response)
            != {
                "format",
                "status",
                "manifest_base64",
                "contents_base64",
                "usage",
            }
            or response.get("format") != CONTROLLED_PROVIDER_RESPONSE_FORMAT
            or response.get("status") != "SUCCEEDED"
            or type(response.get("contents_base64")) is not dict
            or type(response.get("usage")) is not dict
            or _canonical_bytes(response) != raw
        ):
            raise ControlledExecutionRuntimeV2Error(
                "Controlled provider response fields are invalid"
            )
        try:
            manifest_text = response["manifest_base64"]
            manifest = base64.b64decode(manifest_text, validate=True)
            contents = {}
            for key, value in response["contents_base64"].items():
                decoded = base64.b64decode(value, validate=True)
                if base64.b64encode(decoded).decode("ascii") != value:
                    raise ValueError("non-canonical content base64")
                contents[key] = decoded
            if base64.b64encode(manifest).decode("ascii") != manifest_text:
                raise ValueError("non-canonical manifest base64")
        except (TypeError, ValueError) as exc:
            raise ControlledExecutionRuntimeV2Error(
                "Controlled provider response is not canonical base64 bytes"
            ) from exc
        if (
            type(manifest) is not bytes
            or not manifest
            or any(type(key) is not str or type(value) is not bytes for key, value in contents.items())
        ):
            raise ControlledExecutionRuntimeV2Error(
                "Controlled provider must return bytes only"
            )
        return {
            "manifest": manifest,
            "contents": contents,
            "usage": response["usage"],
        }


class _ControlledExecutionAttemptV2:
    """One reservation-bound provider call, never persisted or reusable."""

    __slots__ = (
        "_runtime",
        "_reservation",
        "_context",
        "_invoked",
        "_settled",
        "_usage_evidence",
    )

    def __init__(
        self,
        *,
        runtime: "ControlledExecutionRuntimeV2",
        reservation: _ControlledBudgetReservationV2,
        context: Mapping[str, Any],
    ) -> None:
        self._runtime = runtime
        self._reservation = reservation
        exact_context = dict(context)
        exact_context["lease_id"] = reservation.lease_id
        exact_context["budget_reservation_id"] = reservation.reservation_id
        exact_context["budget_id"] = reservation.budget_id
        exact_context["snapshot_handle"] = "SCM_RIGHTS:0"
        exact_context["projection_handle"] = "SCM_RIGHTS:1"
        exact_context["projection_document_digest"] = runtime._snapshot.projection_digest
        exact_context["budget_reserved_maximums"] = dict(
            runtime._budget.reserved_maximums
        )
        self._context = MappingProxyType(exact_context)
        self._invoked = False
        self._settled = False
        self._usage_evidence: bytes | None = None

    @property
    def context(self) -> Mapping[str, Any]:
        return self._context

    @property
    def reservation_id(self) -> str:
        return self._reservation.reservation_id

    def invoke(self) -> Mapping[str, Any]:
        if self._invoked or self._settled:
            raise ControlledExecutionRuntimeV2Error(
                "Controlled provider reservation is one-call only"
            )
        self._runtime._budget.mark_executing(self._reservation)
        self._invoked = True
        request = _canonical_bytes(
            {
                "format": CONTROLLED_PROVIDER_REQUEST_FORMAT,
                "context": dict(self._context),
            }
        )
        output = self._runtime._provider.execute_bytes(
            request,
            snapshot_fd=self._runtime._snapshot.snapshot_fd,
            projection_fd=self._runtime._snapshot.projection_fd,
        )
        if (
            type(output) is not dict
            or set(output) != {"manifest", "contents", "usage"}
            or type(output["manifest"]) is not bytes
            or type(output["contents"]) is not dict
            or type(output["usage"]) is not dict
            or any(
                type(key) is not str or type(value) is not bytes
                for key, value in output["contents"].items()
            )
        ):
            raise ControlledExecutionRuntimeV2Error(
                "Controlled provider output must contain bytes only"
            )
        self._usage_evidence = _verified_usage_evidence(
            output["usage"],
            context=self._context,
            manifest=output["manifest"],
            contents=output["contents"],
            reserved_maximums=self._runtime._budget.reserved_maximums,
        )
        return {"manifest": output["manifest"], "contents": output["contents"]}

    def reverify_snapshot(self) -> None:
        """Detect pinned resource drift after provider work and pre-commit."""

        if not self._invoked or self._settled:
            raise ControlledExecutionRuntimeV2Error(
                "Controlled snapshot revalidation requires one active provider call"
            )
        self._runtime._snapshot.verify_context(self._context)

    def settle(self, *, outcome: str, error: BaseException | None = None) -> None:
        if self._settled:
            raise ControlledExecutionRuntimeV2Error(
                "Controlled provider reservation was already settled"
            )
        if outcome == "success" and (
            not self._invoked or self._usage_evidence is None or error is not None
        ):
            raise ControlledExecutionRuntimeV2Error(
                "Controlled success requires one verified provider response"
            )
        self._runtime._budget.settle(
            self._reservation,
            outcome=outcome,
            error_class=None if error is None else type(error).__name__,
            usage_evidence=self._usage_evidence,
        )
        self._settled = True


class ControlledExecutionRuntimeV2:
    """Server-constructed runtime; no request-time provider injection exists."""

    __slots__ = (
        "_environment",
        "_provider",
        "_budget",
        "_snapshot",
        "_production_bound",
    )

    def __init__(
        self,
        *,
        environment: str,
        provider: ControlledExecutionProviderV2,
        budget: ControlledPersistentBudgetLedgerV2,
        snapshot: PinnedControlledSnapshotV2,
        production_bound: bool,
        _token: object,
    ) -> None:
        if (
            _token is not _RUNTIME_CONSTRUCTION_TOKEN
            or environment not in {"staging", "production"}
            or not isinstance(provider, ControlledExecutionProviderV2)
            or type(budget) is not ControlledPersistentBudgetLedgerV2
            or type(snapshot) is not PinnedControlledSnapshotV2
            or type(production_bound) is not bool
            or (
                production_bound is True
                and type(provider) is not UnixControlledExecutionProviderV2
            )
        ):
            raise ControlledExecutionRuntimeV2Error(
                "Controlled runtime requires exact server-constructed components"
            )
        self._environment = environment
        self._provider = provider
        self._budget = budget
        self._snapshot = snapshot
        self._production_bound = production_bound

    def begin(self, context: Mapping[str, Any]) -> _ControlledExecutionAttemptV2:
        if type(context) is not dict or context.get("environment") != self._environment:
            raise ControlledExecutionRuntimeV2Error(
                "Controlled runtime execution context is invalid"
            )
        self._snapshot.verify_context(context)
        reservation = self._budget.reserve(
            context,
            snapshot_digest=self._snapshot.snapshot_digest,
            projection_digest=self._snapshot.projection_digest,
        )
        return _ControlledExecutionAttemptV2(
            runtime=self,
            reservation=reservation,
            context=context,
        )


def _build_server_controlled_execution_runtime_v2(
    *,
    environment: str,
    provider: ControlledExecutionProviderV2,
    budget: ControlledPersistentBudgetLedgerV2,
    snapshot: PinnedControlledSnapshotV2,
) -> ControlledExecutionRuntimeV2:
    return ControlledExecutionRuntimeV2(
        environment=environment,
        provider=provider,
        budget=budget,
        snapshot=snapshot,
        production_bound=True,
        _token=_RUNTIME_CONSTRUCTION_TOKEN,
    )


def _build_test_controlled_execution_runtime_v2(
    *,
    environment: str,
    provider: ControlledExecutionProviderV2,
    budget: ControlledPersistentBudgetLedgerV2,
    snapshot: PinnedControlledSnapshotV2,
) -> ControlledExecutionRuntimeV2:
    """Test-distribution component builder; rejected by production writers."""

    return ControlledExecutionRuntimeV2(
        environment=environment,
        provider=provider,
        budget=budget,
        snapshot=snapshot,
        production_bound=False,
        _token=_RUNTIME_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "CONTROLLED_PROVIDER_REQUEST_FORMAT",
    "CONTROLLED_PROVIDER_RESPONSE_FORMAT",
    "CONTROLLED_PROVIDER_USAGE_FORMAT",
    "ControlledExecutionProviderV2",
    "ControlledExecutionRuntimeV2Error",
    "ControlledProviderTimeoutV2",
]
