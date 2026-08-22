"""Profit-hypothesis LLM/agent entry (not window tweaks; not GO).

Generation stays in ``research.offline.factory``. Unique/combo templates
are not enabled here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from research.offline.factory_templates import (
    LOGIC_TEMPLATES,
    NUMERIC_ONLY_KNOBS,
)
from research.unique_logic.constants import RESEARCH_UNIQUE_LOGIC_IDS


def _is_window_tweak_only(proposal: Mapping[str, Any]) -> bool:
    """True when proposal only mutates hold/mom/frac without new thesis/signal."""
    thesis = str(proposal.get("thesis") or "").strip()
    signal = str(
        proposal.get("signal_definition") or proposal.get("signal") or ""
    ).strip()
    position = str(
        proposal.get("position_rule") or proposal.get("position") or ""
    ).strip()
    if not thesis or not signal or not position:
        return True
    structural = (
        proposal.get("structural_keys")
        or proposal.get("mode")
        or (proposal.get("params") or {}).get("mode")
    )
    params = dict(proposal.get("params") or {})
    only_numeric = (
        bool(params)
        and set(params.keys()) <= NUMERIC_ONLY_KNOBS
        and not structural
    )
    if only_numeric and str(proposal.get("logic_id") or "") in LOGIC_TEMPLATES:
        return True
    tweak_words = ("window", "hold_days only", "mom only", "frac only")
    blob = f"{thesis} {signal}".lower()
    if any(w in blob for w in tweak_words) and "factor" not in blob:
        if not proposal.get("datasets") and not proposal.get("datasets_used"):
            return True
    return False


def propose_profit_hypotheses(
    proposals: Sequence[Mapping[str, Any]],
    *,
    evaluate: bool = True,
    synthetic: bool = False,
    config: MassFactoryConfig | None = None,
    ctx: BatchDataContext | None = None,
) -> dict[str, Any]:
    """Entry for different profit hypotheses (not window tweaks).

    Always through the factory evaluator when ``evaluate=True``.
    Does not arm Mass / READY / GO / continuous paper.
    """
    cfg = config or MassFactoryConfig(seed=DEFAULT_SEED, n=max(20, len(proposals) + 5))
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for i, raw in enumerate(proposals):
        prop = dict(raw or {})
        if _is_window_tweak_only(prop):
            rejected.append(
                {
                    "index": i,
                    "proposal": prop,
                    "reject_reason": "window_tweak_only_forbidden",
                }
            )
            continue
        logic_id = str(prop.get("logic_id") or "").strip()
        if logic_id and logic_id in LOGIC_TEMPLATES:
            tpl = LOGIC_TEMPLATES[logic_id]
            params = dict(tpl.base_params)
            params.update(dict(prop.get("params") or {}))
            ok, reason = validate_strategy_at_gen(
                tpl.family_id,
                params,
                available_datasets=cfg.available_datasets,
                logic_id=logic_id,
            )
            if not ok:
                rejected.append(
                    {
                        "index": i,
                        "proposal": prop,
                        "reject_reason": reason,
                    }
                )
                continue
            ind = {
                "strategy_id": stable_strategy_id(
                    seed=cfg.seed,
                    family_id=tpl.family_id,
                    params=params,
                    generation_index=i,
                    logic_id=logic_id,
                ),
                "logic_id": logic_id,
                "logic_fingerprint": tpl.logic_fingerprint(),
                "thesis": str(prop.get("thesis") or tpl.thesis),
                "signal_definition": str(
                    prop.get("signal_definition") or tpl.signal_definition
                ),
                "position_rule": str(
                    prop.get("position_rule") or tpl.position_rule
                ),
                "datasets_used": list(
                    prop.get("datasets_used")
                    or prop.get("datasets")
                    or tpl.datasets_used
                ),
                "datasets_required": list(tpl.datasets_used),
                "family_id": tpl.family_id,
                "params": params,
                "status": "accepted",
                "source": "profit_hypothesis_entry",
                "generation_index": i,
                "seed": cfg.seed,
            }
            if logic_id in RESEARCH_UNIQUE_LOGIC_IDS:
                ind["eval_mapped_to_catalog"] = False
                ind["research_family_recognition"] = True
                ind["research_candidate"] = False
                ind["promote_as_main"] = False
                ind["go"] = False
                ind["registration"] = "recognition"
                ind["registration_is_not_a_pass"] = True
            accepted.append(ind)
        else:
            family = str(
                prop.get("family_id") or prop.get("family") or ""
            ).strip()
            if not family:
                rejected.append(
                    {
                        "index": i,
                        "proposal": prop,
                        "reject_reason": "missing_logic_id_or_family",
                    }
                )
                continue
            params = dict(prop.get("params") or {})
            ind = {
                "strategy_id": stable_strategy_id(
                    seed=cfg.seed,
                    family_id=family,
                    params=params,
                    generation_index=i,
                    logic_id=logic_id or f"adhoc_{i}",
                ),
                "logic_id": logic_id or f"adhoc_{i}",
                "logic_fingerprint": hashlib.sha256(
                    json.dumps(
                        {
                            "thesis": prop.get("thesis"),
                            "signal": prop.get("signal_definition"),
                            "position": prop.get("position_rule"),
                            "family": family,
                        },
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()[:16],
                "thesis": str(prop.get("thesis") or ""),
                "signal_definition": str(
                    prop.get("signal_definition") or prop.get("signal") or ""
                ),
                "position_rule": str(
                    prop.get("position_rule") or prop.get("position") or ""
                ),
                "datasets_used": list(
                    prop.get("datasets_used") or prop.get("datasets") or []
                ),
                "datasets_required": list(
                    prop.get("datasets_used") or prop.get("datasets") or []
                ),
                "family_id": family,
                "params": params,
                "status": "accepted",
                "source": "profit_hypothesis_entry_adhoc",
                "generation_index": i,
                "seed": cfg.seed,
            }
            accepted.append(ind)

    out: dict[str, Any] = {
        "version": MASS_FACTORY_VERSION,
        "wave": MASS_FACTORY_WAVE,
        "n_proposals": len(proposals),
        "n_accepted": len(accepted),
        "n_rejected": len(rejected),
        "accepted": accepted,
        "rejected": rejected,
        "always_through_evaluator": bool(evaluate),
        **_freeze(),
    }
    if evaluate and accepted:
        from research.offline.factory_eval import run_batch_eval

        gen = {
            "strategies_after_dedup": accepted,
            "strategies": accepted,
            "n_generated": len(accepted),
            "n_unique_logic": len({a["logic_id"] for a in accepted}),
            "n_after_dedup": len(accepted),
            "n_numeric_variant": 0,
            "n_requested": len(accepted),
            "config": cfg.to_dict(),
        }
        batch = run_batch_eval(
            gen, config=cfg, ctx=ctx, synthetic=synthetic
        )
        out["eval"] = {
            k: batch[k]
            for k in batch
            if k not in {"results", "screens"}
        }
        out["eval_screens"] = batch.get("screens")
        out["eval_ranking"] = batch.get("ranking")
        out["eval_results"] = batch.get("results")
    elif evaluate and not accepted:
        out["eval"] = {
            "n_strategies_evaluated": 0,
            "note": "no accepted proposals to evaluate",
        }
    return out


def llm_logic_entry_status() -> dict[str, Any]:
    """LLM / agent entry for different profit hypotheses (not window tweaks)."""
    return {
        "status": "connected",
        "wave": MASS_FACTORY_WAVE,
        "version": MASS_FACTORY_VERSION,
        "entry_fn": "research.offline.factory.propose_profit_hypotheses",
        "always_through_evaluator": True,
        **_freeze(),
    }


from research.offline.factory import (  # noqa: E402
    DEFAULT_SEED,
    MASS_FACTORY_VERSION,
    MASS_FACTORY_WAVE,
    BatchDataContext,
    MassFactoryConfig,
    _freeze,
    stable_strategy_id,
    validate_strategy_at_gen,
)

__all__ = [
    "llm_logic_entry_status",
    "propose_profit_hypotheses",
]
