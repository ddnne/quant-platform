"""Cloud-only N225 option sidecar producer on the existing v13 runner."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, BinaryIO, Callable, Mapping, Sequence

from research.options_225_vol_series import (
    ATM_IV_ROLE,
    DATASET_ID,
    OPTIONS_225_VOL_SERIES_VERSION,
    OPTIONS_225_VOL_SERIES_WAVE,
    build_daily_atm_iv_series,
    build_daily_basevol_delta_series,
    build_daily_basevol_series,
    build_daily_skew_series,
    build_daily_term_ratio_series,
    build_daily_term_series,
    build_opt225_regime_bundle,
    build_series_bundle_from_rows,
    build_spread_series,
    summarize_vol_series,
)
from research.freezes import MASS_RESEARCH, OPERATIONAL_GO, PHASE7, READY_DECLARED

R2_ORIGIN = "http://research.r2"
PRODUCER_ID = "personal-n225-option-sidecar-producer/v1"
COHORT_ID = "personal-n225-option-sidecar/v1"
RUNNER_VERSION = "personal-cloud-runner/v13"
INPUT_SCHEMA = "personal-n225-option-sidecar-input/v1"
MANIFEST_SCHEMA = "personal-n225-option-sidecar-manifest/v1"
OBJECT_SCHEMA = "personal-n225-option-sidecar/v1"
DATASET = DATASET_ID
SOURCE_VERSION = OPTIONS_225_VOL_SERIES_VERSION
KIND = "option-sidecar"
RECORDS_SCHEMA = "jquants_records/v1"
NATURAL_KEY = ["Date", "Code"]
DUPLICATE_RESOLUTION = {
    "compare": ["ingested_at", "object_key", "line_index"],
    "natural_key": NATURAL_KEY,
    "winner": "lexicographic_max",
}
AUTHORITY = {
    "draft_only": True,
    "screening_only": True,
    "ready": False,
    "mass": False,
    "promotion": False,
    "live_orders": False,
    "go": False,
    "not_a_pass": True,
}
PERIODS = (
    {
        "period_id": "y2021_full",
        "year": 2021,
        "raw_start": "2020-10-05",
        "period_start": "2021-01-04",
        "period_end": "2021-10-15",
        "evaluation_sessions": 193,
        "warmup_sessions": 61,
    },
    {
        "period_id": "y2023_full",
        "year": 2023,
        "raw_start": "2022-10-04",
        "period_start": "2023-01-04",
        "period_end": "2023-10-13",
        "evaluation_sessions": 193,
        "warmup_sessions": 61,
    },
    {
        "period_id": "y2025_q4",
        "year": 2025,
        "raw_start": "2025-06-04",
        "period_start": "2025-09-01",
        "period_end": "2025-12-29",
        "evaluation_sessions": 81,
        "warmup_sessions": 61,
    },
)
INDIVIDUAL_STOCK_DATASETS = frozenset(
    {
        "derivatives_bars_daily_options_equity",
        "derivatives_bars_daily_single_stock_options",
        "equity_option_iv",
        "individual_stock_iv",
        "single_stock_option",
    }
)
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OPTIONS_OBJECT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024

_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class OptionSidecarJobInputError(ValueError):
    """The Worker supplied a non-closed option-sidecar job document."""


def _canonical_bytes(value: Mapping[str, Any] | Sequence[Any] | Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _prefix(job_id: str) -> str:
    return f"research/personal/option-sidecar/job={job_id}"


def _object_key(digest: str) -> str:
    if _DIGEST_RE.fullmatch(digest) is None:
        raise RuntimeError("content-addressed digest is invalid")
    return f"research/personal/option-sidecar/objects/{digest}.json"


@dataclass(frozen=True, slots=True)
class PersonalOptionSidecarJobSpec:
    cohort_id: str
    input_manifest_digest: str
    input_manifest_key: str
    job_id: str
    manifest_key: str
    producer_id: str
    request_digest: str
    runner_version: str

    @property
    def cohort_digest(self) -> str:
        return _sha256(
            _canonical_bytes(
                {
                    "cohort_id": COHORT_ID,
                    "producer_id": PRODUCER_ID,
                    "runner_version": RUNNER_VERSION,
                }
            )
        )

    @classmethod
    def from_document(cls, document: Any) -> "PersonalOptionSidecarJobSpec":
        fields = {
            "cohort_id",
            "input_manifest_digest",
            "input_manifest_key",
            "job_id",
            "manifest_key",
            "producer_id",
            "request_digest",
            "runner_version",
        }
        if not isinstance(document, dict) or set(document) != fields:
            raise OptionSidecarJobInputError("option sidecar job fields are closed")
        if not all(isinstance(document[field], str) for field in fields):
            raise OptionSidecarJobInputError("option sidecar job fields must be strings")
        spec = cls(**{field: document[field] for field in fields})
        spec.validate()
        return spec

    def validate(self) -> None:
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise OptionSidecarJobInputError("job_id is invalid")
        if (
            self.cohort_id != COHORT_ID
            or self.producer_id != PRODUCER_ID
            or self.runner_version != RUNNER_VERSION
        ):
            raise OptionSidecarJobInputError("fixed option sidecar identity mismatch")
        if _DIGEST_RE.fullmatch(self.input_manifest_digest) is None:
            raise OptionSidecarJobInputError("input manifest digest is invalid")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise OptionSidecarJobInputError("request digest is invalid")
        prefix = _prefix(self.job_id)
        if self.input_manifest_key != f"{prefix}/input-manifest.json":
            raise OptionSidecarJobInputError("input_manifest_key mismatch")
        if self.manifest_key != f"{prefix}/manifest.json":
            raise OptionSidecarJobInputError("manifest_key mismatch")

    def derived_request_digest(self) -> str:
        return _sha256(
            _canonical_bytes(
                {
                    "cohort_id": COHORT_ID,
                    "duplicate_resolution": DUPLICATE_RESOLUTION,
                    "input_manifest_digest": self.input_manifest_digest,
                    "input_manifest_key": self.input_manifest_key,
                    "job_id": self.job_id,
                    "periods": [row["period_id"] for row in PERIODS],
                    "producer_id": PRODUCER_ID,
                    "runner_version": RUNNER_VERSION,
                }
            )
        )

    def headers(self) -> dict[str, str]:
        return {
            "x-option-sidecar-job-id": self.job_id,
            "x-option-sidecar-input-manifest-key": self.input_manifest_key,
            "x-option-sidecar-input-manifest-digest": self.input_manifest_digest,
        }


def _open_input(spec: PersonalOptionSidecarJobSpec, key: str, *, timeout: float = 120):
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}",
        method="GET",
        headers=spec.headers(),
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _read_bounded(response: BinaryIO, maximum: int) -> bytes:
    declared = response.headers.get("content-length", "")
    if not declared.isdigit() or not 0 < int(declared) <= maximum:
        raise RuntimeError("input content length missing or out of bounds")
    expected = int(declared)
    data = response.read(expected + 1)
    if len(data) != expected:
        raise RuntimeError("input content length mismatch")
    return data


def _put_bytes(
    spec: PersonalOptionSidecarJobSpec,
    key: str,
    data: bytes,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    if not 0 < len(data) <= MAX_OUTPUT_BYTES:
        raise RuntimeError("option sidecar output size out of bounds")
    digest = _sha256(data)
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}",
        data=data,
        method="PUT",
        headers={
            **spec.headers(),
            "content-length": str(len(data)),
            "x-content-sha256": digest,
        },
    )
    with opener(request, timeout=300) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"option sidecar output upload returned {response.status}")
    return digest


def _safe_detail(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:800]


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _valid_iso_day(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _valid_iso_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _line_identity(line: Mapping[str, Any], day: str) -> tuple[str, str]:
    dataset = line.get("dataset")
    if dataset in INDIVIDUAL_STOCK_DATASETS:
        raise RuntimeError("individual stock options rows are forbidden")
    if dataset != DATASET:
        raise RuntimeError("options row dataset mismatch")
    payload = _mapping(line.get("payload"))
    natural_key = _mapping(line.get("natural_key"))
    if payload is None or natural_key is None:
        raise RuntimeError("options row payload or natural_key is invalid")
    if set(natural_key) != {"Date", "Code"}:
        raise RuntimeError("options natural key must be exact Date+Code")
    payload_day = _valid_iso_day(payload.get("Date"))
    payload_code = payload.get("Code")
    if (
        payload_day != day
        or not isinstance(payload_code, str)
        or not payload_code
        or natural_key.get("Date") != day
        or natural_key.get("Code") != payload_code
    ):
        raise RuntimeError("options natural key does not match payload Date+Code")
    event_at = _valid_iso_instant(line.get("event_time"))
    ingested_at = _valid_iso_instant(line.get("ingested_at"))
    if event_at is None or event_at.date().isoformat() != day:
        raise RuntimeError("options row event_time is invalid")
    if ingested_at is None:
        raise RuntimeError("options row ingested_at is invalid")
    return day, payload_code


def _require_options_ref(reference: Mapping[str, Any], day: str) -> tuple[str, int, str]:
    key = reference.get("key")
    size = reference.get("size")
    bytes_ = reference.get("bytes")
    count = reference.get("count")
    sha = reference.get("sha256")
    if (
        not isinstance(key, str)
        or f"/dt={day}/" not in key
        or not isinstance(size, int)
        or not isinstance(bytes_, int)
        or size != bytes_
        or not 0 < size <= MAX_OPTIONS_OBJECT_BYTES
        or not isinstance(count, int)
        or count < 1
        or reference.get("schema") != RECORDS_SCHEMA
        or reference.get("dataset") != DATASET
        or reference.get("date") != day
        or not isinstance(reference.get("run_id"), str)
        or not reference["run_id"]
        or not isinstance(sha, str)
        or _DIGEST_RE.fullmatch(sha) is None
    ):
        raise RuntimeError("options object reference mismatch")
    return key, size, sha


def load_one_options_day(
    spec: PersonalOptionSidecarJobSpec,
    day_entry: Mapping[str, Any],
    *,
    opener: Callable[[PersonalOptionSidecarJobSpec, str], Any] = _open_input,
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    day = str(day_entry.get("date") or "")
    objects = day_entry.get("objects")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is None or not isinstance(objects, list) or not objects:
        raise RuntimeError("options day manifest entry is invalid")
    selected: dict[tuple[str, str], tuple[tuple[str, str, int], Mapping[str, Any]]] = {}
    parsed_rows = 0
    for reference in objects:
        if not isinstance(reference, dict):
            raise RuntimeError("options object reference is invalid")
        key, expected_size, expected_sha = _require_options_ref(reference, day)
        digest = hashlib.sha256()
        received = 0
        nonblank = 0
        with opener(spec, key) as response:
            declared = response.headers.get("content-length", "")
            if not declared.isdigit() or int(declared) != expected_size:
                raise RuntimeError("options object content length mismatch")
            for line_index, raw_line in enumerate(response):
                received += len(raw_line)
                if received > expected_size:
                    raise RuntimeError("options object exceeded its manifest size")
                digest.update(raw_line)
                if not raw_line.strip():
                    continue
                nonblank += 1
                try:
                    parsed = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("options object contains malformed JSON") from exc
                if not isinstance(parsed, dict):
                    raise RuntimeError("options object line must be a JSON object")
                identity = _line_identity(parsed, day)
                payload = _mapping(parsed.get("payload"))
                if payload is None:
                    raise RuntimeError("options row payload is invalid")
                parsed_rows += 1
                rank = (str(parsed["ingested_at"]), key, line_index)
                current = selected.get(identity)
                if current is None or rank > current[0]:
                    selected[identity] = (rank, payload)
        if received != expected_size:
            raise RuntimeError("options object content length mismatch")
        if nonblank != reference["count"]:
            raise RuntimeError("options object count mismatch")
        if "sha256:" + digest.hexdigest() != expected_sha:
            raise RuntimeError("options object sha256 mismatch")
    rows = [selected[key][1] for key in sorted(selected)]
    return rows, {
        "source_rows": parsed_rows,
        "rejected_rows": 0,
        "deduplicated_rows": parsed_rows - len(rows),
        "natural_keys": len(rows),
    }


def load_input_manifest(
    spec: PersonalOptionSidecarJobSpec,
    *,
    opener: Callable = _open_input,
) -> dict[str, Any]:
    with opener(spec, spec.input_manifest_key) as response:
        data = _read_bounded(response, MAX_INPUT_BYTES)
    if _sha256(data) != spec.input_manifest_digest:
        raise RuntimeError("input manifest digest mismatch")
    parsed = json.loads(data)
    if (
        not isinstance(parsed, dict)
        or parsed.get("schema_version") != INPUT_SCHEMA
        or parsed.get("job_id") != spec.job_id
        or parsed.get("producer_id") != PRODUCER_ID
        or parsed.get("cohort_id") != COHORT_ID
        or parsed.get("runner_version") != RUNNER_VERSION
        or parsed.get("dataset") != DATASET
        or parsed.get("source_version") != SOURCE_VERSION
        or parsed.get("duplicate_resolution") != DUPLICATE_RESOLUTION
        or not isinstance(parsed.get("periods"), dict)
    ):
        raise RuntimeError("input manifest identity mismatch")
    if spec.request_digest != spec.derived_request_digest():
        raise RuntimeError("request digest mismatch")
    return parsed


def _contains_individual_stock(value: Any) -> bool:
    if isinstance(value, Mapping):
        dataset = value.get("dataset")
        if dataset in INDIVIDUAL_STOCK_DATASETS:
            return True
        if "by_code" in value and isinstance(value.get("by_code"), dict):
            return True
        return any(_contains_individual_stock(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_individual_stock(item) for item in value)
    return False


def daily_outputs_from_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "base_vol_series": build_daily_basevol_series(rows),
        "atm_iv_series": build_daily_atm_iv_series(rows),
        "skew_series": build_daily_skew_series(rows),
        "cm_term_series": build_daily_term_series(rows),
    }


def assemble_series_bundle(
    daily: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    base = list(daily["base_vol_series"])
    atm = list(daily["atm_iv_series"])
    skew = list(daily["skew_series"])
    term = list(daily["cm_term_series"])
    spread = build_spread_series(base, atm)
    term_ratio = build_daily_term_ratio_series(term)
    delta = build_daily_basevol_delta_series(base=base)
    stats = summarize_vol_series(base, atm, spread)
    stats["n_skew_days"] = len(skew)
    stats["n_cm_term_days"] = len(term)
    stats["n_cm_term_ratio_days"] = len(term_ratio)
    stats["n_basevol_delta_days"] = len(delta)
    if skew:
        stats["skew_mean"] = statistics.mean(float(r["skew"]) for r in skew)
    if term:
        stats["cm_term_mean"] = statistics.mean(float(r["cm_term"]) for r in term)
    if term_ratio:
        stats["cm_term_ratio_mean"] = statistics.mean(
            float(r["cm_term_ratio"]) for r in term_ratio
        )
    if delta:
        stats["basevol_delta_mean"] = statistics.mean(
            float(r["basevol_delta"]) for r in delta
        )
    return {
        "base_vol_series": base,
        "atm_iv_series": atm,
        "spread_series": spread,
        "skew_series": skew,
        "cm_term_series": term,
        "cm_term_ratio_series": term_ratio,
        "basevol_delta_series": delta,
        "stats": stats,
        "version": OPTIONS_225_VOL_SERIES_VERSION,
        "wave": OPTIONS_225_VOL_SERIES_WAVE,
        "dataset": DATASET_ID,
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "ffill_applied": False,
        "canonical_level": "base_vol",
        "atm_iv_role": ATM_IV_ROLE,
    }


def build_period_sidecar(
    spec: PersonalOptionSidecarJobSpec,
    period: Mapping[str, Any],
    locked: Mapping[str, Any],
    *,
    opener: Callable,
) -> dict[str, Any]:
    daily: dict[str, list[dict[str, Any]]] = {
        "base_vol_series": [],
        "atm_iv_series": [],
        "skew_series": [],
        "cm_term_series": [],
    }
    for day_entry in locked["options"]:
        day_rows, _audit = load_one_options_day(spec, day_entry, opener=opener)
        outputs = daily_outputs_from_rows(day_rows)
        del day_rows
        for field, rows in outputs.items():
            daily[field].extend(rows)
    bundle = assemble_series_bundle(daily)
    regime = build_opt225_regime_bundle(
        bundle["base_vol_series"],
        bundle["atm_iv_series"],
        bundle["spread_series"],
        skew_rows=bundle["skew_series"],
        term_rows=bundle["cm_term_series"],
        term_ratio_rows=bundle["cm_term_ratio_series"],
        basevol_delta_rows=bundle["basevol_delta_series"],
    )
    if _contains_individual_stock(regime):
        raise RuntimeError("individual stock IV is forbidden")
    regime["source"] = {
        "dataset": DATASET,
        "version": SOURCE_VERSION,
        "raw_input_digest": locked["raw_input_digest"],
        "calendar_digest": locked["calendar_digest"],
    }
    return {
        "schema_version": OBJECT_SCHEMA,
        "period_id": period["period_id"],
        "year": period["year"],
        "period_start": period["period_start"],
        "period_end": period["period_end"],
        "opt225_regime": regime,
    }


def _authority() -> dict[str, Any]:
    return dict(AUTHORITY)


def execute_option_sidecar_job(
    spec: PersonalOptionSidecarJobSpec,
    *,
    opener: Callable = _open_input,
    uploader: Callable = _put_bytes,
) -> dict[str, Any]:
    try:
        manifest = load_input_manifest(spec, opener=opener)
        sidecars: dict[str, Any] = {}
        for period in PERIODS:
            period_id = period["period_id"]
            locked = manifest["periods"][period_id]
            if (
                not isinstance(locked, dict)
                or locked.get("period_id") != period_id
                or locked.get("year") != period["year"]
                or locked.get("raw_start") != period["raw_start"]
                or locked.get("warmup_sessions") != period["warmup_sessions"]
                or locked.get("evaluation_sessions") != period["evaluation_sessions"]
                or locked.get("period_start") != period["period_start"]
                or locked.get("period_end") != period["period_end"]
            ):
                raise RuntimeError("option sidecar period lock mismatch")
            sidecar = build_period_sidecar(spec, period, locked, opener=opener)
            sidecar_bytes = _canonical_bytes(sidecar)
            digest = uploader(spec, _object_key(_sha256(sidecar_bytes)), sidecar_bytes)
            if digest != _sha256(sidecar_bytes):
                raise RuntimeError("option sidecar digest mismatch")
            sidecars[period_id] = {
                "period_id": period_id,
                "year": period["year"],
                "period_start": period["period_start"],
                "period_end": period["period_end"],
                "key": _object_key(digest),
                "sha256": digest,
                "size": len(sidecar_bytes),
                "raw_input_digest": locked["raw_input_digest"],
                "calendar_digest": locked["calendar_digest"],
            }
        terminal = {
            "schema_version": MANIFEST_SCHEMA,
            "status": "COMPLETED",
            "kind": KIND,
            "producer_id": PRODUCER_ID,
            "job_id": spec.job_id,
            "cohort_id": COHORT_ID,
            "runner_version": RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "input_manifest_key": spec.input_manifest_key,
            "input_manifest_digest": spec.input_manifest_digest,
            "sidecars": sidecars,
            **_authority(),
        }
    except Exception as error:
        terminal = {
            "schema_version": MANIFEST_SCHEMA,
            "status": "FAILED",
            "kind": KIND,
            "producer_id": PRODUCER_ID,
            "job_id": spec.job_id,
            "cohort_id": COHORT_ID,
            "runner_version": RUNNER_VERSION,
            "request_digest": spec.request_digest,
            "input_manifest_key": spec.input_manifest_key,
            "input_manifest_digest": spec.input_manifest_digest,
            "error": _safe_detail(error),
            **_authority(),
        }
    uploader(spec, spec.manifest_key, _canonical_bytes(terminal))
    return terminal
