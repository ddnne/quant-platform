"""Behavioral invariants for the separate offline and controlled paper APIs."""

from __future__ import annotations

import hashlib
from dataclasses import fields, replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agents.trader import TraderAgent
from agents.types import PortfolioDecision
from execution.paper_service import (
    ControlledPilotExecutionService,
    ControlledPilotRunConfig,
    ImmutableSnapshotHandle,
    OfflineFixturePaperService,
    PaperExecutionRejected,
)
from paper_runtime import data_snapshot_id
from research.dependency_closure import (
    build_plan_dependency_closure,
    resolve_strategy_spec,
)
from research.experiment_plans import load_experiment_plans
from research.readiness import ReadinessAttestationPublisher
from research.ready_manifest import ExactFourPilotReadyBinding, build_ready_manifest
from research.research_data_profile import profile_from_dependency_closure
from storage.sqlite_store import SqliteStore
from strategies.paper import Lifecycle, PaperRunConfig

from _coreseed import CODES, seed_db


def _weekdays(count: int) -> list[str]:
    days: list[str] = []
    cursor = date(2025, 4, 1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _controlled_bundle(
    tmp_path: Path, *, staggered_membership: bool = False
) -> dict[str, object]:
    days = _weekdays(20)
    prices = {
        code: {
            day: 100.0 + code_index * 10.0 + day_index * (code_index + 1)
            for day_index, day in enumerate(days)
        }
        for code_index, code in enumerate(CODES)
    }
    db = seed_db(tmp_path, codes=CODES, days=days, prices=prices)
    if staggered_membership:
        master_rows = []
        for snapshot_date, visible_codes in (
            (days[0], ("1332",)),
            (days[1], tuple(CODES)),
        ):
            for code in visible_codes:
                master_rows.append(
                    {
                        "source": "jquants",
                        "code": code,
                        "snapshot_date": snapshot_date,
                        "event_time": f"{snapshot_date}T08:00:00+09:00",
                        "available_at": f"{snapshot_date}T08:00:00+09:00",
                        "ingested_at": f"{snapshot_date}T08:00:00+09:00",
                        "company_name": f"Co-{code}",
                        "sector_17_code": "1",
                        "market_code": "1",
                    }
                )
        with SqliteStore(db) as store:
            store.upsert("jquants_listed_info", master_rows)
    snapshot_id = data_snapshot_id(db)
    immutable_db = tmp_path / f"{snapshot_id.replace(':', '_', 1)}.sqlite"
    db.rename(immutable_db)
    immutable_db.chmod(0o444)
    db = immutable_db
    plans = tuple(
        replace(
            plan,
            ready_snapshot_id=snapshot_id,
            period_start=days[0],
            period_end=days[-1],
        )
        for plan in load_experiment_plans()
    )
    closures = tuple(build_plan_dependency_closure(plan) for plan in plans)
    profiles = tuple(profile_from_dependency_closure(item) for item in closures)
    binding = ExactFourPilotReadyBinding(
        plans=plans,
        closures=closures,
        profiles=profiles,
    )
    proof = "sha256:" + ("ab" * 32)
    manifest = build_ready_manifest(
        snapshot_id=snapshot_id,
        publication_scope="PILOT",
        profile_id=binding.profile_id,
        profile_version=binding.profile_version,
        profile_digest=binding.profile_digest,
        plan_ids=binding.plan_ids,
        plan_set_digest=binding.plan_set_digest,
        dependency_closure_digest=binding.closure_set_digest,
        dataset_ids=binding.required_datasets,
        coverage_proof_digest=proof,
        raw_proof_digest=proof,
        receipt_proof_digest=proof,
        validation_proof_digest=proof,
        b0_proof_digest=proof,
        b4_proof_digest=proof,
        source_generation="cursor-7",
        applied_sync_generation="cursor-7",
        export_cursor="cursor-7",
        applied_cursor="cursor-7",
        pit_contract_digests={"pit_api": proof},
        feature_generation=proof,
        catalog_generation=proof,
        created_at="2026-08-25T00:00:00+00:00",
        published_at="2026-08-25T00:01:00+00:00",
    )
    publisher = ReadinessAttestationPublisher(
        key_id="controlled-pilot-test",
        private_key=Ed25519PrivateKey.generate(),
    )
    immutable_digest = _sha256_file(db)
    readiness = publisher.mint_pilot(
        manifest,
        immutable_db_digest=immutable_digest,
        profile_binding=binding,
    )
    selected_index = binding.plan_ids.index("exp-mdh-hold10-momentum")
    plan = plans[selected_index]
    closure = closures[selected_index]
    spec = resolve_strategy_spec(
        plan.strategy_spec_id,
        plan.strategy_spec_version,
        plan.strategy_spec_hash,
    )
    universe = tuple(sorted(CODES))
    decision = PortfolioDecision(
        approved=True,
        strategy_spec=spec,
        max_gross_weight=0.5,
    )
    authorization = TraderAgent().prepare(
        decision,
        ready_snapshot_id=snapshot_id,
        ready_manifest_digest=manifest.manifest_digest,
        readiness_attestation_id=readiness.attestation_id,
        profile_digest=binding.profile_digest,
        plan_set_digest=binding.plan_set_digest,
        dependency_closure_digest=binding.closure_set_digest,
        universe=universe,
        period_start=plan.period_start,
        period_end=plan.period_end,
        cost_scenario=plan.cost_scenario,
    )
    config = ControlledPilotRunConfig(
        snapshot=ImmutableSnapshotHandle(
            snapshot_id=snapshot_id,
            immutable_db_digest=immutable_digest,
            artifact_path=db,
        ),
        start=plan.period_start,
        end=plan.period_end,
        universe_contract_id=plan.universe[0],
        universe=universe,
        max_gross_weight=0.5,
    )
    service = ControlledPilotExecutionService(
        verifier=publisher.public_registry()
    )
    return {
        "service": service,
        "plan": plan,
        "closure": closure,
        "binding": binding,
        "manifest": manifest,
        "readiness": readiness,
        "authorization": authorization,
        "spec": spec,
        "config": config,
        "db": db,
    }


def test_controlled_service_binds_exact_plan_ready_and_immutable_snapshot(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    result = bundle["service"].execute(  # type: ignore[union-attr]
        experiment_plan=bundle["plan"],
        dependency_closure=bundle["closure"],
        plan_set_binding=bundle["binding"],
        ready_manifest=bundle["manifest"],
        readiness=bundle["readiness"],
        authorization=bundle["authorization"],
        strategy_spec=bundle["spec"],
        config=bundle["config"],
    )
    assert result.lifecycle is Lifecycle.PAPER
    assert result.reproducibility["execution_authority_scope"] == "CONTROLLED_PILOT"
    assert result.reproducibility["max_gross_weight_limit"] == 0.5
    first_fill = min(trade["fill_date"] for trade in result.trades)
    first_fill_gross = sum(
        abs(float(trade["notional"]))
        for trade in result.trades
        if trade["fill_date"] == first_fill
    )
    # The decision-time target is capped at 50%; the next-close fill may move
    # before execution, so the observed notional includes that bounded gap.
    assert first_fill_gross <= 0.51 * 1_000_000.0
    assert result.reproducibility["promotion_eligible"] is False


def test_controlled_service_rejects_any_digest_chain_substitution(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    authorization = replace(
        bundle["authorization"],  # type: ignore[arg-type]
        dependency_closure_digest="sha256:" + ("00" * 32),
    )
    with pytest.raises(PaperExecutionRejected, match="dependency_closure_digest"):
        bundle["service"].execute(  # type: ignore[union-attr]
            experiment_plan=bundle["plan"],
            dependency_closure=bundle["closure"],
            plan_set_binding=bundle["binding"],
            ready_manifest=bundle["manifest"],
            readiness=bundle["readiness"],
            authorization=authorization,
            strategy_spec=bundle["spec"],
            config=bundle["config"],
        )


def test_controlled_service_preserves_narrower_trader_gross_limit(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    config = replace(  # system policy permits more than the Trader authorized
        bundle["config"],  # type: ignore[arg-type]
        max_gross_weight=0.75,
    )
    result = bundle["service"].execute(  # type: ignore[union-attr]
        experiment_plan=bundle["plan"],
        dependency_closure=bundle["closure"],
        plan_set_binding=bundle["binding"],
        ready_manifest=bundle["manifest"],
        readiness=bundle["readiness"],
        authorization=bundle["authorization"],
        strategy_spec=bundle["spec"],
        config=config,
    )
    assert result.reproducibility["max_gross_weight_limit"] == 0.5


def test_controlled_config_has_no_mutable_db_or_readiness_switch() -> None:
    field_names = {field.name for field in fields(ControlledPilotRunConfig)}
    assert "db_path" not in field_names
    assert "require_ready_snapshot" not in field_names
    assert "snapshot" in field_names


def test_controlled_allowlist_remains_candidates_for_daily_pit_intersection(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    config = bundle["config"]
    closure = bundle["closure"]
    runtime = config.to_runtime_config(  # type: ignore[union-attr]
        artifact_path=config.snapshot.artifact_path,  # type: ignore[union-attr]
        dependency_closure_digest=closure.closure_digest,  # type: ignore[union-attr]
    )
    assert tuple(runtime.universe) == tuple(sorted(CODES))
    assert runtime.universe.membership_proof.startswith(  # type: ignore[union-attr]
        "controlled-plan-closure:sha256:"
    )


def test_controlled_service_admits_mid_period_listing_through_daily_pit(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path, staggered_membership=True)
    result = bundle["service"].execute(  # type: ignore[union-attr]
        experiment_plan=bundle["plan"],
        dependency_closure=bundle["closure"],
        plan_set_binding=bundle["binding"],
        ready_manifest=bundle["manifest"],
        readiness=bundle["readiness"],
        authorization=bundle["authorization"],
        strategy_spec=bundle["spec"],
        config=bundle["config"],
    )
    assert result.backtest.metadata["fixed_allowlist"] == sorted(CODES)
    assert "8697" in {trade["code"] for trade in result.trades}


def test_controlled_service_rejects_writable_current_database(tmp_path: Path) -> None:
    bundle = _controlled_bundle(tmp_path)
    config = bundle["config"]
    artifact = config.snapshot.artifact_path  # type: ignore[union-attr]
    artifact.chmod(0o644)
    with pytest.raises(PaperExecutionRejected, match="writable"):
        bundle["service"].execute(  # type: ignore[union-attr]
            experiment_plan=bundle["plan"],
            dependency_closure=bundle["closure"],
            plan_set_binding=bundle["binding"],
            ready_manifest=bundle["manifest"],
            readiness=bundle["readiness"],
            authorization=bundle["authorization"],
            strategy_spec=bundle["spec"],
            config=config,
        )


def test_offline_fixture_service_is_draft_and_non_promotable(tmp_path: Path) -> None:
    bundle = _controlled_bundle(tmp_path)
    spec = bundle["spec"]
    decision = PortfolioDecision(
        approved=True,
        strategy_spec=spec,  # type: ignore[arg-type]
        max_gross_weight=0.5,
    )
    auth = TraderAgent().prepare(decision)
    plan = bundle["plan"]
    config = PaperRunConfig(
        start=plan.period_start,  # type: ignore[union-attr]
        end=plan.period_end,  # type: ignore[union-attr]
        db_path=bundle["db"],
        universe=None,
        lifecycle=Lifecycle.DRAFT,
    )
    result = OfflineFixturePaperService().execute(auth, spec, config)  # type: ignore[arg-type]
    assert result.lifecycle is Lifecycle.DRAFT
    assert result.reproducibility["execution_authority_scope"] == "OFFLINE_FIXTURE"
    assert result.reproducibility["promotion_eligible"] is False
    with pytest.raises(PaperExecutionRejected, match="DRAFT only"):
        OfflineFixturePaperService().execute(
            auth,
            spec,  # type: ignore[arg-type]
            replace(config, lifecycle=Lifecycle.PAPER),
        )
