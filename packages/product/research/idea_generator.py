"""Hypothesis-class-aware research idea generation (W77 / w0816k).

Default generation uses the multi-class registry mix and **never** mass-defaults
to ``simple_daily_sign`` (opt-in only). Does not arm Mass / READY / Phase7.

This is a **declaration helper** for ResearchIdea payloads — not a mass job
runner and not connected to ``agents.mass_research``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from research.artifacts import ResearchIdea
from research.hypothesis_classes import (
    CLASS_SIMPLE_DAILY_SIGN,
    MASS_RESEARCH,
    PHASE7,
    READY_DECLARED,
    REGISTRY_VERSION,
    REGISTRY_WAVE,
    assert_generation_mix_not_skewed,
    build_research_idea_payload,
    default_generation_class_ids,
    get_hypothesis_class,
    is_generation_enabled,
    select_generation_classes,
)

GENERATOR_VERSION: str = "hypothesis-idea-generator/v1"
GENERATOR_WAVE: str = REGISTRY_WAVE


@dataclass(frozen=True)
class GeneratedIdeaBatch:
    """One generation batch (ResearchIdea declarations only)."""

    batch_id: str
    class_ids: tuple[str, ...]
    ideas: tuple[ResearchIdea, ...]
    simple_daily_sign_included: bool
    version: str = GENERATOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "class_ids": list(self.class_ids),
            "ideas": [idea.to_dict() for idea in self.ideas],
            "simple_daily_sign_included": self.simple_daily_sign_included,
            "mass_research": MASS_RESEARCH,
            "phase7": PHASE7,
            "ready_declared": READY_DECLARED,
            "version": self.version,
            "registry_version": REGISTRY_VERSION,
            "wave": GENERATOR_WAVE,
        }


def generate_idea_payloads(
    *,
    author: str,
    batch_id: str = "idea-gen-default",
    n_classes: int | None = None,
    class_ids: Sequence[str] | None = None,
    explicit_opt_in: Sequence[str] | None = None,
    include_simple_daily_sign: bool = False,
    hypotheses_by_class: Mapping[str, str] | None = None,
) -> GeneratedIdeaBatch:
    """Generate ResearchIdea objects across the selected class mix.

    Parameters
    ----------
    include_simple_daily_sign:
        Explicit opt-in. Default **False** — simple_daily_sign is not generated.
    class_ids:
        Optional override list; still filtered by generation policy.
    hypotheses_by_class:
        Optional map class_id → hypothesis text; default text is class description.
    """
    selected = select_generation_classes(
        n=n_classes,
        class_ids=class_ids,
        explicit_opt_in=explicit_opt_in,
        include_simple_daily_sign=include_simple_daily_sign,
    )
    assert_generation_mix_not_skewed(selected)

    hyp_map = dict(hypotheses_by_class or {})
    ideas: list[ResearchIdea] = []
    for i, cid in enumerate(selected):
        spec = get_hypothesis_class(cid)
        hyp_text = str(hyp_map.get(cid) or "").strip()
        if not hyp_text:
            hyp_text = (
                f"[{spec.class_id}] {spec.description or spec.display_name} "
                f"(horizon={spec.horizon}; research declaration only)"
            )
        payload = build_research_idea_payload(
            class_id=cid,
            idea_id=f"{batch_id}:{cid}:{i}",
            hypothesis=hyp_text,
            author=author,
            explicit_opt_in=explicit_opt_in
            if not include_simple_daily_sign
            else list(explicit_opt_in or ()) + [CLASS_SIMPLE_DAILY_SIGN],
            extra_lineage={
                "generator_version": GENERATOR_VERSION,
                "batch_id": batch_id,
            },
        )
        ideas.append(ResearchIdea.from_dict(payload))

    return GeneratedIdeaBatch(
        batch_id=str(batch_id).strip(),
        class_ids=selected,
        ideas=tuple(ideas),
        simple_daily_sign_included=CLASS_SIMPLE_DAILY_SIGN in selected,
    )


def default_generation_policy() -> dict[str, Any]:
    """Document the default generation policy (for scheduler / agents)."""
    return {
        "version": GENERATOR_VERSION,
        "wave": GENERATOR_WAVE,
        "default_class_ids": list(default_generation_class_ids()),
        "simple_daily_sign_default": False,
        "simple_daily_sign_class_id": CLASS_SIMPLE_DAILY_SIGN,
        "opt_in_required_for": [CLASS_SIMPLE_DAILY_SIGN],
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "note": (
            "Default idea generation uses multi_day_hold, event_post, "
            "cross_section_relative, macro_conditioned, fundamentals_price, "
            "flow_demand. simple_daily_sign is lowest priority and OFF unless "
            "explicitly opted in. Not connected to Mass / READY."
        ),
    }


def require_class_generation_allowed(
    class_id: str,
    *,
    explicit_opt_in: Sequence[str] | None = None,
) -> None:
    """Raise ValueError if class is not allowed under generation policy."""
    if not is_generation_enabled(class_id, explicit_opt_in=explicit_opt_in):
        raise ValueError(
            f"hypothesis class {class_id!r} not allowed for generation "
            f"without explicit opt-in (simple_daily_sign default OFF)"
        )


__all__ = [
    "GENERATOR_VERSION",
    "GENERATOR_WAVE",
    "GeneratedIdeaBatch",
    "default_generation_policy",
    "generate_idea_payloads",
    "require_class_generation_allowed",
]
