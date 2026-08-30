"""Fixed 2023 Nikkei-225 index-volatility overlay DRAFT job.

The job reuses the existing personal Container and immutable R2 artifacts.  It
does not expose a new binding, select a winner, promote a strategy, or place an
order.  Single-stock option IV is outside the wire and prepared-row schemas.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import statistics
import tarfile
import tempfile
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

import pit
from research.options_225_smile_features import (
    OPTIONS_225_SMILE_SURFACE_SCOPE,
    build_options_225_smile_slices,
)
from research.options_225_smile_transport import (
    OPTIONS_225_SMILE_TRANSPORT_VERSION,
    build_daily_svi_smile_transport_features,
)
from research.options_225_vol_series import DATASET_ID, build_daily_basevol_series
from research.personal_base_sleeve import (
    validate_personal_base_sleeve_am_pm_artifact,
    validate_personal_base_sleeve_artifact,
)
from research.personal_index_vol_overlay import (
    AM_PM_BASE_COHORT_ID,
    AM_PM_BASE_SLEEVE_ID,
    AM_PM_BASE_SLEEVE_SCHEMA,
    AM_PM_EXECUTION_MODE,
    AmPmFillOutcomeEvidence,
    AmPmLaggedFeatureEvidence,
    AmPmSignalEvidence,
    BETA_MIN_RETURNS,
    IndexVolOverlayAmPmObservation,
    IndexVolOverlayObservation,
    am_pm_base_producer_unavailable_reason,
    verified_am_pm_base_digests,
    OVERLAY_AM_PM_CANDIDATE_IDS,
    SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS,
    SMILE_TRANSPORT_CANDIDATE_IDS,
    SMILE_TRANSPORT_CORE_MODULE,
    TOPIX_ETF_CODE,
    am_pm_proxy_mapping,
    am_pm_temporal_contract_digest,
    build_prepared_am_pm_panel_manifest,
    build_prepared_panel_manifest,
    evaluate_index_smile_transport_overlays,
    evaluate_index_smile_transport_overlays_am_pm,
    evaluate_index_vol_overlays,
    evaluate_index_vol_overlays_am_pm,
    smile_transport_core_digest,
)

from personal_svi_2023_job import (
    COHORT_ID as SVI_COHORT_ID,
    RUNNER_VERSION as SVI_RUNNER_VERSION,
    STRATEGY_ID as SVI_STRATEGY_ID,
    PersonalSvi2023JobSpec,
    _canonical_bytes,
    _put_bytes,
    _read_bounded,
    _safe_detail,
    _sha256,
    load_input_manifest as load_svi_input_manifest,
    load_one_options_day,
    load_panel as load_svi_panel,
)


R2_ORIGIN = "http://research.r2"
COHORT_ID = "personal-index-vol-overlay-2023-v1"
SMILE_TRANSPORT_COHORT_ID = "personal-index-smile-transport-2023-v1"
AM_PM_COHORT_ID = "personal-index-vol-overlay-2023-am-pm-v1"
AM_PM_SMILE_TRANSPORT_COHORT_ID = "personal-index-smile-transport-2023-am-pm-v1"
RUNNER_VERSION = "personal-index-vol-overlay-cloud-runner/v1"
SMILE_TRANSPORT_RUNNER_VERSION = "personal-index-smile-transport-cloud-runner/v1"
AM_PM_RUNNER_VERSION = "personal-index-vol-overlay-am-pm-cloud-runner/v1"
AM_PM_SMILE_TRANSPORT_RUNNER_VERSION = (
    "personal-index-smile-transport-am-pm-cloud-runner/v1"
)
EARLIEST_DAY = "2023-01-04"
LATEST_DAY = "2023-10-13"
INPUT_SCHEMA = "personal-index-vol-overlay-2023-input/v1"
SMILE_TRANSPORT_INPUT_SCHEMA = "personal-index-smile-transport-2023-input/v2"
AM_PM_INPUT_SCHEMA = "personal-index-vol-overlay-2023-am-pm-input/v1"
AM_PM_SMILE_TRANSPORT_INPUT_SCHEMA = (
    "personal-index-smile-transport-2023-am-pm-input/v1"
)
PANEL_SCHEMA = "personal-index-vol-overlay-prepared-panel/v1"
SMILE_TRANSPORT_PANEL_SCHEMA = "personal-index-smile-transport-prepared-panel/v2"
AM_PM_PANEL_SCHEMA = "personal-index-vol-overlay-am-pm-prepared-panel/v1"
AM_PM_SMILE_TRANSPORT_PANEL_SCHEMA = (
    "personal-index-smile-transport-am-pm-prepared-panel/v1"
)
REPORT_SCHEMA = "personal-index-vol-overlay-report/v1"
SMILE_TRANSPORT_REPORT_SCHEMA = "personal-index-smile-transport-report/v2"
AM_PM_REPORT_SCHEMA = "personal-index-vol-overlay-am-pm-report/v1"
AM_PM_SMILE_TRANSPORT_REPORT_SCHEMA = (
    "personal-index-smile-transport-am-pm-report/v1"
)
MANIFEST_SCHEMA = "personal-index-vol-overlay-manifest/v1"
SMILE_TRANSPORT_MANIFEST_SCHEMA = "personal-index-smile-transport-manifest/v2"
AM_PM_MANIFEST_SCHEMA = "personal-index-vol-overlay-am-pm-manifest/v1"
AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA = (
    "personal-index-smile-transport-am-pm-manifest/v1"
)
OVERLAY_R2_PREFIX = "research/personal/index-vol-overlay-2023"
SMILE_TRANSPORT_R2_PREFIX = "research/personal/index-smile-transport-2023"
AM_PM_R2_PREFIX = "research/personal/index-vol-overlay-2023-am-pm"
AM_PM_SMILE_TRANSPORT_R2_PREFIX = (
    "research/personal/index-smile-transport-2023-am-pm"
)
_FITTED_SLICE_FIELDS = (
    "date",
    "expiry",
    "cm",
    "dte_days",
    "maturity_years",
    "under_px",
    "fit_success",
    "fit_reason",
    "svi_parameters",
    "fit_log_moneyness_min",
    "fit_log_moneyness_max",
    "surface_scope",
    "source_dataset_id",
)
SMILE_TRANSPORT_SIGNAL_START_POLICY = (
    "BETA_MIN_63_PAIRS_PLUS_OFFICIAL_D_MINUS_1_AND_D_PLUS_2"
)
_SMILE_TRANSPORT_WINDOW = {
    "start": EARLIEST_DAY,
    "end": LATEST_DAY,
    "signal_start_policy": SMILE_TRANSPORT_SIGNAL_START_POLICY,
    "signal_end_policy": "LAST_SESSION_MINUS_TWO",
}
_SMILE_TRANSPORT_TEMPORAL = {
    "source_decision_cutoff_jst": "15:00:00+09:00",
    "prepared_available_at": "NO_EARLIER_THAN_D_23_59_59_JST",
    "fill_timing": "next_close",
    "first_pnl_interval": "fill_close_to_following_close",
    "no_forward_fill": True,
    "no_expiry_rank_substitution": True,
    "no_extrapolation": True,
    "d_minus_1_rule": "immediately_preceding_official_session",
}
_SMILE_TRANSPORT_CANDIDATES = {
    "ids": list(SMILE_TRANSPORT_CANDIDATE_IDS),
    "sticky_models": ["sticky_strike", "sticky_moneyness"],
    "families": [
        "downside_smile_term_surprise",
        "potential_minimum_transport",
    ],
    "selection": "NOT_PERFORMED",
    "adaptive_model_switch": False,
}
_SMILE_TRANSPORT_FORMULAS = {
    "downside_q": (
        "actual_downside_smile_term_ratio/"
        "predicted_downside_smile_term_ratio-1"
    ),
    "downside_g": "clip(1/(1+q),0.5,1.0)",
    "potential_minimum_M": "(abs(e_front)+abs(e_next))/2+abs(e_next-e_front)",
    "potential_minimum_g": "clip(1/(1+M/0.10),0.5,1.0)",
    "hedge_h": "clip(-g*beta_D,-1.5,1.5)",
}
_SMILE_TRANSPORT_GATE = {
    "min_common_valid_signal_days": 40,
    "min_distinct_calendar_months": 4,
    "common_invalid_policy": "flatten_g0_h0_at_d_plus_1_close_prior",
}
_SMILE_TRANSPORT_CORE = {
    "version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
    "module": SMILE_TRANSPORT_CORE_MODULE,
}
_SMILE_TRANSPORT_PHYSICAL = {"metaphor_only": True, "causal_claim": False}
_SMILE_TRANSPORT_SVI_FEATURES = {
    "trusted_for_transport": False,
    "reason": "lacks_exact_expiry_svi_parameters_and_fit_bands",
}
BASE_STRATEGY_ID = "personal_sector_balanced_four_factor_v1_ls"
BASE_COHORT_ID = "sector-relative-ls-v1"
BASE_UNIVERSE_ID = "topix_all"
MAX_INPUT_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 512 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_BASE_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_FEATURE_BYTES = 8 * 1024 * 1024
TRADING_DAY_FLAG = "1"
ANNUALIZATION_SESSIONS = 252

_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_WINDOW = {
    "start": EARLIEST_DAY,
    "end": LATEST_DAY,
    "signal_start_policy": (
        "RV20_20_RETURN_WARMUP_PLUS_INCLUSIVE_126_RATIO_HISTORY"
    ),
    "signal_end_policy": "LAST_SESSION_MINUS_TWO",
}
_TEMPORAL = {
    "source_decision_cutoff_jst": "15:00:00+09:00",
    "prepared_available_at": "SAME_DAY_23_59_59_JST",
    "fill_timing": "next_close",
    "first_pnl_interval": "fill_close_to_following_close",
    "no_forward_fill": True,
}
_AM_PM_WINDOW = {
    "start": EARLIEST_DAY,
    "end": LATEST_DAY,
    "signal_start_policy": (
        "D_MINUS_1_OPTION_HISTORY_PLUS_D_AM_BETA_AND_D_PLUS_1_PM"
    ),
    "signal_end_policy": "LAST_SESSION_MINUS_ONE",
}
_AM_PM_SMILE_WINDOW = {
    "start": EARLIEST_DAY,
    "end": LATEST_DAY,
    "signal_start_policy": "BETA_MIN_63_PAIRS_PLUS_OFFICIAL_D_MINUS_2_AND_D_PLUS_1_PM",
    "signal_end_policy": "LAST_SESSION_MINUS_ONE",
}
_AM_PM_TEMPORAL = {
    "source_decision_cutoff_jst": "11:30:00+09:00",
    "equity_am_usable_by_jst": "12:30:00+09:00",
    "prepared_available_at": "NO_LATER_THAN_D_12_30_JST",
    "fill_timing": "d_pm_aadjc",
    "first_pnl_interval": "d_pm_to_d_plus_1_pm",
    "order_sizing": "d_am_price",
    "option_signal_as_of": "through_d_minus_1",
    "no_forward_fill": True,
    "no_full_close_fallback": True,
    "no_recovery_promotion": True,
}
_AM_PM_SMILE_TEMPORAL = {
    **_AM_PM_TEMPORAL,
    "smile_transport_pair": "d_minus_2_to_d_minus_1",
    "no_expiry_rank_substitution": True,
    "no_extrapolation": True,
    "d_minus_1_rule": "immediately_preceding_official_session",
}
_AM_PM_OVERLAY_CANDIDATES = {
    "ids": list(OVERLAY_AM_PM_CANDIDATE_IDS),
    "selection": "NOT_PERFORMED",
    "adaptive_model_switch": False,
}
_AM_PM_SMILE_CANDIDATES = {
    "ids": list(SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS),
    "sticky_models": ["sticky_strike", "sticky_moneyness"],
    "families": [
        "downside_smile_term_surprise",
        "potential_minimum_transport",
    ],
    "selection": "NOT_PERFORMED",
    "adaptive_model_switch": False,
}
_AM_PM_SMILE_GATE = {
    "min_common_valid_signal_days": 40,
    "min_distinct_calendar_months": 4,
    "common_invalid_policy": "flatten_g0_h0_at_d_pm",
}
_INPUT_AUTHORITY = {
    "draft_only": True,
    "screening_only": True,
    "ready": False,
    "mass": False,
    "promotion": False,
    "live_orders": False,
    "go": False,
    "single_stock_option_iv": "FORBIDDEN",
}


class OverlayJobInputError(ValueError):
    """The Worker supplied a non-closed overlay job document."""


def _closed_identity(cohort_id: str, runner_version: str) -> str:
    if cohort_id == COHORT_ID and runner_version == RUNNER_VERSION:
        return OVERLAY_R2_PREFIX
    if (
        cohort_id == SMILE_TRANSPORT_COHORT_ID
        and runner_version == SMILE_TRANSPORT_RUNNER_VERSION
    ):
        return SMILE_TRANSPORT_R2_PREFIX
    if cohort_id == AM_PM_COHORT_ID and runner_version == AM_PM_RUNNER_VERSION:
        return AM_PM_R2_PREFIX
    if (
        cohort_id == AM_PM_SMILE_TRANSPORT_COHORT_ID
        and runner_version == AM_PM_SMILE_TRANSPORT_RUNNER_VERSION
    ):
        return AM_PM_SMILE_TRANSPORT_R2_PREFIX
    raise OverlayJobInputError("overlay fixed identity mismatch")


def _artifact_key(kind: str, digest: str, *, prefix: str) -> str:
    if kind not in {"prepared-panel", "report"} or _DIGEST_RE.fullmatch(digest) is None:
        raise RuntimeError("overlay artifact identity is invalid")
    return (
        f"{prefix}/artifacts/"
        f"{kind}/sha256={digest.removeprefix('sha256:')}.json"
    )


@dataclass(frozen=True, slots=True)
class PersonalIndexVolOverlay2023JobSpec:
    base_job_id: str
    cohort_id: str
    input_manifest_digest: str
    input_manifest_key: str
    job_id: str
    manifest_key: str
    request_digest: str
    runner_version: str
    svi_job_id: str

    @property
    def r2_prefix(self) -> str:
        return _closed_identity(self.cohort_id, self.runner_version)

    @property
    def is_smile_transport(self) -> bool:
        return self.cohort_id == SMILE_TRANSPORT_COHORT_ID

    @property
    def is_am_pm_overlay(self) -> bool:
        return self.cohort_id == AM_PM_COHORT_ID

    @property
    def is_am_pm_smile_transport(self) -> bool:
        return self.cohort_id == AM_PM_SMILE_TRANSPORT_COHORT_ID

    @property
    def cohort_digest(self) -> str:
        return _sha256(
            _canonical_bytes(
                {
                    "cohort_id": self.cohort_id,
                    "fixed_window": [EARLIEST_DAY, LATEST_DAY],
                    "runner_version": self.runner_version,
                    "single_stock_option_iv": "FORBIDDEN",
                }
            )
        )

    @classmethod
    def from_document(cls, document: Any) -> "PersonalIndexVolOverlay2023JobSpec":
        fields = {
            "base_job_id",
            "cohort_id",
            "input_manifest_digest",
            "input_manifest_key",
            "job_id",
            "manifest_key",
            "request_digest",
            "runner_version",
            "svi_job_id",
        }
        if not isinstance(document, dict) or set(document) != fields:
            raise OverlayJobInputError("overlay job fields are closed")
        if not all(isinstance(document[field], str) for field in fields):
            raise OverlayJobInputError("overlay job fields must be strings")
        spec = cls(**{field: document[field] for field in fields})
        spec.validate()
        return spec

    def validate(self) -> None:
        if any(
            _JOB_ID_RE.fullmatch(value) is None
            for value in (self.job_id, self.base_job_id, self.svi_job_id)
        ):
            raise OverlayJobInputError("overlay job ids are invalid")
        prefix = f"{_closed_identity(self.cohort_id, self.runner_version)}/job={self.job_id}"
        if any(
            _DIGEST_RE.fullmatch(value) is None
            for value in (self.input_manifest_digest, self.request_digest)
        ):
            raise OverlayJobInputError("overlay digest is invalid")
        if self.input_manifest_key != f"{prefix}/input-manifest.json":
            raise OverlayJobInputError("overlay input manifest key mismatch")
        if self.manifest_key != f"{prefix}/manifest.json":
            raise OverlayJobInputError("overlay terminal manifest key mismatch")
        if self.request_digest != self.derived_request_digest():
            raise OverlayJobInputError("overlay request digest mismatch")

    def derived_request_digest(self) -> str:
        return _sha256(
            _canonical_bytes(
                {
                    "base_job_id": self.base_job_id,
                    "cohort_id": self.cohort_id,
                    "input_manifest_digest": self.input_manifest_digest,
                    "input_manifest_key": self.input_manifest_key,
                    "job_id": self.job_id,
                    "runner_version": self.runner_version,
                    "svi_job_id": self.svi_job_id,
                }
            )
        )

    def headers(self) -> dict[str, str]:
        return {
            "x-overlay-job-id": self.job_id,
            "x-overlay-input-manifest-key": self.input_manifest_key,
            "x-overlay-input-manifest-digest": self.input_manifest_digest,
        }


def _open_overlay(spec: PersonalIndexVolOverlay2023JobSpec, key: str):
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}", method="GET", headers=spec.headers()
    )
    return urllib.request.urlopen(request, timeout=300)


def load_input_manifest(
    spec: PersonalIndexVolOverlay2023JobSpec,
    *,
    opener: Callable[[PersonalIndexVolOverlay2023JobSpec, str], Any] = _open_overlay,
) -> dict[str, Any]:
    with opener(spec, spec.input_manifest_key) as response:
        raw = _read_bounded(response, MAX_INPUT_BYTES)
    if _sha256(raw) != spec.input_manifest_digest:
        raise RuntimeError("overlay input manifest digest mismatch")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("overlay input manifest is not an object")
    base, svi = parsed.get("base"), parsed.get("svi")
    shared_ok = (
        parsed.get("job_id") == spec.job_id
        and parsed.get("cohort_id") == spec.cohort_id
        and parsed.get("runner_version") == spec.runner_version
        and isinstance(base, dict)
        and base.get("job_id") == spec.base_job_id
        and isinstance(svi, dict)
        and svi.get("job_id") == spec.svi_job_id
        and parsed.get("authority") == _INPUT_AUTHORITY
    )
    if spec.is_smile_transport:
        if (
            not shared_ok
            or parsed.get("schema_version") != SMILE_TRANSPORT_INPUT_SCHEMA
            or parsed.get("fixed_window") != _SMILE_TRANSPORT_WINDOW
            or parsed.get("temporal_contract") != _SMILE_TRANSPORT_TEMPORAL
            or parsed.get("candidates") != _SMILE_TRANSPORT_CANDIDATES
            or parsed.get("formulas") != _SMILE_TRANSPORT_FORMULAS
            or parsed.get("gate") != _SMILE_TRANSPORT_GATE
            or parsed.get("core") != _SMILE_TRANSPORT_CORE
            or parsed.get("physical_potential") != _SMILE_TRANSPORT_PHYSICAL
            or parsed.get("svi_features_jsonl") != _SMILE_TRANSPORT_SVI_FEATURES
        ):
            raise RuntimeError("overlay input manifest closed contract mismatch")
    elif spec.is_am_pm_smile_transport:
        if (
            not shared_ok
            or parsed.get("schema_version") != AM_PM_SMILE_TRANSPORT_INPUT_SCHEMA
            or parsed.get("fixed_window") != _AM_PM_SMILE_WINDOW
            or parsed.get("temporal_contract") != _AM_PM_SMILE_TEMPORAL
            or parsed.get("candidates") != _AM_PM_SMILE_CANDIDATES
            or parsed.get("formulas") != _SMILE_TRANSPORT_FORMULAS
            or parsed.get("gate") != _AM_PM_SMILE_GATE
            or parsed.get("core") != _SMILE_TRANSPORT_CORE
            or parsed.get("physical_potential") != _SMILE_TRANSPORT_PHYSICAL
            or parsed.get("svi_features_jsonl") != _SMILE_TRANSPORT_SVI_FEATURES
            or parsed.get("selection") != "NOT_PERFORMED"
        ):
            raise RuntimeError("overlay input manifest closed contract mismatch")
        _reject_legacy_am_pm_input(parsed)
    elif spec.is_am_pm_overlay:
        if (
            not shared_ok
            or parsed.get("schema_version") != AM_PM_INPUT_SCHEMA
            or parsed.get("fixed_window") != _AM_PM_WINDOW
            or parsed.get("temporal_contract") != _AM_PM_TEMPORAL
            or parsed.get("candidates") != _AM_PM_OVERLAY_CANDIDATES
            or parsed.get("selection") != "NOT_PERFORMED"
        ):
            raise RuntimeError("overlay input manifest closed contract mismatch")
        _reject_legacy_am_pm_input(parsed)
    elif (
        not shared_ok
        or parsed.get("schema_version") != INPUT_SCHEMA
        or parsed.get("fixed_window") != _WINDOW
        or parsed.get("temporal_contract") != _TEMPORAL
    ):
        raise RuntimeError("overlay input manifest closed contract mismatch")
    return parsed


def _reject_legacy_am_pm_input(parsed: Mapping[str, Any]) -> None:
    if parsed.get("schema_version") in {INPUT_SCHEMA, SMILE_TRANSPORT_INPUT_SCHEMA}:
        raise RuntimeError("old next-close overlay schema is invalid for AM/PM")
    if parsed.get("temporal_contract", {}).get("fill_timing") == "next_close":
        raise RuntimeError("old next-close base sleeve is invalid for AM/PM overlay")
    base = parsed.get("base")
    if isinstance(base, Mapping):
        cohort = base.get("cohort_id")
        execution = base.get("execution_mode")
        schema = base.get("artifact_schema_version") or base.get("schema_version")
        if cohort == BASE_COHORT_ID or execution == "next_close":
            raise RuntimeError("old next-close base sleeve is invalid for AM/PM overlay")
        if execution == "am_pm":
            raise RuntimeError("am_pm is not an execution mode")
        if execution is not None and execution != AM_PM_EXECUTION_MODE:
            raise RuntimeError("AM/PM overlay requires am_signal_pm_close")
        if schema == "personal-base-sleeve-source/v1":
            raise RuntimeError("old next-close base sleeve is invalid for AM/PM overlay")


def _download(
    spec: PersonalIndexVolOverlay2023JobSpec,
    reference: Mapping[str, Any],
    destination: Path,
    *,
    maximum: int,
    expected_digest: str | None,
    opener: Callable[[PersonalIndexVolOverlay2023JobSpec, str], Any],
) -> None:
    key = reference.get("key")
    size = reference.get("size")
    if (
        not isinstance(key, str)
        or type(size) is not int
        or not 0 < size <= maximum
        or destination.exists()
    ):
        raise RuntimeError("overlay input reference is invalid")
    digest = hashlib.sha256()
    received = 0
    with opener(spec, key) as response, destination.open("xb") as output:
        declared = response.headers.get("content-length", "")
        if not declared.isdigit() or int(declared) != size:
            raise RuntimeError("overlay input declared length mismatch")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > size or received > maximum:
                raise RuntimeError("overlay input exceeded size bound")
            digest.update(chunk)
            output.write(chunk)
    if received != size:
        raise RuntimeError("overlay input transport length mismatch")
    if expected_digest is not None and "sha256:" + digest.hexdigest() != expected_digest:
        raise RuntimeError("overlay input sha256 mismatch")


def _expand_snapshot(transport: Path, destination: Path, raw_digest: str) -> None:
    digest = hashlib.sha256()
    expanded = 0
    source: Any
    source = gzip.open(transport, "rb") if transport.name.endswith(".gz") else transport.open("rb")
    with source, destination.open("xb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            expanded += len(chunk)
            if expanded > MAX_SNAPSHOT_BYTES:
                raise RuntimeError("expanded overlay snapshot exceeded size bound")
            digest.update(chunk)
            output.write(chunk)
    if expanded < 1 or "sha256:" + digest.hexdigest() != raw_digest:
        raise RuntimeError("expanded overlay snapshot sha256 mismatch")


def load_base_sleeve_from_archive(
    archive_path: Path,
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    member_name = reference.get("archive_member")
    expected_digest = reference.get("sha256")
    if (
        not isinstance(member_name, str)
        or not isinstance(expected_digest, str)
        or _DIGEST_RE.fullmatch(expected_digest) is None
    ):
        raise RuntimeError("base sleeve archive reference is invalid")
    member_path = PurePosixPath(member_name)
    if (
        member_path.is_absolute()
        or ".." in member_path.parts
        or member_name
        != f"base-sleeve/{expected_digest.removeprefix('sha256:')}.json"
    ):
        raise RuntimeError("base sleeve archive member is unsafe")
    matches: list[tarfile.TarInfo] = []
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive:
            if member.name == member_name:
                matches.append(member)
        if len(matches) != 1 or not matches[0].isreg():
            raise RuntimeError("base sleeve archive member is missing or ambiguous")
        member = matches[0]
        if not 0 < member.size <= MAX_BASE_ARTIFACT_BYTES:
            raise RuntimeError("base sleeve archive member size denied")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError("base sleeve archive member cannot be read")
        raw = extracted.read(member.size + 1)
    if len(raw) != member.size or _sha256(raw) != expected_digest:
        raise RuntimeError("base sleeve archive member digest mismatch")
    document = json.loads(raw)
    validate_personal_base_sleeve_artifact(document)
    if not isinstance(document, dict):
        raise RuntimeError("base sleeve artifact is not an object")
    return document


def validate_am_pm_base_sleeve_artifact(document: Any) -> None:
    """Reject legacy, fixture, or non-comparable sleeves on the AM overlay path."""

    try:
        validate_personal_base_sleeve_am_pm_artifact(document)
    except (TypeError, ValueError) as error:
        raise RuntimeError(str(error)) from error
    if not isinstance(document, Mapping):
        raise RuntimeError("AM/PM base sleeve artifact must be an object")
    quality = document.get("data_quality")
    if not isinstance(quality, Mapping) or quality.get("comparable") is not True:
        raise RuntimeError("AM/PM overlay requires a comparable base sleeve")
    expected_spec, expected_cohort = verified_am_pm_base_digests()
    strategy = document.get("strategy")
    cohort = document.get("cohort")
    source = document.get("source_run")
    if not all(isinstance(value, Mapping) for value in (strategy, cohort, source)):
        raise RuntimeError("AM/PM base sleeve provenance is incomplete")
    if (
        strategy.get("strategy_spec_digest") != expected_spec
        or cohort.get("cohort_digest") != expected_cohort
        or source.get("execution_mode") != AM_PM_EXECUTION_MODE
    ):
        raise RuntimeError("AM/PM base sleeve does not match the repository producer")


def load_am_pm_base_sleeve_from_archive(
    archive_path: Path,
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    member_name = reference.get("archive_member")
    expected_digest = reference.get("sha256")
    if (
        not isinstance(member_name, str)
        or not isinstance(expected_digest, str)
        or _DIGEST_RE.fullmatch(expected_digest) is None
    ):
        raise RuntimeError("base sleeve archive reference is invalid")
    member_path = PurePosixPath(member_name)
    if (
        member_path.is_absolute()
        or ".." in member_path.parts
        or member_name
        != f"base-sleeve/{expected_digest.removeprefix('sha256:')}.json"
    ):
        raise RuntimeError("base sleeve archive member is unsafe")
    matches: list[tarfile.TarInfo] = []
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive:
            if member.name == member_name:
                matches.append(member)
        if len(matches) != 1 or not matches[0].isreg():
            raise RuntimeError("base sleeve archive member is missing or ambiguous")
        member = matches[0]
        if not 0 < member.size <= MAX_BASE_ARTIFACT_BYTES:
            raise RuntimeError("base sleeve archive member size denied")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError("base sleeve archive member cannot be read")
        raw = extracted.read(member.size + 1)
    if len(raw) != member.size or _sha256(raw) != expected_digest:
        raise RuntimeError("base sleeve archive member digest mismatch")
    document = json.loads(raw)
    validate_am_pm_base_sleeve_artifact(document)
    if not isinstance(document, dict):
        raise RuntimeError("base sleeve artifact is not an object")
    return document


def _svi_spec(manifest: Mapping[str, Any]) -> PersonalSvi2023JobSpec:
    svi = manifest["svi"]
    assert isinstance(svi, Mapping)
    input_reference = svi.get("input_manifest")
    feature_reference = svi.get("feature")
    if not all(
        isinstance(value, Mapping)
        for value in (input_reference, feature_reference)
    ):
        raise RuntimeError("overlay SVI references are invalid")
    job_id = str(svi.get("job_id") or "")
    prefix = f"research/personal/svi-2023/job={job_id}"
    document = {
        "cohort_id": SVI_COHORT_ID,
        "feature_key": str(feature_reference.get("key") or ""),
        "input_manifest_digest": str(input_reference.get("sha256") or ""),
        "input_manifest_key": str(input_reference.get("key") or ""),
        "job_id": job_id,
        "manifest_key": f"{prefix}/manifest.json",
        "report_key": f"{prefix}/report.json",
        "request_digest": str(svi.get("request_digest") or ""),
        "runner_version": SVI_RUNNER_VERSION,
        "strategy_id": SVI_STRATEGY_ID,
    }
    return PersonalSvi2023JobSpec.from_document(document)


def _load_feature_rows(
    spec: PersonalIndexVolOverlay2023JobSpec,
    reference: Mapping[str, Any],
    *,
    opener: Callable[[PersonalIndexVolOverlay2023JobSpec, str], Any],
) -> list[dict[str, Any]]:
    key = reference.get("key")
    expected_digest = reference.get("sha256")
    if not isinstance(key, str) or not isinstance(expected_digest, str):
        raise RuntimeError("overlay SVI feature reference is invalid")
    with opener(spec, key) as response:
        raw = _read_bounded(response, MAX_FEATURE_BYTES)
    if _sha256(raw) != expected_digest:
        raise RuntimeError("overlay SVI feature digest mismatch")
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError("overlay SVI feature row is invalid")
        rows.append(value)
    return rows


def _number(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or (positive and number <= 0.0):
        return None
    return number


def _ratio_from_minus_one(front: Any, ratio_minus_one: Any) -> float | None:
    front_value = _number(front, positive=True)
    change = _number(ratio_minus_one)
    denominator = None if change is None else 1.0 + change
    if front_value is None or denominator is None or denominator <= 0.0:
        return None
    return front_value / denominator


def _left_relative(rr: Any, bf: Any) -> float | None:
    rr_value = _number(rr)
    bf_value = _number(bf)
    if rr_value is None or bf_value is None:
        return None
    value = 1.0 + bf_value - rr_value / 2.0
    return value if math.isfinite(value) and value > 0.0 else None


def option_feature_values(row: Mapping[str, Any] | None) -> dict[str, float | None]:
    """Map the immutable SVI row into decimal-IV overlay fields."""

    if row is None:
        return dict.fromkeys(
            (
                "n225_atm_iv",
                "front_atm",
                "next_atm",
                "front_downside",
                "next_downside",
                "svi_atm_term_ratio",
                "svi_downside_term_ratio",
            )
        )
    front_atm = _number(row.get("observed_atm_iv_decimal"), positive=True)
    next_atm = _ratio_from_minus_one(
        front_atm, row.get("observed_atm_short_over_next_minus_one")
    )
    front_downside = _number(row.get("observed_left_iv_decimal"), positive=True)
    front_rr, front_bf = (
        _number(row.get("observed_rr_over_atm")),
        _number(row.get("observed_bf_over_atm")),
    )
    rr_delta, bf_delta = (
        _number(row.get("observed_rr_over_atm_short_minus_next")),
        _number(row.get("observed_bf_over_atm_short_minus_next")),
    )
    next_relative = (
        _left_relative(front_rr - rr_delta, front_bf - bf_delta)
        if None not in (front_rr, front_bf, rr_delta, bf_delta)
        else None
    )
    next_downside = (
        next_atm * next_relative
        if next_atm is not None and next_relative is not None
        else None
    )
    svi_atm_change = _number(row.get("svi_atm_short_over_next_minus_one"))
    svi_atm_term = (
        1.0 + svi_atm_change
        if svi_atm_change is not None and 1.0 + svi_atm_change > 0.0
        else None
    )
    svi_rr, svi_bf = (
        _number(row.get("svi_rr_over_atm")),
        _number(row.get("svi_bf_over_atm")),
    )
    svi_rr_delta, svi_bf_delta = (
        _number(row.get("svi_rr_over_atm_short_minus_next")),
        _number(row.get("svi_bf_over_atm_short_minus_next")),
    )
    svi_front_relative = _left_relative(svi_rr, svi_bf)
    svi_next_relative = (
        _left_relative(svi_rr - svi_rr_delta, svi_bf - svi_bf_delta)
        if None not in (svi_rr, svi_bf, svi_rr_delta, svi_bf_delta)
        else None
    )
    svi_downside_term = (
        svi_front_relative / svi_next_relative
        if svi_front_relative is not None and svi_next_relative is not None
        else None
    )
    return {
        "n225_atm_iv": front_atm,
        "front_atm": front_atm,
        "next_atm": next_atm,
        "front_downside": front_downside,
        "next_downside": next_downside,
        "svi_atm_term_ratio": svi_atm_term,
        "svi_downside_term_ratio": svi_downside_term,
    }


def _topix_closes(panel: Mapping[str, Any]) -> dict[str, float]:
    identity = panel.get("index_proxy")
    bars = panel.get("bars")
    if (
        not isinstance(identity, Mapping)
        or identity.get("dataset") != "indices_bars_daily_topix"
        or identity.get("label") != "TOPIX"
        or not isinstance(bars, Mapping)
        or not isinstance(bars.get("__NKY_PROXY__"), Sequence)
    ):
        raise RuntimeError("overlay TOPIX proxy identity is invalid")
    closes: dict[str, float] = {}
    for pair in bars["__NKY_PROXY__"]:
        if not isinstance(pair, Sequence) or len(pair) < 2:
            continue
        day = str(pair[0])[:10]
        close = _number(pair[1], positive=True)
        if close is not None and EARLIEST_DAY <= day <= LATEST_DAY:
            if day in closes:
                raise RuntimeError("overlay TOPIX proxy date is duplicated")
            closes[day] = close
    return closes


def _realized_vol_20(
    session_dates: Sequence[str], closes: Mapping[str, float]
) -> dict[str, float | None]:
    returns: list[float | None] = [None]
    for previous, current in zip(session_dates, session_dates[1:]):
        before = closes.get(previous)
        after = closes.get(current)
        returns.append(
            after / before - 1.0
            if before is not None and after is not None and before > 0.0
            else None
        )
    values: dict[str, float | None] = {}
    for index, day in enumerate(session_dates):
        window = returns[max(0, index - 19) : index + 1]
        if len(window) != 20 or any(value is None for value in window):
            values[day] = None
            continue
        finite = [float(value) for value in window if value is not None]
        values[day] = statistics.stdev(finite) * math.sqrt(ANNUALIZATION_SESSIONS)
    return values


def _calendar_dates(snapshot: Path) -> list[str]:
    result = pit.get_market_calendar(
        as_of=f"{LATEST_DAY}T23:59:59+09:00",
        from_date=EARLIEST_DAY,
        to_date=LATEST_DAY,
        db_path=snapshot,
    )
    return [
        str(row.get("date"))
        for row in result.rows
        if str(row.get("holiday_division") or row.get("HolidayDivision") or "")
        == TRADING_DAY_FLAG
    ]


def require_exact_calendar(
    pit_dates: Sequence[str],
    option_dates: Sequence[str],
    topix_dates: Sequence[str],
) -> list[str]:
    authoritative = list(pit_dates)
    if (
        authoritative != list(option_dates)
        or authoritative != list(topix_dates)
        or len(authoritative) < 148
    ):
        raise RuntimeError(
            "PIT market calendar does not exactly match overlay observations"
        )
    return authoritative


def build_observations(
    *,
    session_dates: Sequence[str],
    base_artifact: Mapping[str, Any],
    topix_closes: Mapping[str, float],
    base_vol_percent: Mapping[str, float],
    feature_rows: Mapping[str, Mapping[str, Any]],
) -> list[IndexVolOverlayObservation]:
    base_rows = base_artifact.get("daily_path")
    if not isinstance(base_rows, list) or any(
        not isinstance(row, Mapping) or not isinstance(row.get("date"), str)
        for row in base_rows
    ):
        raise RuntimeError("overlay base daily path is invalid")
    fixed_window_rows = [
        row
        for row in base_rows
        if EARLIEST_DAY <= str(row["date"]) <= LATEST_DAY
    ]
    if [str(row["date"]) for row in fixed_window_rows] != list(session_dates):
        raise RuntimeError(
            "overlay base daily path does not exactly match authoritative dates"
        )
    base_returns = {
        str(row["date"]): _number(row.get("base_sleeve_return"))
        for row in fixed_window_rows
    }
    realized = _realized_vol_20(session_dates, topix_closes)
    observations: list[IndexVolOverlayObservation] = []
    for day in session_dates:
        option = option_feature_values(feature_rows.get(day))
        raw_base_vol = _number(base_vol_percent.get(day), positive=True)
        observations.append(
            IndexVolOverlayObservation(
                date=day,
                available_at=f"{day}T23:59:59+09:00",
                base_sleeve_return=base_returns.get(day),
                topix_cash_close=topix_closes.get(day),
                # J-Quants BaseVol is percent; all IV/RV fields below are decimal.
                n225_base_vol=(raw_base_vol / 100.0 if raw_base_vol else None),
                n225_atm_iv=option["n225_atm_iv"],
                topix_realized_vol_20=realized.get(day),
                n225_front_atm_iv=option["front_atm"],
                n225_next_atm_iv=option["next_atm"],
                n225_front_downside_wing_iv=option["front_downside"],
                n225_next_downside_wing_iv=option["next_downside"],
                svi_equivalent_atm_term_ratio=option["svi_atm_term_ratio"],
                svi_equivalent_downside_smile_term_ratio=option[
                    "svi_downside_term_ratio"
                ],
            )
        )
    return observations


def _etf_ma_from_snapshot(
    snapshot: Path,
    session_dates: Sequence[str],
    *,
    code: str = TOPIX_ETF_CODE,
) -> dict[str, tuple[float, float]]:
    result = pit.get_equity_bars_daily(
        as_of=f"{LATEST_DAY}T23:59:59+09:00",
        code=code,
        from_event=EARLIEST_DAY,
        to_event=LATEST_DAY,
        db_path=snapshot,
    )
    prices: dict[str, tuple[float, float]] = {}
    for row in result.rows:
        payload = row if isinstance(row, Mapping) else getattr(row, "__dict__", {})
        day = str(payload.get("date") or "")[:10]
        morning = _number(
            payload.get("morning_adjustment_close") or payload.get("MAdjC"),
            positive=True,
        )
        afternoon = _number(
            payload.get("afternoon_adjustment_close") or payload.get("AAdjC"),
            positive=True,
        )
        if not day:
            continue
        if morning is None:
            continue
        if day in prices:
            raise RuntimeError(f"ETF {code} date is duplicated")
        prices[day] = (morning, afternoon)
    missing_m = [day for day in session_dates if day not in prices]
    if missing_m:
        raise RuntimeError(
            f"ETF {code} missing exact MAdjC observations on {missing_m[0]}"
        )
    return {day: prices[day] for day in session_dates}


def build_am_pm_observations(
    *,
    session_dates: Sequence[str],
    base_artifact: Mapping[str, Any],
    etf_ma: Mapping[str, tuple[float, float]],
    topix_closes: Mapping[str, float],
    n225_closes: Mapping[str, float] | None = None,
    base_vol_percent: Mapping[str, float],
    feature_rows: Mapping[str, Mapping[str, Any]],
) -> list[IndexVolOverlayAmPmObservation]:
    validate_am_pm_base_sleeve_artifact(base_artifact)
    base_rows = base_artifact.get("daily_path")
    if not isinstance(base_rows, list):
        raise RuntimeError("overlay base daily path is invalid")
    fixed_window_rows = [
        row
        for row in base_rows
        if isinstance(row, Mapping) and EARLIEST_DAY <= str(row.get("date")) <= LATEST_DAY
    ]
    if [str(row["date"]) for row in fixed_window_rows] != list(session_dates):
        raise RuntimeError(
            "overlay base daily path does not exactly match authoritative dates"
        )
    realized = _realized_vol_20(session_dates, topix_closes)
    observations: list[IndexVolOverlayAmPmObservation] = []
    for index, day in enumerate(session_dates):
        option = option_feature_values(feature_rows.get(day))
        raw_base_vol = _number(base_vol_percent.get(day), positive=True)
        etf = etf_ma.get(day)
        if etf is None:
            raise RuntimeError(f"ETF {TOPIX_ETF_CODE} missing exact MAdjC observations")
        source = next(row for row in fixed_window_rows if str(row["date"]) == day)
        pm_nav = _number(source.get("pm_nav"), positive=True)
        etf_a = etf[1]
        fill = None
        if pm_nav is not None or etf_a is not None:
            fill = AmPmFillOutcomeEvidence(
                date=day,
                fill_available_at=f"{day}T15:00:00+09:00",
                outcome_available_at=f"{day}T15:00:00+09:00",
                base_sleeve_pm_nav=pm_nav,
                topix_etf_13060_aadjc=etf_a,
            )
        previous = session_dates[index - 1] if index else None
        observations.append(
            IndexVolOverlayAmPmObservation(
                date=day,
                signal=AmPmSignalEvidence(
                    date=day,
                    signal_available_at=f"{day}T12:30:00+09:00",
                    base_sleeve_am_nav=_number(source.get("am_nav"), positive=True),
                    topix_etf_13060_madjc=etf[0],
                ),
                lagged_features=AmPmLaggedFeatureEvidence(
                    source_session_date=day,
                    feature_available_at=f"{day}T15:00:00+09:00",
                    prior_source_session_date=previous,
                    prior_feature_available_at=(
                        f"{previous}T15:00:00+09:00" if previous else None
                    ),
                    topix_cash_close=topix_closes.get(day),
                    n225_cash_close=(n225_closes or {}).get(day),
                    n225_base_vol=(raw_base_vol / 100.0 if raw_base_vol else None),
                    n225_atm_iv=option["n225_atm_iv"],
                    topix_realized_vol_20=realized.get(day),
                    n225_front_atm_iv=option["front_atm"],
                    n225_next_atm_iv=option["next_atm"],
                    n225_front_downside_wing_iv=option["front_downside"],
                    n225_next_downside_wing_iv=option["next_downside"],
                    svi_equivalent_atm_term_ratio=option["svi_atm_term_ratio"],
                    svi_equivalent_downside_smile_term_ratio=option[
                        "svi_downside_term_ratio"
                    ],
                ),
                fill_outcome=fill,
            )
        )
    return observations


def remap_smile_transport_features_for_am_pm(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    remapped: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        candidate_id = str(copy.get("candidate_id") or "")
        if candidate_id.endswith("_v1") and not candidate_id.endswith("_am_pm_v1"):
            copy["source_candidate_id"] = candidate_id
            copy["candidate_id"] = candidate_id[:-3] + "_am_pm_v1"
        remapped.append(copy)
    return remapped


def _am_pm_base_digests(base_artifact: Mapping[str, Any]) -> tuple[str, str]:
    expected_spec, expected_cohort = verified_am_pm_base_digests()
    strategy = base_artifact.get("strategy")
    cohort = base_artifact.get("cohort")
    if not isinstance(strategy, Mapping) or not isinstance(cohort, Mapping):
        raise RuntimeError("AM/PM base sleeve provenance is incomplete")
    spec_digest = str(strategy.get("strategy_spec_digest") or "")
    cohort_digest = str(cohort.get("cohort_digest") or "")
    if spec_digest != expected_spec or cohort_digest != expected_cohort:
        raise RuntimeError("AM/PM base sleeve digests do not match the repository producer")
    return spec_digest, cohort_digest


def _authority(spec: PersonalIndexVolOverlay2023JobSpec) -> dict[str, Any]:
    return {
        "job_id": spec.job_id,
        "cohort_id": spec.cohort_id,
        "base_job_id": spec.base_job_id,
        "svi_job_id": spec.svi_job_id,
        "input_manifest_digest": spec.input_manifest_digest,
        "draft_only": True,
        "screening_only": True,
        "ready": False,
        "mass": False,
        "promotion": False,
        "live_orders": False,
        "go": False,
        "not_a_pass": True,
        "single_stock_option_iv_used": False,
    }


def bounded_fitted_svi_slice(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Keep only a successful exact-expiry SVI document; drop raw quotes."""

    if row.get("surface_scope") != OPTIONS_225_SMILE_SURFACE_SCOPE:
        raise RuntimeError("single-stock option IV is forbidden")
    if row.get("source_dataset_id") != DATASET_ID:
        raise RuntimeError("single-stock option IV is forbidden")
    if row.get("fit_success") is not True:
        return None
    parameters = row.get("svi_parameters")
    if not isinstance(parameters, Mapping):
        return None
    bounded = {field: row.get(field) for field in _FITTED_SLICE_FIELDS}
    bounded["svi_parameters"] = dict(parameters)
    return bounded


def _market_observations(
    *,
    session_dates: Sequence[str],
    base_artifact: Mapping[str, Any],
    topix_closes: Mapping[str, float],
) -> list[IndexVolOverlayObservation]:
    base_rows = base_artifact.get("daily_path")
    if not isinstance(base_rows, list) or any(
        not isinstance(row, Mapping) or not isinstance(row.get("date"), str)
        for row in base_rows
    ):
        raise RuntimeError("overlay base daily path is invalid")
    fixed_window_rows = [
        row
        for row in base_rows
        if EARLIEST_DAY <= str(row["date"]) <= LATEST_DAY
    ]
    if [str(row["date"]) for row in fixed_window_rows] != list(session_dates):
        raise RuntimeError(
            "overlay base daily path does not exactly match authoritative dates"
        )
    base_returns = {
        str(row["date"]): _number(row.get("base_sleeve_return"))
        for row in fixed_window_rows
    }
    observations: list[IndexVolOverlayObservation] = []
    for day in session_dates:
        observations.append(
            IndexVolOverlayObservation(
                date=day,
                available_at=f"{day}T23:59:59+09:00",
                base_sleeve_return=base_returns.get(day),
                topix_cash_close=topix_closes.get(day),
                n225_base_vol=None,
                n225_atm_iv=None,
                topix_realized_vol_20=None,
                n225_front_atm_iv=None,
                n225_next_atm_iv=None,
                n225_front_downside_wing_iv=None,
                n225_next_downside_wing_iv=None,
            )
        )
    return observations


def _parse_official_options_days_once(
    _spec: PersonalIndexVolOverlay2023JobSpec,
    source_svi_spec: PersonalSvi2023JobSpec,
    options: Mapping[str, Any],
    *,
    opener: Callable[[PersonalSvi2023JobSpec, str], Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read each official day's raw objects once and retain fitted slices."""

    days = options.get("days")
    if not isinstance(days, list):
        raise RuntimeError("overlay SVI option manifest is invalid")
    fitted_slices: list[dict[str, Any]] = []
    parse_audit: list[dict[str, Any]] = []
    for entry in days:
        if not isinstance(entry, Mapping):
            raise RuntimeError("overlay SVI option manifest is invalid")
        day_rows, audit = load_one_options_day(
            source_svi_spec,
            entry,
            opener=opener,
        )
        slices = build_options_225_smile_slices(day_rows, dataset_id=DATASET_ID)
        retained = 0
        for slice_row in slices:
            bounded = bounded_fitted_svi_slice(slice_row)
            if bounded is None:
                continue
            fitted_slices.append(bounded)
            retained += 1
        parse_audit.append(
            {
                "date": str(entry.get("date") or ""),
                "object_count": (
                    len(entry["objects"]) if isinstance(entry.get("objects"), list) else 0
                ),
                "source_rows": audit.get("source_rows"),
                "fitted_slices_retained": retained,
            }
        )
        del day_rows, slices
    return fitted_slices, parse_audit


def execute_overlay_job(
    spec: PersonalIndexVolOverlay2023JobSpec,
    *,
    overlay_opener: Callable[[PersonalIndexVolOverlay2023JobSpec, str], Any] = _open_overlay,
    svi_opener: Callable[[PersonalSvi2023JobSpec, str], Any] | None = None,
    uploader: Callable[[PersonalIndexVolOverlay2023JobSpec, str, bytes], str] = _put_bytes,
) -> dict[str, Any]:
    if spec.is_am_pm_smile_transport:
        return execute_am_pm_smile_transport_job(
            spec,
            overlay_opener=overlay_opener,
            svi_opener=svi_opener,
            uploader=uploader,
        )
    if spec.is_am_pm_overlay:
        return execute_am_pm_overlay_job(
            spec,
            overlay_opener=overlay_opener,
            svi_opener=svi_opener,
            uploader=uploader,
        )
    if spec.is_smile_transport:
        return execute_smile_transport_job(
            spec,
            overlay_opener=overlay_opener,
            svi_opener=svi_opener,
            uploader=uploader,
        )
    try:
        input_manifest = load_input_manifest(spec, opener=overlay_opener)
        base = input_manifest["base"]
        svi = input_manifest["svi"]
        assert isinstance(base, Mapping) and isinstance(svi, Mapping)
        result_reference = base.get("result")
        snapshot_reference = base.get("snapshot")
        sleeve_reference = base.get("sleeve_artifact")
        if not all(
            isinstance(value, Mapping)
            for value in (result_reference, snapshot_reference, sleeve_reference)
        ):
            raise RuntimeError("overlay base references are invalid")
        with tempfile.TemporaryDirectory(prefix=f"overlay-{spec.job_id}-") as root:
            root_path = Path(root)
            archive = root_path / "base-result.tar.gz"
            _download(
                spec,
                result_reference,
                archive,
                maximum=MAX_RESULT_BYTES,
                expected_digest=str(result_reference.get("sha256") or ""),
                opener=overlay_opener,
            )
            base_artifact = load_base_sleeve_from_archive(archive, sleeve_reference)
            archive.unlink()

            snapshot_key = str(snapshot_reference.get("key") or "")
            transport = root_path / (
                "source.sqlite.gz" if snapshot_key.endswith(".gz") else "source.transport"
            )
            snapshot = root_path / "source.sqlite"
            _download(
                spec,
                snapshot_reference,
                transport,
                maximum=MAX_SNAPSHOT_BYTES,
                expected_digest=None,
                opener=overlay_opener,
            )
            _expand_snapshot(
                transport,
                snapshot,
                str(snapshot_reference.get("raw_sha256") or ""),
            )
            transport.unlink()
            authoritative_dates = _calendar_dates(snapshot)

            source_svi_spec = _svi_spec(input_manifest)
            def admitted_svi_opener(
                _source_spec: PersonalSvi2023JobSpec, key: str
            ) -> Any:
                return overlay_opener(spec, key)

            source_svi_opener = svi_opener or admitted_svi_opener
            svi_manifest = load_svi_input_manifest(
                source_svi_spec,
                opener=source_svi_opener,
            )
            source_options = svi_manifest.get("options")
            exact_inventory = {
                "panel": svi_manifest.get("panel"),
                "options": {
                    field: source_options.get(field)
                    for field in ("days", "object_count", "total_bytes")
                }
                if isinstance(source_options, Mapping)
                else None,
            }
            if exact_inventory != {"panel": svi.get("panel"), "options": svi.get("options")}:
                raise RuntimeError(
                    "overlay input inventory does not match immutable SVI manifest"
                )
            panel = load_svi_panel(
                source_svi_spec,
                svi_manifest,
                opener=source_svi_opener,
            )
            feature_reference = svi.get("feature")
            if not isinstance(feature_reference, Mapping):
                raise RuntimeError("overlay SVI feature reference is invalid")
            features = _load_feature_rows(
                spec,
                feature_reference,
                opener=overlay_opener,
            )
            feature_by_date: dict[str, Mapping[str, Any]] = {}
            for row in features:
                day = str(row.get("date") or "")
                if day in feature_by_date:
                    raise RuntimeError("overlay SVI feature date is duplicated")
                feature_by_date[day] = row

            options = svi_manifest.get("options")
            if not isinstance(options, Mapping) or not isinstance(options.get("days"), list):
                raise RuntimeError("overlay SVI option manifest is invalid")
            option_dates = [str(entry.get("date") or "") for entry in options["days"]]
            topix = _topix_closes(panel)
            topix_dates = sorted(topix)
            authoritative_dates = require_exact_calendar(
                authoritative_dates, option_dates, topix_dates
            )

            base_vol_percent: dict[str, float] = {}
            for entry in options["days"]:
                day_rows, _audit = load_one_options_day(
                    source_svi_spec,
                    entry,
                    opener=source_svi_opener,
                )
                built = build_daily_basevol_series(day_rows)
                if len(built) == 1 and built[0].get("date") == entry.get("date"):
                    value = _number(built[0].get("base_vol"), positive=True)
                    if value is not None:
                        base_vol_percent[str(entry["date"])] = value

            observations = build_observations(
                session_dates=authoritative_dates,
                base_artifact=base_artifact,
                topix_closes=topix,
                base_vol_percent=base_vol_percent,
                feature_rows=feature_by_date,
            )
            snapshot_digest = str(snapshot_reference.get("raw_sha256") or "")
            base_report_digest = str(sleeve_reference.get("sha256") or "")
            prepared_manifest = build_prepared_panel_manifest(
                observations,
                authoritative_session_dates=authoritative_dates,
                snapshot_digest=snapshot_digest,
                base_report_digest=base_report_digest,
            )
            result = evaluate_index_vol_overlays(
                observations,
                manifest=prepared_manifest,
                authoritative_session_dates=authoritative_dates,
                signal_start=authoritative_dates[145],
                signal_end=authoritative_dates[-3],
            )

        panel_document = {
            "schema_version": PANEL_SCHEMA,
            **_authority(spec),
            "runner_version": RUNNER_VERSION,
            "prepared_panel_manifest": asdict(prepared_manifest),
            "observations": [asdict(row) for row in observations],
            "unit_policy": {
                "jquants_base_vol_input": "percent",
                "prepared_iv_and_rv": "annualized_decimal",
                "base_vol_conversion": "percent_divided_by_100",
            },
            "calendar_source": "pit.get_market_calendar",
            "calendar_alignment": "EXACT_ORDERED_DATE_MATCH",
            "no_forward_fill": True,
        }
        panel_bytes = _canonical_bytes(panel_document)
        panel_digest = _sha256(panel_bytes)
        panel_key = _artifact_key(
            "prepared-panel", panel_digest, prefix=spec.r2_prefix
        )
        uploaded_panel_digest = uploader(spec, panel_key, panel_bytes)
        if uploaded_panel_digest != panel_digest:
            raise RuntimeError("overlay prepared-panel upload digest mismatch")

        report_document = {
            "schema_version": REPORT_SCHEMA,
            **_authority(spec),
            "runner_version": RUNNER_VERSION,
            "prepared_panel_key": panel_key,
            "prepared_panel_sha256": panel_digest,
            "result": result,
        }
        report_bytes = _canonical_bytes(report_document)
        report_digest = _sha256(report_bytes)
        report_key = _artifact_key("report", report_digest, prefix=spec.r2_prefix)
        uploaded_report_digest = uploader(spec, report_key, report_bytes)
        if uploaded_report_digest != report_digest:
            raise RuntimeError("overlay report upload digest mismatch")

        terminal = {
            "schema_version": MANIFEST_SCHEMA,
            "status": "COMPLETED",
            **_authority(spec),
            "runner_version": RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "prepared_panel_key": panel_key,
            "prepared_panel_sha256": panel_digest,
            "report_key": report_key,
            "report_sha256": report_digest,
            "candidate_status": result.get("status"),
            "candidate_count": 4,
            "post_result_selection": "NOT_PERFORMED",
        }
    except Exception as error:
        terminal = {
            "schema_version": MANIFEST_SCHEMA,
            "status": "FAILED",
            **_authority(spec),
            "runner_version": RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "error": _safe_detail(error),
        }
    terminal_bytes = _canonical_bytes(terminal)
    uploader(spec, spec.manifest_key, terminal_bytes)
    return terminal


def execute_smile_transport_job(
    spec: PersonalIndexVolOverlay2023JobSpec,
    *,
    overlay_opener: Callable[[PersonalIndexVolOverlay2023JobSpec, str], Any] = _open_overlay,
    svi_opener: Callable[[PersonalSvi2023JobSpec, str], Any] | None = None,
    uploader: Callable[[PersonalIndexVolOverlay2023JobSpec, str, bytes], str] = _put_bytes,
) -> dict[str, Any]:
    try:
        input_manifest = load_input_manifest(spec, opener=overlay_opener)
        base = input_manifest["base"]
        svi = input_manifest["svi"]
        assert isinstance(base, Mapping) and isinstance(svi, Mapping)
        result_reference = base.get("result")
        snapshot_reference = base.get("snapshot")
        sleeve_reference = base.get("sleeve_artifact")
        if not all(
            isinstance(value, Mapping)
            for value in (result_reference, snapshot_reference, sleeve_reference)
        ):
            raise RuntimeError("overlay base references are invalid")
        with tempfile.TemporaryDirectory(prefix=f"overlay-{spec.job_id}-") as root:
            root_path = Path(root)
            archive = root_path / "base-result.tar.gz"
            _download(
                spec,
                result_reference,
                archive,
                maximum=MAX_RESULT_BYTES,
                expected_digest=str(result_reference.get("sha256") or ""),
                opener=overlay_opener,
            )
            base_artifact = load_base_sleeve_from_archive(archive, sleeve_reference)
            archive.unlink()

            snapshot_key = str(snapshot_reference.get("key") or "")
            transport = root_path / (
                "source.sqlite.gz" if snapshot_key.endswith(".gz") else "source.transport"
            )
            snapshot = root_path / "source.sqlite"
            _download(
                spec,
                snapshot_reference,
                transport,
                maximum=MAX_SNAPSHOT_BYTES,
                expected_digest=None,
                opener=overlay_opener,
            )
            _expand_snapshot(
                transport,
                snapshot,
                str(snapshot_reference.get("raw_sha256") or ""),
            )
            transport.unlink()
            authoritative_dates = _calendar_dates(snapshot)

            source_svi_spec = _svi_spec(input_manifest)

            def admitted_svi_opener(
                _source_spec: PersonalSvi2023JobSpec, key: str
            ) -> Any:
                return overlay_opener(spec, key)

            source_svi_opener = svi_opener or admitted_svi_opener
            svi_manifest = load_svi_input_manifest(
                source_svi_spec,
                opener=source_svi_opener,
            )
            source_options = svi_manifest.get("options")
            exact_inventory = {
                "panel": svi_manifest.get("panel"),
                "options": {
                    field: source_options.get(field)
                    for field in ("days", "object_count", "total_bytes")
                }
                if isinstance(source_options, Mapping)
                else None,
            }
            if exact_inventory != {"panel": svi.get("panel"), "options": svi.get("options")}:
                raise RuntimeError(
                    "overlay input inventory does not match immutable SVI manifest"
                )
            panel = load_svi_panel(
                source_svi_spec,
                svi_manifest,
                opener=source_svi_opener,
            )
            options = svi_manifest.get("options")
            if not isinstance(options, Mapping) or not isinstance(options.get("days"), list):
                raise RuntimeError("overlay SVI option manifest is invalid")
            option_dates = [str(entry.get("date") or "") for entry in options["days"]]
            topix = _topix_closes(panel)
            topix_dates = sorted(topix)
            authoritative_dates = require_exact_calendar(
                authoritative_dates, option_dates, topix_dates
            )
            fitted_slices, parse_audit = _parse_official_options_days_once(
                spec,
                source_svi_spec,
                options,
                opener=source_svi_opener,
            )
            # Old SVI features.jsonl is admitted as provenance only.  Transport
            # uses exact-expiry fitted slices from this one official-day parse.
            transport_features = build_daily_svi_smile_transport_features(
                fitted_slices
            )
            observations = _market_observations(
                session_dates=authoritative_dates,
                base_artifact=base_artifact,
                topix_closes=topix,
            )
            snapshot_digest = str(snapshot_reference.get("raw_sha256") or "")
            base_report_digest = str(sleeve_reference.get("sha256") or "")
            prepared_manifest = build_prepared_panel_manifest(
                observations,
                authoritative_session_dates=authoritative_dates,
                snapshot_digest=snapshot_digest,
                base_report_digest=base_report_digest,
            )
            core_digest = smile_transport_core_digest()
            result = evaluate_index_smile_transport_overlays(
                observations,
                transport_features,
                manifest=prepared_manifest,
                authoritative_session_dates=authoritative_dates,
                signal_start=authoritative_dates[BETA_MIN_RETURNS],
                signal_end=authoritative_dates[-3],
                core_digest=core_digest,
            )
            inventory_digest = _sha256(
                _canonical_bytes(
                    {
                        "panel": svi.get("panel"),
                        "options": svi.get("options"),
                    }
                )
            )

        panel_document = {
            "schema_version": SMILE_TRANSPORT_PANEL_SCHEMA,
            **_authority(spec),
            "runner_version": SMILE_TRANSPORT_RUNNER_VERSION,
            "prepared_panel_manifest": asdict(prepared_manifest),
            "market_observations": [
                {
                    "date": row.date,
                    "available_at": row.available_at,
                    "base_sleeve_return": row.base_sleeve_return,
                    "topix_cash_close": row.topix_cash_close,
                }
                for row in observations
            ],
            "transport_rows": transport_features,
            "common_validity": result["common_validity_gate"],
            "raw_inventory_digest": inventory_digest,
            "calendar_digest": prepared_manifest.trading_calendar_digest,
            "base_report_digest": prepared_manifest.base_report_digest,
            "core_version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
            "core_digest": core_digest,
            "parse_once": {
                "official_days": len(parse_audit),
                "raw_day_passes": len(parse_audit),
                "fitted_slices_retained": len(fitted_slices),
                "days": parse_audit,
            },
            "svi_features_jsonl": _SMILE_TRANSPORT_SVI_FEATURES,
            "calendar_source": "pit.get_market_calendar",
            "calendar_alignment": "EXACT_ORDERED_DATE_MATCH",
            "no_forward_fill": True,
            "physical_potential": _SMILE_TRANSPORT_PHYSICAL,
        }
        panel_bytes = _canonical_bytes(panel_document)
        panel_digest = _sha256(panel_bytes)
        panel_key = _artifact_key(
            "prepared-panel", panel_digest, prefix=spec.r2_prefix
        )
        uploaded_panel_digest = uploader(spec, panel_key, panel_bytes)
        if uploaded_panel_digest != panel_digest:
            raise RuntimeError("overlay prepared-panel upload digest mismatch")

        report_document = {
            "schema_version": SMILE_TRANSPORT_REPORT_SCHEMA,
            **_authority(spec),
            "runner_version": SMILE_TRANSPORT_RUNNER_VERSION,
            "prepared_panel_key": panel_key,
            "prepared_panel_sha256": panel_digest,
            "selection": "NOT_PERFORMED",
            "result": result,
        }
        report_bytes = _canonical_bytes(report_document)
        report_digest = _sha256(report_bytes)
        report_key = _artifact_key("report", report_digest, prefix=spec.r2_prefix)
        uploaded_report_digest = uploader(spec, report_key, report_bytes)
        if uploaded_report_digest != report_digest:
            raise RuntimeError("overlay report upload digest mismatch")

        terminal = {
            "schema_version": SMILE_TRANSPORT_MANIFEST_SCHEMA,
            "status": "COMPLETED",
            **_authority(spec),
            "runner_version": SMILE_TRANSPORT_RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "prepared_panel_key": panel_key,
            "prepared_panel_sha256": panel_digest,
            "report_key": report_key,
            "report_sha256": report_digest,
            "candidate_status": result.get("status"),
            "candidate_count": 4,
            "post_result_selection": "NOT_PERFORMED",
            "selection": "NOT_PERFORMED",
            "core_version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
            "core_digest": core_digest,
        }
    except Exception as error:
        terminal = {
            "schema_version": SMILE_TRANSPORT_MANIFEST_SCHEMA,
            "status": "FAILED",
            **_authority(spec),
            "runner_version": SMILE_TRANSPORT_RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "error": _safe_detail(error),
        }
    terminal_bytes = _canonical_bytes(terminal)
    uploader(spec, spec.manifest_key, terminal_bytes)
    return terminal


def _am_pm_producer_unavailable_terminal(
    spec: PersonalIndexVolOverlay2023JobSpec,
) -> dict[str, Any] | None:
    unavailable = am_pm_base_producer_unavailable_reason()
    if unavailable is None:
        return None
    return {
        "schema_version": (
            AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA
            if spec.is_am_pm_smile_transport
            else AM_PM_MANIFEST_SCHEMA
        ),
        "status": "FAILED",
        **_authority(spec),
        "runner_version": spec.runner_version,
        "request_digest": spec.request_digest,
        "error": unavailable,
        "producer_dependency": {
            "required_cohort_id": AM_PM_BASE_COHORT_ID,
            "required_strategy_id": AM_PM_BASE_SLEEVE_ID,
            "required_schema": AM_PM_BASE_SLEEVE_SCHEMA,
        },
    }


def _open_am_pm_sources(
    spec: PersonalIndexVolOverlay2023JobSpec,
    *,
    overlay_opener: Callable[[PersonalIndexVolOverlay2023JobSpec, str], Any],
    svi_opener: Callable[[PersonalSvi2023JobSpec, str], Any] | None,
) -> dict[str, Any]:
    input_manifest = load_input_manifest(spec, opener=overlay_opener)
    base = input_manifest["base"]
    svi = input_manifest["svi"]
    if not isinstance(base, Mapping) or not isinstance(svi, Mapping):
        raise RuntimeError("overlay base references are invalid")
    if (
        base.get("cohort_id") == BASE_COHORT_ID
        or base.get("execution_mode") in {"next_close", "am_pm"}
        or str(base.get("artifact_schema_version") or "")
        == "personal-base-sleeve-source/v1"
    ):
        raise RuntimeError("old next-close base sleeve is invalid for AM/PM overlay")
    result_reference = base.get("result")
    snapshot_reference = base.get("snapshot")
    sleeve_reference = base.get("sleeve_artifact")
    if not all(
        isinstance(value, Mapping)
        for value in (result_reference, snapshot_reference, sleeve_reference)
    ):
        raise RuntimeError("overlay base references are invalid")
    return {
        "input_manifest": input_manifest,
        "base": base,
        "svi": svi,
        "result_reference": result_reference,
        "snapshot_reference": snapshot_reference,
        "sleeve_reference": sleeve_reference,
        "svi_opener": svi_opener,
    }


def execute_am_pm_overlay_job(
    spec: PersonalIndexVolOverlay2023JobSpec,
    *,
    overlay_opener: Callable[[PersonalIndexVolOverlay2023JobSpec, str], Any] = _open_overlay,
    svi_opener: Callable[[PersonalSvi2023JobSpec, str], Any] | None = None,
    uploader: Callable[[PersonalIndexVolOverlay2023JobSpec, str, bytes], str] = _put_bytes,
) -> dict[str, Any]:
    unavailable = _am_pm_producer_unavailable_terminal(spec)
    if unavailable is not None:
        uploader(spec, spec.manifest_key, _canonical_bytes(unavailable))
        return unavailable
    try:
        opened = _open_am_pm_sources(
            spec, overlay_opener=overlay_opener, svi_opener=svi_opener
        )
        with tempfile.TemporaryDirectory(prefix=f"overlay-{spec.job_id}-") as root:
            root_path = Path(root)
            archive = root_path / "base-result.tar.gz"
            _download(
                spec,
                opened["result_reference"],
                archive,
                maximum=MAX_RESULT_BYTES,
                expected_digest=str(opened["result_reference"].get("sha256") or ""),
                opener=overlay_opener,
            )
            base_artifact = load_am_pm_base_sleeve_from_archive(
                archive, opened["sleeve_reference"]
            )
            archive.unlink()
            snapshot_key = str(opened["snapshot_reference"].get("key") or "")
            transport = root_path / (
                "source.sqlite.gz" if snapshot_key.endswith(".gz") else "source.transport"
            )
            snapshot = root_path / "source.sqlite"
            _download(
                spec,
                opened["snapshot_reference"],
                transport,
                maximum=MAX_SNAPSHOT_BYTES,
                expected_digest=None,
                opener=overlay_opener,
            )
            _expand_snapshot(
                transport,
                snapshot,
                str(opened["snapshot_reference"].get("raw_sha256") or ""),
            )
            transport.unlink()
            authoritative_dates = _calendar_dates(snapshot)
            source_svi_spec = _svi_spec(opened["input_manifest"])

            def admitted_svi_opener(_source_spec: PersonalSvi2023JobSpec, key: str) -> Any:
                return overlay_opener(spec, key)

            source_svi_opener = opened["svi_opener"] or admitted_svi_opener
            svi_manifest = load_svi_input_manifest(
                source_svi_spec, opener=source_svi_opener
            )
            source_options = svi_manifest.get("options")
            exact_inventory = {
                "panel": svi_manifest.get("panel"),
                "options": {
                    field: source_options.get(field)
                    for field in ("days", "object_count", "total_bytes")
                }
                if isinstance(source_options, Mapping)
                else None,
            }
            if exact_inventory != {
                "panel": opened["svi"].get("panel"),
                "options": opened["svi"].get("options"),
            }:
                raise RuntimeError(
                    "overlay input inventory does not match immutable SVI manifest"
                )
            panel = load_svi_panel(
                source_svi_spec, svi_manifest, opener=source_svi_opener
            )
            feature_reference = opened["svi"].get("feature")
            if not isinstance(feature_reference, Mapping):
                raise RuntimeError("overlay SVI feature reference is invalid")
            features = _load_feature_rows(
                spec, feature_reference, opener=overlay_opener
            )
            feature_by_date: dict[str, Mapping[str, Any]] = {}
            for row in features:
                day = str(row.get("date") or "")
                if day in feature_by_date:
                    raise RuntimeError("overlay SVI feature date is duplicated")
                feature_by_date[day] = row
            options = svi_manifest.get("options")
            if not isinstance(options, Mapping) or not isinstance(options.get("days"), list):
                raise RuntimeError("overlay SVI option manifest is invalid")
            option_dates = [str(entry.get("date") or "") for entry in options["days"]]
            topix = _topix_closes(panel)
            etf_ma = _etf_ma_from_snapshot(snapshot, option_dates)
            authoritative_dates = require_exact_calendar(
                authoritative_dates, option_dates, list(etf_ma)
            )
            base_vol_percent: dict[str, float] = {}
            for entry in options["days"]:
                day_rows, _audit = load_one_options_day(
                    source_svi_spec, entry, opener=source_svi_opener
                )
                built = build_daily_basevol_series(day_rows)
                if len(built) == 1 and built[0].get("date") == entry.get("date"):
                    value = _number(built[0].get("base_vol"), positive=True)
                    if value is not None:
                        base_vol_percent[str(entry["date"])] = value
            observations = build_am_pm_observations(
                session_dates=authoritative_dates,
                base_artifact=base_artifact,
                etf_ma=etf_ma,
                topix_closes=topix,
                base_vol_percent=base_vol_percent,
                feature_rows=feature_by_date,
            )
            spec_digest, cohort_digest = _am_pm_base_digests(base_artifact)
            prepared_manifest = build_prepared_am_pm_panel_manifest(
                observations,
                authoritative_session_dates=authoritative_dates,
                snapshot_digest=str(opened["snapshot_reference"].get("raw_sha256") or ""),
                base_report_digest=str(opened["sleeve_reference"].get("sha256") or ""),
                strategy_spec_digest=spec_digest,
                cohort_digest=cohort_digest,
            )
            result = evaluate_index_vol_overlays_am_pm(
                observations,
                manifest=prepared_manifest,
                authoritative_session_dates=authoritative_dates,
                signal_start=authoritative_dates[146],
                signal_end=authoritative_dates[-2],
            )
        panel_document = {
            "schema_version": AM_PM_PANEL_SCHEMA,
            **_authority(spec),
            "runner_version": AM_PM_RUNNER_VERSION,
            "prepared_panel_manifest": asdict(prepared_manifest),
            "observations": [asdict(row) for row in observations],
            "temporal_contract_digest": am_pm_temporal_contract_digest(),
            "proxy_mapping": am_pm_proxy_mapping(),
            "selection": "NOT_PERFORMED",
            "unit_policy": {
                "jquants_base_vol_input": "percent",
                "prepared_iv_and_rv": "annualized_decimal",
                "base_vol_conversion": "percent_divided_by_100",
            },
            "calendar_source": "pit.get_market_calendar",
            "calendar_alignment": "EXACT_ORDERED_DATE_MATCH",
            "no_forward_fill": True,
            "cash_index_executable_fill_claim": False,
        }
        panel_bytes = _canonical_bytes(panel_document)
        panel_digest = _sha256(panel_bytes)
        panel_key = _artifact_key("prepared-panel", panel_digest, prefix=spec.r2_prefix)
        if uploader(spec, panel_key, panel_bytes) != panel_digest:
            raise RuntimeError("overlay prepared-panel upload digest mismatch")
        report_document = {
            "schema_version": AM_PM_REPORT_SCHEMA,
            **_authority(spec),
            "runner_version": AM_PM_RUNNER_VERSION,
            "prepared_panel_key": panel_key,
            "prepared_panel_sha256": panel_digest,
            "selection": "NOT_PERFORMED",
            "result": result,
        }
        report_bytes = _canonical_bytes(report_document)
        report_digest = _sha256(report_bytes)
        report_key = _artifact_key("report", report_digest, prefix=spec.r2_prefix)
        if uploader(spec, report_key, report_bytes) != report_digest:
            raise RuntimeError("overlay report upload digest mismatch")
        terminal = {
            "schema_version": AM_PM_MANIFEST_SCHEMA,
            "status": "COMPLETED",
            **_authority(spec),
            "runner_version": AM_PM_RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "prepared_panel_key": panel_key,
            "prepared_panel_sha256": panel_digest,
            "report_key": report_key,
            "report_sha256": report_digest,
            "candidate_status": result.get("status"),
            "candidate_count": 4,
            "post_result_selection": "NOT_PERFORMED",
            "selection": "NOT_PERFORMED",
        }
    except Exception as error:
        terminal = {
            "schema_version": AM_PM_MANIFEST_SCHEMA,
            "status": "FAILED",
            **_authority(spec),
            "runner_version": AM_PM_RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "error": _safe_detail(error),
        }
    terminal_bytes = _canonical_bytes(terminal)
    uploader(spec, spec.manifest_key, terminal_bytes)
    return terminal


def execute_am_pm_smile_transport_job(
    spec: PersonalIndexVolOverlay2023JobSpec,
    *,
    overlay_opener: Callable[[PersonalIndexVolOverlay2023JobSpec, str], Any] = _open_overlay,
    svi_opener: Callable[[PersonalSvi2023JobSpec, str], Any] | None = None,
    uploader: Callable[[PersonalIndexVolOverlay2023JobSpec, str, bytes], str] = _put_bytes,
) -> dict[str, Any]:
    unavailable = _am_pm_producer_unavailable_terminal(spec)
    if unavailable is not None:
        uploader(spec, spec.manifest_key, _canonical_bytes(unavailable))
        return unavailable
    try:
        opened = _open_am_pm_sources(
            spec, overlay_opener=overlay_opener, svi_opener=svi_opener
        )
        with tempfile.TemporaryDirectory(prefix=f"overlay-{spec.job_id}-") as root:
            root_path = Path(root)
            archive = root_path / "base-result.tar.gz"
            _download(
                spec,
                opened["result_reference"],
                archive,
                maximum=MAX_RESULT_BYTES,
                expected_digest=str(opened["result_reference"].get("sha256") or ""),
                opener=overlay_opener,
            )
            base_artifact = load_am_pm_base_sleeve_from_archive(
                archive, opened["sleeve_reference"]
            )
            archive.unlink()
            snapshot_key = str(opened["snapshot_reference"].get("key") or "")
            transport = root_path / (
                "source.sqlite.gz" if snapshot_key.endswith(".gz") else "source.transport"
            )
            snapshot = root_path / "source.sqlite"
            _download(
                spec,
                opened["snapshot_reference"],
                transport,
                maximum=MAX_SNAPSHOT_BYTES,
                expected_digest=None,
                opener=overlay_opener,
            )
            _expand_snapshot(
                transport,
                snapshot,
                str(opened["snapshot_reference"].get("raw_sha256") or ""),
            )
            transport.unlink()
            authoritative_dates = _calendar_dates(snapshot)
            source_svi_spec = _svi_spec(opened["input_manifest"])

            def admitted_svi_opener(_source_spec: PersonalSvi2023JobSpec, key: str) -> Any:
                return overlay_opener(spec, key)

            source_svi_opener = opened["svi_opener"] or admitted_svi_opener
            svi_manifest = load_svi_input_manifest(
                source_svi_spec, opener=source_svi_opener
            )
            source_options = svi_manifest.get("options")
            exact_inventory = {
                "panel": svi_manifest.get("panel"),
                "options": {
                    field: source_options.get(field)
                    for field in ("days", "object_count", "total_bytes")
                }
                if isinstance(source_options, Mapping)
                else None,
            }
            if exact_inventory != {
                "panel": opened["svi"].get("panel"),
                "options": opened["svi"].get("options"),
            }:
                raise RuntimeError(
                    "overlay input inventory does not match immutable SVI manifest"
                )
            panel = load_svi_panel(
                source_svi_spec, svi_manifest, opener=source_svi_opener
            )
            options = svi_manifest.get("options")
            if not isinstance(options, Mapping) or not isinstance(options.get("days"), list):
                raise RuntimeError("overlay SVI option manifest is invalid")
            option_dates = [str(entry.get("date") or "") for entry in options["days"]]
            topix = _topix_closes(panel)
            etf_ma = _etf_ma_from_snapshot(snapshot, option_dates)
            authoritative_dates = require_exact_calendar(
                authoritative_dates, option_dates, list(etf_ma)
            )
            fitted_slices, parse_audit = _parse_official_options_days_once(
                spec, source_svi_spec, options, opener=source_svi_opener
            )
            transport_features = remap_smile_transport_features_for_am_pm(
                build_daily_svi_smile_transport_features(fitted_slices)
            )
            observations = build_am_pm_observations(
                session_dates=authoritative_dates,
                base_artifact=base_artifact,
                etf_ma=etf_ma,
                topix_closes=topix,
                base_vol_percent={},
                feature_rows={},
            )
            spec_digest, cohort_digest = _am_pm_base_digests(base_artifact)
            prepared_manifest = build_prepared_am_pm_panel_manifest(
                observations,
                authoritative_session_dates=authoritative_dates,
                snapshot_digest=str(opened["snapshot_reference"].get("raw_sha256") or ""),
                base_report_digest=str(opened["sleeve_reference"].get("sha256") or ""),
                strategy_spec_digest=spec_digest,
                cohort_digest=cohort_digest,
            )
            core_digest = smile_transport_core_digest()
            result = evaluate_index_smile_transport_overlays_am_pm(
                observations,
                transport_features,
                manifest=prepared_manifest,
                authoritative_session_dates=authoritative_dates,
                signal_start=authoritative_dates[BETA_MIN_RETURNS],
                signal_end=authoritative_dates[-2],
                core_digest=core_digest,
            )
            inventory_digest = _sha256(
                _canonical_bytes(
                    {
                        "panel": opened["svi"].get("panel"),
                        "options": opened["svi"].get("options"),
                    }
                )
            )
        panel_document = {
            "schema_version": AM_PM_SMILE_TRANSPORT_PANEL_SCHEMA,
            **_authority(spec),
            "runner_version": AM_PM_SMILE_TRANSPORT_RUNNER_VERSION,
            "prepared_panel_manifest": asdict(prepared_manifest),
            "market_observations": [
                {
                    "date": row.date,
                    "signal": asdict(row.signal),
                    "fill_outcome": (
                        asdict(row.fill_outcome) if row.fill_outcome else None
                    ),
                }
                for row in observations
            ],
            "transport_rows": transport_features,
            "common_validity": result["common_validity_gate"],
            "raw_inventory_digest": inventory_digest,
            "calendar_digest": prepared_manifest.trading_calendar_digest,
            "base_report_digest": prepared_manifest.base_report_digest,
            "temporal_contract_digest": am_pm_temporal_contract_digest(),
            "proxy_mapping": am_pm_proxy_mapping(),
            "core_version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
            "core_digest": core_digest,
            "parse_once": {
                "official_days": len(parse_audit),
                "raw_day_passes": len(parse_audit),
                "fitted_slices_retained": len(fitted_slices),
                "days": parse_audit,
            },
            "svi_features_jsonl": _SMILE_TRANSPORT_SVI_FEATURES,
            "calendar_source": "pit.get_market_calendar",
            "calendar_alignment": "EXACT_ORDERED_DATE_MATCH",
            "no_forward_fill": True,
            "selection": "NOT_PERFORMED",
            "physical_potential": _SMILE_TRANSPORT_PHYSICAL,
            "cash_index_executable_fill_claim": False,
        }
        panel_bytes = _canonical_bytes(panel_document)
        panel_digest = _sha256(panel_bytes)
        panel_key = _artifact_key("prepared-panel", panel_digest, prefix=spec.r2_prefix)
        if uploader(spec, panel_key, panel_bytes) != panel_digest:
            raise RuntimeError("overlay prepared-panel upload digest mismatch")
        report_document = {
            "schema_version": AM_PM_SMILE_TRANSPORT_REPORT_SCHEMA,
            **_authority(spec),
            "runner_version": AM_PM_SMILE_TRANSPORT_RUNNER_VERSION,
            "prepared_panel_key": panel_key,
            "prepared_panel_sha256": panel_digest,
            "selection": "NOT_PERFORMED",
            "result": result,
        }
        report_bytes = _canonical_bytes(report_document)
        report_digest = _sha256(report_bytes)
        report_key = _artifact_key("report", report_digest, prefix=spec.r2_prefix)
        if uploader(spec, report_key, report_bytes) != report_digest:
            raise RuntimeError("overlay report upload digest mismatch")
        terminal = {
            "schema_version": AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA,
            "status": "COMPLETED",
            **_authority(spec),
            "runner_version": AM_PM_SMILE_TRANSPORT_RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "prepared_panel_key": panel_key,
            "prepared_panel_sha256": panel_digest,
            "report_key": report_key,
            "report_sha256": report_digest,
            "candidate_status": result.get("status"),
            "candidate_count": 4,
            "post_result_selection": "NOT_PERFORMED",
            "selection": "NOT_PERFORMED",
            "core_version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
            "core_digest": core_digest,
        }
    except Exception as error:
        terminal = {
            "schema_version": AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA,
            "status": "FAILED",
            **_authority(spec),
            "runner_version": AM_PM_SMILE_TRANSPORT_RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "error": _safe_detail(error),
        }
    terminal_bytes = _canonical_bytes(terminal)
    uploader(spec, spec.manifest_key, terminal_bytes)
    return terminal


__all__ = [
    "AM_PM_COHORT_ID",
    "AM_PM_RUNNER_VERSION",
    "AM_PM_SMILE_TRANSPORT_COHORT_ID",
    "AM_PM_SMILE_TRANSPORT_RUNNER_VERSION",
    "COHORT_ID",
    "RUNNER_VERSION",
    "SMILE_TRANSPORT_COHORT_ID",
    "SMILE_TRANSPORT_RUNNER_VERSION",
    "OverlayJobInputError",
    "PersonalIndexVolOverlay2023JobSpec",
    "bounded_fitted_svi_slice",
    "build_am_pm_observations",
    "build_observations",
    "execute_am_pm_overlay_job",
    "execute_am_pm_smile_transport_job",
    "execute_overlay_job",
    "execute_smile_transport_job",
    "load_am_pm_base_sleeve_from_archive",
    "load_base_sleeve_from_archive",
    "load_input_manifest",
    "option_feature_values",
    "remap_smile_transport_features_for_am_pm",
    "require_exact_calendar",
    "validate_am_pm_base_sleeve_artifact",
]
