#!/usr/bin/env python3
"""Fail-closed tracked-path and content secret scan.

Path matches are reported by relative path only. Content matches are reported
as path:line with a redacted placeholder. Matched secret values are never
printed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REDACTED = "<redacted>"
SAFE_ENV_EXAMPLE = re.compile(r"(?:^|/)\.env\.example$")
SECRET_JSON_NAME = re.compile(r"(secret|credential)", re.IGNORECASE)
CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN (OPENSSH |EC |RSA )?PRIVATE KEY-----"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-(proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".tgz",
    ".xz",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
    ".sqlite",
    ".bin",
}


def posix_path(value: str) -> str:
    return value.replace("\\", "/")


def is_forbidden_tracked_path(path: str) -> bool:
    relative = posix_path(path)
    name = relative.rsplit("/", 1)[-1]
    if SAFE_ENV_EXAMPLE.search(relative):
        return False
    if name.startswith(".env"):
        return True
    if name.startswith(".dev.vars"):
        return True
    lower = name.lower()
    if lower.endswith((".key", ".pem", ".p12", ".pfx", ".jks")):
        return True
    if lower.endswith(".json") and SECRET_JSON_NAME.search(name):
        return True
    return False


def forbidden_tracked_paths(paths: list[str]) -> list[str]:
    return sorted({posix_path(path) for path in paths if is_forbidden_tracked_path(path)})


def _git_ls_files() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [path.decode("utf-8") for path in listed.stdout.split(b"\0") if path]


def scan_content_hits(paths: list[str], *, root: Path = ROOT) -> list[str]:
    hits: list[str] = []
    for relative in sorted(posix_path(path) for path in paths):
        suffix = Path(relative).suffix.lower()
        if suffix in BINARY_SUFFIXES:
            continue
        if relative.endswith("uv.lock") or relative.endswith("package-lock.json"):
            continue
        file_path = root / relative
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in CONTENT_PATTERNS):
                hits.append(f"{relative}:{lineno}: {REDACTED}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    paths = _git_ls_files()
    forbidden = forbidden_tracked_paths(paths)
    if forbidden:
        print("tracked secret path must not be in git ls-files:", file=sys.stderr)
        for path in forbidden:
            print(path, file=sys.stderr)
        return 1
    hits = scan_content_hits(paths, root=args.root)
    if hits:
        print("tracked content matches a private-key or provider-token signature:", file=sys.stderr)
        for hit in hits:
            print(hit, file=sys.stderr)
        return 1
    print("secret/path scan: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
