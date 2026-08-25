"""Structural checks for the singular current production runbook."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "docs" / "operations" / "current_production_runbook.md"
HISTORICAL = (
    ROOT / "docs" / "phase61_production_runbook.md",
    ROOT / "docs" / "phase62_production_runbook.md",
)
MANIFEST = ROOT / "specs" / "cloudflare" / "active_worker_bindings.json"
MIGRATION_MANIFEST = ROOT / "specs" / "cloudflare" / "d1_migration_manifest.json"
OPS_TOOLS = ROOT / "platform" / "workers" / "quant-ops-mcp" / "src" / "domain.js"


def _ops_tool_count() -> int:
    text = OPS_TOOLS.read_text(encoding="utf-8")
    start = text.index("export const OPS_TOOLS")
    block = text[start : text.index("]);", start)]
    return len(re.findall(r'tool\("', block))


def test_current_runbook_is_marked_and_links_machine_readable_authorities() -> None:
    text = CURRENT.read_text(encoding="utf-8")
    assert "CURRENT_PRODUCTION_RUNBOOK" in text
    assert "specs/cloudflare/d1_migration_manifest.json" in text
    assert "specs/cloudflare/active_worker_bindings.json" in text
    assert "scripts/cloudflare_d1_migration_manifest.py" in text
    assert "scripts/cloudflare_binding_manifest.py" in text
    assert "scripts/publish_ops_projection.py" in text
    assert "platform/workers/quant-ops-mcp/src/domain.js" in text
    assert "OPS_TOOLS" in text
    assert f"**{_ops_tool_count()}**" in text
    assert MIGRATION_MANIFEST.is_file()
    assert MANIFEST.is_file()


def test_current_runbook_commands_follow_canonical_owners() -> None:
    text = CURRENT.read_text(encoding="utf-8")
    assert "npx wrangler d1 migrations apply quant-ingest --remote" in text
    assert "npx wrangler d1 migrations apply quant-ops-projection --remote" in text
    assert "npx wrangler d1 migrations apply quant-ops-quota --remote" in text
    assert "npx wrangler d1 execute quant-ingest --remote" not in text
    assert "for migration in migrations/000" not in text
    assert "preview_urls = true" not in text
    assert "exactly 16" not in text.lower()
    assert "shared Mass credential" not in text or "not a shared Mass credential" in text
    bindings = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for environments in bindings["workers"].values():
        for surface in environments.values():
            assert surface["preview_urls"] is False


def test_historical_runbooks_are_non_executable() -> None:
    for path in HISTORICAL:
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:12])
        assert "HISTORICAL / NON-EXECUTABLE" in head
        assert "operations/current_production_runbook.md" in head
