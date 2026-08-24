"""Guard scripts/verify_ci.sh as authoritative CI (no skips, no live deploy)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_ci.sh"
WORKERS_BUILDS_WRAPPER = ROOT / "scripts" / "workers_builds_verify_ci.sh"
WORKERS_BUILDS_DOC = ROOT / "docs" / "ci" / "workers_builds.md"

WORKERS = (
    "ingestion-jsda",
    "ingestion-premium",
    "ingestion-secrets",
    "quant-ops-mcp",
    "research-ai-gateway",
    "research-mass-eval",
    "ci-aggregate",
)

SKIP_FLAGS = (
    "VERIFY_NPM_CI",
    "VERIFY_NPM_TYPECHECK",
    "VERIFY_NPM_BUILD",
    "VERIFY_CREATE_VENV",
)


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _code_lines(src: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, line in enumerate(src.splitlines(), start=1):
        out.append((i, line.split("#", 1)[0]))
    return out


def _extract_bash_function(src: str, name: str) -> str:
    lines = src.splitlines(keepends=True)
    out: list[str] = []
    capturing = False
    depth = 0
    for line in lines:
        if not capturing:
            if line.lstrip().startswith(f"{name}()"):
                capturing = True
            else:
                continue
        code = line.split("#", 1)[0]
        depth += code.count("{") - code.count("}")
        out.append(line)
        if depth <= 0:
            break
    body = "".join(out).strip()
    assert body, f"function {name}() not found in {SCRIPT}"
    return body


def _helpers_script() -> str:
    src = _src()
    return "\n".join(
        (
            _extract_bash_function(src, "python_is_311_plus"),
            _extract_bash_function(src, "find_python_311_plus"),
        )
    )


def _pytest_python_first_env() -> dict[str, str]:
    """Run helper probes with pytest's already-validated interpreter first."""

    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(
        (str(Path(sys.executable).resolve().parent), env.get("PATH", ""))
    )
    return env


def test_verify_ci_script_exists_executable_and_covers_required_steps() -> None:
    assert SCRIPT.is_file(), SCRIPT
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"
    src = _src()
    assert "legacy-peer-deps" in src
    assert ".venv" in src
    assert "3.11" in src
    assert "sys.version_info" in src
    assert "import sqlite3" in src
    assert 'sqlite3.connect(":memory:")' in src
    assert 'db.execute("SELECT 1")' in src
    assert "do not silently use system python" in src
    assert "find_python_311_plus" in src
    assert "-m venv" in src
    assert "python3.11" in src
    assert "bootstrap .venv" in src
    assert "pip install -e" in src
    assert ".[dev]" in src
    assert "pytest tests/" in src
    assert "compile_catalog" in src
    assert "assert_catalog_ids_emit_frozen" in src
    assert "catalog_ids" in src
    assert "specs/evaluation_ir/golden.jsonl" in src
    assert "specs/evaluation_ir/schema.json" in src
    assert "evaluation_ir.py" in src
    assert "evaluation_ir.ts" in src
    assert "evaluation_ir_allowed_fields.generated.ts" in src
    assert "evaluation_ir_codec.generated.ts" in src
    assert "evaluation_ir_codec.generated.py" in src
    assert "evaluation_ir_types.generated.py" in src
    assert "assert_evaluation_ir_allowed_fields_ts_frozen()" in src
    assert "assert_evaluation_ir_codec_ts_frozen()" in src
    assert "assert_evaluation_ir_codec_py_frozen()" in src
    assert "assert_evaluation_ir_types_py_frozen()" in src
    assert "assert_evaluation_ir_encode_keys_match_schema()" in src
    assert "jsonschema" in src
    assert "jsonschema.validate" in src
    assert "decode_evaluation_ir" in src
    assert "encode_evaluation_ir" in src
    assert "load_evaluation_ir_schema" in src
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "jsonschema" in pyproject
    assert len(WORKERS) == 7
    assert "package-lock.json" in src
    assert "npm ci" in src
    assert "npm test" in src
    assert "npm run typecheck" in src
    assert "wrangler deploy --dry-run" in src
    assert "wrangler types --check" in src
    assert "wrangler types" in src
    assert "npm run types" in src
    assert "git ls-files" in src
    assert ".env" in src
    assert ".pem" in src
    assert "commit generated types" in src
    for name in WORKERS:
        assert name in src, f"{SCRIPT} must cover worker {name}"
    for flag in SKIP_FLAGS:
        assert flag not in src, f"{SCRIPT} must not define skip flag {flag}"


def test_all_workers_package_json_has_types_script() -> None:
    for name in WORKERS:
        pkg = ROOT / "platform" / "workers" / name / "package.json"
        assert pkg.is_file(), pkg
        data = json.loads(pkg.read_text(encoding="utf-8"))
        types = str((data.get("scripts") or {}).get("types") or "")
        assert types, f"{pkg} must define scripts.types (verify_ci runs wrangler types --check)"
        assert "wrangler types" in types, f"{pkg} scripts.types must invoke wrangler types"
        assert "--include-runtime" in types, (
            f"{pkg} scripts.types must pin --include-runtime "
            "(verify_ci runs npm run types -- --check)"
        )


def test_verify_ci_bans_legacy_peer_deps_skips_and_live_deploy() -> None:
    src = _src()
    for i, code in _code_lines(src):
        assert "--legacy-peer-deps" not in code, (
            f"{SCRIPT}:{i} must not pass --legacy-peer-deps"
        )
        assert "VERIFY_NPM" not in code, (
            f"{SCRIPT}:{i} must not use VERIFY_* skip flags"
        )
        if "node_modules" in code:
            assert "skip" not in code.lower(), (
                f"{SCRIPT}:{i} must not skip missing node_modules"
            )
        if "wrangler deploy" in code:
            assert "--dry-run" in code, (
                f"{SCRIPT}:{i} must not live wrangler deploy"
            )
        if "python3" in code or "python3." in code:
            # Host python3.11 / python3>=3.11 may be located via command -v
            # only to create .venv. Pytest still runs under .venv/bin/python.
            stripped = code.strip()
            if stripped and not stripped.startswith("echo "):
                assert ".venv" in src
                if "command -v" in code and "npm" not in code:
                    assert "python3.11" in src
                    assert "-m venv" in src
                    assert "find_python_311_plus" in src


def test_verify_ci_evaluation_ir_invokes_schema_and_codec_not_only_presence() -> None:
    src = _src()
    start = src.index("Evaluation IR")
    end = src.index("npm not found")
    block = src[start:end]
    assert "$py" in block
    assert "jsonschema.validate" in block
    assert "Draft7Validator" in block
    assert "decode_evaluation_ir" in block
    assert "encode_evaluation_ir" in block
    assert "load_evaluation_ir_schema" in block
    assert "specs/evaluation_ir/schema.json" in block
    assert "specs/evaluation_ir/golden.jsonl" in block
    assert "evaluation_ir.ts" in block
    assert "evaluation_ir_allowed_fields.generated.ts" in block
    assert "evaluation_ir_codec.generated.ts" in block
    assert "evaluation_ir_codec.generated.py" in block
    assert "evaluation_ir_types.generated.py" in block
    assert "assert_evaluation_ir_allowed_fields_ts_frozen()" in block
    assert "assert_evaluation_ir_codec_ts_frozen()" in block
    assert "assert_evaluation_ir_codec_py_frozen()" in block
    assert "assert_evaluation_ir_types_py_frozen()" in block
    assert "assert_evaluation_ir_encode_keys_match_schema()" in block


def test_verify_ci_syntax_and_bootstrap_helpers_execute() -> None:
    syntax = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr
    helpers = _helpers_script()
    probe = subprocess.run(
        [
            "bash",
            "-c",
            helpers
            + """
set -euo pipefail
found="$(find_python_311_plus)"
test -n "$found"
python_is_311_plus "$found"
"$found" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
""",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=_pytest_python_first_env(),
        check=False,
    )
    assert probe.returncode == 0, probe.stderr + probe.stdout


def test_verify_ci_bootstrap_creates_venv_when_missing(tmp_path: Path) -> None:
    helpers = _helpers_script()
    script = f"""
set -euo pipefail
{helpers}
ROOT="{tmp_path}"
venv_py="$ROOT/.venv/bin/python"
test ! -x "$venv_py"
host_py="$(find_python_311_plus)"
"$host_py" -m venv "$ROOT/.venv"
test -x "$venv_py"
python_is_311_plus "$venv_py"
"""
    created = subprocess.run(
        ["bash", "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=_pytest_python_first_env(),
        check=False,
    )
    assert created.returncode == 0, created.stderr + created.stdout
    venv_py = tmp_path / ".venv" / "bin" / "python"
    assert venv_py.is_file() or venv_py.is_symlink()


def test_verify_ci_find_python_skips_system_39(tmp_path: Path) -> None:
    fake_py = tmp_path / "python3"
    fake_py.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    fake_py.chmod(fake_py.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(tmp_path), "/bin", "/usr/bin"))
    skipped = subprocess.run(
        [
            "bash",
            "-c",
            _helpers_script()
            + """
set -euo pipefail
if find_python_311_plus; then
  echo "selected a host python from a 3.9-only PATH" >&2
  exit 1
fi
exit 0
""",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert skipped.returncode == 0, skipped.stderr + skipped.stdout


def test_verify_ci_find_python_rejects_version_only_runtime_without_sqlite(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "python3.11"
    fake.write_text(
        "#!/bin/bash\n"
        "payload=$(/bin/cat)\n"
        "if [[ \"$payload\" == *sqlite3* ]]; then exit 1; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "python3").symlink_to(fake)
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)
    rejected = subprocess.run(
        [
            "/bin/bash",
            "-c",
            _helpers_script()
            + """
set -euo pipefail
if find_python_311_plus; then
  echo "accepted a version-only Python without sqlite3" >&2
  exit 1
fi
""",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert rejected.returncode == 0, rejected.stderr + rejected.stdout


def test_verify_ci_existing_venv_below_311_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "python"
    fake.write_text(
        "#!/bin/bash\n"
        'if [[ "${1:-}" == "-V" ]]; then echo "Python 3.9.18"; exit 0; fi\n'
        "exit 1\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    rejected = subprocess.run(
        [
            "bash",
            "-c",
            _extract_bash_function(_src(), "python_is_311_plus")
            + f"""
set -euo pipefail
venv_py="{fake}"
if python_is_311_plus "$venv_py"; then
  echo "accepted Python <3.11 venv" >&2
  exit 1
fi
exit 0
""",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 0, rejected.stderr + rejected.stdout


def test_no_github_actions_workflows() -> None:
    gha = ROOT / ".github" / "workflows"
    assert not gha.exists(), (
        f"{gha} must stay absent; CI is Cloudflare Workers Builds, not GitHub Actions"
    )
    listed = subprocess.run(
        ["git", "ls-files", ".github/workflows"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert listed.stdout.strip() == "", listed.stdout


def test_workers_builds_wrapper_is_fail_closed_and_hands_off_to_verify_ci() -> None:
    assert WORKERS_BUILDS_WRAPPER.is_file()
    assert os.access(WORKERS_BUILDS_WRAPPER, os.X_OK)
    src = WORKERS_BUILDS_WRAPPER.read_text(encoding="utf-8")
    assert '"${WORKERS_CI:-}" == "1"' in src
    assert '"${SKIP_DEPENDENCY_INSTALL:-}" == "1"' in src
    assert '"${ID:-}" == "ubuntu"' in src
    assert '"${VERSION_ID:-}" == "24.04"' in src
    assert 'system_py="/usr/bin/python3"' in src
    assert "virtualenv==21.7.4" in src
    assert "python_has_ci_runtime" in src
    assert "import sqlite3" in src
    assert 'db.execute("SELECT 1")' in src
    assert 'exec bash "$ROOT/scripts/verify_ci.sh"' in src
    assert "apt-get" not in src
    assert "asdf install" not in src
    assert "asdf uninstall" not in src
    syntax = subprocess.run(
        ["bash", "-n", str(WORKERS_BUILDS_WRAPPER)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr
    outside = subprocess.run(
        [str(WORKERS_BUILDS_WRAPPER)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "")},
        check=False,
    )
    assert outside.returncode != 0
    assert "WORKERS_CI=1 is required" in outside.stderr


def test_workers_builds_doc_names_native_check_and_deprecates_ci_aggregate() -> None:
    doc = WORKERS_BUILDS_DOC.read_text(encoding="utf-8")
    assert WORKERS_BUILDS_DOC.is_file()
    assert "scripts/verify_ci.sh" in doc
    assert ".github/workflows" in doc
    assert "legacy-peer-deps" in doc
    assert "Cloudflare Workers & Pages" in doc or "GitHub App" in doc
    assert "expected source" in doc.lower()
    assert "informational" in doc.lower()
    assert "deprecated" in doc.lower()
    assert "ci-aggregate" in doc
    assert "CI_LANE_TOKEN" in doc
    assert "HUMAN" in doc
    assert "not live" in doc.lower() or "not exist" in doc.lower() or "does not exist" in doc.lower()
    assert "do not delete" in doc.lower() or "abolish" in doc.lower()
    assert "repo-root" in doc.lower() or "repository root" in doc.lower()
