"""READY publication consumes only a sealed one-shot applied-mirror handle."""

from __future__ import annotations

import copy
import inspect
import sqlite3
import threading
from pathlib import Path

import pytest

from paper_runtime.ready_publication import (
    ReadyPublicationService,
    verify_controlled_publication_evidence,
)
from scripts import sync_d1_to_sqlite as sync
from selection.budget_ledger import MassResearchDisabledError
from tests.test_ready_policy_fail_closed import (
    AUTHENTICATED_EXPORT_AT,
    _open_ready_handle,
    _seed_exact_pit_scope,
    _verify_scope,
    authenticate_applied_mirror,
)


def _identity_fields(proof: dict) -> tuple[str, ...]:
    return (
        "environment",
        "resource_identity",
        "audit_digest",
        "issuer_key_id",
        "export_digest",
        "source_change_seq",
        "applied_change_seq",
        "export_cursor",
        "applied_cursor",
        "source_content_digest",
        "local_content_digest",
        "source_schema_digest",
        "schema_digest",
        "table_counts",
        "exported_at",
        "observed_through",
        "physical_db_digest",
        "physical_db_identity",
        "applied_mirror_identity",
    )


def test_governed_mirror_without_personal_history_manifest_uses_exported_at(
    tmp_path: Path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    proof = _verify_scope(db_path, binding, monkeypatch)
    assert proof["status"] == "PASS"
    assert proof["exported_at"] == AUTHENTICATED_EXPORT_AT
    assert proof["observed_through"] == AUTHENTICATED_EXPORT_AT
    assert proof["export_cursor"] == proof["source_change_seq"]
    assert proof["applied_cursor"] == proof["applied_change_seq"]
    identity = proof["applied_mirror_identity"]
    assert identity["exported_at"] == AUTHENTICATED_EXPORT_AT
    assert set(identity) == sync._APPLIED_MIRROR_IDENTITY_FIELDS
    for field in _identity_fields(proof):
        assert field in proof
        assert proof[field] not in (None, "", {}, [])
    listing_conn = sqlite3.connect(db_path)
    try:
        listing = listing_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='personal_history_manifest'"
        ).fetchone()
    finally:
        listing_conn.close()
    assert listing is None


def test_ready_publication_rejects_caller_db_path(
    tmp_path: Path,
    receipt_ed25519_keys,
) -> None:
    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    service = ReadyPublicationService()
    with pytest.raises(TypeError, match="filesystem path"):
        service.request_verified_publication(db_path, binding)
    with pytest.raises(TypeError, match="filesystem path"):
        service.request_verified_publication(str(db_path), binding)
    with pytest.raises(TypeError, match="filesystem path"):
        verify_controlled_publication_evidence(db_path, binding)
    signature = inspect.signature(service.request_verified_publication)
    assert "db_path" not in signature.parameters
    assert "path" not in signature.parameters


def test_generic_applied_mirror_callback_escape_is_gone() -> None:
    assert not hasattr(sync, "_consume_authenticated_applied_mirror")
    assert not hasattr(sync._AuthenticatedAppliedMirror, "_consume_for_projection")
    for name, value in vars(sync).items():
        if not callable(value):
            continue
        try:
            parameters = inspect.signature(value).parameters
        except (TypeError, ValueError):
            continue
        assert "consumer" not in parameters, name


def test_forged_copied_reused_and_wrong_thread_handles_fail_closed(
    tmp_path: Path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    handle = _open_ready_handle(db_path, monkeypatch)
    forged = object.__new__(sync._AuthenticatedAppliedMirror)
    with pytest.raises(RuntimeError, match="not authentic|already consumed"):
        ReadyPublicationService().request_verified_publication(forged, binding)
    with pytest.raises(RuntimeError, match="cannot be copied"):
        copy.copy(handle)
    with pytest.raises(RuntimeError, match="cannot be copied"):
        copy.deepcopy(handle)

    observed: list[BaseException] = []

    def consume_on_other_thread() -> None:
        try:
            ReadyPublicationService().request_verified_publication(
                handle, binding
            )
        except BaseException as exc:  # noqa: BLE001
            observed.append(exc)

    worker = threading.Thread(target=consume_on_other_thread)
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert len(observed) == 1
    assert "wrong thread" in str(observed[0])
    with pytest.raises(RuntimeError, match="already consumed"):
        ReadyPublicationService().request_verified_publication(handle, binding)

    reused = _open_ready_handle(db_path, monkeypatch)
    evidence = ReadyPublicationService().request_verified_publication(
        reused, binding
    )
    assert evidence.as_dict()["status"] == "PASS"
    with pytest.raises(RuntimeError, match="already consumed"):
        ReadyPublicationService().request_verified_publication(reused, binding)


def test_path_replacement_after_freeze_is_rejected(
    tmp_path: Path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    handle = _open_ready_handle(db_path, monkeypatch)
    replacement = tmp_path / "attacker.sqlite"
    sqlite3.connect(replacement).close()
    replacement.replace(db_path)
    with pytest.raises(RuntimeError, match="path was replaced"):
        ReadyPublicationService().request_verified_publication(handle, binding)
    with pytest.raises(RuntimeError, match="already consumed"):
        ReadyPublicationService().request_verified_publication(handle, binding)


def test_cursor_exported_at_and_digest_tamper_after_freeze_is_rejected(
    tmp_path: Path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    authenticate_applied_mirror(db_path, monkeypatch)
    real = sync._authenticated_applied_mirror_identity_from_conn
    seen = {"n": 0}

    def tamper(conn: sqlite3.Connection) -> dict[str, object]:
        identity = real(conn)
        seen["n"] += 1
        if seen["n"] > 2:
            identity["source_change_seq"] = int(identity["source_change_seq"]) + 1
            identity["applied_change_seq"] = int(identity["applied_change_seq"]) + 1
            identity["exported_at"] = "2026-08-25T12:00:01+00:00"
            identity["local_content_digest"] = "sha256:" + ("ab" * 32)
            identity["source_content_digest"] = identity["local_content_digest"]
        return identity

    monkeypatch.setattr(
        sync, "_authenticated_applied_mirror_identity_from_conn", tamper
    )
    handle = sync.open_authenticated_applied_mirror(db_path)
    with pytest.raises(RuntimeError, match="identity changed"):
        ReadyPublicationService().request_verified_publication(handle, binding)


def test_authentication_freeze_happens_before_ready_verification(
    tmp_path: Path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import paper_runtime.ready_publication as publication

    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    authenticate_applied_mirror(db_path, monkeypatch)
    order: list[str] = []
    real_canonical = sync._canonical_applied_mirror_identity_json
    real_verify = publication._verify_publication_on_authenticated_mirror

    def tracing_canonical(identity: dict[str, object]) -> str:
        order.append("authenticate")
        return real_canonical(identity)

    def tracing_verify(conn, identity, bound):
        order.append("ready")
        return real_verify(conn, identity, bound)

    monkeypatch.setattr(
        sync, "_canonical_applied_mirror_identity_json", tracing_canonical
    )
    monkeypatch.setattr(
        publication,
        "_verify_publication_on_authenticated_mirror",
        tracing_verify,
    )
    handle = sync.open_authenticated_applied_mirror(db_path)
    assert "authenticate" in order
    assert "ready" not in order
    evidence = ReadyPublicationService().request_verified_publication(
        handle, binding
    )
    assert evidence.as_dict()["status"] == "PASS"
    assert order.index("authenticate") < order.index("ready")
    assert order.count("ready") == 1


@pytest.mark.parametrize(
    "exported_at",
    [
        None,
        "not-an-export-time",
        "2026-08-25T12:00:00Z",
        "2026-08-25T12:00:00",
        "2026-08-25T21:00:00+09:00",
        "2099-01-01T00:00:00+00:00",
    ],
)
def test_missing_malformed_noncanonical_future_exported_at_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exported_at: object,
) -> None:
    from tests.test_ops_projection_publish import (
        _opaque_source,
        _test_mirror_identity,
    )

    source = tmp_path / "authenticated.sqlite"
    _opaque_source(source, "trusted")
    if exported_at is None:
        def identity(conn: sqlite3.Connection) -> dict[str, object]:
            value = _test_mirror_identity()(conn)
            del value["exported_at"]
            return value
    else:
        identity = _test_mirror_identity(exported_at=exported_at)
    monkeypatch.setattr(
        sync, "_authenticated_applied_mirror_identity_from_conn", identity
    )
    with pytest.raises(ValueError, match="authenticated current D1 export"):
        sync.open_authenticated_applied_mirror(source)


def test_ready_service_does_not_accept_raw_connection_or_callback(
    tmp_path: Path,
    receipt_ed25519_keys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, binding = _seed_exact_pit_scope(tmp_path, receipt_ed25519_keys)
    authenticate_applied_mirror(db_path, monkeypatch)
    connection = sqlite3.connect(db_path)
    try:
        with pytest.raises((TypeError, RuntimeError, MassResearchDisabledError)):
            ReadyPublicationService().request_verified_publication(
                connection, binding
            )
    finally:
        connection.close()
    with pytest.raises(TypeError):
        ReadyPublicationService().request_verified_publication(  # type: ignore[misc]
            object(),
            binding,
            consumer=lambda *_a, **_k: None,
        )
