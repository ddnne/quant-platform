from __future__ import annotations


import pytest

from scripts.d1_export_poll_descriptor import parse_export_complete_envelope


def test_parse_complete_envelope_uses_inner_signed_url() -> None:
    envelope = {
        "success": True,
        "result": {
            "at_bookmark": "bm-complete",
            "status": "complete",
            "success": True,
            "type": "export",
            "signed_url": "https://wrong.example/outer.sql",
            "result": {
                "filename": "export.sql",
                "signed_url": "https://acct.r2.cloudflarestorage.com/export.sql?X-Amz-Signature=secret",
            },
        },
    }
    parsed = parse_export_complete_envelope(envelope)
    assert parsed["at_bookmark"] == "bm-complete"
    assert parsed["download_host"] == "acct.r2.cloudflarestorage.com"
    assert parsed["signed_url"].startswith("https://acct.r2.cloudflarestorage.com/")


def test_parse_complete_envelope_rejects_outer_signed_url_only() -> None:
    envelope = {
        "success": True,
        "result": {
            "at_bookmark": "bm-complete",
            "status": "complete",
            "signed_url": "https://acct.r2.cloudflarestorage.com/export.sql",
        },
    }
    with pytest.raises(ValueError, match="signed_url missing"):
        parse_export_complete_envelope(envelope)
