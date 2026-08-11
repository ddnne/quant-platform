"""Public types for the features package.

A :class:`FeatureDefinition` is metadata: id, version, required inputs,
``as_of`` rule. A :class:`FeatureOutput` is the value computed for one
``(as_of, code, ...)`` key plus provenance metadata that makes the call
reproducible (``as_of``, ``feature_id``, ``feature_version``,
``pit_api_version``, ``rows_seen``, ``db_path``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

# Lifecycle / role vocabularies. ``Literal`` keeps the values statically
# checkable and lets the registry refuse unknown roles at construction time.
IntendedRole = Literal["signal", "state", "structural", "utility"]
FeatureStatus = Literal["candidate", "shadow", "approved", "retired"]


@dataclass(frozen=True)
class FeatureVersion:
    """SemVer-ish version of a feature's compute contract.

    Bump ``major`` when the output meaning changes (so callers must opt in to
    the new behaviour); bump ``minor`` when compatible inputs are added;
    bump ``patch`` for fixes that preserve semantics.
    """

    major: int
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class FeatureInput:
    """Required input keys for a feature compute call.

    The runtime enforces these: a call missing a required key raises
    ``KeyError`` before the compute function runs.

    ``as_of_rule`` documents how ``as_of`` should be interpreted for this
    feature — e.g. ``"session_close"`` means the feature value is the value
    observable at the close of the ``as_of`` session (PIT-safe because PIT's
    ``available_at <= as_of`` is the hard gate).
    """

    required_kwargs: tuple[str, ...] = ("code",)
    optional_kwargs: Mapping[str, Any] = field(default_factory=dict)
    as_of_rule: str = "session_close"


@dataclass(frozen=True)
class FeatureOutput:
    """A single computed feature value with provenance metadata.

    ``value`` may be any JSON-serializable type (float, dict, list). ``None``
    signals "feature could not be computed from the visible facts" (e.g.
    insufficient history) — distinct from an exception, which signals a
    contract violation (missing input, PIT failure).
    """

    value: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureDefinition:
    """Static definition of one feature: identity, contract, compute fn.

    ``compute(ctx)`` is called by :func:`features.runtime.compute` with a
    read-only :class:`features.runtime.FeatureContext` carrying the PIT
    getters scoped to ``as_of``. The compute function must be a pure function
    of ``(ctx, as_of, inputs)``; it must NOT touch wall-clock time, randomness,
    or any global state.

    Lifecycle / role metadata (P0-5):

    * ``intended_role`` (required) declares *how the feature is meant to be
      consumed* — ``"signal"`` (model input), ``"state"`` (regime / context),
      ``"structural"`` (universe / master-derived), or ``"utility"`` (debug /
      diagnostic only). A model registry can refuse to ingest features whose
      role it does not support.
    * ``status`` (optional, default ``"approved"`` for built-ins) is the
      promotion tier: ``"candidate"`` (unvetted), ``"shadow"`` (logged but
      not used), ``"approved"`` (default for shipped features), ``"retired"``
      (kept for audit; do not consume in new code).
    """

    id: str
    version: FeatureVersion
    inputs: FeatureInput
    description: str
    compute: Callable[[Any], FeatureOutput]
    tags: tuple[str, ...] = ()
    intended_role: IntendedRole = "signal"
    status: FeatureStatus = "approved"
