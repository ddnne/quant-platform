"""Create-if-absent: local digest store and default R2 put. Not GO."""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import research.r2_io as r2_io
from research.r2_io import (
    PYTHON_R2_PUT_ENV,
    R2IOError,
    WORKER_CHILDREN_THEN_MANIFEST_ERROR,
    WORKER_CHILDREN_THEN_MANIFEST_PATH,
    WORKER_PUT_TOKEN_ENV,
    WORKER_PUT_URL_ENV,
    default_r2_put,
    put_children_then_manifest_via_worker,
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

    monkeypatch.setattr(r2_io.subprocess, "run", boom)
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


def test_default_r2_put_documents_toctou_not_atomic() -> None:
    sig = inspect.signature(default_r2_put)
    assert sig.parameters["create_only"].default is True
    assert sig.parameters["authoritative"].default is False
    text = f"{default_r2_put.__doc__ or ''}\n{inspect.getsource(default_r2_put)}"
    assert "TOCTOU" in text
    assert "not the immutable authority" in text
    assert "Worker onlyIf" in text
    assert "not artifact authority" in text
    assert PYTHON_R2_PUT_ENV in text
    assert "TOCTOU" in (r2_io.__doc__ or "")
    assert "not artifact authority" in (r2_io.__doc__ or "")
    assert r2_io.python_cli_put_is_not_immutable_authority is True


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
        raise AssertionError("remote put must not run without env")

    monkeypatch.setattr(r2_io.subprocess, "run", boom)
    with pytest.raises(R2IOError, match=rf"{PYTHON_R2_PUT_ENV}=1"):
        default_r2_put(
            "quant-structured",
            "research/eval/job=x/daily_path.json",
            b"{}",
            wrangler=wr,
            config=cfg,
        )
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "true")
    with pytest.raises(R2IOError, match="not artifact authority"):
        default_r2_put(
            "quant-structured",
            "research/eval/job=x/daily_path.json",
            b"{}",
            wrangler=wr,
            config=cfg,
        )


def test_create_only_head_success_skips_put(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    wr = tmp_path / "wrangler"
    wr.write_text("")
    cfg = tmp_path / "wrangler.toml"
    cfg.write_text("")
    seen: list[list[str]] = []

    def fake_run(cmd, **_k):
        seen.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(r2_io.subprocess, "run", fake_run)
    got = default_r2_put(
        "quant-structured",
        "research/eval/job=x/daily_path.json",
        b"{}",
        wrangler=wr,
        config=cfg,
    )
    assert got["status"] == "exists"
    assert got["created"] is False
    assert len(seen) == 1
    assert "head" in seen[0]
    assert "put" not in seen[0]


def test_create_only_head_miss_calls_put(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    wr = tmp_path / "wrangler"
    wr.write_text("")
    cfg = tmp_path / "wrangler.toml"
    cfg.write_text("")
    seen: list[list[str]] = []

    def fake_run(cmd, **_k):
        seen.append(list(cmd))
        if "head" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="not found")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(r2_io.subprocess, "run", fake_run)
    got = default_r2_put(
        "quant-structured",
        "research/eval/job=x/daily_path.json",
        b"{}",
        wrangler=wr,
        config=cfg,
    )
    assert got["status"] == "put_ok"
    assert got["created"] is True
    assert any("head" in c for c in seen)
    assert any("put" in c for c in seen)


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

    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
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

    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
    children, manifest = _children_then_manifest_payload()
    with pytest.raises(R2IOError, match="python must use Worker children-then-manifest"):
        put_children_then_manifest_via_worker(children, manifest)


def test_remote_children_then_manifest_url_only_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.delenv(WORKER_PUT_TOKEN_ENV, raising=False)
    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
    children, manifest = _children_then_manifest_payload()
    with pytest.raises(R2IOError, match="python must use Worker children-then-manifest"):
        put_children_then_manifest_via_worker(children, manifest)


def test_remote_children_then_manifest_posts_when_bound(monkeypatch) -> None:
    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.setenv(WORKER_PUT_TOKEN_ENV, "tok")
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
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
    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
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

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["data"] = json.loads(req.data.decode("utf-8"))
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(r2_io.urllib.request, "urlopen", fake_urlopen)
    children, manifest = _children_then_manifest_payload()
    got = put_children_then_manifest_via_worker(children, manifest)
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
    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
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
    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
    children = [{"key": "research/eval/job=x/child.json", "body": b"not-json"}]
    manifest = {
        "key": "research/eval/job=x/manifest.json",
        "data": {"artifact_key": "research/eval/job=x/child.json"},
    }
    with pytest.raises(R2IOError, match="not JSON"):
        put_children_then_manifest_via_worker(children, manifest)


def test_children_then_manifest_source_is_not_cli_or_digest_forge() -> None:
    src = inspect.getsource(put_children_then_manifest_via_worker)
    helper = inspect.getsource(r2_io._post_worker_children_then_manifest)
    combined = f"{src}\n{helper}\n{inspect.getsource(r2_io._item_json_data)}"
    assert "default_r2_put" not in combined
    assert "subprocess" not in combined
    assert "hashlib" not in combined
    assert "sha256" not in combined
    assert "httpx" not in combined
    assert "wrangler" not in combined
    assert "WORKER_CHILDREN_THEN_MANIFEST_ERROR" in src
    assert "WORKER_CHILDREN_THEN_MANIFEST_PATH" in src
    assert "X-Mass-Eval-Token" in helper
    doc = put_children_then_manifest_via_worker.__doc__ or ""
    assert "CLI put is not authority" in doc
    assert "no digest forge" in doc
    assert "dry_run" in doc
