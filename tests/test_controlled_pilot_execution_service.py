"""Containment invariants for the unprovisioned Controlled Pilot authority."""

from __future__ import annotations

import socket
import sqlite3
from pathlib import Path

import pytest

import execution.paper_service as paper_service_module
from execution.paper_service import (
    CONTROLLED_AUTHORITY_UNPROVISIONED,
    ControlledPilotExecutionService,
    ControlledPilotPending,
)
from strategies.paper import Lifecycle, PaperRunConfig, run_paper


@pytest.mark.parametrize(
    ("args", "kwargs"),
    (
        ((), {}),
        (
            (object(), object()),
            {"config": object(), "db_path": "/tmp/attacker.sqlite"},
        ),
    ),
    ids=("no_args", "legacy_args_config_db_path"),
)
def test_controlled_boundary_is_pending_without_io(
    monkeypatch: pytest.MonkeyPatch,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    service = ControlledPilotExecutionService()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Controlled boundary attempted I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(paper_service_module, "run_paper", forbidden)

    with pytest.raises(ControlledPilotPending) as raised:
        service.execute(*args, **kwargs)

    assert raised.value.status == "PENDING"
    assert raised.value.reason_code == CONTROLLED_AUTHORITY_UNPROVISIONED
    assert "Worker/Container" in str(raised.value)


def test_local_runner_rejects_paper_before_database_access(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.sqlite"
    config = PaperRunConfig(
        start="2026-01-01",
        end="2026-01-02",
        db_path=missing,
        lifecycle=Lifecycle.PAPER,
    )

    with pytest.raises(
        PermissionError,
        match="DRAFT-only.*CONTROLLED_AUTHORITY_UNPROVISIONED",
    ):
        run_paper(object(), config)

    assert not missing.exists()
