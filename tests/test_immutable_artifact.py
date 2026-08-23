"""Create-if-absent: local digest store and default R2 put. Not GO."""

import inspect
import json
import re
from pathlib import Path

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
        raise AssertionError("remote put must not CLI-put")

    monkeypatch.setattr(r2_io.subprocess, "run", boom)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", boom)
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

    monkeypatch.setattr(r2_io.subprocess, "run", boom)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", boom)
    with pytest.raises(R2IOError, match="use Worker children-then-manifest"):
        default_r2_put(
            "quant-structured",
            "research/eval/job=x/daily_path.json",
            b"{}",
            wrangler=wr,
            config=cfg,
        )


def test_default_r2_put_source_is_not_cli_put() -> None:
    src = inspect.getsource(default_r2_put)
    assert "subprocess" not in src
    assert "put_children_then_manifest_via_worker" in src
    assert PYTHON_R2_PUT_ENV in src
    assert "does not resurrect TOCTOU" in src
    assert "WORKER_CHILDREN_THEN_MANIFEST_ERROR" in src
    assert "never runs that CLI sequence" in src


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


def test_put_research_artifact_dry_run_is_local_default_r2_put(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
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
    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
    with pytest.raises(R2IOError, match="python must use Worker children-then-manifest"):
        put_research_artifact(
            "quant-structured",
            "research/eval/job=x/cost_verify.json",
            b'{"n": 1}',
        )


def test_research_job_callers_use_worker_put_not_cli() -> None:
    root = Path(__file__).resolve().parents[1] / "packages" / "product" / "research"
    remote_callers = (
        "cf_mass_eval_job.py",
        "cf_mass_eval_stage.py",
        "cf_mass_eval_run.py",
        "occupancy_audit.py",
        "cf_propose_thesis.py",
        "cf_cost_verify.py",
        "cf_daily_path_job.py",
    )
    for name in remote_callers:
        src = (root / name).read_text(encoding="utf-8")
        assert "put_research_artifact" in src
        assert "QP_ALLOW_PYTHON_R2_PUT" not in src
        if name == "cf_mass_eval_stage.py":
            assert "default_r2_put" not in src
        else:
            assert "default_r2_put(" not in src
    recon = (root / "reconstitution_evidence.py").read_text(encoding="utf-8")
    assert "put_research_artifact" in recon
    assert "dry_run=True" in recon
    assert "default_r2_put(" not in recon
    assert "QP_ALLOW_PYTHON_R2_PUT" not in recon
    helper = inspect.getsource(put_research_artifact)
    assert "put_children_then_manifest_via_worker" in helper
    assert "default_r2_put" in helper
    assert "does not grant CLI put" in (put_research_artifact.__doc__ or "")


def test_put_local_fallback_artifacts_default_remote_uses_worker_put(
    monkeypatch,
) -> None:
    from research.cf_mass_eval_job import design_mass_factory_paths
    from research.cf_mass_eval_run import put_local_fallback_artifacts

    monkeypatch.setenv(WORKER_PUT_URL_ENV, "https://example.invalid/worker")
    monkeypatch.setenv(WORKER_PUT_TOKEN_ENV, "tok")
    monkeypatch.setenv(PYTHON_R2_PUT_ENV, "1")
    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    seen: list[dict] = []

    class _Resp:
        status = 200

        def __init__(self, key: str) -> None:
            self._key = key

        def read(self):
            return json.dumps(
                {
                    "ok": True,
                    "conflict": False,
                    "verified": True,
                    "go": False,
                    "manifest": {"key": self._key, "created": True},
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        seen.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "data": payload,
                "headers": {k.lower(): v for k, v in req.header_items()},
            }
        )
        return _Resp(payload["manifest"]["key"])

    monkeypatch.setattr(r2_io.urllib.request, "urlopen", fake_urlopen)
    puts = put_local_fallback_artifacts(
        {"job_id": "fallback-test"},
        {"ok": True, "n_logics": 1},
    )
    assert seen
    assert all(s["url"].endswith("/v1/children-then-manifest") for s in seen)
    assert all(s["method"] == "POST" for s in seen)
    assert all(s["headers"].get("x-mass-eval-token") == "tok" for s in seen)
    assert all(s["data"]["children"] == [] for s in seen)
    assert all("digest" not in s["data"] for s in seen)
    keys = [s["data"]["manifest"]["key"] for s in seen]
    expected = design_mass_factory_paths("fallback-test")
    assert expected["manifest_r2_key"] in keys
    assert expected["input_plan_r2_key"] in keys
    assert expected["batch_summary_r2_key"] in keys
    assert all(p.get("status") == "put_ok" for p in puts)

    monkeypatch.delenv(WORKER_PUT_URL_ENV, raising=False)
    monkeypatch.delenv(WORKER_PUT_TOKEN_ENV, raising=False)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
    with pytest.raises(R2IOError, match="python must use Worker children-then-manifest"):
        put_local_fallback_artifacts({"job_id": "unbound"}, {"ok": True})

    injected: list[tuple[str, str]] = []

    def _injected(bucket, key, body, **_kwargs):
        injected.append((bucket, key))
        return {"status": "put_ok", "key": key}

    monkeypatch.setattr(r2_io.subprocess, "run", _boom_remote)
    monkeypatch.setattr(r2_io.urllib.request, "urlopen", _boom_remote)
    got = put_local_fallback_artifacts(
        {"job_id": "injected"},
        {"ok": True},
        r2_put=_injected,
    )
    assert injected
    assert all(bucket == "quant-structured" for bucket, _key in injected)
    assert all(p.get("status") == "put_ok" for p in got)


def test_try_r2_get_json_is_non_authority_get_miss_not_complete(monkeypatch) -> None:
    import research.cf_mass_eval_job as job
    from research.cf_mass_eval_job import try_r2_get_json

    src = inspect.getsource(try_r2_get_json)
    assert "r2" in src
    assert "object" in src
    assert "get" in src
    assert "--remote" in src
    assert "wrangler deploy" not in src
    assert "r2 object put" not in src
    # Honesty docs may say "not COMPLETE". Do not mint COMPLETE.
    for match in re.finditer(r"COMPLETE", src):
        window = src[max(0, match.start() - 24) : match.start()].lower()
        assert "not" in window, src[max(0, match.start() - 24) : match.end() + 12]

    def boom(*_a, **_k):
        raise OSError("no wrangler")

    monkeypatch.setattr(job.subprocess, "run", boom)
    got = try_r2_get_json("research/mass_eval/panels_cache/x/meta.json")
    assert got is None
