"""Containment invariants for the unprovisioned Controlled Pilot authority."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

import execution.paper_service as paper_service_module
from execution.paper_service import (
    CONTROLLED_AUTHORITY_UNPROVISIONED,
    ControlledPilotExecutionService,
    ControlledPilotPending,
    OfflineFixturePaperService,
    PaperExecutionService,
)
from strategies.paper import Lifecycle, PaperRunConfig, run_paper
from strategies.paper import runner as paper_runner


def test_controlled_boundary_is_pending_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ControlledPilotExecutionService()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Controlled boundary attempted I/O")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)

    with pytest.raises(ControlledPilotPending) as raised:
        service.execute()

    assert raised.value.status == "PENDING"
    assert raised.value.reason_code == CONTROLLED_AUTHORITY_UNPROVISIONED
    assert "Worker/Container" in str(raised.value)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("paper_store", object()),
        ("socket_path", "/tmp/attacker.sock"),
        ("verifier", object()),
        ("snapshot_path", "/tmp/attacker.sqlite"),
    ),
)
def test_controlled_constructor_has_no_injection_surface(
    name: str, value: object
) -> None:
    with pytest.raises(TypeError, match="takes no arguments"):
        ControlledPilotExecutionService(**{name: value})


def test_controlled_execute_has_no_legacy_local_request_surface() -> None:
    service = ControlledPilotExecutionService()

    with pytest.raises(ControlledPilotPending, match="Worker/Container"):
        service.execute()
    with pytest.raises(ControlledPilotPending, match="Worker/Container"):
        service.execute(config=object())
    with pytest.raises(ControlledPilotPending, match="Worker/Container"):
        service.execute(object(), object(), db_path="/tmp/attacker.sqlite")


def test_controlled_pending_boundary_is_final() -> None:
    with pytest.raises(
        TypeError, match="ControlledPilotExecutionService is final"
    ):

        class ReopenedControlled(ControlledPilotExecutionService):
            pass


def test_offline_fixture_service_has_no_subclass_promotion_seam() -> None:
    assert OfflineFixturePaperService is PaperExecutionService
    with pytest.raises(TypeError, match="PaperExecutionService is final"):

        class ReopenedOfflineFixture(OfflineFixturePaperService):
            pass


def test_controlled_path_and_config_types_are_not_product_api() -> None:
    assert not hasattr(paper_service_module, "ImmutableSnapshotHandle")
    assert not hasattr(paper_service_module, "ControlledPilotRunConfig")


def test_importable_runner_has_no_controlled_capability_minter() -> None:
    assert not hasattr(paper_runner, "_CONTROLLED_PAPER_SEAL")
    assert not hasattr(paper_runner, "_ControlledPaperCapability")
    assert not hasattr(paper_runner, "_mint_controlled_paper_capability")


def test_local_config_and_result_nominal_types_are_final() -> None:
    from strategies.paper import PaperRunResult

    with pytest.raises(TypeError, match="PaperRunConfig is final"):

        class AlternatingLifecycleConfig(PaperRunConfig):
            pass

    with pytest.raises(TypeError, match="PaperRunResult is final"):

        class AlternatingLifecycleResult(PaperRunResult):
            pass


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


def test_removed_capability_keyword_cannot_reopen_local_paper(
    tmp_path: Path,
) -> None:
    config = PaperRunConfig(
        start="2026-01-01",
        end="2026-01-02",
        db_path=tmp_path / "does-not-exist.sqlite",
        lifecycle=Lifecycle.PAPER,
    )

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        run_paper(  # type: ignore[call-arg]
            object(),
            config,
            _controlled_capability=object(),
        )
