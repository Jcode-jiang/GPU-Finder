#!/usr/bin/env python3
"""Fail CI if a real credential looks committed.

This is a guard, not a full secret scanner. It intentionally only flags
high-signal patterns (JWT, bearer tokens, private keys, long token values).
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

SKIP_DIRS = {".git", ".github", "build", "dist", "__pycache__", ".venv", "node_modules"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns", ".zip", ".pdf"}

PATTERNS = [
    ("JWT", re.compile(r"eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}")),
    ("encoded bearer", re.compile(r"Bearer%20[A-Za-z0-9._-]{20,}")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("long credential value", re.compile(
        r"(?i)(autodl_token|gpushare_token|matpool_token|access[_-]?key|secret[_-]?key)"
        r"\s*[:=]\s*['\"][A-Za-z0-9._%+/=-]{24,}['\"]"
    )),
]


def main() -> int:
    findings: list[tuple[str, int, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append((str(path.relative_to(ROOT)), line, name))

    if findings:
        print("Potential secrets found:")
        for path, line, name in findings:
            print(f"  {path}:{line}: {name}")
        print("\nRemove them before committing. See SECURITY.md.")
        return 1
    print("No obvious secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
