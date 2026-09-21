"""Reject common secrets and local runtime files from the public repository."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")
if GIT is None:
    for candidate in (
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path("/usr/bin/git"),
    ):
        if candidate.is_file():
            GIT = str(candidate)
            break

FORBIDDEN_PATHS = (
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)server\.env$"),
    re.compile(r"\.(pem|key|pfx|p12|log|db|sqlite|sqlite3)$"),
    re.compile(r"(^|/)(qr|wechat_qr)\.png$"),
    re.compile(r"^wechat-bot/(bot\.mjs|wcf/)"),
    re.compile(r"(^|/)(bot-config|instance_binding|resolved_account)\.json$"),
)

PRIVATE_MARKERS = (
    "tianfujia.top",
    "47.94.20.240",
)

TEXT_SUFFIXES = {
    ".bat",
    ".cjs",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".txt",
    ".yaml",
    ".yml",
}


def tracked_files() -> list[Path]:
    if GIT is None:
        raise SystemExit("git executable not found")
    result = subprocess.run(
        [GIT, "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        Path(raw.decode("utf-8", "surrogateescape"))
        for raw in result.stdout.split(b"\0")
        if raw
    ]


def main() -> int:
    failures: list[str] = []
    files = tracked_files()

    for path in files:
        name = path.as_posix()
        if any(pattern.search(name) for pattern in FORBIDDEN_PATHS):
            failures.append(f"forbidden runtime file is tracked: {name}")

    for path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != "Dockerfile":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for marker in PRIVATE_MARKERS:
            if marker in content:
                failures.append(f"private deployment marker {marker!r} in {path.as_posix()}")

    if failures:
        print("Public release check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"Public release check passed ({len(files)} tracked files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
