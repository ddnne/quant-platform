"""Behavioral invariants for the separate offline and controlled paper APIs."""

from __future__ import annotations

import base64
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
    PaperExecutionService,
)
from execution.trader_authority import TraderAuthorizationPublicKeyRegistry
from ingestion.jquants.normalize import normalize_generic
from paper_runtime import data_snapshot_id
from research.dependency_closure import (
    resolve_strategy_spec,
)
from research.experiment_plans import (
    PILOT_PERIOD_END,
    PILOT_PERIOD_START,
    load_experiment_plans,
)
from research.readiness import (
    ReadinessPublicKeyRegistry,
)
from research.ready_manifest import (
    build_ready_manifest,
    load_exact_four_pilot_ready_binding,
)
from research.universe_contract import (
    EXACT_FOUR_UNIVERSE_RULE_DIGEST,
    ResolvedUniverseMembership,
    resolve_tse_prime_with_fins,
)
from selection.budget_ledger import MassResearchDisabledError
from storage.sqlite_store import SqliteStore
from strategies.paper import Lifecycle, PaperRunConfig, run_paper
from tests.readiness_test_support import (
    controlled_pilot_execution_service,
    issue_trader_authorization,
    make_readiness_signer,
    make_trader_authorization_issuer,
    mint_pilot_readiness,
)

from _coreseed import CODES, seed_db


def _pilot_weekdays() -> list[str]:
    days: list[str] = []
    cursor = date.fromisoformat(PILOT_PERIOD_START)
    end = date.fromisoformat(PILOT_PERIOD_END)
    while cursor <= end:
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
    days = _pilot_weekdays()
    prices = {
        code: {
            day: 100.0 + code_index * 10.0 + day_index * (code_index + 1)
            for day_index, day in enumerate(days)
        }
        for code_index, code in enumerate(CODES)
    }
    db = seed_db(tmp_path, codes=CODES, days=days, prices=prices)
    with SqliteStore(db) as store:
        store._conn.execute(  # noqa: SLF001
            "UPDATE jquants_market_calendar SET available_at=?, ingested_at=?",
            (f"{days[0]}T08:00:00+09:00", f"{days[0]}T08:00:00+09:00"),
        )
        store._conn.execute(  # noqa: SLF001
            "UPDATE jquants_listed_info SET snapshot_date=?, event_time=?, "
            "available_at=?, ingested_at=?, market_code='0111'",
            (
                days[0],
                f"{days[0]}T08:00:00+09:00",
                f"{days[0]}T08:00:00+09:00",
                f"{days[0]}T08:00:00+09:00",
            ),
        )
        store._conn.commit()  # noqa: SLF001
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
                        "market_code": "0111",
                    }
                )
        with SqliteStore(db) as store:
            store._conn.execute("DELETE FROM jquants_listed_info")  # noqa: SLF001
            store.upsert("jquants_listed_info", master_rows)
    calendar_rows = []
    cursor = date.fromisoformat(PILOT_PERIOD_START)
    calendar_end = date.fromisoformat(PILOT_PERIOD_END)
    while cursor <= calendar_end:
        calendar_rows.append(
            {
                "Date": cursor.isoformat(),
                "HolidayDivision": "1" if cursor.weekday() < 5 else "0",
            }
        )
        cursor += timedelta(days=1)
    master_payloads: list[dict[str, str]] = []
    if staggered_membership:
        for snapshot_date, visible_codes in (
            (days[0], ("1332",)),
            (days[1], tuple(CODES)),
        ):
            for code in visible_codes:
                master_payloads.append(
                    {
                        "Code": code,
                        "Date": snapshot_date,
                        "CompanyName": f"Co-{code}",
                        "MarketCode": "0111",
                    }
                )
    else:
        master_payloads = [
            {
                "Code": code,
                "Date": days[0],
                "CompanyName": f"Co-{code}",
                "MarketCode": "0111",
            }
            for code in CODES
        ]
    # Deliberately keep two non-members in the immutable snapshot.  They make
    # the adversarial cases behavioral: 9001 has financials but is not Prime;
    # 9002 is Prime but has no PIT-visible financial disclosure.
    master_payloads.extend(
        (
            {
                "Code": "9001",
                "Date": days[0],
                "CompanyName": "Non Prime With Fins",
                "MarketCode": "9999",
            },
            {
                "Code": "9002",
                "Date": days[0],
                "CompanyName": "Prime Without Fins",
                "MarketCode": "0111",
            },
        )
    )
    fins_payloads = [
        {
            "Code": code,
            "DiscDate": days[0],
            "DiscTime": "08:00:00",
            "DiscNo": f"disc-{code}",
        }
        for code in CODES
    ]
    fins_payloads.append(
        {
            "Code": "9001",
            "DiscDate": days[0],
            "DiscTime": "08:00:00",
            "DiscNo": "disc-9001",
        }
    )
    with SqliteStore(db) as store:
        generic_rows = [
            *normalize_generic(
                calendar_rows,
                dataset="markets_calendar",
                ingested_at="2022-12-01T00:00:00+09:00",
            ),
            *normalize_generic(
                master_payloads,
                dataset="equities_master",
                ingested_at=f"{days[0]}T08:00:00+09:00",
            ),
            *normalize_generic(
                fins_payloads,
                dataset="fins_summary",
                ingested_at=f"{days[0]}T08:00:00+09:00",
            ),
        ]
        store.upsert("jquants_records", generic_rows)
    resolved_universe = resolve_tse_prime_with_fins(
        db,
        period_start=PILOT_PERIOD_START,
        period_end=PILOT_PERIOD_END,
    )
    snapshot_id = data_snapshot_id(db)
    immutable_db = tmp_path / f"{snapshot_id.replace(':', '_', 1)}.sqlite"
    db.rename(immutable_db)
    immutable_db.chmod(0o444)
    db = immutable_db
    plans = load_experiment_plans()
    binding = load_exact_four_pilot_ready_binding()
    closures = binding.closures
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
        universe_rule_digest=EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        resolved_universe_digest=resolved_universe.resolved_membership_digest,
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
    publisher = make_readiness_signer(
        key_id="controlled-pilot-test",
        private_key=Ed25519PrivateKey.generate(),
    )
    immutable_digest = _sha256_file(db)
    readiness = mint_pilot_readiness(
        manifest,
        publisher=publisher,
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
    decision = PortfolioDecision(
        approved=True,
        strategy_spec=spec,
        max_gross_weight=0.5,
    )
    trader_key = Ed25519PrivateKey.generate()
    trader_key_id = "controlled-trader-test"
    trader_issuer = make_trader_authorization_issuer(
        key_id=trader_key_id,
        private_key=trader_key,
    )
    trader_registry = TraderAuthorizationPublicKeyRegistry(
        {trader_key_id: trader_key.public_key()}
    )
    authorization = issue_trader_authorization(
        trader_issuer,
        readiness_verifier=publisher._public_registry(),
        decision=decision,
        experiment_plan=plan,
        plan_set_binding=binding,
        ready_manifest=manifest,
        readiness=readiness,
        resolved_universe=resolved_universe,
    )
    config = ControlledPilotRunConfig(
        snapshot=ImmutableSnapshotHandle(
            snapshot_id=snapshot_id,
            immutable_db_digest=immutable_digest,
            artifact_path=db,
        ),
        start=plan.period_start,
        end=plan.period_end,
        resolved_universe=resolved_universe,
        max_gross_weight=0.5,
    )
    service = controlled_pilot_execution_service(
        verifier=publisher._public_registry(),
        trader_verifier=trader_registry,
    )
    return {
        "service": service,
        "publisher": publisher,
        "trader_registry": trader_registry,
        "resolved_universe": resolved_universe,
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
    if result.trades:
        first_fill = min(trade["fill_date"] for trade in result.trades)
        first_fill_gross = sum(
            abs(float(trade["notional"]))
            for trade in result.trades
            if trade["fill_date"] == first_fill
        )
        assert first_fill_gross <= 0.51 * 1_000_000.0
    assert result.reproducibility["promotion_eligible"] is False


def test_controlled_service_public_constructor_has_no_caller_trust_root() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        ControlledPilotExecutionService(verifier=object())  # type: ignore[call-arg]


def test_controlled_service_trust_roots_cannot_be_replaced_after_construction(
) -> None:
    service = ControlledPilotExecutionService()
    attacker = TraderAuthorizationPublicKeyRegistry(
        {"attacker": Ed25519PrivateKey.generate().public_key()}
    )
    with pytest.raises(AttributeError):
        service._trader_verifier = attacker  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        service._verifier = object()  # type: ignore[attr-defined]


def test_controlled_service_rejects_caller_signed_readiness_under_configured_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attacker = _controlled_bundle(tmp_path)
    trusted_publisher = make_readiness_signer(
        key_id="configured-controlled-pilot",
        private_key=Ed25519PrivateKey.generate(),
    )
    trusted_registry = trusted_publisher._public_registry()
    monkeypatch.setattr(
        ReadinessPublicKeyRegistry,
        "load_pinned",
        classmethod(lambda cls: trusted_registry),
    )
    service = ControlledPilotExecutionService()
    with pytest.raises(MassResearchDisabledError, match="signature mismatch"):
        service.execute(
            experiment_plan=attacker["plan"],
            dependency_closure=attacker["closure"],
            plan_set_binding=attacker["binding"],
            ready_manifest=attacker["manifest"],
            readiness=attacker["readiness"],
            authorization=attacker["authorization"],
            strategy_spec=attacker["spec"],
            config=attacker["config"],
        )


def test_controlled_service_rejects_any_digest_chain_substitution(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    authorization = replace(
        bundle["authorization"],  # type: ignore[arg-type]
        dependency_closure_digest="sha256:" + ("00" * 32),
    )
    with pytest.raises(PaperExecutionRejected, match="forged"):
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


def test_controlled_service_rejects_forged_trader_signature(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    forged = replace(
        bundle["authorization"],  # type: ignore[arg-type]
        signature="ed25519:"
        + base64.b64encode(b"\x00" * 64).decode("ascii"),
    )
    with pytest.raises(PaperExecutionRejected, match="forged"):
        bundle["service"].execute(  # type: ignore[union-attr]
            experiment_plan=bundle["plan"],
            dependency_closure=bundle["closure"],
            plan_set_binding=bundle["binding"],
            ready_manifest=bundle["manifest"],
            readiness=bundle["readiness"],
            authorization=forged,
            strategy_spec=bundle["spec"],
            config=bundle["config"],
        )


@pytest.mark.parametrize(
    "forged_code",
    (
        pytest.param("9999", id="caller-arbitrary"),
        pytest.param("9001", id="non-prime"),
        pytest.param("9002", id="no-financials"),
    ),
)
def test_controlled_service_rejects_non_governed_universe_membership(
    tmp_path: Path,
    forged_code: str,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    resolved = bundle["resolved_universe"]
    forged_memberships = tuple(
        (day, tuple(sorted((*codes, forged_code))))
        for day, codes in resolved.decision_memberships  # type: ignore[union-attr]
    )
    forged = ResolvedUniverseMembership(
        period_start=resolved.period_start,  # type: ignore[union-attr]
        period_end=resolved.period_end,  # type: ignore[union-attr]
        decision_memberships=forged_memberships,
    )
    config = replace(
        bundle["config"],  # type: ignore[arg-type]
        resolved_universe=forged,
    )

    with pytest.raises(
        PaperExecutionRejected,
        match="snapshot-resolved READY membership",
    ):
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
    assert "universe" not in field_names
    assert "resolved_universe" in field_names


def test_legacy_verified_boolean_scope_entry_no_longer_exists() -> None:
    service = PaperExecutionService()
    assert not hasattr(service, "_execute_verified")
    with pytest.raises(AttributeError):
        getattr(service, "_execute_verified")(
            require_ready=True,
            execution_scope="CONTROLLED_PILOT",
        )


def test_offline_trader_has_no_ready_authorization_surface(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    decision = PortfolioDecision(
        approved=True,
        strategy_spec=bundle["spec"],  # type: ignore[arg-type]
        max_gross_weight=0.5,
    )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        TraderAgent().prepare(  # type: ignore[call-arg]
            decision,
            ready_snapshot_id=bundle["manifest"].snapshot_id,  # type: ignore[union-attr]
        )


def test_direct_low_level_paper_run_is_rejected(tmp_path: Path) -> None:
    bundle = _controlled_bundle(tmp_path)
    plan = bundle["plan"]
    config = PaperRunConfig(
        start=plan.period_start,  # type: ignore[union-attr]
        end=plan.period_end,  # type: ignore[union-attr]
        db_path=bundle["db"],
        universe=bundle["resolved_universe"],
        lifecycle=Lifecycle.PAPER,
    )
    from strategies.spec import interpret_strategy_spec

    with pytest.raises(
        PermissionError,
        match="opaque controlled execution capability",
    ):
        run_paper(interpret_strategy_spec(bundle["spec"]), config)  # type: ignore[arg-type]


def test_controlled_resolved_membership_reaches_daily_pit_intersection(
    tmp_path: Path,
) -> None:
    bundle = _controlled_bundle(tmp_path)
    config = bundle["config"]
    runtime = config.to_runtime_config(  # type: ignore[union-attr]
        artifact_path=config.snapshot.artifact_path,  # type: ignore[union-attr]
    )
    assert runtime.universe.resolved_membership_digest == (  # type: ignore[union-attr]
        bundle["resolved_universe"].resolved_membership_digest  # type: ignore[union-attr]
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
    assert result.backtest.metadata["fixed_allowlist"] is None
    assert result.backtest.metadata["resolved_universe_digest"] == (
        bundle["resolved_universe"].resolved_membership_digest  # type: ignore[union-attr]
    )
    assert result.reproducibility["execution_authority_scope"] == "CONTROLLED_PILOT"


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
