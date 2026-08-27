from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import receipt_authority_pending_live_acceptance as live


SHA = "1" * 40
ACCOUNT = "2" * 32


def _documents(environment: str) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    manifest = live.build_manifest()
    deployments: dict[str, Any] = {}
    versions: dict[str, Any] = {}
    public: dict[str, Any] = {}
    source_provenance: dict[str, Any] = {}
    for ordinal, (role, worker) in enumerate(live.CHAIN, start=1):
        surface = manifest["workers"][worker][environment]
        deployment_id = f"00000000-0000-4000-8000-{ordinal:012d}"
        version_id = f"10000000-0000-4000-8000-{ordinal:012d}"
        deployments[role] = {
            "id": deployment_id,
            "source": "wrangler",
            "strategy": "percentage",
            "annotations": {
                "workers/message": live.deployment_message(role, environment, SHA),
                "workers/triggered_by": "deployment",
            },
            "versions": [{"version_id": version_id, "percentage": 100}],
        }
        bindings = []
        for row in live._expected_bindings(surface).values():  # noqa: SLF001
            materialized = copy.deepcopy(row)
            if materialized.get("namespace_id") == "<LIVE_NAMESPACE_ID>":
                materialized["namespace_id"] = f"{ordinal:x}" * 32
            bindings.append(materialized)
        handlers = ["fetch"] + (["scheduled"] if surface["crons"] else [])
        script_resource: dict[str, Any] = {
            "etag": f"{ordinal:x}" * 64,
            "handlers": handlers,
            "last_deployed_from": "wrangler",
        }
        named_handlers = live._expected_named_handlers(surface)  # noqa: SLF001
        if named_handlers:
            script_resource["named_handlers"] = copy.deepcopy(named_handlers)
        script_runtime: dict[str, Any] = {
            "compatibility_date": surface["compatibility_date"],
            "usage_model": "standard",
        }
        migration_tag = live._expected_migration_tag(surface)  # noqa: SLF001
        if migration_tag is not None:
            script_runtime["migration_tag"] = migration_tag
        versions[role] = {
            "id": version_id,
            "annotations": {
                "workers/message": live.deployment_message(role, environment, SHA),
                "workers/tag": live.version_tag(role, environment, SHA),
                "workers/triggered_by": "version_upload",
            },
            "metadata": {
                "created_on": "2026-08-27T08:00:00.000000Z",
                "source": "wrangler",
                "has_preview": False,
            },
            "resources": {
                "script": script_resource,
                "script_runtime": script_runtime,
                "bindings": bindings,
            },
        }
        public[role] = {
            "subdomain": {
                "enabled": surface["workers_dev"],
                "previews_enabled": surface["preview_urls"],
            },
            "routes": [],
            "custom_domains": [],
            "custom_domain_total": 0,
            "schedules": {
                "schedules": [
                    {
                        "cron": cron,
                        "created_on": "2026-08-27T08:00:00.000000Z",
                        "modified_on": "2026-08-27T08:00:00.000000Z",
                    }
                    for cron in surface["crons"]
                ]
            },
            "script_settings": {
                "logpush": False,
                "observability": copy.deepcopy(surface["observability"]),
                "tail_consumers": copy.deepcopy(surface["tail_consumers"]),
            },
        }
        digest = "sha256:" + f"{ordinal:x}" * 64
        source_provenance[role] = {
            "local_main_module": "index.js",
            "local_main_module_digest": digest,
            "local_main_module_bytes": 100 + ordinal,
            "live_main_module": "src/index.js",
            "live_main_module_digest": digest,
            "live_main_module_bytes": 100 + ordinal,
        }
    return deployments, versions, public, source_provenance


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_exact_live_pending_chain_is_read_only_and_source_bound(
    environment: str,
) -> None:
    deployments, versions, public, source_provenance = _documents(environment)
    result = live.validate_live_pending_receipt_chain(
        environment=environment,
        source_sha=SHA,
        account_id=ACCOUNT,
        deployments=deployments,
        versions=versions,
        public_surfaces=public,
        source_provenance=source_provenance,
    )
    assert result["format"] == "receipt-authority-pending-live-acceptance/v1"
    assert result["source_sha"] == SHA
    assert result["account_id"] == ACCOUNT
    assert result["authority_mode"] == "PENDING"
    assert result["active_key_count"] == 0
    assert result["positive_operation_allowed"] is False
    assert result["research_eligible"] is False
    assert result["source_provenance"] == "VERIFIED_EXACT_MODULE_BYTES"
    assert set(result["workers"]) == {"acquisition", "authority", "caller"}
    assert all(row["traffic_percent"] == 100 for row in result["workers"].values())
    assert all(
        row["source_provenance"]["status"] == "VERIFIED_EXACT_MODULE_BYTES"
        for row in result["workers"].values()
    )


def test_staging_chain_declares_only_minimum_non_proxy_secrets() -> None:
    deployments, versions, public, source_provenance = _documents("staging")
    result = live.validate_live_pending_receipt_chain(
        environment="staging",
        source_sha=SHA,
        account_id=ACCOUNT,
        deployments=deployments,
        versions=versions,
        public_surfaces=public,
        source_provenance=source_provenance,
    )
    assert result["workers"]["acquisition"]["secret_binding_names"] == [
        "JQUANTS_API_KEY",
        "JQUANTS_RPC_CURSOR_HMAC_KEY",
    ]
    assert result["workers"]["caller"]["secret_binding_names"] == [
        "INGESTION_RUN_TOKEN"
    ]
    assert result["workers"]["authority"]["secret_binding_names"] == [
        "RECEIPT_KEY_WRAP_KEY"
    ]
    assert "JQUANTS_PROXY_TOKEN" not in json.dumps(result)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda deployments, _versions, _public: deployments["authority"][
                "annotations"
            ].update({"workers/message": "caller-supplied"}),
            "reviewed source SHA",
        ),
        (
            lambda deployments, _versions, _public: deployments["authority"].update(
                versions=[
                    {
                        "version_id": "10000000-0000-4000-8000-000000000002",
                        "percentage": 90,
                    },
                    {
                        "version_id": "10000000-0000-4000-8000-000000000003",
                        "percentage": 10,
                    },
                ]
            ),
            "one version at 100 percent",
        ),
        (
            lambda _deployments, versions, _public: versions["authority"][
                "resources"
            ]["bindings"].append(
                {"name": "SIGN_CALLER_CLAIMS", "type": "plain_text", "text": "true"}
            ),
            "binding-name inventory",
        ),
        (
            lambda _deployments, versions, _public: next(
                row
                for row in versions["authority"]["resources"]["bindings"]
                if row["name"] == "AUTHORITY_MODE"
            ).update(text="ACTIVE"),
            "AUTHORITY_MODE.*drifted",
        ),
        (
            lambda _deployments, _versions, public: public["authority"].update(
                routes=[{"pattern": "authority.example/*"}]
            ),
            "undeclared route",
        ),
        (
            lambda _deployments, _versions, public: public["authority"][
                "schedules"
            ]["schedules"].append({"cron": "* * * * *"}),
            "Cron trigger surface",
        ),
        (
            lambda _deployments, _versions, public: public["authority"][
                "script_settings"
            ].update(tail_consumers=[{"service": "log-exfiltrator"}]),
            "tail-consumer capability",
        ),
    ],
)
def test_live_chain_fails_closed_on_source_traffic_binding_and_route_drift(
    mutate,
    match: str,
) -> None:
    deployments, versions, public, source_provenance = _documents("staging")
    mutate(deployments, versions, public)
    with pytest.raises(live.ReceiptPendingLiveAcceptanceError, match=match):
        live.validate_live_pending_receipt_chain(
            environment="staging",
            source_sha=SHA,
            account_id=ACCOUNT,
            deployments=deployments,
            versions=versions,
            public_surfaces=public,
            source_provenance=source_provenance,
        )


def test_live_chain_rejects_extra_resource_capability_surface() -> None:
    deployments, versions, public, source_provenance = _documents("staging")
    versions["authority"]["resources"]["unsafe_capability"] = {"enabled": True}
    with pytest.raises(
        live.ReceiptPendingLiveAcceptanceError,
        match="undeclared resource surface",
    ):
        live.validate_live_pending_receipt_chain(
            environment="staging",
            source_sha=SHA,
            account_id=ACCOUNT,
            deployments=deployments,
            versions=versions,
            public_surfaces=public,
            source_provenance=source_provenance,
        )


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda versions, _public: versions["authority"]["resources"][
                "script"
            ].update({"undeclared_module_loader": True}),
            "script handler, source, or etag drifted",
        ),
        (
            lambda versions, _public: versions["authority"]["resources"][
                "script_runtime"
            ].update({"unsafe_runtime_capability": True}),
            "compatibility runtime drifted",
        ),
        (
            lambda _versions, public: public["authority"]["script_settings"][
                "observability"
            ].update({"logs": {"destinations": ["external-log-sink"]}}),
            "observability settings drifted",
        ),
        (
            lambda _versions, public: public["authority"]["script_settings"].update(
                {"unsafe_export": {"destination": "external"}}
            ),
            "undeclared capability",
        ),
        (
            lambda _versions, public: public["authority"]["script_settings"].update(
                {"tags": ["unexpected-capability-tag"]}
            ),
            "log export or tail-consumer capability",
        ),
    ],
)
def test_live_chain_rejects_nested_and_extra_version_capabilities(
    mutate,
    match: str,
) -> None:
    deployments, versions, public, source_provenance = _documents("staging")
    mutate(versions, public)
    with pytest.raises(live.ReceiptPendingLiveAcceptanceError, match=match):
        live.validate_live_pending_receipt_chain(
            environment="staging",
            source_sha=SHA,
            account_id=ACCOUNT,
            deployments=deployments,
            versions=versions,
            public_surfaces=public,
            source_provenance=source_provenance,
        )


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda script, _runtime: script.pop("named_handlers"),
            "script handler, source, or etag drifted",
        ),
        (
            lambda script, _runtime: script["named_handlers"][0].update(
                name="CallerSelectedAuthority"
            ),
            "script handler, source, or etag drifted",
        ),
        (
            lambda script, _runtime: script["named_handlers"].append(
                {"name": "UnexpectedAuthority", "handlers": ["class"]}
            ),
            "script handler, source, or etag drifted",
        ),
        (
            lambda _script, runtime: runtime.pop("migration_tag"),
            "compatibility runtime drifted",
        ),
        (
            lambda _script, runtime: runtime.update(migration_tag="caller-v2"),
            "compatibility runtime drifted",
        ),
        (
            lambda _script, runtime: runtime.update(unknown_runtime_field="v1"),
            "compatibility runtime drifted",
        ),
    ],
)
def test_live_chain_requires_exact_named_handlers_and_migration_tag(
    mutate,
    match: str,
) -> None:
    deployments, versions, public, source_provenance = _documents("staging")
    authority = versions["authority"]["resources"]
    mutate(authority["script"], authority["script_runtime"])
    with pytest.raises(live.ReceiptPendingLiveAcceptanceError, match=match):
        live.validate_live_pending_receipt_chain(
            environment="staging",
            source_sha=SHA,
            account_id=ACCOUNT,
            deployments=deployments,
            versions=versions,
            public_surfaces=public,
            source_provenance=source_provenance,
        )


@pytest.mark.parametrize("role", ["acquisition", "caller"])
def test_live_chain_rejects_named_handlers_or_migration_tag_without_manifest_authority(
    role: str,
) -> None:
    deployments, versions, public, source_provenance = _documents("staging")
    resources = versions[role]["resources"]
    resources["script"]["named_handlers"] = [
        {"name": "UnexpectedAuthority", "handlers": ["class"]}
    ]
    resources["script_runtime"]["migration_tag"] = "v1"
    with pytest.raises(live.ReceiptPendingLiveAcceptanceError):
        live.validate_live_pending_receipt_chain(
            environment="staging",
            source_sha=SHA,
            account_id=ACCOUNT,
            deployments=deployments,
            versions=versions,
            public_surfaces=public,
            source_provenance=source_provenance,
        )


def test_live_chain_rejects_module_bytes_not_built_from_reviewed_source() -> None:
    deployments, versions, public, source_provenance = _documents("staging")
    source_provenance["authority"]["live_main_module_digest"] = "sha256:" + "f" * 64
    with pytest.raises(
        live.ReceiptPendingLiveAcceptanceError,
        match="differs from the clean reviewed source build",
    ):
        live.validate_live_pending_receipt_chain(
            environment="staging",
            source_sha=SHA,
            account_id=ACCOUNT,
            deployments=deployments,
            versions=versions,
            public_surfaces=public,
            source_provenance=source_provenance,
        )


def test_production_acquisition_public_surface_is_explicit_not_hidden() -> None:
    deployments, versions, public, source_provenance = _documents("production")
    result = live.validate_live_pending_receipt_chain(
        environment="production",
        source_sha=SHA,
        account_id=ACCOUNT,
        deployments=deployments,
        versions=versions,
        public_surfaces=public,
        source_provenance=source_provenance,
    )
    assert result["workers"]["acquisition"]["public_surface"] == {
        "workers_dev": True,
        "preview_urls": False,
        "route_count": 0,
        "custom_domain_count": 0,
        "cron_triggers": [],
        "logpush": False,
        "tail_consumer_count": 0,
        "observability_enabled": True,
        "observability_head_sampling_rate": 1,
    }
    assert result["workers"]["authority"]["public_surface"]["workers_dev"] is False
    assert result["workers"]["caller"]["public_surface"]["workers_dev"] is False


def test_strict_json_rejects_duplicate_keys_and_non_finite_values() -> None:
    with pytest.raises(live.ReceiptPendingLiveAcceptanceError, match="duplicates"):
        live._load_json('{"id":1,"id":2}', label="test")  # noqa: SLF001
    with pytest.raises(live.ReceiptPendingLiveAcceptanceError, match="non-finite"):
        live._load_json('{"value":NaN}', label="test")  # noqa: SLF001


def test_public_surface_inventory_is_get_only_and_includes_cron_and_tail() -> None:
    calls: list[Any] = []

    class Response:
        def __init__(self, document: dict[str, Any]) -> None:
            self.raw = json.dumps(document).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, bound: int) -> bytes:
            return self.raw[:bound]

    def opener(request, *, timeout: int):
        calls.append(request)
        url = request.full_url
        result_info = None
        if url.endswith("/subdomain"):
            result = {"enabled": False, "previews_enabled": False}
        elif "/routes?" in url:
            result = []
        elif "/domains/records?" in url:
            assert "page=1" in url
            result = []
            result_info = {"total_count": 0}
        elif url.endswith("/schedules"):
            result = {"schedules": []}
        elif url.endswith("/script-settings"):
            result = {
                "logpush": False,
                "observability": {"enabled": True, "head_sampling_rate": 1},
                "tail_consumers": [],
            }
        else:  # pragma: no cover - closes the endpoint inventory
            raise AssertionError(url)
        document = {"success": True, "errors": [], "result": result}
        if result_info is not None:
            document["result_info"] = result_info
        assert timeout == 30
        return Response(document)

    result = live._live_public_surface(  # noqa: SLF001
        worker_name="quant-platform-receipt-evidence-authority-staging",
        account_id=ACCOUNT,
        api_token="read-only-token",
        opener=opener,
    )
    assert result["schedules"] == {"schedules": []}
    assert result["script_settings"]["tail_consumers"] == []
    assert len(calls) == 5
    assert all(request.get_method() == "GET" for request in calls)
    assert all(
        request.get_header("Authorization") == "Bearer read-only-token"
        for request in calls
    )


@pytest.mark.parametrize("live_matches", [True, False])
def test_source_provenance_compares_secretless_local_build_to_live_main(
    monkeypatch: pytest.MonkeyPatch,
    live_matches: bool,
) -> None:
    worker = "ingestion-secrets"
    executable = (
        live.ROOT / "platform" / "workers" / worker / "node_modules" / ".bin" / "wrangler"
    )
    assert executable.is_file()
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "must-not-enter-local-build")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-enter-local-build")
    calls: list[dict[str, Any]] = []
    local_bundle = b"export default {fetch(){return new Response('pending')}};\n"
    live_bundle = local_bundle if live_matches else local_bundle + b"// drift\n"

    def runner(command, **kwargs):
        command = tuple(command)
        calls.append({"command": command, **kwargs})
        if "deploy" in command:
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / "index.js").write_bytes(local_bundle)
        elif "init" in command:
            downloaded = Path(kwargs["cwd"]) / "quant-platform-ingestion-secrets-staging"
            (downloaded / "src").mkdir(parents=True)
            (downloaded / "wrangler.jsonc").write_text(
                json.dumps({"main": "src/index.js"}), encoding="utf-8"
            )
            (downloaded / "src" / "index.js").write_bytes(live_bundle)
        else:  # pragma: no cover - keeps the fake closed if the command changes
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    if live_matches:
        result = live._source_provenance(  # noqa: SLF001
            worker=worker,
            worker_name="quant-platform-ingestion-secrets-staging",
            environment="staging",
            account_id=ACCOUNT,
            api_token="read-only-token",
            runner=runner,
        )
        assert result["local_main_module_digest"] == result["live_main_module_digest"]
        assert result["local_main_module_bytes"] == len(local_bundle)
    else:
        with pytest.raises(
            live.ReceiptPendingLiveAcceptanceError,
            match="differs from the clean reviewed source build",
        ):
            live._source_provenance(  # noqa: SLF001
                worker=worker,
                worker_name="quant-platform-ingestion-secrets-staging",
                environment="staging",
                account_id=ACCOUNT,
                api_token="read-only-token",
                runner=runner,
            )
    local_environment = calls[0]["env"]
    assert "CLOUDFLARE_API_TOKEN" not in local_environment
    assert "CLOUDFLARE_ACCOUNT_ID" not in local_environment
    assert "AWS_SECRET_ACCESS_KEY" not in local_environment
    assert local_environment["HOME"] != str(Path.home())
    assert Path(local_environment["HOME"]).name == "isolated-home"
    assert Path(local_environment["XDG_CONFIG_HOME"]).name == "isolated-config"
    assert Path(local_environment["WRANGLER_HOME"]).name == "isolated-wrangler"
    assert local_environment["WRANGLER_SEND_METRICS"] == "false"
    live_environment = calls[1]["env"]
    assert live_environment["CLOUDFLARE_API_TOKEN"] == "read-only-token"
    assert live_environment["CLOUDFLARE_ACCOUNT_ID"] == ACCOUNT
    assert "AWS_SECRET_ACCESS_KEY" not in live_environment
    assert live_environment["HOME"] != str(Path.home())
    assert Path(live_environment["HOME"]).name == "isolated-home"
    assert live_environment["WRANGLER_SEND_METRICS"] == "false"


def test_wrangler_inventory_receives_only_explicit_cloudflare_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-enter-inventory")
    monkeypatch.setenv("CLOUDFLARE_API_KEY", "legacy-key-must-not-enter-inventory")
    calls: list[dict[str, Any]] = []

    def runner(command, **kwargs):
        calls.append({"command": tuple(command), **kwargs})
        return subprocess.CompletedProcess(command, 0, "{}", "")

    assert live._wrangler_json(  # noqa: SLF001
        worker="ingestion-secrets",
        environment="staging",
        arguments=("deployments", "status", "--json"),
        account_id=ACCOUNT,
        api_token="read-only-token",
        runner=runner,
    ) == {}
    environment = calls[0]["env"]
    assert environment["CLOUDFLARE_ACCOUNT_ID"] == ACCOUNT
    assert environment["CLOUDFLARE_API_TOKEN"] == "read-only-token"
    assert "CLOUDFLARE_API_KEY" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment
    assert environment["HOME"] != str(Path.home())


def test_official_origin_main_is_remote_observed_with_isolated_git_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-enter-network-check")
    calls: list[dict[str, Any]] = []

    def runner(command, **kwargs):
        command = tuple(command)
        calls.append({"command": command, **kwargs})
        if command == ("git", "remote", "get-url", "origin"):
            stdout = "https://github.com/ddnne/quant-platform.git\n"
        elif command == (
            "git",
            "rev-parse",
            "--verify",
            "refs/remotes/origin/main^{commit}",
        ):
            stdout = f"{SHA}\n"
        elif command[:4] == ("git", "ls-remote", "--exit-code", "--refs"):
            stdout = f"{SHA}\trefs/heads/main\n"
        else:  # pragma: no cover - closes the Git observation protocol
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    live._require_official_origin_main(SHA, runner=runner)  # noqa: SLF001
    assert len(calls) == 3
    remote_environment = calls[2]["env"]
    assert "AWS_SECRET_ACCESS_KEY" not in remote_environment
    assert remote_environment["GIT_TERMINAL_PROMPT"] == "0"
    assert remote_environment["GIT_ASKPASS"] == "/usr/bin/false"
    assert Path(remote_environment["HOME"]).name == "isolated-home"


def test_official_origin_main_rejects_caller_selected_non_main_sha() -> None:
    def runner(command, **kwargs):
        del kwargs
        command = tuple(command)
        if command == ("git", "remote", "get-url", "origin"):
            stdout = "https://github.com/ddnne/quant-platform.git\n"
        elif command == (
            "git",
            "rev-parse",
            "--verify",
            "refs/remotes/origin/main^{commit}",
        ):
            stdout = f"{'f' * 40}\n"
        else:  # pragma: no cover - rejection occurs before the network check
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    with pytest.raises(
        live.ReceiptPendingLiveAcceptanceError,
        match="not the pinned official origin/main",
    ):
        live._require_official_origin_main(SHA, runner=runner)  # noqa: SLF001


def test_official_origin_main_rejects_lookalike_remote() -> None:
    def runner(command, **kwargs):
        del kwargs
        command = tuple(command)
        if command == ("git", "remote", "get-url", "origin"):
            stdout = "https://example.invalid/ddnne/quant-platform.git\n"
        elif command == (
            "git",
            "rev-parse",
            "--verify",
            "refs/remotes/origin/main^{commit}",
        ):
            stdout = f"{SHA}\n"
        else:  # pragma: no cover - rejection occurs before the network check
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    with pytest.raises(
        live.ReceiptPendingLiveAcceptanceError,
        match="not the pinned official origin/main",
    ):
        live._require_official_origin_main(SHA, runner=runner)  # noqa: SLF001


def test_collection_rejects_change_after_an_earlier_worker_local_bracket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployments, versions, public, source_provenance = _documents("staging")
    worker_to_role = {worker: role for role, worker in live.CHAIN}
    deployment_reads = {role: 0 for role, _worker in live.CHAIN}

    def wrangler_json(*, worker, arguments, **_kwargs):
        role = worker_to_role[worker]
        if arguments[:2] == ("deployments", "status"):
            deployment_reads[role] += 1
            result = copy.deepcopy(deployments[role])
            if role == "acquisition" and deployment_reads[role] == 3:
                result["id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
            return result
        assert arguments[:2] == ("versions", "view")
        return copy.deepcopy(versions[role])

    def public_surface(*, worker_name, **_kwargs):
        role = next(
            role
            for role, worker in live.CHAIN
            if live.build_manifest()["workers"][worker]["staging"]["name"]
            == worker_name
        )
        return copy.deepcopy(public[role])

    def provenance(*, worker, **_kwargs):
        return copy.deepcopy(source_provenance[worker_to_role[worker]])

    monkeypatch.setattr(live, "_wrangler_json", wrangler_json)
    monkeypatch.setattr(live, "_live_public_surface", public_surface)
    monkeypatch.setattr(live, "_source_provenance", provenance)
    with pytest.raises(
        live.ReceiptPendingLiveAcceptanceError,
        match="acquisition deployment changed during whole-chain acceptance",
    ):
        live.collect_live_pending_receipt_chain(
            environment="staging",
            source_sha=SHA,
            account_id=ACCOUNT,
            api_token="read-only-token",
        )


def test_production_collection_stays_hold_without_access_evidence() -> None:
    with pytest.raises(
        live.ReceiptPendingLiveAcceptanceError,
        match="C7 HOLD.*Cloudflare Access",
    ):
        live.collect_live_pending_receipt_chain(
            environment="production",
            source_sha=SHA,
            account_id=ACCOUNT,
            api_token="read-only-token",
        )
