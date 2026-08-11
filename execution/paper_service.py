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
from pathlib import Path

import features
from agents.types import AuthorizedPaperExecutionRequest
from paper_runtime import data_snapshot_id
from strategies.paper import JsonPaperStore, PaperRunConfig, PaperRunResult, run_paper
from strategies.spec import StrategySpec, interpret_strategy_spec


class PaperExecutionRejected(ValueError):
    """Raised when an execution request fails the authority gate."""


def _strategy_spec_hash(spec: StrategySpec) -> str:
    """Re-derive the canonical StrategySpec hash covered by authorization."""
    blob = json.dumps(
        spec.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _authorization_id(mode: str, spec_hash: str, max_gross_weight: float) -> str:
    """Re-derive the immutable authorization id from its three covered fields.

    Mirrors :meth:`agents.trader.TraderAgent.prepare` byte-for-byte so a request
    minted by the trader is accepted and a tampered one is refused.
    """
    payload = {
        "mode": mode,
        "strategy_spec_hash": spec_hash,
        "max_gross_weight": max_gross_weight,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


class PaperExecutionService:
    """The single positive capability reaching :func:`strategies.paper.run_paper`.

    Construction is cheap and stateless aside from the optional paper store.
    :meth:`execute` is the only entry point; it never exposes ``run_paper``,
    the SQLite path, or any engine handle to its caller.
    """

    def __init__(self, paper_store: JsonPaperStore | None = None) -> None:
        self.paper_store = paper_store

    def execute(
        self,
        plan: AuthorizedPaperExecutionRequest,
        spec: StrategySpec,
        config: PaperRunConfig,
    ) -> PaperRunResult:
        """Authorize the request, run paper, and verify the pinned snapshot."""
        pinned_snapshot = self._authorize(plan, spec, config)
        strategy = interpret_strategy_spec(spec)
        result = run_paper(strategy, config, store=self.paper_store)
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
        return result

    def _authorize(
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

        # 3. authorization id: re-derive the immutable id from (mode, hash,
        #    constraint) and require an exact match. A replayed or tampered id
        #    is refused even if the individual fields happen to look valid.
        expected_auth = _authorization_id(
            plan.mode, expected_hash, plan.max_gross_weight
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

        # 5. exact READY snapshot: pin the data snapshot before any trusted
        #    work runs, then (in execute) prove the run consumed this exact one.
        db_path = Path(config.db_path or "data/structured/ingestion.sqlite")
        try:
            pinned_snapshot = data_snapshot_id(db_path)
        except FileNotFoundError as exc:
            raise PaperExecutionRejected(str(exc)) from exc

        # 6. FeatureRef versions: every referenced feature must resolve to an
        #    approved signal definition at the exact pinned version.
        self._validate_feature_refs(spec)

        return pinned_snapshot

    @staticmethod
    def _validate_feature_refs(spec: StrategySpec) -> None:
        ref = spec.rule.feature
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


__all__ = ["PaperExecutionService", "PaperExecutionRejected"]
