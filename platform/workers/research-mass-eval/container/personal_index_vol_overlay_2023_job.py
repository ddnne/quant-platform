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
from research.options_225_vol_series import build_daily_basevol_series
from research.personal_base_sleeve import validate_personal_base_sleeve_artifact
from research.personal_index_vol_overlay import (
    IndexVolOverlayObservation,
    build_prepared_panel_manifest,
    evaluate_index_vol_overlays,
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
RUNNER_VERSION = "personal-index-vol-overlay-cloud-runner/v1"
EARLIEST_DAY = "2023-01-04"
LATEST_DAY = "2023-10-13"
INPUT_SCHEMA = "personal-index-vol-overlay-2023-input/v1"
PANEL_SCHEMA = "personal-index-vol-overlay-prepared-panel/v1"
REPORT_SCHEMA = "personal-index-vol-overlay-report/v1"
MANIFEST_SCHEMA = "personal-index-vol-overlay-manifest/v1"
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
    "signal_start_policy": "MAX_126_SESSION_LOOKBACK",
    "signal_end_policy": "LAST_SESSION_MINUS_TWO",
}
_TEMPORAL = {
    "source_decision_cutoff_jst": "15:00:00+09:00",
    "prepared_available_at": "SAME_DAY_23_59_59_JST",
    "fill_timing": "next_close",
    "first_pnl_interval": "fill_close_to_following_close",
    "no_forward_fill": True,
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


def _artifact_key(kind: str, digest: str) -> str:
    if kind not in {"prepared-panel", "report"} or _DIGEST_RE.fullmatch(digest) is None:
        raise RuntimeError("overlay artifact identity is invalid")
    return (
        "research/personal/index-vol-overlay-2023/artifacts/"
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
    def cohort_digest(self) -> str:
        return _sha256(
            _canonical_bytes(
                {
                    "cohort_id": COHORT_ID,
                    "fixed_window": [EARLIEST_DAY, LATEST_DAY],
                    "runner_version": RUNNER_VERSION,
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
        if self.cohort_id != COHORT_ID or self.runner_version != RUNNER_VERSION:
            raise OverlayJobInputError("overlay fixed identity mismatch")
        if any(
            _DIGEST_RE.fullmatch(value) is None
            for value in (self.input_manifest_digest, self.request_digest)
        ):
            raise OverlayJobInputError("overlay digest is invalid")
        prefix = f"research/personal/index-vol-overlay-2023/job={self.job_id}"
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
    if (
        parsed.get("schema_version") != INPUT_SCHEMA
        or parsed.get("job_id") != spec.job_id
        or parsed.get("cohort_id") != COHORT_ID
        or parsed.get("runner_version") != RUNNER_VERSION
        or not isinstance(base, dict)
        or base.get("job_id") != spec.base_job_id
        or not isinstance(svi, dict)
        or svi.get("job_id") != spec.svi_job_id
        or parsed.get("fixed_window") != _WINDOW
        or parsed.get("temporal_contract") != _TEMPORAL
        or parsed.get("authority") != _INPUT_AUTHORITY
    ):
        raise RuntimeError("overlay input manifest closed contract mismatch")
    return parsed


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
        or len(authoritative) < 128
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
    if not isinstance(base_rows, list):
        raise RuntimeError("overlay base daily path is invalid")
    base_returns = {
        str(row.get("date")): _number(row.get("base_sleeve_return"))
        for row in base_rows
        if isinstance(row, Mapping)
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


def _authority(spec: PersonalIndexVolOverlay2023JobSpec) -> dict[str, Any]:
    return {
        "job_id": spec.job_id,
        "cohort_id": COHORT_ID,
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


def execute_overlay_job(
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
                signal_start=authoritative_dates[125],
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
        panel_key = _artifact_key("prepared-panel", panel_digest)
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
        report_key = _artifact_key("report", report_digest)
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


__all__ = [
    "COHORT_ID",
    "RUNNER_VERSION",
    "OverlayJobInputError",
    "PersonalIndexVolOverlay2023JobSpec",
    "build_observations",
    "execute_overlay_job",
    "load_base_sleeve_from_archive",
    "load_input_manifest",
    "option_feature_values",
    "require_exact_calendar",
]
