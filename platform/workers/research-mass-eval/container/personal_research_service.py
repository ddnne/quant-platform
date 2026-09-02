#!/usr/bin/env python3
"""Single-job HTTP service for deterministic personal research in a Container."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_CONTAINER_MODULE_DIR = str(Path(__file__).resolve().parent)
if _CONTAINER_MODULE_DIR not in sys.path:
    sys.path.insert(0, _CONTAINER_MODULE_DIR)

from job_process_supervisor import (
    KILL_GRACE_SECONDS as SUPERVISOR_KILL_GRACE_SECONDS,
    START_GRACE_SECONDS as SUPERVISOR_START_GRACE_SECONDS,
    TERM_GRACE_SECONDS as SUPERVISOR_TERM_GRACE_SECONDS,
    JobProcessSupervisor as _ProcessGroupSupervisor,
)
from personal_history_source_client import PersonalHistorySourceClient
from personal_svi_2023_job import (
    PersonalSvi2023JobSpec,
    SviJobInputError,
    execute_svi_job,
)
from personal_index_vol_overlay_2023_job import (
    AM_PM_MANIFEST_SCHEMA,
    AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA,
    MANIFEST_SCHEMA,
    OverlayJobInputError,
    PersonalIndexVolOverlay2023JobSpec,
    SMILE_TRANSPORT_MANIFEST_SCHEMA,
    execute_overlay_job,
)
from personal_vol_am_pm_panel_job import (
    PersonalVolAmPmPanelJobSpec,
    VolPanelJobInputError,
    execute_vol_am_pm_panel_job,
)
from personal_option_sidecar_job import (
    OptionSidecarJobInputError,
    PersonalOptionSidecarJobSpec,
    execute_option_sidecar_job,
)
from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    compact_history_state,
)
from ingestion.personal_history import (
    PERSONAL_COMPLETENESS_CLAIM,
    PERSONAL_CONTROLLED_ELIGIBILITY,
    PERSONAL_HISTORY_FORMAT,
    PERSONAL_HISTORY_SCOPE_DIGEST,
    PERSONAL_HISTORY_SCOPE_ID,
    PERSONAL_HISTORY_SCOPE_VERSION,
    PERSONAL_RESEARCH_STATE,
    PersonalHistoryHydrator,
    assert_personal_history_database,
    build_personal_history_plan,
)
from storage.sqlite_store import SqliteStore
from pit.personal_retrospective_session import am_session_view_digest
from research.factor_cohorts import (
    AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT,
    AM_SIGNAL_PM_CLOSE_EXECUTION_MODE,
    DRAFT_FACTOR_COHORT_PURPOSE_ID,
    LEGACY_NEXT_CLOSE_EXECUTION_MODE,
    get_research_cohort,
    is_am_pm_factor_cohort,
)
from research.personal_universe import (
    PersonalUniverseError,
    personal_research_universe_rule_digest,
)
from research.personal_base_sleeve import (
    AM_PM_BASE_COHORT_ID,
    AM_PM_BASE_SLEEVE_ID,
    BASE_COHORT_ID,
    BASE_SLEEVE_ID,
    BASE_UNIVERSE_ID,
    PERSONAL_BASE_SLEEVE_AM_PM_ARTIFACT_SCHEMA,
    PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA,
    PERSONAL_BASE_SLEEVE_RANKING_ROLE,
    PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA,
    PERSONAL_BASE_SLEEVE_ROLE,
    validate_personal_base_sleeve_am_pm_artifact,
    validate_personal_base_sleeve_artifact,
)
from paper_runtime.canonical_json import canonical_json_digest

RUNNER_VERSION = "personal-cloud-runner/v15"
# Expanded sqlite / snapshot-builder physical cap.
SNAPSHOT_MAX_DATABASE_BYTES = 5 * 1024 * 1024 * 1024
SNAPSHOT_MINIMUM_FREE_BYTES = 256 * 1024 * 1024
R2_ORIGIN = "http://research.r2"
DEFAULT_TIMEOUT_SECONDS = 165 * 60
MAX_JOB_LIFETIME_SECONDS = 180 * 60
MAX_PERIOD_DAYS = 7000
MAX_REQUEST_BYTES = 16 * 1024
MAX_RESULT_BYTES = 512 * 1024 * 1024
# Compressed R2/HTTP transport (gzip or legacy raw sqlite).
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024
MAX_BASE_SLEEVE_ARTIFACT_BYTES = 16 * 1024 * 1024

_JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STRATEGY_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ERROR_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_DIAGNOSTIC_REPORT_BYTES = 8 * 1024 * 1024
MAX_CANDIDATE_DIAGNOSTICS = 4
MAX_ERROR_DETAIL_CHARS = 160
_SNAPSHOT_RE = re.compile(
    r"^research/personal/snapshots/sha256=([0-9a-f]{64})\.sqlite(?:\.gz)?$"
)
DEFAULT_PERSONAL_COHORT_ID = "diverse-core-am-pm-v1"
PERSONAL_EXECUTABLE_COHORT_IDS = frozenset(
    {
        "price-relative-am-pm-v1",
        "fundamental-relative-am-pm-v1",
        "diverse-core-am-pm-v1",
        "compact-market-diverse-am-pm-v1",
        "sector-relative-ls-am-pm-v1",
    }
)
PERSONAL_LEGACY_DRAFT_ONLY_COHORT_IDS = frozenset(
    {
        "price-relative-v1",
        "fundamental-relative-v1",
        "diverse-core-v1",
        "compact-market-diverse-v1",
        "sector-relative-ls-v1",
    }
)
COMPACT_MARKET_COHORT_IDS = frozenset(
    {"compact-market-diverse-am-pm-v1"}
)
PERSONAL_EXECUTABLE_UNIVERSE_IDS = frozenset(
    {
        "topix_all",
        "topix_core30",
        "topix_large70",
        "topix_mid400",
        "topix_small1",
        "topix_small2",
        "topix_small",
        "topix100",
        "topix500",
    }
)
COMPACT_MARKET_UNIVERSE_IDS = frozenset(
    {"topix_core30", "topix_large70", "topix100"}
)


class JobInputError(ValueError):
    """The Worker supplied an invalid closed job document."""


class JobConflictError(RuntimeError):
    """A job id was reused with different parameters."""


class JobBusyError(RuntimeError):
    """The one allowed Container job is already running."""


class ControlledLeaseConflict(RuntimeError):
    """Durable lease CAS precondition failed."""


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _personal_cohort_identity(cohort_id: str) -> dict[str, Any]:
    cohort = get_research_cohort(cohort_id)
    am_pm = is_am_pm_factor_cohort(cohort_id)
    return {
        "cohort_id": cohort_id,
        "cohort_digest": str(cohort.to_dict()["cohort_digest"]),
        "am_pm": am_pm,
        "execution_mode": (
            AM_SIGNAL_PM_CLOSE_EXECUTION_MODE
            if am_pm
            else LEGACY_NEXT_CLOSE_EXECUTION_MODE
        ),
        "execution_contract_digest": (
            str(AM_SIGNAL_PM_CLOSE_EXECUTION_CONTRACT["contract_digest"])
            if am_pm
            else None
        ),
        "session_view_digest": (
            am_session_view_digest(include_morning_turnover_history=True)
            if am_pm
            else None
        ),
        "base_sleeve": cohort_id
        in {BASE_COHORT_ID, AM_PM_BASE_COHORT_ID},
        "base_sleeve_schema": (
            PERSONAL_BASE_SLEEVE_AM_PM_ARTIFACT_SCHEMA
            if cohort_id == AM_PM_BASE_COHORT_ID
            else (
                PERSONAL_BASE_SLEEVE_ARTIFACT_SCHEMA
                if cohort_id == BASE_COHORT_ID
                else None
            )
        ),
        "base_sleeve_strategy_id": (
            AM_PM_BASE_SLEEVE_ID
            if cohort_id == AM_PM_BASE_COHORT_ID
            else (BASE_SLEEVE_ID if cohort_id == BASE_COHORT_ID else None)
        ),
        "purpose_id": str(cohort.to_dict().get("purpose_id") or ""),
    }


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_day(value: Any, label: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise JobInputError(f"{label} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise JobInputError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise JobInputError(f"{label} must be an ISO date")
    return parsed


@dataclass(frozen=True, slots=True)
class JobSpec:
    cohort_id: str
    cohort_digest: str
    universe_id: str
    universe_rule_digest: str
    job_id: str
    snapshot_key: str
    snapshot_sha256: str
    period_start: str
    period_end: str
    request_digest: str
    result_key: str
    manifest_key: str
    runner_version: str

    @classmethod
    def from_document(cls, document: Any) -> "JobSpec":
        if not isinstance(document, dict):
            raise JobInputError("job must be a JSON object")
        fields = {
            "cohort_id",
            "cohort_digest",
            "job_id",
            "manifest_key",
            "period_end",
            "period_start",
            "request_digest",
            "result_key",
            "runner_version",
            "snapshot_key",
            "snapshot_sha256",
            "universe_id",
            "universe_rule_digest",
        }
        if set(document) != fields or not all(
            isinstance(document[field], str) for field in fields
        ):
            raise JobInputError("job fields are closed strings")
        spec = cls(**{field: document[field] for field in fields})
        spec.validate()
        return spec

    def validate(self) -> None:
        if self.cohort_id in PERSONAL_LEGACY_DRAFT_ONLY_COHORT_IDS:
            raise JobInputError(
                "legacy diverse-core-v1/session-close/next-close cohorts are "
                "OfflineFixture DRAFT-only and are rejected at JobSpec parsing"
            )
        if self.cohort_id not in PERSONAL_EXECUTABLE_COHORT_IDS:
            raise JobInputError("cohort_id is not executable by personal research")
        if _DIGEST_RE.fullmatch(self.cohort_digest) is None:
            raise JobInputError("cohort_digest is invalid")
        if self.universe_id not in PERSONAL_EXECUTABLE_UNIVERSE_IDS:
            raise JobInputError("universe_id is not executable by personal research")
        compact_universe = self.universe_id in COMPACT_MARKET_UNIVERSE_IDS
        compact_cohort = self.cohort_id in COMPACT_MARKET_COHORT_IDS
        if compact_universe != compact_cohort:
            raise JobInputError("cohort_id and universe_id profile mismatch")
        if _DIGEST_RE.fullmatch(self.universe_rule_digest) is None:
            raise JobInputError("universe_rule_digest is invalid")
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise JobInputError("job_id is invalid")
        if _SHA_RE.fullmatch(self.snapshot_sha256) is None:
            raise JobInputError("snapshot_sha256 is invalid")
        match = _SNAPSHOT_RE.fullmatch(self.snapshot_key)
        if match is None or match.group(1) != self.snapshot_sha256:
            raise JobInputError("snapshot key does not match its digest")
        start = _parse_day(self.period_start, "period_start")
        end = _parse_day(self.period_end, "period_end")
        inclusive_days = (end - start).days + 1
        if inclusive_days < 2 or inclusive_days > MAX_PERIOD_DAYS:
            raise JobInputError(
                f"research period must be 2-{MAX_PERIOD_DAYS} inclusive calendar dates"
            )
        if self.runner_version != RUNNER_VERSION:
            raise JobInputError("runner version mismatch")
        if self.result_key != (
            f"research/personal/jobs/job={self.job_id}/result.tar.gz"
        ):
            raise JobInputError("result key mismatch")
        if self.manifest_key != (
            f"research/personal/jobs/job={self.job_id}/manifest.json"
        ):
            raise JobInputError("manifest key mismatch")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise JobInputError("request_digest is invalid")
        if self.request_digest != self.derived_request_digest():
            raise JobInputError("request_digest mismatch")
        identity = _personal_cohort_identity(self.cohort_id)
        if self.cohort_digest != identity["cohort_digest"]:
            raise JobInputError("cohort_digest does not match repository definition")
        try:
            expected_universe_digest = personal_research_universe_rule_digest(
                self.universe_id,
                am_pm=bool(identity["am_pm"]),
            )
        except PersonalUniverseError as exc:
            raise JobInputError(
                "universe_id is not executable by personal research"
            ) from exc
        if self.universe_rule_digest != expected_universe_digest:
            raise JobInputError(
                "universe_rule_digest does not match cohort and universe"
            )

    def derived_request_digest(self) -> str:
        body = {
            "cohort_digest": self.cohort_digest,
            "cohort_id": self.cohort_id,
            "job_id": self.job_id,
            "period_end": self.period_end,
            "period_start": self.period_start,
            "runner_version": self.runner_version,
            "snapshot_key": self.snapshot_key,
            "snapshot_sha256": self.snapshot_sha256,
            "universe_id": self.universe_id,
            "universe_rule_digest": self.universe_rule_digest,
        }
        return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotJobSpec:
    job_id: str
    period_start: str
    period_end: str
    lookback_sessions: int
    request_digest: str
    manifest_key: str
    runner_version: str
    environment: str
    format: str
    max_database_bytes: int
    deployment_id: str

    @classmethod
    def from_document(cls, document: Any) -> "SnapshotJobSpec":
        if not isinstance(document, dict):
            raise JobInputError("snapshot job must be a JSON object")
        required = {
            "deployment_id",
            "environment",
            "format",
            "job_id",
            "lookback_sessions",
            "manifest_key",
            "max_database_bytes",
            "period_end",
            "period_start",
            "request_digest",
            "runner_version",
        }
        if set(document) != required:
            raise JobInputError("snapshot job fields are closed")
        lookback = document["lookback_sessions"]
        max_bytes = document["max_database_bytes"]
        if type(lookback) is not int or not 0 <= lookback <= 252:
            raise JobInputError("lookback_sessions is invalid")
        if type(max_bytes) is not int or max_bytes != SNAPSHOT_MAX_DATABASE_BYTES:
            raise JobInputError("max_database_bytes is invalid")
        string_fields = required - {"lookback_sessions", "max_database_bytes"}
        if not all(isinstance(document[field], str) for field in string_fields):
            raise JobInputError("snapshot job string fields are closed")
        spec = cls(
            job_id=document["job_id"],
            period_start=document["period_start"],
            period_end=document["period_end"],
            lookback_sessions=lookback,
            request_digest=document["request_digest"],
            manifest_key=document["manifest_key"],
            runner_version=document["runner_version"],
            environment=document["environment"],
            format=document["format"],
            max_database_bytes=max_bytes,
            deployment_id=document["deployment_id"],
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if _JOB_ID_RE.fullmatch(self.job_id) is None:
            raise JobInputError("job_id is invalid")
        start = _parse_day(self.period_start, "period_start")
        end = _parse_day(self.period_end, "period_end")
        inclusive_days = (end - start).days + 1
        if inclusive_days < 1 or inclusive_days > MAX_PERIOD_DAYS:
            raise JobInputError(
                f"snapshot period must be 1-{MAX_PERIOD_DAYS} inclusive calendar dates"
            )
        if self.runner_version != RUNNER_VERSION:
            raise JobInputError("runner version mismatch")
        if self.environment not in {"production", "staging"}:
            raise JobInputError("environment is invalid")
        if self.format != PERSONAL_HISTORY_FORMAT:
            raise JobInputError("snapshot format mismatch")
        if self.manifest_key != (
            f"research/personal/snapshot-builds/job={self.job_id}/manifest.json"
        ):
            raise JobInputError("manifest key mismatch")
        if _DIGEST_RE.fullmatch(self.request_digest) is None:
            raise JobInputError("request_digest is invalid")
        if self.request_digest != self.derived_request_digest():
            raise JobInputError("request_digest mismatch")

    def derived_request_digest(self) -> str:
        body = {
            "format": self.format,
            "job_id": self.job_id,
            "lookback_sessions": self.lookback_sessions,
            "period_end": self.period_end,
            "period_start": self.period_start,
            "runner_version": self.runner_version,
        }
        return "sha256:" + hashlib.sha256(_canonical_bytes(body)).hexdigest()


def _download_snapshot_transport(spec: JobSpec, destination: Path) -> str:
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{spec.snapshot_key}",
        method="GET",
        headers={
            "accept": (
                "application/gzip"
                if spec.snapshot_key.endswith(".sqlite.gz")
                else "application/vnd.sqlite3"
            )
        },
    )
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != HTTPStatus.OK:
            raise RuntimeError(f"snapshot download returned {response.status}")
        raw_length = response.headers.get("content-length", "")
        if (
            not raw_length.isdigit()
            or not 0 < int(raw_length) <= MAX_SNAPSHOT_BYTES
        ):
            raise RuntimeError("snapshot content length is missing or out of bounds")
        expected_length = int(raw_length)
        received = 0
        created = False
        try:
            with destination.open("xb") as handle:
                created = True
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > expected_length or received > MAX_SNAPSHOT_BYTES:
                        raise RuntimeError("snapshot exceeded its declared size bound")
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        if received != expected_length:
            destination.unlink(missing_ok=True)
            raise RuntimeError("snapshot content length mismatch")
    return digest.hexdigest()


def _expand_gzip_snapshot(
    transport: Path,
    destination: Path,
    *,
    expected_sha256: str,
) -> None:
    digest = hashlib.sha256()
    expanded = 0
    created = False
    try:
        try:
            with gzip.open(transport, "rb") as compressed:
                with destination.open("xb") as raw:
                    created = True
                    while True:
                        chunk = compressed.read(1024 * 1024)
                        if not chunk:
                            break
                        expanded += len(chunk)
                        if expanded > SNAPSHOT_MAX_DATABASE_BYTES:
                            raise RuntimeError(
                                "expanded snapshot exceeds the fixed size bound"
                            )
                        digest.update(chunk)
                        raw.write(chunk)
        except (EOFError, gzip.BadGzipFile, zlib.error) as error:
            raise RuntimeError("snapshot gzip stream is invalid") from error
        if expanded < 1:
            raise RuntimeError("expanded snapshot is empty")
        if digest.hexdigest() != expected_sha256:
            raise RuntimeError("snapshot sha256 mismatch")
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise



_CONTRACT_PATH = (
    Path(__file__).resolve().parents[4]
    / "specs"
    / "ready"
    / "controlled_pilot_v1.generated.json"
)
_CONTROLLED_CONTRACT = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
CONTROLLED_PILOT_IDENTITY = str(_CONTROLLED_CONTRACT["identity"])
CONTROLLED_SNAPSHOT_KEY_PREFIX = "research/controlled_pilot/v1/snapshots/"
CONTROLLED_R2_ORIGIN = "http://controlled.r2"
CONTROLLED_FILL_CONTRACT_DIGEST = str(_CONTROLLED_CONTRACT["fill_contract_digest"])
CONTROLLED_FILL_EXECUTION_MODE = str(
    _CONTROLLED_CONTRACT["fill_contract"]["execution_mode"]
)
CONTROLLED_PROFILE_DIGEST = str(_CONTROLLED_CONTRACT["profile_digest"])
CONTROLLED_PLAN_SET_DIGEST = str(_CONTROLLED_CONTRACT["plan_set_digest"])
CONTROLLED_CLOSURE_DIGEST = str(_CONTROLLED_CONTRACT["dependency_closure_digest"])
CONTROLLED_BINDING_DIGEST = str(_CONTROLLED_CONTRACT["exact_four_binding_digest"])
CONTROLLED_PLAN_BINDINGS = {
    str(plan["plan_id"]): plan for plan in _CONTROLLED_CONTRACT["plans"]
}


@dataclass
class ControlledPilotJobSpec:
    job_id: str
    request_digest: str
    document: dict[str, Any]
    manifest_key: str
    execution_id: str
    runner_version: str

    @classmethod
    def from_document(cls, document: Any) -> "ControlledPilotJobSpec":
        if not isinstance(document, dict):
            raise JobInputError("controlled job must be a JSON object")
        if set(document) != CONTROLLED_JOB_SPEC_FIELDS:
            raise JobInputError("controlled job fields are closed")
        job_id = str(document.get("job_id") or "")
        request_digest = str(document.get("request_digest") or "")
        manifest_key = str(document.get("manifest_key") or "")
        execution_id = str(document.get("execution_id") or "")
        if _JOB_ID_RE.fullmatch(job_id) is None:
            raise JobInputError("controlled job_id is invalid")
        if _DIGEST_RE.fullmatch(request_digest) is None:
            raise JobInputError("request_digest must be sha256")
        if _DIGEST_RE.fullmatch(execution_id) is None:
            raise JobInputError("execution_id must be sha256")
        runner_version = str(document.get("runner_version") or "")
        if runner_version != str(_CONTROLLED_CONTRACT["runner_version"]):
            raise JobInputError("controlled runner_version is invalid")
        if not manifest_key.endswith("/container-terminal.json"):
            raise JobInputError("controlled manifest_key is invalid")
        for field in ("ready_manifest_digest", "signed_projection_document_digest"):
            if _DIGEST_RE.fullmatch(str(document.get(field) or "")) is None:
                raise JobInputError(f"controlled {field} must be sha256")
        if not isinstance(document.get("session_scope"), dict):
            raise JobInputError("controlled session_scope is missing")
        return cls(
            job_id=job_id,
            request_digest=request_digest,
            document=dict(document),
            manifest_key=manifest_key,
            execution_id=execution_id,
            runner_version=runner_version,
        )

    @property
    def stage_key(self) -> str:
        return self.manifest_key[: -len("container-terminal.json")] + "container-stage.json"

    @property
    def lease_key(self) -> str:
        return self.manifest_key[: -len("container-terminal.json")] + "container-lease.json"


CONTROLLED_LEASE_FIELDS = {
    "identity",
    "job_id",
    "request_digest",
    "execution_id",
    "runner_version",
    "kind",
    "owner_nonce",
    "fencing_token",
    "expires_at",
    "heartbeat_at",
    "status",
}
CONTROLLED_TERMINAL_LEASE_FIELDS = CONTROLLED_LEASE_FIELDS | {
    "terminal_digest",
    "terminal_status",
    "terminal_payload_b64",
}
# Must match Worker CONTROLLED_LEASE_STORED_MAX_BYTES:
# CONTROLLED_LEASE_MAX_BYTES + ceil(CONTROLLED_TERMINAL_MAX_BYTES / 3) * 4
# + TERMINAL_ENVELOPE_OVERHEAD. Claim PUT stays at CONTROLLED_LEASE_MAX_BYTES.
CONTROLLED_LEASE_MAX_BYTES = 8 * 1024
CONTROLLED_TERMINAL_MAX_BYTES = 64 * 1024
_TERMINAL_ENVELOPE_OVERHEAD = 2048
CONTROLLED_LEASE_STORED_MAX_BYTES = (
    CONTROLLED_LEASE_MAX_BYTES
    + ((CONTROLLED_TERMINAL_MAX_BYTES + 2) // 3) * 4
    + _TERMINAL_ENVELOPE_OVERHEAD
)

CONTROLLED_JOB_SPEC_FIELDS = {
    "identity",
    "format",
    "runner_version",
    "job_id",
    "idempotency_key",
    "ready_attestation_id",
    "ready_manifest_digest",
    "signed_projection_document_digest",
    "session_scope",
    "snapshot_id",
    "immutable_db_digest",
    "snapshot_key",
    "snapshot_size",
    "fill_contract_digest",
    "authorization_digest",
    "request_digest",
    "resolved_universe_digest",
    "universe_rule_digest",
    "max_gross_weight_ppm",
    "manifest_key",
    "execution_id",
    "profile_digest",
    "plan_set_digest",
    "dependency_closure_digest",
    "exact_four_binding_digest",
}

_CONTROLLED_TERMINAL_BIND_FIELDS = {
    "identity",
    "job_id",
    "request_digest",
    "execution_id",
    "runner_version",
    "owner_nonce",
    "fencing_token",
    "status",
}
_CONTROLLED_COMPLETED_TERMINAL_FIELDS = _CONTROLLED_TERMINAL_BIND_FIELDS | {
    "ok",
    "automatic_promotion",
    "live_orders_enabled",
    "ephemeral_cleaned",
    "papers",
    "risks",
    "selection",
    "knowledge",
    "generation",
    "max_parallel",
}
_CONTROLLED_FAILED_TERMINAL_FIELDS = _CONTROLLED_TERMINAL_BIND_FIELDS | {
    "ok",
    "error",
    "go",
    "automatic_promotion",
    "live_orders_enabled",
}
_CONTROLLED_FAILED_ERROR_MAX_CHARS = 500
_JS_MAX_SAFE_INTEGER = (1 << 53) - 1


def _header(response: Any, *names: str) -> str:
    headers = getattr(response, "headers", {})
    getter = getattr(headers, "get", None)
    if callable(getter):
        for name in names:
            value = getter(name)
            if value:
                return str(value)
        return ""
    if isinstance(headers, Mapping):
        lowered = {str(key).lower(): str(value) for key, value in headers.items()}
        for name in names:
            value = lowered.get(name.lower())
            if value:
                return value
    return ""


def _download_controlled_snapshot(
    snapshot_key: str,
    destination: Path,
    *,
    expected_hex: str,
    expected_size: int,
) -> str:
    request = urllib.request.Request(
        f"{CONTROLLED_R2_ORIGIN}/{snapshot_key}",
        method="GET",
        headers={"accept": "application/vnd.sqlite3"},
    )
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != HTTPStatus.OK:
            raise RuntimeError(f"snapshot download returned {response.status}")
        raw_length = _header(response, "content-length")
        if (
            not raw_length.isdigit()
            or not 0 < int(raw_length) <= MAX_SNAPSHOT_BYTES
            or int(raw_length) != expected_size
        ):
            raise RuntimeError("snapshot content length is missing or out of bounds")
        declared_hash = _header(response, "x-content-sha256").strip()
        if declared_hash not in {expected_hex, f"sha256:{expected_hex}"}:
            raise RuntimeError("snapshot immutable hash metadata mismatch")
        immutable = _header(response, "x-r2-immutable").strip().lower()
        if immutable not in {"true", "1"}:
            raise RuntimeError("snapshot immutable metadata missing")
        expected_length = int(raw_length)
        received = 0
        created = False
        try:
            with destination.open("xb") as handle:
                created = True
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > expected_length or received > MAX_SNAPSHOT_BYTES:
                        raise RuntimeError("snapshot exceeded its declared size bound")
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        if received != expected_length:
            destination.unlink(missing_ok=True)
            raise RuntimeError("snapshot content length mismatch")
    hex_digest = digest.hexdigest()
    if hex_digest != expected_hex:
        destination.unlink(missing_ok=True)
        raise RuntimeError("snapshot sha256 mismatch")
    return hex_digest


def _canonical_feature_tuple(refs: Sequence[Any]) -> tuple[tuple[str, str, str], ...]:
    rows = []
    for ref in refs:
        payload = ref.to_dict() if hasattr(ref, "to_dict") else dict(ref)
        rows.append(
            (
                str(payload.get("id") or ""),
                str(payload.get("version") or ""),
                json.dumps(payload.get("params") or {}, sort_keys=True, separators=(",", ":")),
            )
        )
    return tuple(rows)


_CONTROLLED_VERIFIED_JOB = threading.local()


def _mint_controlled_am_view(db_path: Any, physical_digest: str, document: Mapping[str, Any]):
    from pit.governed_am_view import (
        _open_verified_controlled_snapshot,
        _session_scope_from_verified_worker_job,
    )
    verified_scope = _session_scope_from_verified_worker_job(
        session_scope=document.get("session_scope"),
        ready_manifest_digest=document.get("ready_manifest_digest"),
        signed_projection_document_digest=document.get(
            "signed_projection_document_digest"
        ),
        profile_digest=document.get("profile_digest"),
    )
    return _open_verified_controlled_snapshot(
        pinned_path=db_path,
        verified_physical_digest=physical_digest,
        verified_session_scope=verified_scope,
    )


def _run_controlled_paper(
    strategy: Any,
    config: Any,
) -> Any:
    from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED, RAW
    from strategies.paper import Lifecycle, PaperRunResult
    from strategies.paper.runner import execute_paper_backtest

    if config.lifecycle is not Lifecycle.PAPER:
        raise JobInputError("controlled container lifecycle must be Paper")
    if config.execution_mode != CONTROLLED_FILL_EXECUTION_MODE:
        raise JobInputError("controlled fill must be morning close to same-day afternoon close")
    if config.execution_mode == "next_close":
        raise JobInputError("next_close cannot authorize Controlled execution")
    if str(config.price_basis) == PERSONAL_RETROSPECTIVE_ADJUSTED:
        raise JobInputError("retrospective fill cannot authorize Controlled execution")
    if str(config.price_basis) != RAW:
        raise JobInputError("controlled paper requires the as-of-safe RAW fill")
    if float(config.cost_bps) != 10.0:
        raise JobInputError("controlled paper cost is not the governed 10bp scenario")
    job = getattr(_CONTROLLED_VERIFIED_JOB, "document", None)
    physical = getattr(_CONTROLLED_VERIFIED_JOB, "physical_digest", None)
    handle = getattr(_CONTROLLED_VERIFIED_JOB, "snapshot_handle", None)
    if not isinstance(job, dict) or type(physical) is not str or handle is None:
        raise JobInputError("controlled pinned snapshot handle is missing")
    am_view = handle.am_session_data_view()
    backtest, reproduction, experiment_id = execute_paper_backtest(
        strategy, config, am_session_data_view=am_view
    )
    result = PaperRunResult(
        experiment_id=experiment_id,
        run_id=experiment_id,
        lifecycle=Lifecycle.PAPER,
        backtest=backtest,
        reproducibility=reproduction,
    )
    if result.lifecycle is not Lifecycle.PAPER:
        raise JobInputError("controlled paper result is not Paper")
    if not result.experiment_id or not result.metrics:
        raise JobInputError("controlled paper artifact is incomplete")
    return result


def execute_controlled_pilot_container(document: Any) -> dict[str, Any]:
    """Stream the verified physical snapshot, run the canonical four, then delete temp files."""
    if not isinstance(document, dict):
        raise JobInputError("controlled job must be a JSON object")
    if set(document) != CONTROLLED_JOB_SPEC_FIELDS:
        raise JobInputError("controlled job fields are closed")
    if document.get("identity") != CONTROLLED_PILOT_IDENTITY:
        raise JobInputError("controlled identity must be controlled_pilot_v1")
    if document.get("format") != "controlled-pilot-job-spec/v1":
        raise JobInputError("controlled job spec format is invalid")
    if document.get("fill_contract_digest") != CONTROLLED_FILL_CONTRACT_DIGEST:
        raise JobInputError("controlled fill-contract mismatch")
    for field in ("ready_manifest_digest", "signed_projection_document_digest"):
        if _DIGEST_RE.fullmatch(str(document.get(field) or "")) is None:
            raise JobInputError(f"controlled {field} must be sha256")
    if not isinstance(document.get("session_scope"), dict):
        raise JobInputError("controlled session_scope is missing")
    job_id = str(document.get("job_id") or "")
    if _JOB_ID_RE.fullmatch(job_id) is None:
        raise JobInputError("controlled job_id is invalid")
    if document.get("idempotency_key") != job_id:
        raise JobInputError("controlled job_id must equal the idempotency key")
    resolved_universe_digest = str(document.get("resolved_universe_digest") or "")
    universe_rule_digest = str(document.get("universe_rule_digest") or "")
    max_gross_weight_ppm = document.get("max_gross_weight_ppm")
    if _DIGEST_RE.fullmatch(resolved_universe_digest) is None:
        raise JobInputError("resolved_universe_digest must be sha256")
    snapshot_id = document["snapshot_id"]
    physical_digest = document["immutable_db_digest"]
    snapshot_key = document["snapshot_key"]
    snapshot_size = document["snapshot_size"]
    if _DIGEST_RE.fullmatch(str(snapshot_id) or "") is None:
        raise JobInputError("snapshot_id must be sha256")
    if _DIGEST_RE.fullmatch(str(physical_digest) or "") is None:
        raise JobInputError("immutable_db_digest must be sha256")
    if snapshot_id == physical_digest:
        raise JobInputError("logical snapshot_id cannot be the physical digest")
    physical_hex = str(physical_digest)[len("sha256:") :]
    expected_key = f"{CONTROLLED_SNAPSHOT_KEY_PREFIX}sha256={physical_hex}.sqlite"
    if snapshot_key != expected_key:
        raise JobInputError("snapshot key is not the physical digest key")
    if type(snapshot_size) is not int or snapshot_size < 1:
        raise JobInputError("snapshot_size is invalid")
    tmp = tempfile.TemporaryDirectory(prefix="controlled-pilot-")
    destination = Path(tmp.name) / "snapshot.sqlite"
    result: dict[str, Any] | None = None
    controlled_handle: Any = None
    try:
        digest = _download_controlled_snapshot(
            snapshot_key,
            destination,
            expected_hex=physical_hex,
            expected_size=snapshot_size,
        )
        if digest != physical_hex:
            raise JobInputError("ephemeral snapshot hash mismatch")
        reopened = hashlib.sha256()
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                reopened.update(chunk)
        if reopened.hexdigest() != physical_hex:
            raise JobInputError("reopened snapshot hash mismatch")
        verify_sqlite(destination)
        controlled_handle = _mint_controlled_am_view(
            destination,
            str(physical_digest),
            document,
        )
        controlled_handle._begin_controlled_batch_reads()
        _CONTROLLED_VERIFIED_JOB.document = document
        _CONTROLLED_VERIFIED_JOB.physical_digest = physical_digest
        _CONTROLLED_VERIFIED_JOB.snapshot_handle = controlled_handle
        from price_basis import RAW
        from agents.risk_agent import RiskAgent
        from research.dependency_closure import resolve_strategy_spec
        from research.experiment_plans import PILOT_COST_SCENARIO, load_experiment_plans
        from research.universe_contract import (
            EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        )
        from selection.decision import SelectionDecision
        from strategies.paper import Lifecycle, PaperRunConfig
        from strategies.spec import interpret_strategy_spec, iter_feature_refs
        if type(max_gross_weight_ppm) is not int or max_gross_weight_ppm != 500_000:
            raise JobInputError("controlled gross cap must be 500000 ppm")
        if universe_rule_digest != EXACT_FOUR_UNIVERSE_RULE_DIGEST:
            raise JobInputError("controlled universe rule digest mismatch")
        if document.get("profile_digest") != CONTROLLED_PROFILE_DIGEST:
            raise JobInputError("controlled profile digest mismatch")
        if document.get("plan_set_digest") != CONTROLLED_PLAN_SET_DIGEST:
            raise JobInputError("controlled plan-set digest mismatch")
        if document.get("dependency_closure_digest") != CONTROLLED_CLOSURE_DIGEST:
            raise JobInputError("controlled closure digest mismatch")
        if document.get("exact_four_binding_digest") != CONTROLLED_BINDING_DIGEST:
            raise JobInputError("controlled binding digest mismatch")

        logical_id = controlled_handle.logical_snapshot_id()
        if logical_id != snapshot_id:
            raise JobInputError("recomputed logical snapshot_id mismatch")
        papers: list[dict[str, Any]] = []
        audits: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        risk_agent = RiskAgent()
        plans = tuple(load_experiment_plans())
        resolved_universe = controlled_handle.resolve_controlled_universe(
            period_start=plans[0].period_start,
            period_end=plans[0].period_end,
        )
        if resolved_universe.rule_digest != universe_rule_digest:
            raise JobInputError("recomputed universe rule digest mismatch")
        if resolved_universe.resolved_membership_digest != resolved_universe_digest:
            raise JobInputError("recomputed snapshot universe digest mismatch")
        for ordinal, plan in enumerate(plans, start=1):
            if plan.identity != CONTROLLED_PILOT_IDENTITY:
                raise JobInputError("plan identity must be controlled_pilot_v1")
            if plan.cost_scenario != PILOT_COST_SCENARIO:
                raise JobInputError("plan cost scenario is not canonical")
            if dict(plan.fill_contract).get("contract_digest") != CONTROLLED_FILL_CONTRACT_DIGEST:
                raise JobInputError("plan fill-contract mismatch")
            spec = resolve_strategy_spec(
                plan.strategy_spec_id,
                plan.strategy_spec_version,
                plan.strategy_spec_hash,
            )
            if _canonical_feature_tuple(plan.feature_refs) != _canonical_feature_tuple(
                iter_feature_refs(spec)
            ):
                raise JobInputError("StrategySpec feature refs do not match the closure")
            strategy = interpret_strategy_spec(spec)
            paper_result = _run_controlled_paper(
                strategy,
                PaperRunConfig(
                    start=plan.period_start,
                    end=plan.period_end,
                    db_path=destination,
                    universe=resolved_universe,
                    execution_mode=CONTROLLED_FILL_EXECUTION_MODE,
                    cost_bps=10.0,
                    lifecycle=Lifecycle.PAPER,
                    price_basis=RAW,
                    max_gross_weight=max_gross_weight_ppm / 1_000_000,
                ),
            )
            engine_meta = getattr(paper_result.backtest, "metadata", None) or {}
            applied_cap = engine_meta.get("max_gross_weight_limit")
            if applied_cap is not None and abs(float(applied_cap) - 0.5) > 1e-12:
                raise JobInputError("controlled gross cap was not applied")
            realized_gross = float(engine_meta.get("realized_gross_weight") or 0.0)
            requested_gross = float(engine_meta.get("requested_gross_weight") or 0.0)
            if realized_gross > 0.5 + 1e-12:
                raise JobInputError("realized PM gross exceeds 0.5")
            if engine_meta.get("authentic_am_session_evidence") is not True:
                raise JobInputError(
                    "missing independently timestamped AM-session evidence available by 11:30"
                )
            binding = CONTROLLED_PLAN_BINDINGS.get(plan.plan_id)
            if binding is None:
                raise JobInputError("plan is not in the canonical four")
            paper = {
                "ordinal": ordinal,
                "plan_id": plan.plan_id,
                "plan_binding_digest": binding["plan_binding_digest"],
                "identity": CONTROLLED_PILOT_IDENTITY,
                "kind": "paper",
                "automatic_promotion": False,
                "live_orders_enabled": False,
                "mass": False,
                "snapshot_id": snapshot_id,
                "immutable_db_digest": physical_digest,
                "snapshot_key": snapshot_key,
                "snapshot_size": snapshot_size,
                "authorization_digest": document.get("authorization_digest"),
                "ready_attestation_id": document.get("ready_attestation_id"),
                "fill_contract_digest": CONTROLLED_FILL_CONTRACT_DIGEST,
                "execution_mode": CONTROLLED_FILL_EXECUTION_MODE,
                "strategy_spec_id": plan.strategy_spec_id,
                "strategy_spec_hash": plan.strategy_spec_hash,
                "strategy_spec_version": plan.strategy_spec_version,
                "profile_digest": CONTROLLED_PROFILE_DIGEST,
                "plan_set_digest": CONTROLLED_PLAN_SET_DIGEST,
                "dependency_closure_digest": CONTROLLED_CLOSURE_DIGEST,
                "exact_four_binding_digest": CONTROLLED_BINDING_DIGEST,
                "feature_refs": [ref.to_dict() for ref in plan.feature_refs],
                "lifecycle": paper_result.lifecycle.value,
                "experiment_id": paper_result.experiment_id,
                "run_id": paper_result.run_id,
                "metrics": dict(paper_result.metrics),
                "n_equity_points": len(paper_result.equity_curve),
                "n_trades": len(paper_result.trades),
                "resolved_universe_digest": resolved_universe_digest,
                "max_gross_weight_ppm": max_gross_weight_ppm,
                "requested_gross_weight": requested_gross,
                "realized_gross_weight": realized_gross,
                "reproducibility": {
                    key: paper_result.reproducibility[key]
                    for key in (
                        "data_snapshot_id",
                        "feature_versions",
                        "feature_definition_hashes",
                        "strategy_definition_hash",
                        "execution_mode",
                    )
                    if key in paper_result.reproducibility
                },
            }
            paper["semantic_digest"] = canonical_json_digest(paper)
            if paper["lifecycle"] != "Paper" or not paper["metrics"]:
                raise JobInputError("controlled paper artifact is not evidence")
            audit = risk_agent.audit(paper_result)
            audit.verify_content_hash()
            risk = {
                "ordinal": ordinal,
                "plan_id": plan.plan_id,
                "plan_binding_digest": binding["plan_binding_digest"],
                "strategy_spec_id": plan.strategy_spec_id,
                "strategy_spec_version": plan.strategy_spec_version,
                "strategy_spec_hash": plan.strategy_spec_hash,
                "identity": CONTROLLED_PILOT_IDENTITY,
                "kind": "risk",
                "automatic_promotion": False,
                "live_orders_enabled": False,
                "mass": False,
                "snapshot_id": snapshot_id,
                "immutable_db_digest": physical_digest,
                "snapshot_key": snapshot_key,
                "snapshot_size": snapshot_size,
                "authorization_digest": document.get("authorization_digest"),
                "ready_attestation_id": document.get("ready_attestation_id"),
                "fill_contract_digest": CONTROLLED_FILL_CONTRACT_DIGEST,
                "profile_digest": CONTROLLED_PROFILE_DIGEST,
                "plan_set_digest": CONTROLLED_PLAN_SET_DIGEST,
                "dependency_closure_digest": CONTROLLED_CLOSURE_DIGEST,
                "exact_four_binding_digest": CONTROLLED_BINDING_DIGEST,
                "paper_semantic_digest": paper["semantic_digest"],
                **audit.to_dict(),
            }
            risk["profile_digest"] = CONTROLLED_PROFILE_DIGEST
            risk["plan_set_digest"] = CONTROLLED_PLAN_SET_DIGEST
            risk["dependency_closure_digest"] = CONTROLLED_CLOSURE_DIGEST
            risk["exact_four_binding_digest"] = CONTROLLED_BINDING_DIGEST
            risk["snapshot_id"] = snapshot_id
            risk["kind"] = "risk"
            risk["semantic_digest"] = canonical_json_digest(risk)
            decision = SelectionDecision(
                decision="HOLD",
                reason_codes=("PENDING_HUMAN_APPROVAL",),
                subject_id=plan.plan_id,
                evidence={"automatic_promotion": False},
            )
            if decision.decision == "PROMOTE":
                raise JobInputError("automatic promotion is disabled")
            papers.append(paper)
            audits.append(risk)
            decisions.append(decision.to_dict())
        if len(papers) != 4 or len(audits) != 4 or len(decisions) != 4:
            raise JobInputError("controlled execution requires exactly four papers")
        paper_semantic_digests = [row["semantic_digest"] for row in papers]
        risk_semantic_digests = [row["semantic_digest"] for row in audits]
        semantic_child_set_digest = canonical_json_digest(
            {
                "paper_semantic_digests": paper_semantic_digests,
                "risk_semantic_digests": risk_semantic_digests,
            }
        )
        selection = {
            "identity": CONTROLLED_PILOT_IDENTITY,
            "kind": "selection",
            "automatic_promotion": False,
            "live_orders_enabled": False,
            "mass": False,
            "snapshot_id": snapshot_id,
            "immutable_db_digest": physical_digest,
            "fill_contract_digest": CONTROLLED_FILL_CONTRACT_DIGEST,
            "decision": "HOLD",
            "rule": "deterministic_hold_pending_human_approval",
            "automatic_promotion": False,
            "selected": [row["plan_id"] for row in papers],
            "rejected": [],
            "decisions": decisions,
            "paper_semantic_digests": paper_semantic_digests,
            "risk_semantic_digests": risk_semantic_digests,
            "semantic_child_set_digest": semantic_child_set_digest,
            "profile_digest": CONTROLLED_PROFILE_DIGEST,
            "plan_set_digest": CONTROLLED_PLAN_SET_DIGEST,
            "dependency_closure_digest": CONTROLLED_CLOSURE_DIGEST,
            "exact_four_binding_digest": CONTROLLED_BINDING_DIGEST,
            "snapshot_key": snapshot_key,
            "snapshot_size": snapshot_size,
            "authorization_digest": document.get("authorization_digest"),
            "ready_attestation_id": document.get("ready_attestation_id"),
            "resolved_universe_digest": resolved_universe_digest,
        }
        selection["semantic_digest"] = canonical_json_digest(selection)
        knowledge_payload = {
            "identity": CONTROLLED_PILOT_IDENTITY,
            "snapshot_id": snapshot_id,
            "selection_decision": "HOLD",
            "paper_experiment_ids": [row["experiment_id"] for row in papers],
            "risk_audit_ids": [row["audit_id"] for row in audits],
            "fill_contract_digest": CONTROLLED_FILL_CONTRACT_DIGEST,
            "semantic_child_set_digest": semantic_child_set_digest,
            "selection_semantic_digest": selection["semantic_digest"],
        }
        knowledge_body = {
            "identity": CONTROLLED_PILOT_IDENTITY,
            "kind": "knowledge",
            "automatic_promotion": False,
            "live_orders_enabled": False,
            "mass": False,
            "snapshot_id": snapshot_id,
            "immutable_db_digest": physical_digest,
            "fill_contract_digest": CONTROLLED_FILL_CONTRACT_DIGEST,
            "selection_decision": "HOLD",
            "artifact_type": "controlled_pilot_knowledge",
            "schema_version": "controlled-pilot-knowledge/v1",
            "producer_role": "knowledge",
            "selection_semantic_digest": selection["semantic_digest"],
            "semantic_child_set_digest": semantic_child_set_digest,
            "profile_digest": CONTROLLED_PROFILE_DIGEST,
            "plan_set_digest": CONTROLLED_PLAN_SET_DIGEST,
            "dependency_closure_digest": CONTROLLED_CLOSURE_DIGEST,
            "exact_four_binding_digest": CONTROLLED_BINDING_DIGEST,
            "snapshot_key": snapshot_key,
            "snapshot_size": snapshot_size,
            "authorization_digest": document.get("authorization_digest"),
            "n_papers": len(papers),
            "n_selected": 4,
            "payload": knowledge_payload,
        }
        knowledge_digest = canonical_json_digest(knowledge_body)
        knowledge = {
            **knowledge_body,
            "artifact_id": knowledge_digest,
            "digest": knowledge_digest,
            "semantic_digest": knowledge_digest,
        }
        result = {
            "ok": True,
            "identity": CONTROLLED_PILOT_IDENTITY,
            "ephemeral_cleaned": False,
            "papers": papers,
            "risks": audits,
            "selection": selection,
            "knowledge": knowledge,
            "generation": 1,
            "max_parallel": 2,
            "automatic_promotion": False,
            "live_orders_enabled": False,
        }
    finally:
        _CONTROLLED_VERIFIED_JOB.document = None
        _CONTROLLED_VERIFIED_JOB.physical_digest = None
        _CONTROLLED_VERIFIED_JOB.snapshot_handle = None
        if controlled_handle is not None:
            try:
                controlled_handle._end_controlled_batch_reads()
            finally:
                controlled_handle.close()
        tmp.cleanup()
        destination.unlink(missing_ok=True)
        if result is not None:
            result["ephemeral_cleaned"] = not destination.exists()
            if not result["ephemeral_cleaned"]:
                raise RuntimeError("ephemeral snapshot was not deleted")
    if result is None:
        raise RuntimeError("controlled execution produced no artifact")
    return result



def download_snapshot(spec: JobSpec, destination: Path) -> None:
    compressed = destination.with_name(f"{destination.name}.transport.gz")
    if destination.exists() or compressed.exists():
        raise RuntimeError("snapshot destination already exists")
    complete = False
    compressed_owned = False
    destination_owned = False
    try:
        if spec.snapshot_key.endswith(".sqlite.gz"):
            _download_snapshot_transport(spec, compressed)
            compressed_owned = True
            _expand_gzip_snapshot(
                compressed,
                destination,
                expected_sha256=spec.snapshot_sha256,
            )
            destination_owned = True
        else:
            digest = _download_snapshot_transport(spec, destination)
            destination_owned = True
            if digest != spec.snapshot_sha256:
                raise RuntimeError("snapshot sha256 mismatch")
        complete = True
    finally:
        if compressed_owned:
            compressed.unlink(missing_ok=True)
        if not complete and destination_owned:
            destination.unlink(missing_ok=True)


def verify_snapshot_observation_evidence(
    manifest: Mapping[str, Any],
    *,
    observed_through: str,
    revision_window_calendar_days: int,
    revision_coverage: str,
) -> None:
    if str(manifest.get("observed_through") or "") != str(observed_through):
        raise RuntimeError("snapshot observed_through mismatch")
    if int(manifest.get("revision_window_calendar_days")) != int(
        revision_window_calendar_days
    ):
        raise RuntimeError("snapshot revision_window_calendar_days mismatch")
    if str(manifest.get("revision_coverage") or "") != str(revision_coverage):
        raise RuntimeError("snapshot revision_coverage mismatch")


def verify_sqlite(path: Path) -> None:
    uri = f"file:{path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute("PRAGMA quick_check").fetchall()
    finally:
        connection.close()
    if rows != [("ok",)]:
        raise RuntimeError("SQLite quick_check failed")


def _archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def build_result_archive(output_root: Path, destination: Path) -> tuple[int, int]:
    files: list[tuple[Path, Path]] = []
    total_bytes = 0
    for path in sorted(output_root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(output_root)
        if path.suffix in {".sqlite", ".sqlite3", ".db"}:
            continue
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > MAX_RESULT_BYTES:
            raise RuntimeError("research artifacts exceed the fixed result bound")
        files.append((path, relative))
    if not files:
        raise RuntimeError("research run produced no archival artifacts")
    with destination.open("xb") as raw_archive:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=raw_archive,
            mtime=0,
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path, relative in files:
                    archive.add(
                        path,
                        arcname=relative.as_posix(),
                        recursive=False,
                        filter=_archive_filter,
                    )
    result_size = destination.stat().st_size
    if result_size > MAX_RESULT_BYTES:
        destination.unlink(missing_ok=True)
        raise RuntimeError("compressed result exceeds the fixed result bound")
    return len(files), result_size


def _require_output_artifact(
    summary: Mapping[str, Any], field: str, output_root: Path
) -> Path:
    value = summary.get(field)
    if not isinstance(value, str):
        raise RuntimeError(f"qp-research {field} artifact is invalid")
    try:
        resolved = Path(value).resolve(strict=True)
        resolved.relative_to(output_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError(f"qp-research {field} artifact is invalid") from error
    if not resolved.is_file():
        raise RuntimeError(f"qp-research {field} artifact is invalid")
    return resolved


def _validated_base_sleeve_reference(
    summary: Mapping[str, Any],
    *,
    spec: JobSpec,
    output_root: Path,
) -> dict[str, Any] | None:
    reference = summary.get("base_sleeve_artifact")
    source_count = summary.get("non_candidate_source_backtest_count")
    identity = _personal_cohort_identity(spec.cohort_id)
    expected_profile = (
        identity["base_sleeve"] and spec.universe_id == BASE_UNIVERSE_ID
    )
    if type(source_count) is not int or source_count not in {0, 1}:
        raise RuntimeError("qp-research base sleeve source count is invalid")
    if reference is None:
        if source_count != 0:
            raise RuntimeError("qp-research base sleeve reference is missing")
        if expected_profile and summary.get("evaluated_count") != 0:
            raise RuntimeError(
                "qp-research evaluated long-short result requires a base sleeve source"
            )
        return None
    if not expected_profile or source_count != 1:
        raise RuntimeError("qp-research emitted an unexpected base sleeve source")
    if not isinstance(reference, dict):
        raise RuntimeError("qp-research base sleeve reference is invalid")
    reference = {
        key: value for key, value in reference.items() if key != "path"
    }
    expected_fields = {
        "archive_member",
        "artifact_schema_version",
        "candidate_count_contribution",
        "cohort_id",
        "ranking_role",
        "role",
        "schema_version",
        "sha256",
        "strategy_id",
        "universe_id",
    }
    if set(reference) != expected_fields:
        raise RuntimeError("qp-research base sleeve reference is invalid")
    expected_schema = identity["base_sleeve_schema"]
    expected_strategy = identity["base_sleeve_strategy_id"]
    if (
        reference.get("schema_version") != PERSONAL_BASE_SLEEVE_REFERENCE_SCHEMA
        or reference.get("artifact_schema_version") != expected_schema
        or reference.get("strategy_id") != expected_strategy
        or reference.get("cohort_id") != spec.cohort_id
        or reference.get("universe_id") != BASE_UNIVERSE_ID
        or reference.get("role") != PERSONAL_BASE_SLEEVE_ROLE
        or reference.get("ranking_role") != PERSONAL_BASE_SLEEVE_RANKING_ROLE
        or reference.get("candidate_count_contribution") != 0
        or not isinstance(reference.get("sha256"), str)
        or _DIGEST_RE.fullmatch(str(reference["sha256"])) is None
        or not isinstance(reference.get("archive_member"), str)
    ):
        raise RuntimeError("qp-research base sleeve reference is invalid")
    artifact = _require_output_artifact(
        {"path": str(output_root / str(reference["archive_member"]))},
        "path",
        output_root,
    )
    archive_member = artifact.relative_to(output_root.resolve(strict=True)).as_posix()
    if (
        archive_member != reference["archive_member"]
        or not archive_member.startswith("base-sleeve/")
        or artifact.suffix != ".json"
        or artifact.stem != str(reference["sha256"])[7:]
        or artifact.stat().st_size > MAX_BASE_SLEEVE_ARTIFACT_BYTES
        or "sha256:" + _sha256_file(artifact) != reference["sha256"]
    ):
        raise RuntimeError("qp-research base sleeve artifact digest is invalid")
    try:
        document = json.loads(artifact.read_bytes())
        if identity["am_pm"]:
            validate_personal_base_sleeve_am_pm_artifact(document)
        else:
            validate_personal_base_sleeve_artifact(document)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("qp-research base sleeve artifact is invalid") from error
    if (
        not isinstance(document, dict)
        or document.get("cohort", {}).get("cohort_digest") != spec.cohort_digest
        or document.get("universe", {}).get("universe_rule_digest")
        != spec.universe_rule_digest
        or document.get("snapshot", {}).get("logical_data_snapshot_id")
        != summary.get("logical_data_snapshot_id")
    ):
        raise RuntimeError("qp-research base sleeve provenance is invalid")
    source_run = document.get("source_run")
    assert isinstance(source_run, dict)
    if identity["am_pm"] and (
        source_run.get("execution_mode") != identity["execution_mode"]
        or source_run.get("execution_contract_digest")
        != identity["execution_contract_digest"]
        or source_run.get("session_view_digest") != identity["session_view_digest"]
    ):
        raise RuntimeError("qp-research AM base sleeve identities drifted")
    for field in ("paper_artifact", "risk_artifact"):
        _require_output_artifact(
            {field: str(output_root / str(source_run[field]))},
            field,
            output_root,
        )
    return {
        key: value
        for key, value in reference.items()
        if key != "path"
    }


_TERMINAL_PUT_DENIED_STATUSES = frozenset({400, 401, 403, 404, 405, 409, 412, 413, 422})


def _put(
    key: str,
    data: bytes | Path,
    *,
    spec: Any,
    content_digest: str,
    extra_headers: Mapping[str, str] | None = None,
) -> None:
    if isinstance(data, Path):
        length = data.stat().st_size
        payload: Any = data.open("rb")
    else:
        length = len(data)
        payload = data
    headers = {
        **_terminal_get_headers(spec),
        "content-length": str(length),
        "content-type": (
            "application/gzip"
            if isinstance(data, Path)
            else (
                "application/json; charset=utf-8"
                if isinstance(spec, ControlledPilotJobSpec)
                else "application/json"
            )
        ),
        "x-content-sha256": content_digest,
    }
    if isinstance(
        spec,
        (
            PersonalSvi2023JobSpec,
            PersonalIndexVolOverlay2023JobSpec,
            PersonalVolAmPmPanelJobSpec,
            PersonalOptionSidecarJobSpec,
        ),
    ):
        headers.update(spec.headers())
    if extra_headers:
        headers.update(extra_headers)
    create_only_keys = {getattr(spec, "manifest_key", None)}
    if isinstance(spec, ControlledPilotJobSpec):
        create_only_keys.add(spec.stage_key)
        if key in create_only_keys and "if-none-match" not in {k.lower() for k in headers}:
            headers["if-none-match"] = "*"
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}",
        data=payload,
        method="PUT",
        headers=headers,
    )
    try:
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                status = int(response.status)
        except urllib.error.HTTPError as error:
            status = int(error.code)
            if key in create_only_keys and status == 409:
                raise JobConflictError(
                    f"controlled create-only digest conflict HTTP {status}"
                ) from error
            if key in create_only_keys and status in _TERMINAL_PUT_DENIED_STATUSES:
                raise TerminalReadDenied(
                    f"terminal PUT denied HTTP {status}"
                ) from error
            if (
                isinstance(spec, ControlledPilotJobSpec)
                and key == spec.lease_key
                and status in {412, 428}
            ):
                raise ControlledLeaseConflict(
                    f"controlled lease cas HTTP {status}"
                ) from error
            raise
        if status not in {HTTPStatus.OK, HTTPStatus.CREATED}:
            if key in create_only_keys and status in _TERMINAL_PUT_DENIED_STATUSES:
                raise TerminalReadDenied(f"terminal PUT denied HTTP {status}")
            raise RuntimeError(f"R2 upload returned {status}")
    finally:
        if isinstance(data, Path):
            payload.close()


class TerminalReadDenied(RuntimeError):
    """The Worker refused this terminal as identity mismatch or forbidden."""


def _job_kind(spec: Any) -> str:
    if isinstance(spec, ControlledPilotJobSpec):
        return "controlled-pilot"
    if isinstance(spec, SnapshotJobSpec):
        return "snapshot"
    if isinstance(spec, PersonalSvi2023JobSpec):
        return "svi"
    if isinstance(spec, PersonalIndexVolOverlay2023JobSpec):
        return "overlay"
    if isinstance(spec, PersonalVolAmPmPanelJobSpec):
        return "vol-panel"
    if isinstance(spec, PersonalOptionSidecarJobSpec):
        return "option-sidecar"
    return "research"


def _terminal_get_headers(spec: Any) -> dict[str, str]:
    headers = {
        "x-personal-job-id": spec.job_id,
        "x-personal-request-digest": spec.request_digest,
        "x-personal-runner-version": spec.runner_version,
        "x-personal-job-kind": _job_kind(spec),
    }
    if isinstance(spec, JobSpec):
        headers["x-personal-cohort-id"] = spec.cohort_id
        headers["x-personal-universe-id"] = spec.universe_id
    elif isinstance(
        spec,
        (
            PersonalSvi2023JobSpec,
            PersonalIndexVolOverlay2023JobSpec,
            PersonalVolAmPmPanelJobSpec,
            PersonalOptionSidecarJobSpec,
        ),
    ):
        headers["x-personal-cohort-id"] = spec.cohort_id
    return headers


def _terminal_body_matches_spec(spec: Any, document: Mapping[str, Any]) -> bool:
    if isinstance(spec, ControlledPilotJobSpec):
        return _controlled_terminal_matches_spec(spec, document)
    if (
        document.get("job_id") != spec.job_id
        or document.get("request_digest") != spec.request_digest
        or document.get("runner_version") != spec.runner_version
        or document.get("status") not in {"COMPLETED", "FAILED"}
    ):
        return False
    if isinstance(spec, JobSpec) and (
        document.get("cohort_id") != spec.cohort_id
        or document.get("universe_id") != spec.universe_id
    ):
        return False
    if isinstance(spec, PersonalSvi2023JobSpec):
        if document.get("cohort_id") != spec.cohort_id:
            return False
    if isinstance(spec, PersonalVolAmPmPanelJobSpec):
        if document.get("cohort_id") != spec.cohort_id:
            return False
    if isinstance(spec, PersonalOptionSidecarJobSpec):
        if document.get("cohort_id") != spec.cohort_id:
            return False
    if isinstance(spec, PersonalIndexVolOverlay2023JobSpec):
        if document.get("cohort_id") != spec.cohort_id:
            return False
        if spec.is_am_pm_smile_transport:
            expected_schema = AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA
        elif spec.is_am_pm_overlay:
            expected_schema = AM_PM_MANIFEST_SCHEMA
        elif spec.is_smile_transport:
            expected_schema = SMILE_TRANSPORT_MANIFEST_SCHEMA
        else:
            expected_schema = MANIFEST_SCHEMA
        if document.get("schema_version") != expected_schema:
            return False
    return True


def _controlled_terminal_matches_spec(
    spec: ControlledPilotJobSpec, document: Mapping[str, Any]
) -> bool:
    if (
        document.get("identity") != CONTROLLED_PILOT_IDENTITY
        or document.get("job_id") != spec.job_id
        or document.get("request_digest") != spec.request_digest
        or document.get("execution_id") != spec.execution_id
        or document.get("runner_version") != spec.runner_version
        or type(document.get("owner_nonce")) is not str
        or len(document["owner_nonce"]) < 8
        or type(document.get("fencing_token")) is not int
        or not 1 <= document["fencing_token"] <= _JS_MAX_SAFE_INTEGER
    ):
        return False
    status = document.get("status")
    if status == "COMPLETED":
        return (
            set(document) == _CONTROLLED_COMPLETED_TERMINAL_FIELDS
            and document.get("ok") is True
            and document.get("automatic_promotion") is False
            and document.get("live_orders_enabled") is False
            and document.get("ephemeral_cleaned") is True
            and isinstance(document.get("papers"), list)
            and len(document["papers"]) == int(_CONTROLLED_CONTRACT["plan_count"])
            and all(isinstance(row, dict) for row in document["papers"])
            and isinstance(document.get("risks"), list)
            and len(document["risks"]) == int(_CONTROLLED_CONTRACT["plan_count"])
            and all(isinstance(row, dict) for row in document["risks"])
            and isinstance(document.get("selection"), dict)
            and isinstance(document.get("knowledge"), dict)
            and type(document.get("generation")) is int
            and document["generation"] == int(_CONTROLLED_CONTRACT["generation"])
            and type(document.get("max_parallel")) is int
            and document["max_parallel"] == int(_CONTROLLED_CONTRACT["max_parallel"])
        )
    if status == "FAILED":
        error = document.get("error")
        return (
            set(document) == _CONTROLLED_FAILED_TERMINAL_FIELDS
            and document.get("ok") is False
            and type(error) is str
            and 1 <= len(error) <= _CONTROLLED_FAILED_ERROR_MAX_CHARS
            and document.get("go") is False
            and document.get("automatic_promotion") is False
            and document.get("live_orders_enabled") is False
        )
    return False


def _get_json(spec: Any) -> dict[str, Any] | None:
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{spec.manifest_key}",
        method="GET",
        headers=_terminal_get_headers(spec),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = int(response.status)
            raw = _read_bounded_bytes(response, CONTROLLED_TERMINAL_MAX_BYTES)
    except urllib.error.HTTPError as error:
        # Absent terminal is retryable. Identity mismatch / forbidden is not.
        if error.code == 404:
            return None
        if error.code in {400, 403}:
            raise TerminalReadDenied(f"terminal GET denied HTTP {error.code}") from error
        return None
    except (OSError, urllib.error.URLError, TimeoutError):
        return None
    if status == 404:
        return None
    if status in {400, 403}:
        raise TerminalReadDenied(f"terminal GET denied HTTP {status}")
    if status != HTTPStatus.OK:
        return None
    if len(raw) > CONTROLLED_TERMINAL_MAX_BYTES:
        raise TerminalReadDenied("terminal exceeds the manifest bound")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TerminalReadDenied("terminal is not JSON") from error
    if not isinstance(parsed, dict) or not _terminal_body_matches_spec(spec, parsed):
        raise TerminalReadDenied("terminal identity mismatch")
    return parsed


def _read_bounded_bytes(handle: Any, maximum: int) -> bytes:
    if type(maximum) is not int or isinstance(maximum, bool) or maximum < 1:
        raise TerminalReadDenied("controlled object exceeds bound")
    reader = getattr(handle, "read", None)
    if not callable(reader):
        raise TerminalReadDenied("controlled object is not readable")
    raw = reader(maximum + 1)
    if raw is None:
        return b""
    if not isinstance(raw, (bytes, bytearray)):
        raise TerminalReadDenied("controlled object is not bytes")
    if len(raw) > maximum:
        raise TerminalReadDenied("controlled object exceeds bound")
    return bytes(raw)


def _stored_get_max_bytes(key: str) -> int:
    if key.endswith("/container-lease.json"):
        return CONTROLLED_LEASE_STORED_MAX_BYTES
    return CONTROLLED_TERMINAL_MAX_BYTES


def _get_json_at(spec: Any, key: str) -> tuple[dict[str, Any] | None, str]:
    request = urllib.request.Request(
        f"{R2_ORIGIN}/{key}",
        method="GET",
        headers=_terminal_get_headers(spec),
    )
    maximum = _stored_get_max_bytes(key)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = int(response.status)
            raw = _read_bounded_bytes(response, maximum)
            etag = str(response.headers.get("etag") or response.headers.get("ETag") or "")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None, ""
        if error.code in {400, 403}:
            raise TerminalReadDenied(
                f"controlled GET denied HTTP {error.code}"
            ) from error
        return None, ""
    except (OSError, urllib.error.URLError, TimeoutError):
        return None, ""
    if status == 404:
        return None, ""
    if status in {400, 403}:
        raise TerminalReadDenied(f"controlled GET denied HTTP {status}")
    if status != HTTPStatus.OK:
        return None, ""
    if len(raw) > maximum:
        raise TerminalReadDenied("controlled object exceeds bound")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TerminalReadDenied("controlled object is not JSON") from error
    if not isinstance(parsed, dict):
        raise TerminalReadDenied("controlled object identity mismatch")
    return parsed, etag


def _safe_detail(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:500]


def _sanitize_error_detail(value: Any) -> str:
    if not isinstance(value, str):
        return "no detail"
    tokens = [
        token
        for token in value.split()
        if "/" not in token and "\\" not in token
    ]
    cleaned = " ".join(tokens)[:MAX_ERROR_DETAIL_CHARS]
    return cleaned or "no detail"


def _candidate_error_rows(report: Mapping[str, Any]) -> list[dict[str, str]]:
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        return []
    rows: list[dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        error = item.get("error")
        if not isinstance(error, Mapping):
            continue
        strategy_id = item.get("strategy_id")
        error_type = error.get("type")
        if (
            not isinstance(strategy_id, str)
            or _STRATEGY_ID_RE.fullmatch(strategy_id) is None
            or not isinstance(error_type, str)
            or _ERROR_TYPE_RE.fullmatch(error_type) is None
        ):
            continue
        rows.append(
            {
                "strategy_id": strategy_id,
                "type": error_type,
                "detail": _sanitize_error_detail(error.get("detail")),
            }
        )
        if len(rows) >= MAX_CANDIDATE_DIAGNOSTICS:
            break
    return rows


def _load_candidate_error_rows(
    summary: Mapping[str, Any], output_root: Path
) -> list[dict[str, str]]:
    try:
        report_path = _require_output_artifact(summary, "report_json", output_root)
        if report_path.stat().st_size > MAX_DIAGNOSTIC_REPORT_BYTES:
            return []
        parsed = json.loads(report_path.read_bytes())
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, dict):
        return []
    return _candidate_error_rows(parsed)


def _candidate_failure_message(
    summary: Mapping[str, Any],
    output_root: Path,
) -> str:
    unexpected = summary.get("unexpected_errors")
    count = unexpected if type(unexpected) is int and unexpected >= 0 else None
    count_text = "unknown" if count is None else str(count)
    rows = _load_candidate_error_rows(summary, output_root)
    if not rows:
        return (
            f"qp-research candidate failures: unexpected_errors={count_text}; "
            "no candidate diagnostic"
        )
    first = rows[0]
    type_counts: dict[str, int] = {}
    for row in rows:
        type_counts[row["type"]] = type_counts.get(row["type"], 0) + 1
    root_type, root_count = max(
        type_counts.items(),
        key=lambda item: (item[1], item[0]),
    )
    return (
        f"qp-research candidate failures: unexpected_errors={count_text}; "
        f"first={first['strategy_id']} {first['type']}: {first['detail']}; "
        f"repeated={root_type}x{root_count}"
    )


def _manifest_base(spec: JobSpec, *, started_at: str, finished_at: str) -> dict[str, Any]:
    return {
        "version": RUNNER_VERSION,
        "runner_version": RUNNER_VERSION,
        "job_id": spec.job_id,
        "cohort_id": spec.cohort_id,
        "cohort_digest": spec.cohort_digest,
        "universe_id": spec.universe_id,
        "universe_rule_digest": spec.universe_rule_digest,
        "request_digest": spec.request_digest,
        "snapshot": {
            "key": spec.snapshot_key,
            "sha256": f"sha256:{spec.snapshot_sha256}",
        },
        "period": {"start": spec.period_start, "end": spec.period_end},
        "started_at": started_at,
        "finished_at": finished_at,
        "purpose_id": DRAFT_FACTOR_COHORT_PURPOSE_ID,
        "draft_only": True,
        "go": False,
        "ready_snapshot_declared": False,
        "automatic_promotion": False,
        "live_orders_enabled": False,
        "model_calls": 0,
        "estimated_ai_cost_usd": 0.0,
    }


def _run_direct_research(
    spec: JobSpec,
    *,
    database: Path,
    output: Path,
    timeout_seconds: float,
    deadline: Any | None = None,
    clock: Callable[[], float] | None = None,
) -> Any:
    """Run the typed personal service in-process with a cooperative deadline."""

    from cf_platform.container_data_view import ContainerEphemeralDataView
    from pit.cooperative_deadline import CooperativeDeadline, DeadlineExceeded
    from research.personal_service import (
        PersonalResearchRequest,
        PersonalResearchService,
    )

    from pit.cooperative_deadline import install_deadline

    monotonic_clock = clock or time.monotonic
    active = deadline or CooperativeDeadline(
        deadline_monotonic=monotonic_clock() + float(timeout_seconds),
        clock=monotonic_clock,
    )
    try:
        with install_deadline(active):
            view = ContainerEphemeralDataView.bind(
                database,
                artifact_root=output,
                decision_cutoff="morning_close",
            )
            return PersonalResearchService().run(
                PersonalResearchRequest(
                    data_view=view,
                    period_start=spec.period_start,
                    period_end=spec.period_end,
                    cohort_id=spec.cohort_id,
                    universe_id=spec.universe_id,
                    deadline=active,
                )
            )
    except DeadlineExceeded as error:
        raise RuntimeError(
            f"personal research exceeded the {timeout_seconds:g}-second limit"
        ) from error


def execute_job(
    spec: JobSpec,
    *,
    work_root: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    downloader: Callable[[JobSpec, Path], None] = download_snapshot,
    uploader: Callable[..., None] = _put,
    deadline: Any | None = None,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    started_at = _now()
    job_root = Path(tempfile.mkdtemp(prefix=f"job-{spec.job_id}-", dir=work_root))
    try:
        try:
            database = job_root / "source.sqlite"
            output = job_root / "output"
            output.mkdir()
            downloader(spec, database)
            if _sha256_file(database) != spec.snapshot_sha256:
                raise RuntimeError("snapshot sha256 mismatch after persistence")
            verify_sqlite(database)
            direct_kwargs: dict[str, Any] = {
                "database": database,
                "output": output,
                "timeout_seconds": timeout_seconds,
            }
            try:
                import inspect as _inspect

                params = _inspect.signature(_run_direct_research).parameters
            except (TypeError, ValueError):
                params = {}
            if "deadline" in params:
                direct_kwargs["deadline"] = deadline
            if "clock" in params:
                direct_kwargs["clock"] = clock
            run = _run_direct_research(spec, **direct_kwargs)
            returned_reference = getattr(run, "base_sleeve_artifact", None)
            if isinstance(returned_reference, dict):
                base_sleeve_artifact = dict(returned_reference)
                base_sleeve_artifact.pop("path", None)
            elif returned_reference is None:
                base_sleeve_artifact = None
            else:
                raise RuntimeError("base sleeve artifact reference is invalid")
            summary = {
                "report_id": run.report_id,
                "report_json": str(
                    (output / run.report_json.archive_member).resolve()
                ),
                "report_markdown": str(
                    (output / run.report_markdown.archive_member).resolve()
                ),
                "snapshot_id": run.snapshot.snapshot_id,
                "logical_data_snapshot_id": run.snapshot.logical_data_snapshot_id,
                "candidate_count": run.candidate_count,
                "evaluated_count": run.evaluated_count,
                "hold_count": run.hold_count,
                "unexpected_errors": run.unexpected_errors,
                "cohort_id": run.cohort_id,
                "cohort_digest": run.cohort_digest,
                "universe_id": run.universe_id,
                "universe_rule_digest": run.universe_rule_digest,
                "execution_mode": run.execution_mode,
                "execution_contract_digest": run.execution_contract_digest,
                "base_sleeve_artifact": base_sleeve_artifact,
                "non_candidate_source_backtest_count": (
                    run.non_candidate_source_backtest_count
                ),
                "live_orders_enabled": getattr(run, "live_orders_enabled", False),
                "automatic_promotion": getattr(run, "automatic_promotion", False),
                "model_calls": getattr(run, "model_calls", 0),
                "estimated_ai_cost_usd": getattr(run, "estimated_ai_cost_usd", 0.0),
                "go": getattr(run, "go", False),
                "ready_snapshot_declared": getattr(
                    run, "ready_snapshot_declared", False
                ),
            }
            if run.exit_code == 1:
                raise RuntimeError(_candidate_failure_message(summary, output))
            evaluated_count = summary.get("evaluated_count")
            hold_count = summary.get("hold_count")
            unexpected_errors = summary.get("unexpected_errors")
            candidate_count = summary.get("candidate_count")
            model_calls = summary.get("model_calls")
            estimated_ai_cost_usd = summary.get("estimated_ai_cost_usd")
            # The closed CLI either skips all four candidates at preflight or
            # evaluates all four. Per-candidate failures increment
            # unexpected_errors and exit 1, which this boundary rejects.
            if (
                type(candidate_count) is not int
                or candidate_count != 4
                or type(evaluated_count) is not int
                or evaluated_count not in {0, 4}
                or type(hold_count) is not int
                or not 0 <= hold_count <= evaluated_count
                or type(unexpected_errors) is not int
                or unexpected_errors != 0
                or type(model_calls) is not int
                or model_calls != 0
                or type(estimated_ai_cost_usd) not in {int, float}
                or estimated_ai_cost_usd != 0
                or any(
                    not isinstance(summary.get(field), str)
                    or _DIGEST_RE.fullmatch(summary[field]) is None
                    for field in (
                        "report_id",
                        "snapshot_id",
                        "logical_data_snapshot_id",
                    )
                )
                or summary.get("cohort_id") != spec.cohort_id
                or summary.get("cohort_digest") != spec.cohort_digest
                or summary.get("universe_id") != spec.universe_id
                or summary.get("universe_rule_digest")
                != spec.universe_rule_digest
                or summary.get("go") is not False
                or summary.get("ready_snapshot_declared") is not False
                or summary.get("live_orders_enabled") is not False
                or summary.get("automatic_promotion") is not False
            ):
                raise RuntimeError("qp-research violated the fixed personal policy")
            identity = _personal_cohort_identity(spec.cohort_id)
            observed_mode = summary.get("execution_mode", LEGACY_NEXT_CLOSE_EXECUTION_MODE)
            if observed_mode != identity["execution_mode"]:
                raise RuntimeError("qp-research execution_mode does not match repository contract")
            if identity["am_pm"] and summary.get("execution_contract_digest") != (
                identity["execution_contract_digest"]
            ):
                raise RuntimeError(
                    "qp-research execution_contract_digest does not match repository contract"
                )
            expected_exit_code = 0 if evaluated_count == 4 else 2
            if run.exit_code != expected_exit_code:
                raise RuntimeError(
                    "personal research exit/result contract mismatch: "
                    f"exit={run.exit_code}, evaluated_count={evaluated_count}"
                )
            _require_output_artifact(summary, "report_json", output)
            _require_output_artifact(summary, "report_markdown", output)
            base_sleeve_reference = _validated_base_sleeve_reference(
                summary,
                spec=spec,
                output_root=output,
            )
            stable_summary = {
                key: summary.get(key)
                for key in (
                    "cohort_id",
                    "cohort_digest",
                    "universe_id",
                    "universe_rule_digest",
                    "report_id",
                    "snapshot_id",
                    "logical_data_snapshot_id",
                    "candidate_count",
                    "evaluated_count",
                    "hold_count",
                    "unexpected_errors",
                    "model_calls",
                    "estimated_ai_cost_usd",
                    "go",
                    "ready_snapshot_declared",
                    "live_orders_enabled",
                    "automatic_promotion",
                )
            }
            stable_summary["base_sleeve_artifact"] = base_sleeve_reference
            stable_summary["non_candidate_source_backtest_count"] = int(
                base_sleeve_reference is not None
            )
            if identity["am_pm"]:
                stable_summary["execution_mode"] = identity["execution_mode"]
                stable_summary["execution_contract_digest"] = identity[
                    "execution_contract_digest"
                ]
                stable_summary["session_view_digest"] = identity["session_view_digest"]
            (output / "runner-summary.json").write_bytes(
                _canonical_bytes(stable_summary)
            )
            archive = job_root / "result.tar.gz"
            archived_files, result_bytes = build_result_archive(output, archive)
            result_digest = "sha256:" + _sha256_file(archive)
            uploader(
                spec.result_key,
                archive,
                spec=spec,
                content_digest=result_digest,
            )
            manifest = {
                **_manifest_base(spec, started_at=started_at, finished_at=_now()),
                "status": "COMPLETED",
                "result_key": spec.result_key,
                "result_sha256": result_digest,
                "result_bytes": result_bytes,
                "archived_file_count": archived_files,
                "report_id": summary.get("report_id"),
                "cohort_digest": summary.get("cohort_digest"),
                "universe_rule_digest": summary.get("universe_rule_digest"),
                "snapshot_id": summary.get("snapshot_id"),
                "candidate_count": 4,
                "evaluated_count": summary.get("evaluated_count"),
                "hold_count": summary.get("hold_count"),
                "unexpected_errors": summary.get("unexpected_errors"),
                "base_sleeve_artifact": base_sleeve_reference,
                "non_candidate_source_backtest_count": int(
                    base_sleeve_reference is not None
                ),
            }
            if identity["am_pm"]:
                manifest["execution_mode"] = identity["execution_mode"]
                manifest["execution_contract_digest"] = identity[
                    "execution_contract_digest"
                ]
                manifest["session_view_digest"] = identity["session_view_digest"]
        except Exception as error:
            manifest = {
                **_manifest_base(spec, started_at=started_at, finished_at=_now()),
                "status": "FAILED",
                "error": _safe_detail(error),
            }
        manifest_bytes = _canonical_bytes(manifest)
        manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        uploader(
            spec.manifest_key,
            manifest_bytes,
            spec=spec,
            content_digest=manifest_digest,
        )
        return manifest
    finally:
        shutil.rmtree(job_root, ignore_errors=True)


def _bar_session_coverage(
    connection: sqlite3.Connection, table: str, *, source_filter: bool
) -> dict[str, Any]:
    where = " WHERE source='jquants'" if source_filter else ""
    row = connection.execute(
        f"""
        SELECT
            COUNT(*) AS bar_rows,
            SUM(morning_adjustment_close IS NOT NULL) AS am_close,
            SUM(morning_turnover_value IS NOT NULL) AS am_turnover,
            SUM(morning_adjustment_volume IS NOT NULL) AS am_volume,
            SUM(afternoon_adjustment_close IS NOT NULL) AS pm_close,
            SUM(afternoon_turnover_value IS NOT NULL) AS pm_turnover,
            SUM(afternoon_adjustment_volume IS NOT NULL) AS pm_volume
        FROM {table}{where}
        """
    ).fetchone()
    return {
        "bar_rows": int(row["bar_rows"] or 0),
        "am": {
            "morning_adjustment_close_non_null": int(row["am_close"] or 0),
            "morning_turnover_value_non_null": int(row["am_turnover"] or 0),
            "morning_adjustment_volume_non_null": int(row["am_volume"] or 0),
        },
        "pm": {
            "afternoon_adjustment_close_non_null": int(row["pm_close"] or 0),
            "afternoon_turnover_value_non_null": int(row["pm_turnover"] or 0),
            "afternoon_adjustment_volume_non_null": int(row["pm_volume"] or 0),
        },
    }


def _session_coverage(connection: sqlite3.Connection) -> dict[str, Any]:
    state = compact_history_state(connection)
    if state == "invalid":
        raise RuntimeError(
            "snapshot compact v8 marker or schema is invalid; "
            "rebuild as personal-draft-history/v8"
        )
    if state == "mixed":
        raise RuntimeError(
            "snapshot cannot mix compact with typed or generic bars"
        )
    if state == "compact":
        return _bar_session_coverage(
            connection, PERSONAL_HISTORY_COMPACT_BARS_TABLE, source_filter=False
        )
    return _bar_session_coverage(
        connection, "jquants_daily_bars", source_filter=True
    )


def _gzip_file(source: Path, destination: Path) -> None:
    with destination.open("xb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=raw,
            mtime=0,
        ) as compressed:
            with source.open("rb") as handle:
                shutil.copyfileobj(handle, compressed, 1024 * 1024)


def _snapshot_cache_metrics(client: Any) -> dict[str, int]:
    getter = getattr(client, "cache_metrics", None) if client is not None else None
    if not callable(getter):
        return {}
    try:
        payload = getter()
        return {
            "cache_hits": int(payload["cache_hits"]),
            "cache_misses": int(payload["cache_misses"]),
            "cache_published": int(payload["cache_published"]),
            "cache_unavailable": int(payload["cache_unavailable"]),
            "live_fetch_calls": int(payload["live_fetch_calls"]),
        }
    except (TypeError, ValueError, KeyError):
        return {}


def _snapshot_manifest_base(
    spec: SnapshotJobSpec, *, started_at: str, finished_at: str
) -> dict[str, Any]:
    return {
        "version": RUNNER_VERSION,
        "job_id": spec.job_id,
        "request_digest": spec.request_digest,
        "format": PERSONAL_HISTORY_FORMAT,
        "history_scope_id": PERSONAL_HISTORY_SCOPE_ID,
        "history_scope_version": PERSONAL_HISTORY_SCOPE_VERSION,
        "history_scope_digest": PERSONAL_HISTORY_SCOPE_DIGEST,
        "period_start": spec.period_start,
        "period_end": spec.period_end,
        "lookback_sessions": spec.lookback_sessions,
        "started_at": started_at,
        "finished_at": finished_at,
        "runner_version": RUNNER_VERSION,
        "deployment_id": spec.deployment_id,
        "research_state": PERSONAL_RESEARCH_STATE,
        "completeness_claim": PERSONAL_COMPLETENESS_CLAIM,
        "controlled_live_eligibility": PERSONAL_CONTROLLED_ELIGIBILITY,
        "go": False,
        "ready_snapshot_declared": False,
        "automatic_promotion": False,
        "live_orders_enabled": False,
        "model_calls": 0,
    }


def execute_snapshot_job(
    spec: SnapshotJobSpec,
    *,
    work_root: Path,
    uploader: Callable[..., None] = _put,
    client_factory: Callable[[SnapshotJobSpec], Any] | None = None,
    deadline: Any | None = None,
) -> dict[str, Any]:
    from pit.cooperative_deadline import check_deadline

    del deadline
    check_deadline()
    started_at = _now()
    job_root = Path(tempfile.mkdtemp(prefix=f"snapshot-{spec.job_id}-", dir=work_root))
    gzip_key: str | None = None
    client: Any = None
    sqlite_observed = ""
    sqlite_revision_days = 0
    sqlite_revision_coverage = ""
    try:
        try:
            database = job_root / "personal-history.sqlite"
            assert_personal_history_database(
                database, governed_default=Path("/app/data/structured/ingestion.sqlite")
            )
            plan = build_personal_history_plan(
                period_start=spec.period_start,
                period_end=spec.period_end,
                lookback_sessions=spec.lookback_sessions,
            )
            # Period-dependent planning allowance, not a conservative proof.
            # The physical file-size guard after hydrate remains the measured cap.
            if plan.estimated_bytes > spec.max_database_bytes:
                raise RuntimeError(
                    "snapshot planning allowance exceeds builder cap: "
                    f"estimated={plan.estimated_bytes} "
                    f"limit={spec.max_database_bytes}"
                )
            store = SqliteStore(database)
            client = (client_factory or (
                lambda job: PersonalHistorySourceClient(
                    environment=job.environment,
                    period_end=job.period_end,
                    spool_path=job_root / "acquisition-spool.sqlite",
                    r2_opener=urllib.request,
                )
            ))(spec)
            hydrator = PersonalHistoryHydrator(
                client=client,
                store=store,
                plan=plan,
                max_database_bytes=spec.max_database_bytes,
                minimum_free_bytes=SNAPSHOT_MINIMUM_FREE_BYTES,
            )
            summary = hydrator.hydrate()
            from pit.governed_session_materialize import materialize_canonical_session_fields

            try:
                materialize_canonical_session_fields(store._conn)
            except Exception as exc:
                if "equities_bars_daily_am" in str(exc):
                    pass
                else:
                    raise
            coverage = _session_coverage(store._conn)
            observation = store._conn.execute(
                "SELECT observed_through, revision_window_calendar_days, "
                "revision_coverage FROM personal_history_manifest "
                "WHERE singleton=1"
            ).fetchone()
            store._conn.close()
            verify_sqlite(database)
            raw_bytes = database.stat().st_size
            if raw_bytes > spec.max_database_bytes:
                raise RuntimeError("snapshot sqlite exceeds the 5 GiB builder cap")
            raw_digest = "sha256:" + _sha256_file(database)
            gzip_path = job_root / "personal-history.sqlite.gz"
            _gzip_file(database, gzip_path)
            gzip_bytes = gzip_path.stat().st_size
            if gzip_bytes > MAX_SNAPSHOT_BYTES:
                raise RuntimeError(
                    "compressed snapshot exceeds 4 GiB transport cap"
                )
            gzip_digest = "sha256:" + _sha256_file(gzip_path)
            if (
                observation is None
                or not str(observation[0] or "").strip()
                or observation[1] is None
                or not str(observation[2] or "").strip()
            ):
                raise RuntimeError(
                    "snapshot sqlite is missing immutable observation evidence"
                )
            sqlite_observed = str(observation[0])
            sqlite_revision_days = int(observation[1])
            sqlite_revision_coverage = str(observation[2])
            gzip_key = (
                "research/personal/snapshots/sha256="
                f"{raw_digest[7:]}.sqlite.gz"
            )
            uploader(
                gzip_key,
                gzip_path,
                spec=spec,
                content_digest=gzip_digest,
                extra_headers={"x-personal-raw-sha256": raw_digest},
            )
            manifest = {
                **_snapshot_manifest_base(
                    spec, started_at=started_at, finished_at=_now()
                ),
                "status": "COMPLETED",
                "observed_through": sqlite_observed,
                "revision_window_calendar_days": sqlite_revision_days,
                "revision_coverage": sqlite_revision_coverage,
                "data_start": summary.bar_start,
                "calendar_start": plan.calendar_start,
                "calendar_end": spec.period_end,
                "actual_lookback_sessions": summary.actual_lookback_sessions,
                "lookback_truncated": bool(summary.lookback_truncated),
                "dataset_segment_counts": dict(summary.segment_counts),
                "fetched_rows": summary.fetched_rows,
                "written_rows": summary.written_rows,
                "am_field_non_null_coverage": coverage["am"],
                "pm_field_non_null_coverage": coverage["pm"],
                "bar_rows": coverage["bar_rows"],
                "raw_bytes": raw_bytes,
                "raw_sha256": raw_digest,
                "gzip_bytes": gzip_bytes,
                "gzip_sha256": gzip_digest,
                "snapshot_key": gzip_key,
            }
        except Exception as error:
            manifest = {
                **_snapshot_manifest_base(
                    spec, started_at=started_at, finished_at=_now()
                ),
                "status": "FAILED",
                "error": _safe_detail(error),
            }
        manifest = {**manifest, **_snapshot_cache_metrics(client)}
        if manifest.get("status") == "COMPLETED":
            verify_snapshot_observation_evidence(
                manifest,
                observed_through=sqlite_observed,
                revision_window_calendar_days=sqlite_revision_days,
                revision_coverage=sqlite_revision_coverage,
            )
        manifest_bytes = _canonical_bytes(manifest)
        manifest_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        uploader(
            spec.manifest_key,
            manifest_bytes,
            spec=spec,
            content_digest=manifest_digest,
        )
        return manifest
    finally:
        closer = getattr(client, "close", None)
        if callable(closer):
            closer()
        shutil.rmtree(job_root, ignore_errors=True)


JobSpecLike = (
    JobSpec
    | SnapshotJobSpec
    | PersonalSvi2023JobSpec
    | PersonalIndexVolOverlay2023JobSpec
    | PersonalVolAmPmPanelJobSpec
    | PersonalOptionSidecarJobSpec
    | ControlledPilotJobSpec
)
Runner = Callable[[JobSpecLike], dict[str, Any]]
TerminalCallback = Callable[[], None]



class JobManager:
    _RETRY_SCHEDULE = (0.05, 0.2, 0.5, 1.0, 2.0, 5.0)
    _MAX_TERMINAL_PUT_ATTEMPTS = 12

    def __init__(
        self,
        runner: Runner,
        *,
        on_terminal: TerminalCallback | None = None,
        max_job_seconds: float = MAX_JOB_LIFETIME_SECONDS,
        terminal_uploader: Callable[..., None] | None = None,
        terminal_reader: Callable[[JobSpecLike], dict[str, Any] | None] | None = None,
        object_reader: Callable[..., tuple[dict[str, Any] | None, str]] | None = None,
        retry_schedule: Sequence[float] | None = None,
        clock: Callable[[], float] | None = None,
        work_root: Path | None = None,
        lease_ttl_seconds: float | None = None,
        process_start_grace_seconds: float = SUPERVISOR_START_GRACE_SECONDS,
        process_term_grace_seconds: float = SUPERVISOR_TERM_GRACE_SECONDS,
        process_kill_grace_seconds: float = SUPERVISOR_KILL_GRACE_SECONDS,
        process_context: Any | None = None,
    ) -> None:
        if max_job_seconds <= 0:
            raise ValueError("max_job_seconds must be positive")
        self._runner = runner
        self._on_terminal = on_terminal
        self._max_job_seconds = max_job_seconds
        self._terminal_uploader = terminal_uploader or _put
        self._terminal_reader = terminal_reader
        self._object_reader = object_reader
        self._retry_schedule = tuple(retry_schedule or self._RETRY_SCHEDULE)
        self._clock = clock or time.monotonic
        self._work_root = work_root
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._specs: dict[str, JobSpecLike] = {}
        self._worker: threading.Thread | None = None
        self._active_job_id: str | None = None
        self._accepting = True
        self._watchdog: threading.Timer | None = None
        self._retry_timer: threading.Timer | None = None
        self._pending_terminal: tuple[JobSpecLike, dict[str, Any]] | None = None
        self._retry_index = 0
        self._shutdown_notified = False
        self._controlled_lease: dict[str, Any] | None = None
        self._lease_heartbeat: threading.Timer | None = None
        self._lease_recovery: threading.Timer | None = None
        self._lease_lost = threading.Event()
        self._lease_etag = ""
        self._lease_ttl_seconds = lease_ttl_seconds
        self._process_start_grace_seconds = process_start_grace_seconds
        self._process_term_grace_seconds = process_term_grace_seconds
        self._process_kill_grace_seconds = process_kill_grace_seconds
        self._process_context = process_context
        self._supervisor: _ProcessGroupSupervisor | None = None
        self._requested_stop: tuple[str, str] | None = None

    def submit(self, spec: JobSpecLike) -> dict[str, Any]:
        if isinstance(spec, ControlledPilotJobSpec):
            existing_terminal = self._read_terminal(spec)
            if existing_terminal is not None:
                with self._lock:
                    self._jobs[spec.job_id] = dict(existing_terminal)
                    self._specs[spec.job_id] = spec
                return dict(existing_terminal)
        with self._lock:
            if not self._accepting:
                raise JobBusyError("container is shutting down")
            existing = self._jobs.get(spec.job_id)
            if existing is not None:
                if existing["request_digest"] != spec.request_digest:
                    raise JobConflictError("job_id was reused with different parameters")
                local_executor = self._active_job_id == spec.job_id
            else:
                local_executor = False
                existing = None
        if existing is not None and local_executor:
            return dict(existing)
        if existing is not None and isinstance(spec, ControlledPilotJobSpec):
            return self._observe_or_claim_controlled(spec)
        with self._lock:
            if not self._accepting:
                raise JobBusyError("container is shutting down")
            if self._active_job_id is not None:
                raise JobBusyError(f"job {self._active_job_id} is already active")
            if isinstance(spec, ControlledPilotJobSpec):
                claim = self._claim_controlled_lease(spec)
                if claim == "lookup":
                    record = {
                        "job_id": spec.job_id,
                        "request_digest": spec.request_digest,
                        "status": "RUNNING",
                        "submitted_at": _now(),
                        "go": False,
                        "automatic_promotion": False,
                        "live_orders_enabled": False,
                        "job_kind": "controlled-pilot",
                        "identity": CONTROLLED_PILOT_IDENTITY,
                        "execution_id": spec.execution_id,
                        "lease_observer": True,
                    }
                    self._jobs[spec.job_id] = record
                    self._specs[spec.job_id] = spec
                    self._schedule_lease_recovery_locked(spec)
                    return dict(record)
                self._write_controlled_stage(spec)
            record = {
                "job_id": spec.job_id,
                "request_digest": spec.request_digest,
                "status": "QUEUED",
                "submitted_at": _now(),
                "go": False,
                "automatic_promotion": False,
                "live_orders_enabled": False,
            }
            if isinstance(spec, SnapshotJobSpec):
                record["job_kind"] = "snapshot-build"
            elif isinstance(spec, ControlledPilotJobSpec):
                record["job_kind"] = "controlled-pilot"
                record["identity"] = CONTROLLED_PILOT_IDENTITY
            else:
                record["cohort_id"] = spec.cohort_id
                record["cohort_digest"] = spec.cohort_digest
            if isinstance(spec, JobSpec):
                record["universe_id"] = spec.universe_id
            self._jobs[spec.job_id] = record
            self._specs[spec.job_id] = spec
            self._start_local_executor_locked(spec)
            return dict(record)

    def _lease_ttl(self) -> float:
        if self._lease_ttl_seconds is not None:
            return float(self._lease_ttl_seconds)
        return float(_CONTROLLED_CONTRACT.get("lease_ttl_seconds") or 1800)

    def lease_lost(self) -> bool:
        return self._lease_lost.is_set()

    def _fencing_headers(self) -> dict[str, str]:
        lease = self._controlled_lease
        if not isinstance(lease, dict) or self._lease_lost.is_set():
            return {}
        owner = str(lease.get("owner_nonce") or "")
        token = lease.get("fencing_token")
        etag = self._lease_etag
        if not owner or not isinstance(token, int):
            return {}
        headers = {
            "x-personal-lease-owner": owner,
            "x-personal-fencing-token": str(token),
        }
        if etag:
            headers["x-personal-lease-etag"] = etag
        return headers

    def _observe_or_claim_controlled(self, spec: ControlledPilotJobSpec) -> dict[str, Any]:
        with self._lock:
            if not self._accepting:
                raise JobBusyError("container is shutting down")
            if self._active_job_id == spec.job_id:
                return dict(self._jobs[spec.job_id])
            if self._active_job_id is not None:
                raise JobBusyError(f"job {self._active_job_id} is already active")
            claim = self._claim_controlled_lease(spec)
            if claim == "lookup":
                record = dict(self._jobs.get(spec.job_id) or {})
                record.update(
                    {
                        "job_id": spec.job_id,
                        "request_digest": spec.request_digest,
                        "status": "RUNNING",
                        "job_kind": "controlled-pilot",
                        "identity": CONTROLLED_PILOT_IDENTITY,
                        "execution_id": spec.execution_id,
                        "lease_observer": True,
                    }
                )
                self._jobs[spec.job_id] = record
                self._specs[spec.job_id] = spec
                self._schedule_lease_recovery_locked(spec)
                return dict(record)
            self._write_controlled_stage(spec)
            record = {
                "job_id": spec.job_id,
                "request_digest": spec.request_digest,
                "status": "QUEUED",
                "submitted_at": _now(),
                "go": False,
                "automatic_promotion": False,
                "live_orders_enabled": False,
                "job_kind": "controlled-pilot",
                "identity": CONTROLLED_PILOT_IDENTITY,
            }
            self._jobs[spec.job_id] = record
            self._specs[spec.job_id] = spec
            self._start_local_executor_locked(spec)
            return dict(record)

    def _schedule_lease_recovery_locked(self, spec: ControlledPilotJobSpec) -> None:
        existing, _etag = self._read_object(spec, spec.lease_key)
        now = datetime.now(UTC).timestamp()
        delay = 0.05
        if isinstance(existing, dict):
            try:
                delay = max(0.0, float(existing.get("expires_at")) - now) + 0.02
            except (TypeError, ValueError):
                delay = 0.05
        pending = self._lease_recovery
        self._lease_recovery = None
        if pending is not None:
            pending.cancel()
        timer = threading.Timer(delay, self._recover_controlled_lease, args=(spec,))
        timer.daemon = True
        self._lease_recovery = timer
        timer.start()

    def _recover_controlled_lease(self, spec: ControlledPilotJobSpec) -> None:
        try:
            with self._lock:
                if not self._accepting or self._active_job_id is not None:
                    return
                if self._jobs.get(spec.job_id, {}).get("status") in {"COMPLETED", "FAILED"}:
                    return
                claim = self._claim_controlled_lease(spec)
                if claim == "lookup":
                    self._schedule_lease_recovery_locked(spec)
                    return
                self._write_controlled_stage(spec)
                record = dict(self._jobs.get(spec.job_id) or {})
                record.update(
                    {
                        "job_id": spec.job_id,
                        "request_digest": spec.request_digest,
                        "status": "QUEUED",
                        "job_kind": "controlled-pilot",
                        "identity": CONTROLLED_PILOT_IDENTITY,
                        "lease_observer": False,
                    }
                )
                self._jobs[spec.job_id] = record
                self._specs[spec.job_id] = spec
                self._start_local_executor_locked(spec)
        except Exception:
            with self._lock:
                if self._accepting and self._active_job_id is None:
                    self._schedule_lease_recovery_locked(spec)

    def _start_local_executor_locked(self, spec: JobSpecLike) -> None:
        self._active_job_id = spec.job_id
        self._requested_stop = None
        if isinstance(spec, ControlledPilotJobSpec):
            self._lease_lost.clear()
        work_root = self._work_root or Path(
            os.environ.get("QP_JOB_ROOT", "/tmp/personal-research")
        )
        supervisor = _ProcessGroupSupervisor(
            self._runner,
            spec,
            work_root=work_root,
            start_grace_seconds=self._process_start_grace_seconds,
            term_grace_seconds=self._process_term_grace_seconds,
            kill_grace_seconds=self._process_kill_grace_seconds,
            process_context=self._process_context,
        )
        self._supervisor = supervisor
        supervisor.start()
        watchdog = threading.Timer(
            self._max_job_seconds,
            self._expire,
            args=(spec.job_id,),
        )
        watchdog.daemon = True
        self._watchdog = watchdog
        watchdog.start()
        thread = threading.Thread(
            target=self._execute,
            args=(spec, supervisor),
            name=f"personal-research-{spec.job_id}",
            daemon=False,
        )
        self._worker = thread
        thread.start()
        if isinstance(spec, ControlledPilotJobSpec):
            self._start_lease_heartbeat(spec)

    def _read_object(self, spec: JobSpecLike, key: str) -> tuple[dict[str, Any] | None, str]:
        if self._object_reader is not None:
            return self._object_reader(spec, key)
        if not isinstance(spec, ControlledPilotJobSpec):
            return None, ""
        return _get_json_at(spec, key)

    def _write_controlled_stage(self, spec: ControlledPilotJobSpec) -> None:
        if self._lease_lost.is_set():
            raise JobConflictError("controlled lease lost")
        headers = self._fencing_headers()
        stage = {
            "identity": CONTROLLED_PILOT_IDENTITY,
            "job_id": spec.job_id,
            "request_digest": spec.request_digest,
            "execution_id": spec.execution_id,
            "runner_version": spec.runner_version,
            "status": "QUEUED",
            "stage": "QUEUED",
        }
        if headers:
            stage["fencing_token"] = int(headers["x-personal-fencing-token"])
            stage["owner_nonce"] = headers["x-personal-lease-owner"]
        stage_bytes = _canonical_bytes(stage)
        digest = "sha256:" + hashlib.sha256(stage_bytes).hexdigest()
        try:
            self._terminal_uploader(
                spec.stage_key,
                stage_bytes,
                spec=spec,
                content_digest=digest,
                extra_headers=headers or None,
            )
            return
        except JobConflictError as exc:
            existing, _ = self._read_object(spec, spec.stage_key)
            if (
                isinstance(existing, dict)
                and existing.get("request_digest") == spec.request_digest
                and existing.get("execution_id") == spec.execution_id
                and existing.get("identity") == CONTROLLED_PILOT_IDENTITY
            ):
                return
            raise JobConflictError(
                "controlled execution stage digest conflict"
            ) from exc
        except TerminalReadDenied as exc:
            existing, _ = self._read_object(spec, spec.stage_key)
            if (
                isinstance(existing, dict)
                and existing.get("request_digest") == spec.request_digest
                and existing.get("execution_id") == spec.execution_id
            ):
                return
            raise JobConflictError(
                "controlled execution stage digest conflict"
            ) from exc

    def _closed_lease_document(
        self, spec: ControlledPilotJobSpec, owner: str, fencing_token: int, now: float
    ) -> dict[str, Any]:
        ttl = self._lease_ttl()
        return {
            "identity": CONTROLLED_PILOT_IDENTITY,
            "job_id": spec.job_id,
            "request_digest": spec.request_digest,
            "execution_id": spec.execution_id,
            "runner_version": spec.runner_version,
            "kind": "controlled-pilot",
            "owner_nonce": owner,
            "fencing_token": fencing_token,
            "expires_at": now + ttl,
            "heartbeat_at": now,
            "status": "CLAIMED",
        }

    def _validate_lease_document(
        self, existing: Mapping[str, Any], spec: ControlledPilotJobSpec
    ) -> None:
        if set(existing) != CONTROLLED_LEASE_FIELDS:
            raise JobConflictError("controlled lease is not a closed document")
        if (
            existing.get("request_digest") != spec.request_digest
            or existing.get("execution_id") != spec.execution_id
            or existing.get("identity") != CONTROLLED_PILOT_IDENTITY
            or existing.get("kind") != "controlled-pilot"
            or existing.get("runner_version") != spec.runner_version
            or existing.get("job_id") != spec.job_id
        ):
            raise JobConflictError("controlled lease identity conflict")
        owner = existing.get("owner_nonce")
        token = existing.get("fencing_token")
        if type(owner) is not str or len(owner) < 8:
            raise JobConflictError("controlled lease owner is invalid")
        if type(token) is not int or isinstance(token, bool) or token < 1:
            raise JobConflictError("controlled lease fencing token is invalid")

    def _claim_controlled_lease(self, spec: ControlledPilotJobSpec) -> str:
        owner = secrets.token_hex(16)
        for _attempt in range(4):
            now = datetime.now(UTC).timestamp()
            existing, etag = self._read_object(spec, spec.lease_key)
            if existing is None:
                lease = self._closed_lease_document(spec, owner, 1, now)
                body = _canonical_bytes(lease)
                digest = "sha256:" + hashlib.sha256(body).hexdigest()
                try:
                    self._terminal_uploader(
                        spec.lease_key,
                        body,
                        spec=spec,
                        content_digest=digest,
                        extra_headers={"if-none-match": "*"},
                    )
                    self._controlled_lease = lease
                    _claimed, claimed_etag = self._read_object(spec, spec.lease_key)
                    self._lease_etag = claimed_etag
                    self._lease_lost.clear()
                    return "claimed"
                except ControlledLeaseConflict:
                    continue
            if not isinstance(existing, dict):
                raise JobConflictError("controlled lease is invalid")
            if existing.get("status") == "TERMINAL":
                return "lookup"
            extra = set(existing) - CONTROLLED_LEASE_FIELDS
            if extra:
                raise JobConflictError("controlled lease has unknown fields")
            if (
                existing.get("request_digest") != spec.request_digest
                or existing.get("execution_id") != spec.execution_id
                or existing.get("identity") != CONTROLLED_PILOT_IDENTITY
                or existing.get("job_id") != spec.job_id
            ):
                raise JobConflictError("controlled lease identity conflict")
            expires_at = existing.get("expires_at")
            try:
                active = float(expires_at) > now
            except (TypeError, ValueError):
                active = False
            if active:
                return "lookup"
            if not etag:
                raise JobConflictError("controlled lease etag missing")
            fencing = existing.get("fencing_token")
            if fencing is None:
                next_token = 1
            elif type(fencing) is not int or isinstance(fencing, bool) or fencing < 1:
                raise JobConflictError("controlled lease fencing token is invalid")
            else:
                next_token = fencing + 1
            lease = self._closed_lease_document(spec, owner, next_token, now)
            body = _canonical_bytes(lease)
            digest = "sha256:" + hashlib.sha256(body).hexdigest()
            try:
                self._terminal_uploader(
                    spec.lease_key,
                    body,
                    spec=spec,
                    content_digest=digest,
                    extra_headers={"if-match": etag},
                )
                self._controlled_lease = lease
                _claimed, claimed_etag = self._read_object(spec, spec.lease_key)
                self._lease_etag = claimed_etag
                self._lease_lost.clear()
                return "claimed"
            except ControlledLeaseConflict:
                continue
        raise JobConflictError("controlled lease claim raced")

    def _start_lease_heartbeat(self, spec: ControlledPilotJobSpec) -> None:
        ttl = self._lease_ttl()
        interval = max(0.05, min(60.0, ttl / 3))

        def beat() -> None:
            try:
                self._heartbeat_controlled_lease(spec)
            except Exception:
                self._mark_lease_lost()
                return
            with self._lock:
                alive = (
                    self._accepting
                    and self._active_job_id == spec.job_id
                    and not self._lease_lost.is_set()
                )
            if not alive:
                return
            timer = threading.Timer(interval, beat)
            timer.daemon = True
            self._lease_heartbeat = timer
            timer.start()

        timer = threading.Timer(interval, beat)
        timer.daemon = True
        self._lease_heartbeat = timer
        timer.start()

    def _mark_lease_lost(self) -> None:
        self._lease_lost.set()
        with self._lock:
            heartbeat = self._lease_heartbeat
            self._lease_heartbeat = None
            supervisor = self._supervisor
            if self._active_job_id is not None and self._requested_stop is None:
                self._requested_stop = (
                    "lease_lost",
                    "controlled lease lost",
                )
                self._accepting = False
        if heartbeat is not None:
            heartbeat.cancel()
        if supervisor is not None:
            supervisor.stop()

    def _heartbeat_controlled_lease(self, spec: ControlledPilotJobSpec) -> None:
        if self._lease_lost.is_set():
            raise JobConflictError("controlled lease lost")
        current = self._controlled_lease
        if not isinstance(current, dict):
            raise JobConflictError("controlled lease missing")
        existing, etag = self._read_object(spec, spec.lease_key)
        if not isinstance(existing, dict) or not etag:
            raise JobConflictError("controlled lease heartbeat read failed")
        if existing.get("status") == "TERMINAL":
            self._mark_lease_lost()
            raise JobConflictError("controlled lease is terminal")
        self._validate_lease_document(existing, spec)
        if existing.get("owner_nonce") != current.get("owner_nonce"):
            self._mark_lease_lost()
            raise JobConflictError("controlled lease owner lost")
        if existing.get("fencing_token") != current.get("fencing_token"):
            self._mark_lease_lost()
            raise JobConflictError("controlled lease fencing token lost")
        now = datetime.now(UTC).timestamp()
        if existing.get("status") != "CLAIMED":
            self._mark_lease_lost()
            raise JobConflictError("controlled lease expired")
        try:
            stored_expires = float(existing.get("expires_at"))
            local_expires = float(current.get("expires_at"))
        except (TypeError, ValueError):
            self._mark_lease_lost()
            raise JobConflictError("controlled lease expired") from None
        if not (stored_expires > now and local_expires > now):
            self._mark_lease_lost()
            raise JobConflictError("controlled lease expired")
        lease = self._closed_lease_document(
            spec,
            str(current["owner_nonce"]),
            int(current["fencing_token"]),
            now,
        )
        body = _canonical_bytes(lease)
        try:
            self._terminal_uploader(
                spec.lease_key,
                body,
                spec=spec,
                content_digest="sha256:" + hashlib.sha256(body).hexdigest(),
                extra_headers={"if-match": etag},
            )
            self._controlled_lease = lease
            _claimed, claimed_etag = self._read_object(spec, spec.lease_key)
            self._lease_etag = claimed_etag or etag
        except ControlledLeaseConflict as exc:
            self._mark_lease_lost()
            raise JobConflictError("controlled lease heartbeat cas lost") from exc

    def _timeout_terminal(self, spec: JobSpecLike) -> dict[str, Any]:
        finished = _now()
        started = str(self._jobs.get(spec.job_id, {}).get("started_at") or finished)
        error = (
            "absolute Container lifetime exceeded "
            f"({self._max_job_seconds:g}s)"
        )
        if isinstance(spec, ControlledPilotJobSpec):
            return {
                "ok": False,
                "identity": CONTROLLED_PILOT_IDENTITY,
                "status": "FAILED",
                "job_id": spec.job_id,
                "request_digest": spec.request_digest,
                "execution_id": spec.execution_id,
                "runner_version": spec.runner_version,
                "error": error,
                "go": False,
                "automatic_promotion": False,
                "live_orders_enabled": False,
            }
        if isinstance(spec, SnapshotJobSpec):
            return {
                **_snapshot_manifest_base(
                    spec, started_at=started, finished_at=finished
                ),
                "status": "FAILED",
                "error": error,
            }
        if isinstance(spec, JobSpec):
            return {
                **_manifest_base(spec, started_at=started, finished_at=finished),
                "status": "FAILED",
                "error": error,
            }
        if isinstance(spec, PersonalSvi2023JobSpec):
            return {
                "schema_version": "personal-svi-2023-manifest/v2",
                "status": "FAILED",
                "job_id": spec.job_id,
                "cohort_id": spec.cohort_id,
                "strategy_id": spec.strategy_id,
                "runner_version": spec.runner_version,
                "request_digest": spec.request_digest,
                "input_manifest_key": spec.input_manifest_key,
                "input_manifest_digest": spec.input_manifest_digest,
                "error": error,
                "draft_only": True,
                "screening_only": True,
                "ready": False,
                "mass": False,
                "promotion": False,
                "live_orders": False,
                "go": False,
                "not_a_pass": True,
            }
        if isinstance(spec, PersonalVolAmPmPanelJobSpec):
            return {
                "schema_version": "personal-vol-ratio-am-pm-panel-writer-manifest/v1",
                "status": "FAILED",
                "kind": "vol-panel",
                "producer_id": spec.producer_id,
                "job_id": spec.job_id,
                "cohort_id": spec.cohort_id,
                "runner_version": spec.runner_version,
                "request_digest": spec.request_digest,
                "input_manifest_key": spec.input_manifest_key,
                "input_manifest_digest": spec.input_manifest_digest,
                "error": error,
                "draft_only": True,
                "screening_only": True,
                "ready": False,
                "mass": False,
                "promotion": False,
                "live_orders": False,
                "go": False,
                "not_a_pass": True,
            }
        if isinstance(spec, PersonalOptionSidecarJobSpec):
            return {
                "schema_version": "personal-n225-option-sidecar-manifest/v1",
                "status": "FAILED",
                "kind": "option-sidecar",
                "producer_id": spec.producer_id,
                "job_id": spec.job_id,
                "cohort_id": spec.cohort_id,
                "runner_version": spec.runner_version,
                "request_digest": spec.request_digest,
                "input_manifest_key": spec.input_manifest_key,
                "input_manifest_digest": spec.input_manifest_digest,
                "error": error,
                "draft_only": True,
                "screening_only": True,
                "ready": False,
                "mass": False,
                "promotion": False,
                "live_orders": False,
                "go": False,
                "not_a_pass": True,
            }
        if spec.is_am_pm_smile_transport:
            schema = AM_PM_SMILE_TRANSPORT_MANIFEST_SCHEMA
        elif spec.is_am_pm_overlay:
            schema = AM_PM_MANIFEST_SCHEMA
        elif spec.is_smile_transport:
            schema = SMILE_TRANSPORT_MANIFEST_SCHEMA
        else:
            schema = MANIFEST_SCHEMA
        return {
            "schema_version": schema,
            "status": "FAILED",
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
            "runner_version": spec.runner_version,
            "request_digest": spec.request_digest,
            "error": error,
        }

    def _failure_terminal(self, spec: JobSpecLike, error: str) -> dict[str, Any]:
        failed = self._timeout_terminal(spec)
        failed["error"] = error
        return failed

    def _read_terminal(self, spec: JobSpecLike) -> dict[str, Any] | None:
        reader = self._terminal_reader
        if reader is not None:
            try:
                return reader(spec)
            except TerminalReadDenied:
                raise
            except Exception:
                return None
        return _get_json(spec)

    def _matching_terminal(self, spec: JobSpecLike, existing: Any) -> bool:
        return isinstance(existing, dict) and _terminal_body_matches_spec(spec, existing)

    def _conflicting_terminal(self, spec: JobSpecLike, existing: Any) -> bool:
        return isinstance(existing, dict) and not self._matching_terminal(spec, existing)

    def _record_terminal_conflict(self, spec: JobSpecLike, detail: str) -> None:
        print(
            json.dumps(
                {
                    "event": "terminal_publication_conflict",
                    "job_id": spec.job_id,
                    "detail": detail,
                    "at": _now(),
                    "go": False,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    def _record_terminal_retry_exhausted(self, spec: JobSpecLike, attempts: int) -> None:
        print(
            json.dumps(
                {
                    "event": "terminal_publication_retry_exhausted",
                    "job_id": spec.job_id,
                    "attempts": attempts,
                    "at": _now(),
                    "go": False,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    def _publish_verified_terminal(
        self, spec: JobSpecLike, manifest: Mapping[str, Any]
    ) -> str:
        extra = None
        if isinstance(spec, ControlledPilotJobSpec):
            if self._lease_lost.is_set():
                return "conflict"
            current = self._controlled_lease
            try:
                existing, _etag = self._read_object(spec, spec.lease_key)
            except Exception:
                existing = current
            if existing is None:
                existing = current
            if (
                not isinstance(existing, dict)
                or not isinstance(current, dict)
                or existing.get("owner_nonce") != current.get("owner_nonce")
                or existing.get("fencing_token") != current.get("fencing_token")
                or existing.get("job_id") != spec.job_id
            ):
                self._mark_lease_lost()
                return "conflict"
            extra = self._fencing_headers()
            if not extra:
                self._mark_lease_lost()
                return "conflict"
            manifest = dict(manifest)
            manifest["fencing_token"] = int(extra["x-personal-fencing-token"])
            manifest["owner_nonce"] = extra["x-personal-lease-owner"]
            if not _controlled_terminal_matches_spec(spec, manifest):
                return "conflict"
        body = _canonical_bytes(manifest)
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        try:
            self._terminal_uploader(
                spec.manifest_key,
                body,
                spec=spec,
                content_digest=digest,
                extra_headers=extra,
            )
            return "ok"
        except TerminalReadDenied:
            try:
                existing = self._read_terminal(spec)
            except TerminalReadDenied:
                return "conflict"
            if self._matching_terminal(spec, existing):
                return "ok"
            return "conflict"
        except Exception as error:
            try:
                existing = self._read_terminal(spec)
            except TerminalReadDenied:
                return "conflict"
            if self._matching_terminal(spec, existing):
                return "ok"
            if self._conflicting_terminal(spec, existing):
                return "conflict"
            raise RuntimeError(_safe_detail(error)) from error

    def _notify_shutdown(self) -> None:
        with self._lock:
            if self._shutdown_notified:
                return
            self._shutdown_notified = True
            pending_retry = self._retry_timer
            self._retry_timer = None
            self._pending_terminal = None
        if pending_retry is not None:
            pending_retry.cancel()
        if self._on_terminal is not None:
            self._on_terminal()

    def _begin_terminal_publication(
        self, spec: JobSpecLike, manifest: dict[str, Any]
    ) -> None:
        with self._lock:
            self._accepting = False
            self._pending_terminal = (spec, manifest)
            self._retry_index = 0
        self._attempt_terminal_publication()

    def _attempt_terminal_publication(self) -> None:
        with self._lock:
            if self._shutdown_notified:
                return
            pending = self._pending_terminal
        if pending is None:
            return
        spec, manifest = pending
        try:
            outcome = self._publish_verified_terminal(spec, manifest)
        except Exception:
            self._schedule_terminal_retry()
            return
        if outcome == "ok":
            self._notify_shutdown()
            return
        if outcome == "conflict":
            self._record_terminal_conflict(
                spec, "immutable terminal conflict or identity denial"
            )
            self._notify_shutdown()

    def _schedule_terminal_retry(self) -> None:
        exhausted_spec: JobSpecLike | None = None
        attempts = 0
        pending_retry: threading.Timer | None = None
        with self._lock:
            if self._shutdown_notified:
                return
            pending = self._pending_terminal
            self._retry_index += 1
            if (
                pending is None
                or self._retry_index >= self._MAX_TERMINAL_PUT_ATTEMPTS
            ):
                exhausted_spec = None if pending is None else pending[0]
                attempts = self._retry_index
                pending_retry = self._retry_timer
                self._retry_timer = None
            else:
                delay = self._retry_schedule[
                    min(self._retry_index - 1, len(self._retry_schedule) - 1)
                ]
                timer = threading.Timer(delay, self._attempt_terminal_publication)
                timer.daemon = True
                self._retry_timer = timer
                timer.start()
                return
        if pending_retry is not None:
            pending_retry.cancel()
        if exhausted_spec is not None:
            self._record_terminal_retry_exhausted(exhausted_spec, attempts)
        self._notify_shutdown()

    def _expire(self, job_id: str) -> None:
        supervisor: _ProcessGroupSupervisor | None = None
        with self._lock:
            if self._active_job_id != job_id or not self._accepting:
                return
            record = self._jobs[job_id]
            self._jobs[job_id] = {
                **record,
                "status": "STOPPING",
                "error": (
                    "absolute Container lifetime exceeded "
                    f"({self._max_job_seconds:g}s)"
                ),
                "go": False,
            }
            self._requested_stop = (
                "timeout",
                self._jobs[job_id]["error"],
            )
            self._accepting = False
            supervisor = self._supervisor
        if supervisor is not None:
            supervisor.stop()

    def cancel(self, job_id: str) -> bool:
        """Cancel the active job through the same bounded process-group stop path."""

        supervisor: _ProcessGroupSupervisor | None = None
        with self._lock:
            if self._active_job_id != job_id or self._requested_stop is not None:
                return False
            record = self._jobs[job_id]
            self._jobs[job_id] = {
                **record,
                "status": "STOPPING",
                "error": "job cancelled",
                "go": False,
            }
            self._requested_stop = ("cancel", "job cancelled")
            self._accepting = False
            supervisor = self._supervisor
        if supervisor is not None:
            supervisor.stop()
        return True

    def _validated_child_result(
        self, spec: JobSpecLike, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        candidate = dict(result)
        if isinstance(spec, ControlledPilotJobSpec):
            headers = self._fencing_headers()
            if not headers:
                raise RuntimeError("controlled child result has no active lease fence")
            candidate_with_fence = {
                **candidate,
                "owner_nonce": headers["x-personal-lease-owner"],
                "fencing_token": int(headers["x-personal-fencing-token"]),
            }
            if not _controlled_terminal_matches_spec(spec, candidate_with_fence):
                raise RuntimeError("controlled child result contract mismatch")
            return candidate
        if not _terminal_body_matches_spec(spec, candidate):
            raise RuntimeError("child result terminal identity mismatch")
        return candidate

    def _execute(
        self,
        spec: JobSpecLike,
        supervisor: _ProcessGroupSupervisor,
    ) -> None:
        with self._lock:
            if self._active_job_id != spec.job_id or self._supervisor is not supervisor:
                supervisor.stop()
                return
            self._jobs[spec.job_id]["status"] = "RUNNING"
            self._jobs[spec.job_id]["started_at"] = _now()
        outcome = supervisor.wait()
        terminal: dict[str, Any] | None = None
        lease_lost = False
        liveness_unknown = False
        with self._lock:
            if self._supervisor is not supervisor:
                return
            stop = self._requested_stop
            if not outcome.quiescent:
                record = self._jobs[spec.job_id]
                self._jobs[spec.job_id] = {
                    **record,
                    "status": "STOPPING",
                    "error": "job process group liveness is unknown",
                    "go": False,
                }
                liveness_unknown = True
            elif stop is not None and stop[0] == "lease_lost":
                record = self._jobs[spec.job_id]
                self._jobs[spec.job_id] = {
                    **record,
                    "status": "FAILED",
                    "error": stop[1],
                    "finished_at": _now(),
                    "go": False,
                }
                lease_lost = True
            elif stop is not None and stop[0] == "timeout":
                terminal = self._timeout_terminal(spec)
            elif stop is not None and stop[0] == "cancel":
                terminal = self._failure_terminal(spec, stop[1])
            elif outcome.error is not None:
                terminal = self._failure_terminal(spec, outcome.error)
            elif outcome.result is None:
                terminal = self._failure_terminal(
                    spec, "supervised child returned no result"
                )
            else:
                try:
                    terminal = self._validated_child_result(spec, outcome.result)
                except Exception as error:
                    terminal = self._failure_terminal(spec, _safe_detail(error))
            if terminal is not None:
                self._jobs[spec.job_id] = dict(terminal)
            self._accepting = False
            if not liveness_unknown:
                self._active_job_id = None
                self._supervisor = None
            watchdog = self._watchdog
            self._watchdog = None
            heartbeat = self._lease_heartbeat
            self._lease_heartbeat = None
            if watchdog is not None:
                watchdog.cancel()
            if heartbeat is not None:
                heartbeat.cancel()
        if liveness_unknown:
            return
        if lease_lost:
            self._notify_shutdown()
            return
        if terminal is not None:
            self._begin_terminal_publication(spec, terminal)

    def status(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs.get(job_id)
            return None if record is None else dict(record)


def default_runner(
    spec: JobSpecLike,
    *,
    work_root: Path | None = None,
    deadline: Any | None = None,
) -> dict[str, Any]:
    from pit.cooperative_deadline import install_deadline

    owned_work_root = work_root is None
    if work_root is None:
        env_root = os.environ.get("QP_JOB_ROOT")
        work_root = bind_container_work_root(None if not env_root else Path(env_root))
    try:
        with install_deadline(deadline):
            if isinstance(spec, ControlledPilotJobSpec):
                result = execute_controlled_pilot_container(spec.document)
                return {
                    **result,
                    "status": "COMPLETED",
                    "job_id": spec.job_id,
                    "request_digest": spec.request_digest,
                    "execution_id": spec.execution_id,
                    "runner_version": spec.runner_version,
                }
            if isinstance(spec, SnapshotJobSpec):
                return execute_snapshot_job(
                    spec,
                    work_root=work_root,
                    uploader=_put_child_artifact,
                    deadline=deadline,
                )
            if isinstance(spec, PersonalIndexVolOverlay2023JobSpec):
                return execute_overlay_job(spec, uploader=_put_child_json, deadline=deadline)
            if isinstance(spec, PersonalSvi2023JobSpec):
                return execute_svi_job(spec, uploader=_put_child_json, deadline=deadline)
            if isinstance(spec, PersonalVolAmPmPanelJobSpec):
                return execute_vol_am_pm_panel_job(
                    spec, uploader=_put_child_json, deadline=deadline
                )
            if isinstance(spec, PersonalOptionSidecarJobSpec):
                return execute_option_sidecar_job(
                    spec, uploader=_put_child_json, deadline=deadline
                )
            return execute_job(
                spec,
                work_root=work_root,
                uploader=_put_child_artifact,
                deadline=deadline,
            )
    finally:
        if owned_work_root:
            shutil.rmtree(work_root, ignore_errors=True)


def bind_container_work_root(path: Path | None = None) -> Path:
    """Create an owned ephemeral job root under the platform temp directory."""

    from pit.personal_research_view import platform_temp_root, require_ephemeral_path

    temp_root = platform_temp_root()
    if path is None:
        return Path(tempfile.mkdtemp(prefix="personal-research-", dir=temp_root))
    requested = require_ephemeral_path(Path(path))
    requested.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="job-root-", dir=requested))


def _put_child_artifact(
    key: str,
    data: bytes | Path,
    *,
    spec: JobSpecLike,
    content_digest: str,
    extra_headers: Mapping[str, str] | None = None,
) -> None:
    if key != spec.manifest_key:
        _put(
            key,
            data,
            spec=spec,
            content_digest=content_digest,
            extra_headers=extra_headers,
        )


def _put_child_json(spec: JobSpecLike, key: str, data: bytes) -> str:
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    if key != spec.manifest_key:
        _put(key, data, spec=spec, content_digest=digest)
    return digest


class PersonalResearchHandler(BaseHTTPRequestHandler):
    manager: JobManager
    server_version = "quant-personal-research/1"

    def _json(self, value: Any, status: int) -> None:
        body = _canonical_bytes(value if isinstance(value, dict) else {"value": value})
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/ready":
            self._json({"ok": True, "service": RUNNER_VERSION}, HTTPStatus.OK)
            return
        prefix = "/v1/jobs/"
        if not self.path.startswith(prefix):
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        job_id = self.path[len(prefix) :]
        if _JOB_ID_RE.fullmatch(job_id) is None:
            self._json({"error": "invalid_job_id"}, HTTPStatus.BAD_REQUEST)
            return
        record = self.manager.status(job_id)
        if record is None:
            self._json({"error": "job_not_found", "job_id": job_id}, HTTPStatus.NOT_FOUND)
            return
        self._json({"ok": record.get("status") == "COMPLETED", "job": record}, HTTPStatus.OK)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path not in {
            "/v1/run",
            "/v1/run-svi-2023",
            "/v1/run-index-vol-overlay-2023",
            "/v1/build-snapshot",
            "/v1/build-personal-vol-am-pm-panel",
            "/v1/produce-option-sidecar",
            "/v1/controlled-pilot",
        }:
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        raw_length = self.headers.get("content-length", "")
        if not raw_length.isdigit() or not 0 < int(raw_length) <= MAX_REQUEST_BYTES:
            self._json({"error": "invalid_content_length"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            document = json.loads(self.rfile.read(int(raw_length)))
            if self.path == "/v1/controlled-pilot":
                spec = ControlledPilotJobSpec.from_document(document)
                record = self.manager.submit(spec)
                self._json(
                    {
                        "ok": True,
                        "accepted": True,
                        "job": record,
                        "identity": CONTROLLED_PILOT_IDENTITY,
                        "go": False,
                        "automatic_promotion": False,
                        "live_orders_enabled": False,
                    },
                    HTTPStatus.ACCEPTED,
                )
                return
            if self.path == "/v1/run-svi-2023":
                spec = PersonalSvi2023JobSpec.from_document(document)
            elif self.path == "/v1/run-index-vol-overlay-2023":
                spec = PersonalIndexVolOverlay2023JobSpec.from_document(document)
            elif self.path == "/v1/build-snapshot":
                spec = SnapshotJobSpec.from_document(document)
            elif self.path == "/v1/build-personal-vol-am-pm-panel":
                spec = PersonalVolAmPmPanelJobSpec.from_document(document)
            elif self.path == "/v1/produce-option-sidecar":
                spec = PersonalOptionSidecarJobSpec.from_document(document)
            else:
                spec = JobSpec.from_document(document)
            record = self.manager.submit(spec)
        except (
            json.JSONDecodeError,
            JobInputError,
            SviJobInputError,
            OverlayJobInputError,
            VolPanelJobInputError,
            OptionSidecarJobInputError,
        ) as error:
            self._json({"error": "invalid_job", "detail": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        except JobConflictError as error:
            self._json({"error": "job_id_conflict", "detail": str(error)}, HTTPStatus.CONFLICT)
            return
        except JobBusyError as error:
            self._json({"error": "container_busy", "detail": str(error)}, HTTPStatus.CONFLICT)
            return
        self._json(
            {
                "ok": True,
                "accepted": True,
                "job": record,
                "go": False,
                "automatic_promotion": False,
                "live_orders_enabled": False,
            },
            HTTPStatus.ACCEPTED,
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(
            json.dumps(
                {
                    "event": "container_http",
                    "message": format % args,
                    "at": _now(),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )


def main() -> None:
    env_root = os.environ.get("QP_JOB_ROOT")
    work_root = bind_container_work_root(None if not env_root else Path(env_root))
    server: ThreadingHTTPServer | None = None
    try:
        server = ThreadingHTTPServer(("0.0.0.0", 8080), PersonalResearchHandler)
        server.daemon_threads = True
        runner = partial(default_runner, work_root=work_root)
        PersonalResearchHandler.manager = JobManager(
            runner,
            on_terminal=server.shutdown,
            work_root=work_root,
        )
        server.serve_forever()
    finally:
        if server is not None:
            server.server_close()
        shutil.rmtree(work_root, ignore_errors=True)


if __name__ == "__main__":
    main()
