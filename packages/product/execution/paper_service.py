"""Offline DRAFT execution and the fail-closed Controlled Pilot boundary.

``PaperExecutionService`` and ``OfflineFixturePaperService`` are local DRAFT
helpers only.  Controlled PAPER execution is the research-mass-eval
Worker/Container path.  This module has no local socket, path, store, snapshot
bytes, or verifier injection surface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import features
from agents.types import AuthorizedPaperExecutionRequest
from selection.controlled_pilot_policy import CONTROLLED_PILOT_IDENTITY
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


CONTROLLED_AUTHORITY_UNPROVISIONED = "CONTROLLED_AUTHORITY_UNPROVISIONED"


class ControlledPilotPending(PaperExecutionRejected):
    """Controlled execution is unavailable until Cloudflare/READY evidence exists."""

    status = "PENDING"
    reason_code = CONTROLLED_AUTHORITY_UNPROVISIONED

    def __init__(self, detail: str = "") -> None:
        suffix = f"; {detail}" if detail else ""
        super().__init__(
            f"{self.status}: {self.reason_code}; controlled execution requires "
            f"Cloudflare/READY public-key evidence{suffix}"
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
    universe: tuple[str, ...] | list[str] = (),
    period_start: str = "",
    period_end: str = "",
    cost_scenario: str = "default",
) -> str:
    """Re-derive the immutable DRAFT authorization id (mirrors TraderAgent.prepare)."""
    payload = {
        "mode": mode,
        "strategy_spec_hash": spec_hash,
        "max_gross_weight": max_gross_weight,
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


class PaperExecutionService:
    """Local authorization checks for offline DRAFT experiments.

    Construction is cheap and stateless aside from the optional paper store.
    :meth:`execute_runtime_dto` is the legacy paper_runtime DTO adapter.  This
    service is not a controlled execution authority and rejects READY-bound or
    non-DRAFT inputs.
    """

    __slots__ = ("paper_store",)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("PaperExecutionService is final")

    def __init__(self, paper_store: JsonPaperStore | None = None) -> None:
        self.paper_store = paper_store

    def execute(
        self,
        plan: AuthorizedPaperExecutionRequest,
        spec: StrategySpec,
        config: PaperRunConfig,
    ) -> PaperRunResult:
        """Compatibility entry for offline fixtures only.

        Controlled execution remains PENDING at
        :class:`ControlledPilotExecutionService`.
        """
        if type(config) is not PaperRunConfig:
            raise PaperExecutionRejected(
                "offline fixture execution requires exact PaperRunConfig"
            )
        if type(plan) is not AuthorizedPaperExecutionRequest:
            raise PaperExecutionRejected(
                "offline fixture execution requires AuthorizedPaperExecutionRequest"
            )
        if config.lifecycle is not Lifecycle.DRAFT:
            raise PaperExecutionRejected(
                "PaperExecutionService compatibility entry is offline DRAFT only"
            )
        pinned_snapshot = self._authorize_offline(plan, spec, config)
        strategy: Any = interpret_strategy_spec(spec)
        result = run_paper(strategy, config, store=None)
        return self._finalize_result(
            plan,
            spec,
            result,
            pinned_snapshot=pinned_snapshot,
            execution_scope="OFFLINE_FIXTURE",
            gross_cap=None,
        )

    def _finalize_result(
        self,
        plan: Any,
        spec: StrategySpec,
        result: PaperRunResult,
        *,
        pinned_snapshot: str,
        execution_scope: str,
        gross_cap: float | None,
    ) -> PaperRunResult:
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
        if (
            type(result) is not PaperRunResult
            or result.lifecycle is not Lifecycle.DRAFT
        ):
            raise PaperExecutionRejected(
                "offline execution returned a noncanonical DRAFT result"
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
        if type(config) is not PaperRunConfig:
            raise PaperExecutionRejected(
                "paper_runtime DTO execute requires exact PaperRunConfig"
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
        if any(
            str(getattr(request, name, "") or "").strip()
            for name in (
                "ready_snapshot_id",
                "ready_manifest_digest",
                "readiness_attestation_id",
                "profile_digest",
                "plan_set_digest",
                "dependency_closure_digest",
                "controlled_pilot_identity",
            )
        ):
            raise PaperExecutionRejected(
                "paper_runtime DTO execute is DRAFT-only and cannot consume READY"
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

    def _authorize_offline(
        self,
        plan: AuthorizedPaperExecutionRequest,
        spec: StrategySpec,
        config: PaperRunConfig,
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


# The descriptive DRAFT entry is an alias, not a subclass seam.  Both names
# resolve to the same final implementation, so overriding ``_finalize_result``
# cannot turn a local fixture run into a PAPER result.
OfflineFixturePaperService = PaperExecutionService



class ControlledPilotExecutionService:
    """Fail-closed local facade. Controlled Paper runs only on Cloudflare."""

    __slots__ = ()
    identity = CONTROLLED_PILOT_IDENTITY

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("ControlledPilotExecutionService is final")

    def execute(self, *args: object, **kwargs: object) -> None:
        raise ControlledPilotPending(
            "controlled execution is the research-mass-eval Worker/Container path"
        )




__all__ = [
    "CONTROLLED_AUTHORITY_UNPROVISIONED",
    "ControlledPilotExecutionService",
    "ControlledPilotPending",
    "OfflineFixturePaperService",
    "PaperExecutionRejected",
    "PaperExecutionService",
]
