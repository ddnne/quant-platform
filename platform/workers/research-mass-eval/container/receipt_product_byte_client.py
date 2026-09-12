"""Container transport for Premium receipt-product describe/byte RPCs.

Spools product bytes to an owned ephemeral file. The 4 MiB bound is the
describe/metadata response cap, never a product-stream cap.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

RECEIPT_PRODUCT_ORIGIN = "http://receipt.products"
DESCRIBE_PATH = "/v1/describe-receipt-product-input"
BYTES_PATH = "/v1/read-receipt-product-bytes"
RECEIPT_PRODUCT_INPUT_REQUEST = "receipt-product-input-request/v1"
RECEIPT_PRODUCT_BYTE_REQUEST = "receipt-product-byte-request/v1"
RECEIPT_PRODUCT_INPUT_SET = "receipt-product-input-set/v1"
DESCRIBE_MAX_BYTES = 4 * 1024 * 1024
RAW_MANIFEST_MAX_BYTES = 4 * 1024 * 1024
OFFICIAL_CALENDAR_MAX_BYTES = 65_536
DESCRIBE_BATCH_SEGMENTS = 128
_IDENTITY_HEADERS = frozenset({"x-quant-resource", "x-quant-receipt-digest"})


class ReceiptProductTransportError(RuntimeError):
    """Premium receipt-product transport refused the request."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def describe_receipt_product_input(
    *,
    profile_id: str,
    profile_digest: str,
    dependency_closure_digest: str,
    segments: Sequence[Mapping[str, str]],
    opener: Any = urllib.request,
) -> dict[str, Any]:
    if not 1 <= len(segments) <= DESCRIBE_BATCH_SEGMENTS:
        raise ReceiptProductTransportError("describe batch is out of range")
    payload = {
        "schema_version": RECEIPT_PRODUCT_INPUT_REQUEST,
        "profile_id": profile_id,
        "profile_digest": profile_digest,
        "dependency_closure_digest": dependency_closure_digest,
        "segments": [
            {"dataset": item["dataset"], "segment_id": item["segment_id"]}
            for item in segments
        ],
    }
    body = _canonical_bytes(payload)
    request = urllib.request.Request(
        f"{RECEIPT_PRODUCT_ORIGIN}{DESCRIBE_PATH}",
        data=body,
        method="POST",
        headers={
            "content-type": "application/json; charset=utf-8",
            "content-length": str(len(body)),
        },
    )
    try:
        with opener.urlopen(request, timeout=120) as response:
            raw = response.read(DESCRIBE_MAX_BYTES + 1)
            status = int(response.status)
    except urllib.error.HTTPError as error:
        raw = error.read(DESCRIBE_MAX_BYTES + 1)
        status = int(error.code)
    if len(raw) > DESCRIBE_MAX_BYTES:
        raise ReceiptProductTransportError("describe response exceeds metadata bound")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptProductTransportError("describe response is not JSON") from exc
    if status != 200 or type(parsed) is not dict or parsed.get("status") != "DESCRIBED":
        raise ReceiptProductTransportError("receipt product input was not described")
    if parsed.get("schema_version") != RECEIPT_PRODUCT_INPUT_SET:
        raise ReceiptProductTransportError("describe schema mismatch")
    return parsed


def spool_receipt_product_bytes(
    *,
    destination: Path,
    profile_id: str,
    profile_digest: str,
    dependency_closure_digest: str,
    dataset: str,
    segment_id: str,
    operation_id: str,
    receipt_digest: str,
    resource: str,
    max_bytes: int,
    opener: Any = urllib.request,
) -> int:
    if resource not in {
        "product_artifact",
        "raw_collection_manifest",
        "official_calendar_raw",
    }:
        raise ReceiptProductTransportError("resource is invalid")
    if max_bytes < 1:
        raise ReceiptProductTransportError("byte budget is invalid")
    payload = {
        "schema_version": RECEIPT_PRODUCT_BYTE_REQUEST,
        "profile_id": profile_id,
        "profile_digest": profile_digest,
        "dependency_closure_digest": dependency_closure_digest,
        "dataset": dataset,
        "segment_id": segment_id,
        "operation_id": operation_id,
        "receipt_digest": receipt_digest,
        "resource": resource,
    }
    body = _canonical_bytes(payload)
    request = urllib.request.Request(
        f"{RECEIPT_PRODUCT_ORIGIN}{BYTES_PATH}",
        data=body,
        method="POST",
        headers={
            "content-type": "application/json; charset=utf-8",
            "content-length": str(len(body)),
        },
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with opener.urlopen(request, timeout=300) as response:
        if int(response.status) != 200:
            raise ReceiptProductTransportError(
                f"receipt product bytes returned {response.status}"
            )
        present = {
            name.lower()
            for name in response.headers
            if name.lower().startswith("x-quant-")
        }
        if not _IDENTITY_HEADERS <= present:
            raise ReceiptProductTransportError("byte identity headers are required")
        if (
            response.headers.get("x-quant-resource") != resource
            or response.headers.get("x-quant-receipt-digest") != receipt_digest
        ):
            raise ReceiptProductTransportError("byte identity headers do not match")
        with destination.open("xb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ReceiptProductTransportError("receipt product bytes exceed budget")
                handle.write(chunk)
    if written < 1:
        raise ReceiptProductTransportError("receipt product bytes were empty")
    return written
