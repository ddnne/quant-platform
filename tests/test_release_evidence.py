from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from scripts import finding_ledger_gate as gate
from scripts import receipt_authority_pending_gate as pending_gate
from scripts import receipt_authority_pending_live_acceptance as live
from scripts import receipt_authority_staging_active_gate as staging
from tests.finding_ledger_test_support import controlled_ledger_document
from tests.test_receipt_authority_pending_live_acceptance import (
    SHA,
    _FakeResponse,
    _install_fake_pinned_wrangler,
    _upload_bundle,
    _version_document_for_surface,
    _version_modules_envelope,
)
from tests.test_receipt_authority_staging_active_gate import (
    ACCESS_AUD,
    ACCESS_CLIENT_ID,
    ACCESS_URL,
    ACCOUNT,
    _access_api_inventory,
    _access_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_release_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_release_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)

INNER = b'{"ok":false,"product_ready":false,"worker":"ingestion-jsda"}'
INNER_DIGEST = "sha256:" + hashlib.sha256(INNER).hexdigest()
MODULE_BODY = b"export default {fetch(){return new Response('jsda');}};\n"
OBSERVER_VERSION = "10000000-0000-4000-8000-000000000010"
JSDA_VERSION = "10000000-0000-4000-8000-000000000011"


def test_build_envelope_refuses_payload_without_writing() -> None:
    with pytest.raises(
        release.ReleaseObservationAuthorityUnavailable,
        match="release evidence publication is PENDING",
    ):
        release.build_envelope({"collector": "caller-self-claim"})


def test_write_envelope_creates_no_output(tmp_path: Path) -> None:
    output = tmp_path / "release"
    with pytest.raises(
        release.ReleaseObservationAuthorityUnavailable,
        match="authenticated collection/publication implementation is missing",
    ):
        release.write_envelope({"collector": "caller-self-claim"}, output)
    assert not output.exists()


def _closed_ledger():
    document = json.loads(
        (ROOT / "docs" / "phase633_finding_ledger.json").read_text(encoding="utf-8")
    )
    raw = (
        json.dumps(
            controlled_ledger_document(document), sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode()
    return gate._evaluate_ledger_bytes(raw)


def _observation_bytes() -> bytes:
    body = {
        "access_aud": ACCESS_AUD,
        "binding_name": "JSDA_INGESTION",
        "collector": "private-jsda-health-ready/v1",
        "eligibility": "AUDIT_ONLY",
        "endpoint": "/health/ready",
        "exact_response_b64": base64.b64encode(INNER).decode("ascii"),
        "exact_response_bytes": len(INNER),
        "exact_response_utf8": INNER.decode("utf-8"),
        "http_status": 503,
        "observer_source_sha": SHA,
        "observer_worker_version_id": OBSERVER_VERSION,
        "observer_worker_version_tag": staging._observer_tag(SHA),
        "response_digest": INNER_DIGEST,
        "schema_version": "quant-platform-release-observation/v2",
        "transport": "private-service-binding",
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _collect_seams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    drift: bool = False,
):
    monkeypatch.setattr(
        release, "require_pinned_finding_ledger_gate", lambda: _closed_ledger()
    )
    manifest_path = _access_manifest(tmp_path / "access.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(staging, "ACCESS_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(
        staging, "_cloudflare_api", _access_api_inventory(manifest)
    )
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    monkeypatch.setenv(staging.ACCESS_CLIENT_ID_ENV, ACCESS_CLIENT_ID)
    monkeypatch.setenv(staging.ACCESS_CLIENT_SECRET_ENV, "secret")
    _install_fake_pinned_wrangler(
        tmp_path, monkeypatch, "receipt-activation-observer"
    )
    _install_fake_pinned_wrangler(tmp_path, monkeypatch, "ingestion-jsda")
    monkeypatch.setattr(
        pending_gate.subprocess,
        "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            tuple(cmd), 0, (SHA + "\n") if "rev-parse" in tuple(cmd) else "", ""
        ),
    )
    workers = live.build_manifest()["workers"]
    observer_version = _version_document_for_surface(
        workers["receipt-activation-observer"]["staging"],
        worker="receipt-activation-observer",
        version_id=OBSERVER_VERSION,
        ordinal=1,
        annotations={
            "workers/message": staging._observer_message(SHA),
            "workers/tag": staging._observer_tag(SHA),
            "workers/triggered_by": "version_upload",
        },
    )
    jsda_version = _version_document_for_surface(
        workers["ingestion-jsda"]["staging"],
        worker="ingestion-jsda",
        version_id=JSDA_VERSION,
        ordinal=2,
        annotations={"workers/triggered_by": "version_upload"},
    )
    deployments = {
        "observer": {
            "id": "20000000-0000-4000-8000-000000000020",
            "created_on": "2026-09-13T00:00:00Z",
            "source": "wrangler",
            "strategy": "percentage",
            "annotations": {"workers/message": staging._observer_message(SHA)},
            "versions": [{"version_id": OBSERVER_VERSION, "percentage": 100}],
        },
        "jsda": {
            "id": "20000000-0000-4000-8000-000000000021",
            "created_on": "2026-09-13T00:00:00Z",
            "source": "wrangler",
            "strategy": "percentage",
            "annotations": {"workers/message": "jsda"},
            "versions": [{"version_id": JSDA_VERSION, "percentage": 100}],
        },
    }
    after_get = {"n": 0}
    ticks = [datetime(2026, 9, 14, 12, 0, tzinfo=UTC)]

    def runner(command, **kwargs):
        argv = tuple(command)
        if after_get["n"]:
            ticks[0] = datetime(2026, 9, 14, 12, 1, tzinfo=UTC)
        if argv and argv[0] == "git":
            if "ls-remote" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, f"{SHA}\trefs/heads/main\n", ""
                )
            if argv[1:3] == ("remote", "get-url"):
                return subprocess.CompletedProcess(
                    argv, 0, "https://github.com/ddnne/quant-platform.git\n", ""
                )
            return subprocess.CompletedProcess(argv, 0, SHA + "\n", "")
        if "deploy" in argv and "--outfile" in argv:
            Path(argv[argv.index("--outfile") + 1]).write_bytes(
                _upload_bundle(modules=[("index.js", "application/javascript+module", MODULE_BODY)])
            )
            return subprocess.CompletedProcess(argv, 0, "", "")
        cwd = Path(str(kwargs.get("cwd", "")))
        role = "jsda" if cwd.name == "ingestion-jsda" else "observer"
        if "deployments" in argv:
            document = dict(deployments[role])
            if drift and after_get["n"] and role == "jsda":
                document = {**document, "created_on": "2026-09-13T00:00:01Z"}
            return subprocess.CompletedProcess(argv, 0, json.dumps(document), "")
        if "versions" in argv:
            document = observer_version if role == "observer" else jsda_version
            return subprocess.CompletedProcess(argv, 0, json.dumps(document), "")
        raise AssertionError(argv)

    def opener(request: Request, timeout: int = 30):
        url = request.full_url
        if "api.github.com" in url:
            payload = {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": pending_gate._NATIVE_CHECK_NAME,
                        "head_sha": SHA,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": pending_gate._NATIVE_CHECK_APP_ID},
                    }
                ],
            }
            return _FakeResponse(json.dumps(payload).encode())
        if "/v1/private/jsda-health-ready" in url:
            if request.get_header("Cf-access-client-id"):
                after_get["n"] += 1
                return _FakeResponse(
                    _observation_bytes(),
                    url=ACCESS_URL + "/v1/private/jsda-health-ready",
                )
            raise HTTPError(
                url, 403, "Forbidden", {"content-type": "application/json"}, BytesIO(b"{}")
            )
        if "include=modules" in url:
            version_id = OBSERVER_VERSION if OBSERVER_VERSION in url else JSDA_VERSION
            return _FakeResponse(
                _version_modules_envelope(
                    version_id=version_id,
                    main_module="index.js",
                    modules=[("index.js", "application/javascript+module", MODULE_BODY)],
                )
            )
        raise AssertionError(url)

    return tmp_path / "out", runner, opener, lambda: ticks[0]


def test_collect_keeps_jsda_503_audit_only_and_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, runner, opener, clock = _collect_seams(tmp_path, monkeypatch)
    facts = release.collect_and_stage_jsda_observation(
        output_dir=output,
        source_sha=SHA,
        runner=runner,
        opener=opener,
        clock=clock,
    )
    path = Path(facts["path"])
    document = json.loads(path.read_text(encoding="utf-8"))
    assert facts["publication_state"] == "STAGED_LOCAL_NOT_PUBLISHED"
    assert facts["release_allowed"] is False
    assert document["eligibility"] == "AUDIT_ONLY"
    assert document["jsda_http_status"] == 503
    assert document["observation"]["response_digest"] == INNER_DIGEST
    assert document["observation"]["exact_response_utf8"] == INNER.decode("utf-8")
    assert document["observer"]["source_provenance"]["main_module"] == "index.js"
    assert document["observed_at"] == "2026-09-14T12:00:00Z"
    first = path.read_bytes()
    with pytest.raises(
        release.ReleaseObservationAuthorityUnavailable, match="already exists"
    ):
        release.collect_and_stage_jsda_observation(
            output_dir=output,
            source_sha=SHA,
            runner=runner,
            opener=opener,
            clock=lambda: datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
        )
    assert path.read_bytes() == first


def test_collect_writes_nothing_when_selected_identity_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, runner, opener, _clock = _collect_seams(tmp_path, monkeypatch, drift=True)
    with pytest.raises(
        release.ReleaseObservationAuthorityUnavailable,
        match="identity changed during JSDA collection",
    ):
        release.collect_and_stage_jsda_observation(
            output_dir=output,
            source_sha=SHA,
            runner=runner,
            opener=opener,
            clock=lambda: datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
        )
    assert list(output.glob("*.json")) == []
