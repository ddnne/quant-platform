"""Phase 7 PaperExecutionService — the sole authority over ``run_paper``.

The orchestrator (:class:`agents.pipeline.AgentPaperPipeline`) and every role
agent are capability-free. The single positive capability that can reach the
trusted paper runtime is funneled through this service: it accepts an
:class:`~agents.types.AuthorizedPaperExecutionRequest` together with the
immutable :class:`~strategies.spec.StrategySpec` that authorized it, re-derives
every authorization field, pins the exact data snapshot, and resolves every
FeatureRef against the governed registry before delegating to
:func:`strategies.paper.run_paper`.

This is data, not an order: the request carries no broker, callable,
credential, database handle, or transport. The service is what turns that
capability-free authorization into exactly one reproducible paper run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import features
from agents.types import AuthorizedPaperExecutionRequest
from paper_runtime import data_snapshot_id
from strategies.paper import (
    JsonPaperStore,
    Lifecycle,
    PaperRunConfig,
    PaperRunResult,
    run_paper,
)
from strategies.spec import FeatureRef, StrategySpec, interpret_strategy_spec


class PaperExecutionRejected(ValueError):
    """Raised when an execution request fails the authority gate."""


@dataclass(frozen=True, slots=True)
class ImmutableSnapshotHandle:
    """Content-addressed READY SQLite artifact; never a mutable current DB."""

    snapshot_id: str
    immutable_db_digest: str
    artifact_path: Path

    def verify(self) -> Path:
        artifact = Path(self.artifact_path).resolve()
        if not artifact.is_file():
            raise PaperExecutionRejected(
                f"immutable snapshot artifact does not exist: {artifact}"
            )
        expected_name = self.snapshot_id.replace(":", "_", 1) + ".sqlite"
        if artifact.name != expected_name:
            raise PaperExecutionRejected(
                "controlled snapshot artifact is not content-addressed by snapshot_id"
            )
        if artifact.stat().st_mode & 0o222:
            raise PaperExecutionRejected(
                "controlled snapshot artifact is writable; mutable current DB rejected"
            )
        digest = hashlib.sha256()
        with artifact.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        observed_digest = "sha256:" + digest.hexdigest()
        if observed_digest != self.immutable_db_digest:
            raise PaperExecutionRejected("immutable snapshot artifact digest mismatch")
        try:
            observed_snapshot = data_snapshot_id(artifact)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise PaperExecutionRejected(str(exc)) from exc
        if observed_snapshot != self.snapshot_id:
            raise PaperExecutionRejected("immutable snapshot id mismatch")
        return artifact


class _GovernedCandidateAllowlist:
    """Closure-bound candidates; daily PIT membership is still authoritative."""

    __slots__ = ("membership", "membership_proof", "_codes")
    membership: Mapping[str, None]
    membership_proof: str
    _codes: tuple[str, ...]

    def __init__(self, codes: Sequence[str], *, closure_digest: str) -> None:
        normalized = tuple(sorted({str(code) for code in codes}))
        self._codes = normalized
        self.membership = MappingProxyType({code: None for code in normalized})
        self.membership_proof = f"controlled-plan-closure:{closure_digest}"

    def __iter__(self) -> Iterator[str]:
        return iter(self._codes)

    def __len__(self) -> int:
        return len(self._codes)


@dataclass(frozen=True, slots=True)
class ControlledPilotRunConfig:
    """Controlled-only inputs; no mutable DB or readiness boolean exists."""

    snapshot: ImmutableSnapshotHandle
    start: str
    end: str
    universe_contract_id: str
    universe: tuple[str, ...]
    execution_mode: str = "next_close"
    cost_bps: float = 5.0
    starting_capital: float = 1_000_000.0
    lookback_days: int = 30
    price_basis: str = "RAW"
    calendar_as_of: str | None = None
    max_gross_weight: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, ImmutableSnapshotHandle):
            raise ValueError("ImmutableSnapshotHandle required")
        if not self.start or not self.end or self.start > self.end:
            raise ValueError("controlled pilot period requires start <= end")
        if not self.universe_contract_id.strip():
            raise ValueError("controlled pilot universe contract required")
        normalized = tuple(
            sorted({str(code).strip() for code in self.universe if str(code).strip()})
        )
        if not normalized:
            raise ValueError("controlled pilot requires an explicit universe")
        object.__setattr__(self, "universe", normalized)
        if self.execution_mode != "next_close":
            raise ValueError("controlled pilot execution_mode is fixed to next_close")
        if not 0.0 < float(self.max_gross_weight) <= 1.0:
            raise ValueError("controlled pilot max_gross_weight must be in (0, 1]")

    def to_runtime_config(
        self,
        *,
        artifact_path: Path,
        dependency_closure_digest: str,
    ) -> PaperRunConfig:
        candidates = _GovernedCandidateAllowlist(
            self.universe,
            closure_digest=dependency_closure_digest,
        )
        return PaperRunConfig(
            start=self.start,
            end=self.end,
            db_path=artifact_path,
            universe=candidates,
            execution_mode="next_close",
            cost_bps=self.cost_bps,
            starting_capital=self.starting_capital,
            lookback_days=self.lookback_days,
            price_basis=self.price_basis,
            lifecycle=Lifecycle.PAPER,
            calendar_as_of=self.calendar_as_of,
        )


def _strategy_spec_hash(spec: StrategySpec) -> str:
    """Re-derive the canonical StrategySpec hash covered by authorization."""
    blob = json.dumps(
        spec.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _authorization_id(
    mode: str,
    spec_hash: str,
    max_gross_weight: float,
    *,
    ready_snapshot_id: str = "",
    ready_manifest_digest: str = "",
    readiness_attestation_id: str = "",
    profile_digest: str = "",
    plan_set_digest: str = "",
    dependency_closure_digest: str = "",
    universe: tuple[str, ...] | list[str] = (),
    period_start: str = "",
    period_end: str = "",
    cost_scenario: str = "default",
) -> str:
    """Re-derive the immutable authorization id (mirrors TraderAgent.prepare)."""
    payload = {
        "mode": mode,
        "strategy_spec_hash": spec_hash,
        "max_gross_weight": max_gross_weight,
        "ready_snapshot_id": ready_snapshot_id or "",
        "ready_manifest_digest": ready_manifest_digest or "",
        "readiness_attestation_id": readiness_attestation_id or "",
        "profile_digest": profile_digest or "",
        "plan_set_digest": plan_set_digest or "",
        "dependency_closure_digest": dependency_closure_digest or "",
        "universe": list(universe),
        "period_start": period_start or "",
        "period_end": period_end or "",
        "cost_scenario": cost_scenario or "default",
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _iter_feature_refs(spec: StrategySpec) -> tuple[FeatureRef, ...]:
    """Collect every FeatureRef the rule binds (single- and dual-feature rules)."""
    rule = spec.rule
    refs: list[FeatureRef] = []
    for attr in ("feature", "value_feature", "momentum_feature"):
        value = getattr(rule, attr, None)
        if isinstance(value, FeatureRef):
            refs.append(value)
    if not refs:
        raise PaperExecutionRejected("StrategySpec rule has no FeatureRef to attest")
    return tuple(refs)


class _GrossCappedStrategy:
    """Scale every emitted target book to the controlled gross ceiling."""

    def __init__(self, delegate: Any, *, max_gross_weight: float) -> None:
        self._delegate = delegate
        self._max_gross_weight = float(max_gross_weight)
        self.strategy_id = delegate.strategy_id
        self.feature_ids = delegate.feature_ids
        self.feature_versions = dict(delegate.feature_versions)
        self.params = {
            **dict(delegate.params),
            "controlled_max_gross_weight": self._max_gross_weight,
        }

    def on_bar(self, context: Any) -> list[Any]:
        intents = list(self._delegate.on_bar(context))
        gross = sum(abs(float(intent.target_weight)) for intent in intents)
        if gross <= self._max_gross_weight or gross <= 0.0:
            return intents
        scale = self._max_gross_weight / gross
        return [
            replace(
                intent,
                target_weight=float(intent.target_weight) * scale,
                note=(str(intent.note) + "; " if intent.note else "")
                + "controlled gross cap",
            )
            for intent in intents
        ]


class PaperExecutionService:
    """The single positive capability reaching :func:`strategies.paper.run_paper`.

    Construction is cheap and stateless aside from the optional paper store.
    :meth:`execute` is the authority entry; :meth:`execute_runtime_dto` is the
    paper_runtime DTO adapter. Neither exposes ``run_paper``, the SQLite path,
    or any engine handle to its caller.
    """

    def __init__(self, paper_store: JsonPaperStore | None = None) -> None:
        self.paper_store = paper_store

    def execute(
        self,
        plan: AuthorizedPaperExecutionRequest,
        spec: StrategySpec,
        config: PaperRunConfig,
    ) -> PaperRunResult:
        """Compatibility entry for offline fixtures only.

        Controlled execution is available exclusively through
        :class:`ControlledPilotExecutionService`.
        """
        if config.lifecycle is not Lifecycle.DRAFT:
            raise PaperExecutionRejected(
                "PaperExecutionService compatibility entry is offline DRAFT only"
            )
        if any(
            str(getattr(plan, name, "") or "").strip()
            for name in (
                "ready_snapshot_id",
                "ready_manifest_digest",
                "readiness_attestation_id",
                "profile_digest",
                "plan_set_digest",
                "dependency_closure_digest",
            )
        ):
            raise PaperExecutionRejected(
                "offline fixture execution cannot consume READY authority"
            )
        return self._execute_verified(
            plan,
            spec,
            config,
            require_ready=False,
            execution_scope="OFFLINE_FIXTURE",
        )

    def _execute_verified(
        self,
        plan: AuthorizedPaperExecutionRequest,
        spec: StrategySpec,
        config: PaperRunConfig,
        *,
        require_ready: bool,
        execution_scope: str,
        gross_cap: float | None = None,
    ) -> PaperRunResult:
        pinned_snapshot = self._authorize(
            plan, spec, config, require_ready=require_ready
        )
        strategy: Any = interpret_strategy_spec(spec)
        if gross_cap is not None:
            strategy = _GrossCappedStrategy(
                strategy, max_gross_weight=float(gross_cap)
            )
        result = run_paper(strategy, config, store=None)
        consumed = str(result.reproducibility.get("data_snapshot_id", ""))
        if consumed != pinned_snapshot:
            # run_paper already fails closed on an intra-run mutation; this is
            # the authority-side guarantee that the run consumed the exact
            # snapshot that was authorized, not a different READY generation.
            raise PaperExecutionRejected(
                "paper run consumed a different data snapshot than the one "
                "authorized; refusing to return a result pinned to the wrong "
                "READY snapshot"
            )
        self._attest_consumed_feature_versions(spec, result)
        reproduction = dict(result.reproducibility)
        reproduction.update(
            {
                "execution_authority_scope": execution_scope,
                "max_gross_weight_limit": gross_cap,
                "promotion_eligible": False,
            }
        )
        result = replace(result, reproducibility=reproduction)
        if self.paper_store is not None:
            self.paper_store.save(result)
        return result

    def execute_runtime_dto(self, request: Any) -> PaperRunResult:
        """Adapt ``paper_runtime.execution`` DTO then apply the same authority.

        Raw strategy objects are rejected. This is the only path from the
        name-collision helper into ``run_paper``.
        """
        spec = getattr(request, "strategy", None)
        if not isinstance(spec, StrategySpec):
            raise PaperExecutionRejected(
                "paper_runtime DTO execute requires a StrategySpec; "
                "raw strategies cannot bypass PaperExecutionService"
            )
        config = getattr(request, "config", None)
        if not isinstance(config, PaperRunConfig):
            raise PaperExecutionRejected(
                "paper_runtime DTO execute requires PaperRunConfig"
            )
        max_gross = getattr(request, "max_gross", None)
        if max_gross is None:
            raise PaperExecutionRejected("max_gross required")
        declared_versions = getattr(request, "feature_ref_versions", None)
        if declared_versions:
            expected = {ref.id: str(ref.version) for ref in _iter_feature_refs(spec)}
            for feature_id, version in dict(declared_versions).items():
                pinned = expected.get(str(feature_id))
                if pinned is not None and pinned != str(version):
                    raise PaperExecutionRejected(
                        "feature_ref_versions do not match the StrategySpec"
                    )
        plan = AuthorizedPaperExecutionRequest(
            mode=str(getattr(request, "mode", "")),
            authorization_id=str(getattr(request, "authorization_id", "") or ""),
            strategy_id=spec.strategy_id,
            strategy_spec_hash=str(
                getattr(request, "strategy_spec_hash", "") or ""
            ),
            max_gross_weight=float(max_gross),
            instructions=(),
            ready_snapshot_id=str(getattr(request, "ready_snapshot_id", "") or ""),
            ready_manifest_digest=str(
                getattr(request, "ready_manifest_digest", "") or ""
            ),
            readiness_attestation_id=str(
                getattr(request, "readiness_attestation_id", "") or ""
            ),
            profile_digest=str(getattr(request, "profile_digest", "") or ""),
            plan_set_digest=str(
                getattr(request, "plan_set_digest", "") or ""
            ),
            dependency_closure_digest=str(
                getattr(request, "dependency_closure_digest", "") or ""
            ),
            universe=tuple(getattr(request, "universe", ()) or ()),
            period_start=str(getattr(request, "period_start", "") or ""),
            period_end=str(getattr(request, "period_end", "") or ""),
            cost_scenario=str(getattr(request, "cost_scenario", "default") or "default"),
            expires_at=str(getattr(request, "expires_at", "") or ""),
        )
        object.__setattr__(
            plan,
            "feature_ref_versions",
            declared_versions,
        )
        return self.execute(plan, spec, config)

    def _authorize(
        self,
        plan: AuthorizedPaperExecutionRequest,
        spec: StrategySpec,
        config: PaperRunConfig,
        *,
        require_ready: bool,
    ) -> str:
        # 1. mode: the Phase 7 trader supports paper execution only.
        if plan.mode != "paper":
            raise PaperExecutionRejected("only paper mode is executable")

        # 2. StrategySpec hash: the authorization must cover this exact spec.
        expected_hash = _strategy_spec_hash(spec)
        if plan.strategy_spec_hash != expected_hash:
            raise PaperExecutionRejected(
                "strategy_spec_hash does not match the StrategySpec"
            )
        if plan.strategy_id != spec.strategy_id:
            raise PaperExecutionRejected(
                "strategy_id does not match the StrategySpec"
            )

        # 3. authorization id: re-derive covering READY pin + period + universe.
        expected_auth = _authorization_id(
            plan.mode,
            expected_hash,
            plan.max_gross_weight,
            ready_snapshot_id=getattr(plan, "ready_snapshot_id", "") or "",
            ready_manifest_digest=getattr(plan, "ready_manifest_digest", "") or "",
            readiness_attestation_id=(
                getattr(plan, "readiness_attestation_id", "") or ""
            ),
            profile_digest=getattr(plan, "profile_digest", "") or "",
            plan_set_digest=getattr(plan, "plan_set_digest", "") or "",
            dependency_closure_digest=(
                getattr(plan, "dependency_closure_digest", "") or ""
            ),
            universe=getattr(plan, "universe", ()) or (),
            period_start=getattr(plan, "period_start", "") or "",
            period_end=getattr(plan, "period_end", "") or "",
            cost_scenario=getattr(plan, "cost_scenario", "default") or "default",
        )
        if plan.authorization_id != expected_auth:
            raise PaperExecutionRejected(
                "authorization_id does not match the canonical authorization"
            )

        # 4. constraints: the gross-leverage ceiling the PM/trader approved.
        if not 0.0 < float(plan.max_gross_weight) <= 1.0:
            raise PaperExecutionRejected(
                "max_gross_weight constraint must be in (0, 1]"
            )

        # 4b. expiry
        expires_at = getattr(plan, "expires_at", "") or ""
        if expires_at:
            from datetime import datetime, timezone

            try:
                exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if now > exp:
                    raise PaperExecutionRejected("paper authorization expired")
            except ValueError as exc:
                raise PaperExecutionRejected(
                    f"invalid authorization expires_at: {expires_at}"
                ) from exc

        # 5. exact READY snapshot: prefer authorization pin; never silently
        #    invent a different mutable current DB when pin is present.
        db_path = Path(config.db_path or "data/structured/ingestion.sqlite")
        try:
            pinned_snapshot = data_snapshot_id(db_path)
        except FileNotFoundError as exc:
            raise PaperExecutionRejected(str(exc)) from exc

        auth_snap = getattr(plan, "ready_snapshot_id", "") or ""
        if require_ready and not str(auth_snap).strip():
            raise PaperExecutionRejected(
                "controlled authorization has empty "
                "ready_snapshot_id; refusing paper execution without READY pin"
            )
        if auth_snap and auth_snap != pinned_snapshot:
            raise PaperExecutionRejected(
                "authorized ready_snapshot_id does not match config db snapshot; "
                "refusing mutable/current DB substitution"
            )
        if plan.universe and config.universe:
            if tuple(str(u) for u in config.universe) != tuple(plan.universe):
                raise PaperExecutionRejected(
                    "config universe does not match authorized universe"
                )
        if plan.period_start and str(config.start) != plan.period_start:
            raise PaperExecutionRejected("config start does not match authorized period")
        if plan.period_end and str(config.end) != plan.period_end:
            raise PaperExecutionRejected("config end does not match authorized period")

        # 6. FeatureRef versions: every referenced feature must resolve to an
        #    approved signal definition at the exact pinned version.
        self._validate_feature_refs(spec)
        self._attest_declared_feature_versions(plan, spec)

        # 7. Research data profile identity (digest pin). Does not publish
        #    READY, arm Mass, or evaluate profile_ready evidence.
        self._attest_research_profile(plan, spec)

        return pinned_snapshot

    @staticmethod
    def _validate_feature_refs(spec: StrategySpec) -> None:
        for ref in _iter_feature_refs(spec):
            try:
                definition = features.get_for_strategy(
                    ref.id,
                    version=ref.version,
                    allowed_statuses=("approved",),
                    allowed_roles=("signal",),
                )
            except (KeyError, features.FeatureGovernanceError) as exc:
                raise PaperExecutionRejected(
                    f"FeatureRef {ref.id!r} version {ref.version!r} is not an "
                    f"approved signal feature"
                ) from exc
            if str(definition.version) != str(ref.version):
                raise PaperExecutionRejected(
                    f"FeatureRef {ref.id!r} resolved to version "
                    f"{definition.version!r}, not the pinned {ref.version!r}"
                )

    @staticmethod
    def _attest_declared_feature_versions(
        plan: AuthorizedPaperExecutionRequest, spec: StrategySpec
    ) -> None:
        declared = getattr(plan, "feature_ref_versions", None) or {}
        if not declared:
            return
        expected = {ref.id: str(ref.version) for ref in _iter_feature_refs(spec)}
        for feature_id, version in dict(declared).items():
            pinned = expected.get(str(feature_id))
            if pinned is not None and pinned != str(version):
                raise PaperExecutionRejected(
                    "feature_ref_versions do not match the StrategySpec"
                )

    @staticmethod
    def _attest_research_profile(
        plan: AuthorizedPaperExecutionRequest, spec: StrategySpec
    ) -> None:
        from research.research_data_profile import load_core_profile

        profile = load_core_profile()
        digest = str(profile.profile_digest or "")
        if not digest.startswith("sha256:"):
            raise PaperExecutionRejected(
                "core research data profile digest is missing; "
                "refusing paper execution"
            )
        pinned_versions = {
            str(dep.get("id")): str(dep.get("version"))
            for dep in profile.feature_dependencies
            if dep.get("id")
        }
        for ref in _iter_feature_refs(spec):
            if ref.id in pinned_versions and pinned_versions[ref.id] != str(ref.version):
                raise PaperExecutionRejected(
                    f"FeatureRef {ref.id!r} version {ref.version!r} does not "
                    f"match research data profile pin {pinned_versions[ref.id]!r}"
                )

    @staticmethod
    def _attest_consumed_feature_versions(
        spec: StrategySpec, result: PaperRunResult
    ) -> None:
        consumed = result.reproducibility.get("feature_versions") or {}
        if not isinstance(consumed, dict):
            return
        for ref in _iter_feature_refs(spec):
            got = consumed.get(ref.id)
            if got is not None and str(got) != str(ref.version):
                raise PaperExecutionRejected(
                    f"paper run consumed FeatureRef {ref.id!r} version "
                    f"{got!r}, not the pinned {ref.version!r}"
                )


class OfflineFixturePaperService(PaperExecutionService):
    """Nominal DRAFT-only entry for mutable local fixture databases."""


class ControlledPilotExecutionService:
    """Only controlled path from exact plan + READY to one paper run."""

    def __init__(
        self,
        *,
        verifier: Any,
        paper_store: JsonPaperStore | None = None,
    ) -> None:
        from research.readiness import ReadinessPublicKeyRegistry

        if not isinstance(verifier, ReadinessPublicKeyRegistry):
            raise PaperExecutionRejected(
                "controlled pilot requires a public-key-only readiness verifier"
            )
        self._verifier = verifier
        self._core = PaperExecutionService(paper_store=paper_store)

    def execute(
        self,
        *,
        experiment_plan: Any,
        dependency_closure: Any,
        plan_set_binding: Any,
        ready_manifest: Any,
        readiness: Any,
        authorization: AuthorizedPaperExecutionRequest,
        strategy_spec: StrategySpec,
        config: ControlledPilotRunConfig,
    ) -> PaperRunResult:
        from research.artifacts import ExperimentPlan
        from research.dependency_closure import (
            PlanDependencyClosure,
            verify_plan_dependency_closure,
        )
        from research.readiness import VerifiedPilotReadiness
        from research.ready_manifest import (
            ExactFourPilotReadyBinding,
            ReadyManifest,
            validate_ready_manifest_profile_binding,
        )

        if not isinstance(experiment_plan, ExperimentPlan):
            raise PaperExecutionRejected("exact ExperimentPlan v2 required")
        if not isinstance(dependency_closure, PlanDependencyClosure):
            raise PaperExecutionRejected("PlanDependencyClosure required")
        if not isinstance(plan_set_binding, ExactFourPilotReadyBinding):
            raise PaperExecutionRejected("exact-four plan-set binding required")
        if not isinstance(ready_manifest, ReadyManifest):
            raise PaperExecutionRejected("ReadyManifest required")
        if not isinstance(readiness, VerifiedPilotReadiness):
            raise PaperExecutionRejected("VerifiedPilotReadiness required")
        if not isinstance(config, ControlledPilotRunConfig):
            raise PaperExecutionRejected("ControlledPilotRunConfig required")
        if not isinstance(authorization, AuthorizedPaperExecutionRequest):
            raise PaperExecutionRejected("Trader paper authorization required")

        verify_plan_dependency_closure(experiment_plan, dependency_closure)
        if experiment_plan.plan_id not in plan_set_binding.plan_ids:
            raise PaperExecutionRejected("ExperimentPlan is not in exact-four binding")
        selected = {
            closure.plan_id: closure for closure in plan_set_binding.closures
        }.get(experiment_plan.plan_id)
        if (
            selected is None
            or selected.to_dict() != dependency_closure.to_dict()
        ):
            raise PaperExecutionRejected(
                "ExperimentPlan dependency closure is not the governed exact-four closure"
            )
        if (
            experiment_plan.strategy_spec_id != strategy_spec.strategy_id
            or experiment_plan.strategy_spec_version != strategy_spec.version
            or experiment_plan.strategy_spec_hash != _strategy_spec_hash(strategy_spec)
        ):
            raise PaperExecutionRejected(
                "ExperimentPlan does not bind the supplied StrategySpec"
            )

        validate_ready_manifest_profile_binding(
            ready_manifest, profile=plan_set_binding
        )
        manifest_digest = ready_manifest.to_dict()["manifest_digest"]
        artifact = config.snapshot.verify()
        if (
            experiment_plan.ready_snapshot_id != ready_manifest.snapshot_id
            or config.snapshot.snapshot_id != ready_manifest.snapshot_id
        ):
            raise PaperExecutionRejected(
                "ExperimentPlan/ReadyManifest/immutable snapshot id mismatch"
            )
        if ready_manifest.plan_set_digest != plan_set_binding.plan_set_digest:
            raise PaperExecutionRejected("ReadyManifest plan-set digest mismatch")
        if (
            ready_manifest.dependency_closure_digest
            != plan_set_binding.closure_set_digest
        ):
            raise PaperExecutionRejected("ReadyManifest closure-set digest mismatch")
        readiness.require_valid(
            expected_snapshot_id=ready_manifest.snapshot_id,
            expected_plan_set_digest=plan_set_binding.plan_set_digest,
            expected_closure_digest=plan_set_binding.closure_set_digest,
            verifier=self._verifier,
        )
        if (
            readiness.ready_manifest_digest != manifest_digest
            or readiness.immutable_db_digest != config.snapshot.immutable_db_digest
            or readiness.profile_digest != plan_set_binding.profile_digest
            or readiness.dataset_ids != ready_manifest.dataset_ids
        ):
            raise PaperExecutionRejected(
                "readiness/manifest/profile/immutable artifact digest chain mismatch"
            )

        if (
            config.start != experiment_plan.period_start
            or config.end != experiment_plan.period_end
            or config.universe_contract_id not in experiment_plan.universe
        ):
            raise PaperExecutionRejected(
                "controlled config period or universe contract mismatches ExperimentPlan"
            )
        if authorization.mode != "paper":
            raise PaperExecutionRejected("controlled execution mode is fixed to paper")
        expected_auth_fields = {
            "ready_snapshot_id": ready_manifest.snapshot_id,
            "ready_manifest_digest": manifest_digest,
            "readiness_attestation_id": readiness.attestation_id,
            "profile_digest": plan_set_binding.profile_digest,
            "plan_set_digest": plan_set_binding.plan_set_digest,
            "dependency_closure_digest": plan_set_binding.closure_set_digest,
        }
        for field, expected in expected_auth_fields.items():
            if str(getattr(authorization, field, "") or "") != expected:
                raise PaperExecutionRejected(
                    f"Trader authorization {field} does not match controlled READY"
                )
        if (
            authorization.period_start != experiment_plan.period_start
            or authorization.period_end != experiment_plan.period_end
            or authorization.cost_scenario != experiment_plan.cost_scenario
            or tuple(authorization.universe) != tuple(config.universe)
        ):
            raise PaperExecutionRejected(
                "Trader authorization period/universe/cost does not match plan"
            )
        if float(authorization.max_gross_weight) > float(config.max_gross_weight):
            raise PaperExecutionRejected(
                "Trader authorization exceeds controlled gross limit"
            )

        runtime_config = config.to_runtime_config(
            artifact_path=artifact,
            dependency_closure_digest=dependency_closure.closure_digest,
        )
        return self._core._execute_verified(
            authorization,
            strategy_spec,
            runtime_config,
            require_ready=True,
            execution_scope="CONTROLLED_PILOT",
            # The controlled config is the system ceiling.  A Trader may
            # authorize a narrower book, and execution must preserve that
            # narrower positive capability instead of silently widening it
            # back to the system limit.
            gross_cap=float(authorization.max_gross_weight),
        )


__all__ = [
    "ControlledPilotExecutionService",
    "ControlledPilotRunConfig",
    "ImmutableSnapshotHandle",
    "OfflineFixturePaperService",
    "PaperExecutionRejected",
    "PaperExecutionService",
]
