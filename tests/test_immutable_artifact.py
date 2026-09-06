"""Create-if-absent: local digest store and default R2 put. Not GO."""

import json
from pathlib import Path

import pytest

import ops.r2_cli as r2_cli
import ops.r2_io as r2_io
from ops.r2_io import (
    PYTHON_R2_PUT_ENV,
    R2IOError,
    WORKER_CHILDREN_THEN_MANIFEST_ERROR,
    WORKER_CHILDREN_THEN_MANIFEST_PATH,
    WORKER_PUT_TOKEN_ENV,
    WORKER_PUT_URL_ENV,
    default_r2_put,
    put_children_then_manifest_via_worker,
    put_research_artifact,
    python_r2_put_allowed,
)
from storage.immutable_artifact import ImmutableArtifactStore, content_digest


def test_create_if_absent_and_verify(tmp_path: Path):
    store = ImmutableArtifactStore(tmp_path)
    identity = {"kind": "x", "payload": {"n": 1}}
    ref1 = store.create_if_absent(identity)
    ref2 = store.create_if_absent(identity)
    assert ref1.artifact_id == ref2.artifact_id == content_digest(identity)
    assert ref1.created is True
    assert ref2.created is False
    body = store.verify(ref1.path, ref1.artifact_id)
    assert body["payload"]["n"] == 1


def test_dry_run_r2_put_does_not_need_wrangler(tmp_path: Path) -> None:
    got = default_r2_put(
        "quant-structured",
        "research/eval/job=x/daily_path.json",
        b"{}",
        dry_run=True,
        staging_dir=tmp_path,
    )
    assert got["status"] == "dry_run"
    assert got.get("created") is not True


def test_dry_run_r2_put_does_not_call_remote(tmp_path: Path, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise AssertionError("dry_run must not call remote")

    monkeypatch.setattr(r2_cli.subprocess, "run", boom)
    got = default_r2_put(
        "quant-structured",
        "research/eval/job=x/daily_path.json",
        b"{}",
        dry_run=True,
        staging_dir=tmp_path,
    )
    assert got["status"] == "dry_run"
    assert got.get("created") is not True
    staged = Path(got["staged_path"])
    assert staged.read_bytes() == b"{}"


def test_default_r2_put_authoritative_is_refused(monkeypatch) -> None:
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    with pytest.raises(R2IOError, match="python CLI put is not artifact authority"):
        default_r2_put(
            "quant-structured",
            "research/eval/job=x/daily_path.json",
            b"{}",
            authoritative=True,
            dry_run=True,
        )


def test_python_r2_put_allowed_is_exactly_one(monkeypatch) -> None:
    monkeypatch.delenv(PYTHON_R2_PUT_ENV, raising=False)
    assert python_r2_put_allowed() is False
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "true")
    assert python_r2_put_allowed() is False
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    assert python_r2_put_allowed() is True


def test_remote_r2_put_fail_closed_without_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(PYTHON_R2_PUT_ENV, raising=False)
    wr = tmp_path / "wrangler"
    wr.write_text("")
    cfg = tmp_path / "wrangler.toml"
    cfg.write_text("")

    def boom(*_a, **_k):
        raise AssertionError("remote put must not CLI-put")

    monkeypatch.setattr(r2_cli.subprocess, "run", boom)
    monkeypatch.setattr(r2_io, "post_json_object", boom)
    with pytest.raises(R2IOError, match="use Worker children-then-manifest"):
        default_r2_put(
            "quant-structured",
            "research/eval/job=x/daily_path.json",
            b"{}",
            wrangler=wr,
            config=cfg,
        )
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "true")
    with pytest.raises(R2IOError, match="use Worker children-then-manifest"):
        default_r2_put(
            "quant-structured",
            "research/eval/job=x/daily_path.json",
            b"{}",
            wrangler=wr,
            config=cfg,
        )


def test_remote_r2_put_does_not_cli_put_with_overlay(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    wr = tmp_path / "wrangler"
    wr.write_text("")
    cfg = tmp_path / "wrangler.toml"
    cfg.write_text("")

    def boom(*_a, **_k):
        raise AssertionError("overlay must not resurrect CLI TOCTOU put")

    monkeypatch.setattr(r2_cli.subprocess, "run", boom)
    monkeypatch.setattr(r2_io, "post_json_object", boom)
    with pytest.raises(R2IOError, match="use Worker children-then-manifest"):
        default_r2_put(
            "quant-structured",
            "research/eval/job=x/daily_path.json",
            b"{}",
            wrangler=wr,
            config=cfg,
        )


def _children_then_manifest_payload() -> tuple[list[dict], dict]:
    children = [{"key": "research/eval/job=x/child.json", "data": {"n": 1}}]
    manifest = {
        "key": "research/eval/job=x/manifest.json",
        "data": {"artifact_key": "research/eval/job=x/child.json"},
    }
    return children, manifest


def test_worker_put_env_names_are_mass_eval() -> None:
    assert WORKER_PUT_URL_ENV == "MASS_EVAL_WORKER_URL"
    assert WORKER_PUT_TOKEN_ENV == "MASS_EVAL_TOKEN"
    assert WORKER_CHILDREN_THEN_MANIFEST_PATH == "/v1/children-then-manifest"
    assert WORKER_CHILDREN_THEN_MANIFEST_ERROR == (
        "python must use Worker children-then-manifest; CLI put is not authority"
    )


def _boom_remote(*_a, **_k):
    raise AssertionError("must not call remote")


def test_dry_run_children_then_manifest_is_local_only(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv(WORKER_PUT_URL_ENV, raising=False)
    monkeypatch.delenv(WORKER_PUT_TOKEN_ENV, raising=False)

    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    children, manifest = _children_then_manifest_payload()
    got = put_children_then_manifest_via_worker(
        children, manifest, dry_run=True, staging_dir=tmp_path
    )
    assert got["status"] == "dry_run"
    assert got.get("created") is not True
    assert "digest" not in got
    assert got["manifest_key"] == "research/eval/job=x/manifest.json"
    staged = [Path(p) for p in got["staged_paths"]]
    assert [p.name for p in staged] == [
        "research__eval__job=x__child.json",
        "research__eval__job=x__manifest.json",
    ]
    assert b'"n": 1' in staged[0].read_bytes()
    assert "artifact_key" in staged[-1].read_text()


def test_remote_children_then_manifest_fail_closed_unbound(monkeypatch) -> None:
    monkeypatch.delenv(PYTHON_R2_PUT_ENV, raising=False)
    monkeypatch.delenv(WORKER_PUT_URL_ENV, raising=False)
    monkeypatch.delenv(WORKER_PUT_TOKEN_ENV, raising=False)

    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    children, manifest = _children_then_manifest_payload()
    with pytest.raises(R2IOError, match="closed artifact put port is required"):
        put_children_then_manifest_via_worker(children, manifest)


def test_remote_children_then_manifest_url_only_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.delenv(WORKER_PUT_TOKEN_ENV, raising=False)
    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    children, manifest = _children_then_manifest_payload()
    with pytest.raises(R2IOError, match="closed artifact put port is required"):
        put_children_then_manifest_via_worker(children, manifest)


def test_remote_children_then_manifest_posts_when_bound(monkeypatch) -> None:
    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.setenv(WORKER_PUT_TOKEN_ENV, "tok")
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    seen: dict = {}

    def fake_post(*, url, body, headers):
        seen["url"] = url
        seen["body"] = json.loads(body)
        seen["headers"] = headers
        return {
            "ok": True,
            "conflict": False,
            "verified": True,
            "go": False,
            "children": [
                {
                    "key": "research/eval/job=x/child.json",
                    "created": True,
                    "digest": "sha256:from-worker",
                }
            ],
            "manifest": {
                "key": "research/eval/job=x/manifest.json",
                "created": True,
                "digest": "sha256:from-worker-manifest",
            },
        }

    children, manifest = _children_then_manifest_payload()
    got = put_children_then_manifest_via_worker(
        children, manifest, http_post=fake_post
    )
    assert seen["url"] == "https://example.invalid/worker/v1/children-then-manifest"
    assert seen["headers"]["X-Mass-Eval-Token"] == "tok"
    assert seen["headers"]["Content-Type"] == "application/json"
    assert seen["body"] == {
        "children": [
            {"key": "research/eval/job=x/child.json", "data": {"n": 1}}
        ],
        "manifest": {
            "key": "research/eval/job=x/manifest.json",
            "data": {"artifact_key": "research/eval/job=x/child.json"},
        },
    }
    assert "digest" not in seen["body"]
    assert "expected_child_digest" not in seen["body"]
    assert got["status"] == "put_ok"
    assert got["ok"] is True
    assert got["created"] is True
    assert got["manifest_key"] == "research/eval/job=x/manifest.json"
    assert "digest" not in got


def test_remote_children_then_manifest_stdlib_http_stub(monkeypatch) -> None:
    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.setenv(WORKER_PUT_TOKEN_ENV, "tok")
    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    seen: dict = {}

    class _Resp:
        status = 200

        def read(self):
            return json.dumps(
                {
                    "ok": True,
                    "conflict": False,
                    "verified": True,
                    "go": False,
                    "manifest": {
                        "key": "research/eval/job=x/manifest.json",
                        "created": True,
                    },
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_post(*, url, body, headers, timeout=120):
        seen["url"] = url
        seen["method"] = "POST"
        seen["data"] = json.loads(body.decode("utf-8"))
        seen["headers"] = {k.lower(): v for k, v in headers.items()}
        seen["timeout"] = timeout
        return {
            "ok": True,
            "conflict": False,
            "verified": True,
            "go": False,
            "status": "put_ok",
            "manifest": {
                "key": "research/eval/job=x/manifest.json",
                "created": True,
            },
        }

    monkeypatch.setattr(r2_io, "post_json_object", fake_post)
    children, manifest = _children_then_manifest_payload()
    got = put_children_then_manifest_via_worker(
        children, manifest, http_post=r2_io.post_json_object
    )
    assert seen["url"].endswith("/v1/children-then-manifest")
    assert seen["method"] == "POST"
    assert seen["headers"].get("x-mass-eval-token") == "tok"
    assert seen["data"]["children"][0]["data"] == {"n": 1}
    assert "digest" not in seen["data"]
    assert got["ok"] is True
    assert got["status"] == "put_ok"


def test_remote_children_then_manifest_conflict_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.setenv(WORKER_PUT_TOKEN_ENV, "tok")
    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    children, manifest = _children_then_manifest_payload()

    def fake_post(*, url, body, headers):
        return {"ok": False, "error": "artifact_conflict", "conflict": True}

    with pytest.raises(R2IOError, match="artifact_conflict"):
        put_children_then_manifest_via_worker(
            children, manifest, http_post=fake_post
        )


def test_remote_children_then_manifest_non_json_body_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.setenv(WORKER_PUT_TOKEN_ENV, "tok")
    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    children = [{"key": "research/eval/job=x/child.json", "body": b"not-json"}]
    manifest = {
        "key": "research/eval/job=x/manifest.json",
        "data": {"artifact_key": "research/eval/job=x/child.json"},
    }
    with pytest.raises(R2IOError, match="not JSON"):
        put_children_then_manifest_via_worker(
            children, manifest, http_post=_boom_remote
        )


def test_put_research_artifact_dry_run_is_local_default_r2_put(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    got = put_research_artifact(
        "quant-structured",
        "research/eval/job=x/cost_verify.json",
        b'{"n": 1}',
        dry_run=True,
        staging_dir=tmp_path,
    )
    assert got["status"] == "dry_run"
    assert got.get("created") is not True
    staged = Path(got["staged_path"])
    assert staged.read_bytes() == b'{"n": 1}'


def test_put_research_artifact_remote_posts_worker_not_cli(
    monkeypatch,
) -> None:
    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.setenv(WORKER_PUT_TOKEN_ENV, "tok")
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    seen: dict = {}

    def fake_post(*, url, body, headers):
        seen["url"] = url
        seen["body"] = json.loads(body)
        seen["headers"] = headers
        return {
            "ok": True,
            "conflict": False,
            "verified": True,
            "go": False,
            "manifest": {
                "key": "research/eval/job=x/cost_verify.json",
                "created": True,
            },
        }

    got = put_research_artifact(
        "quant-structured",
        "research/eval/job=x/cost_verify.json",
        b'{"n": 1}',
        http_post=fake_post,
    )
    assert seen["url"].endswith("/v1/children-then-manifest")
    assert seen["headers"]["X-Mass-Eval-Token"] == "tok"
    assert seen["body"] == {
        "children": [],
        "manifest": {
            "key": "research/eval/job=x/cost_verify.json",
            "data": {"n": 1},
        },
    }
    assert got["status"] == "put_ok"
    assert got["ok"] is True
    assert got.get("created") is True


def test_put_research_artifact_remote_unbound_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv(WORKER_PUT_URL_ENV, raising=False)
    monkeypatch.delenv(WORKER_PUT_TOKEN_ENV, raising=False)
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    monkeypatch.setattr(r2_cli.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io, "post_json_object", _boom_remote)
    with pytest.raises(R2IOError, match="closed artifact put port is required"):
        put_research_artifact(
            "quant-structured",
            "research/eval/job=x/cost_verify.json",
            b'{"n": 1}',
        )


def test_put_local_fallback_artifacts_is_mass_disabled(monkeypatch) -> None:
    from research.cf_mass_eval_run import put_local_fallback_artifacts
    from selection.budget_ledger import MassResearchDisabledError

    with pytest.raises(MassResearchDisabledError, match="put_local_fallback_artifacts"):
        put_local_fallback_artifacts(
            {"job_id": "fallback-test"},
            {"ok": True, "n_logics": 1},
            r2_put=lambda *_a, **_k: {"status": "put_ok"},
        )
