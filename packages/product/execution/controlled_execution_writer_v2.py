"""Stable facade for split Controlled validation, IPC, store, and activation."""

from execution.exact_four_codec import ExactFourAuthorityPending, _strict_json_loads
from scripts.finding_ledger_gate import require_pinned_finding_ledger_gate

from execution.controlled_execution_activation_v2 import (
    CONTROLLED_EXECUTION_ACTIVATION_PATH,
    _load_live_controlled_execution_runtime_v2,
    _load_live_controlled_execution_writer_v2,
)
from execution.controlled_execution_store_v2 import (
    CONTROLLED_TRADER_HANDOFF_OPERATION,
    CONTROLLED_TRADER_HANDOFF_PURPOSE,
    CONTROLLED_WRITER_ARTIFACT_TYPES,
    CONTROLLED_WRITER_LIVE_STATE,
    SQLiteControlledExecutionWriterV2,
    _create_test_controlled_execution_writer_v2,
)
from execution.controlled_execution_types_v2 import (
    ControlledExecutionWriterV2Error,
    WrittenExactFourControlledArtifactsV2,
)


def open_live_controlled_execution_writer_v2() -> SQLiteControlledExecutionWriterV2:
    """Reject the legacy public opener before activation or SQLite access."""

    raise ExactFourAuthorityPending(CONTROLLED_WRITER_LIVE_STATE)


def _open_server_bound_controlled_execution_writer_v2(
    *, lifecycle: object | None = None
) -> SQLiteControlledExecutionWriterV2:
    """Execution adapter hook used only inside UnixAuthorityService."""

    return _load_live_controlled_execution_writer_v2(
        server_bound=True,
        lifecycle=lifecycle,
    )


def _open_server_bound_controlled_execution_runtime_v2(
    *, lifecycle: object | None = None
):
    """Build the server-only sealed budget/snapshot/provider runtime."""

    return _load_live_controlled_execution_runtime_v2(lifecycle=lifecycle)


__all__ = [
    "CONTROLLED_EXECUTION_ACTIVATION_PATH",
    "CONTROLLED_TRADER_HANDOFF_OPERATION",
    "CONTROLLED_TRADER_HANDOFF_PURPOSE",
    "CONTROLLED_WRITER_ARTIFACT_TYPES",
    "CONTROLLED_WRITER_LIVE_STATE",
    "ControlledExecutionWriterV2Error",
    "SQLiteControlledExecutionWriterV2",
    "WrittenExactFourControlledArtifactsV2",
    "open_live_controlled_execution_writer_v2",
]
