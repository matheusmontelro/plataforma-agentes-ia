#!/usr/bin/env python3
"""Repository security gate for CI and local preflight."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"sk_live_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"whsec_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|PRIVATE) KEY-----"),
    re.compile(r"postgres(?:ql)?://[^:\s'\"]+:[^@\s'\"]+@"),
]

BANNED_PATH_PATTERNS = [
    re.compile(r"(^|/)\._[^/]+$"),
    re.compile(r"(^|/)debug_[^/]+$"),
    re.compile(r"(^|/)debug_[^/]+\.py$"),
    re.compile(r"(^|/)check_[^/]+\.py$"),
    re.compile(r"(^|/)verify_[^/]+\.py$"),
    re.compile(r"(^|/)inspect_[^/]+\.py$"),
    re.compile(r"(^|/)reset_password\.py$"),
    re.compile(r"(^|/)update_.*creds.*\.py$"),
    re.compile(r"(^|/)trigger_task\.py$"),
    re.compile(r"(^|/)sdk_.*\.txt$"),
    re.compile(r"(^|/)estrutura.*\.txt$"),
    re.compile(r"(^|/)logos/company_.*"),
    re.compile(r"(^|/)static/logos/company_.*"),
    re.compile(r"^backend/prompt/machine_learning/"),
    re.compile(r"^backend/integrations/waha_sdk/OpenAPI\.json$"),
    re.compile(r"(^|/).*\.(?:bak|backup|tmp)$"),
    re.compile(r"(^|/).*backup.*"),
    re.compile(r"(^|/)frontend/public/.*\.(?:csv|html)$"),
]

BANNED_FRONTEND_STORAGE_PATTERNS = [
    re.compile(r"localStorage\.getItem\(['\"](?:token|access_token|refresh_token|api_key)['\"]\)"),
    re.compile(r"sessionStorage\.getItem\(['\"](?:token|access_token|refresh_token|api_key)['\"]\)"),
    re.compile(r"localStorage\.setItem\(['\"](?:token|access_token|refresh_token|api_key)['\"]"),
    re.compile(r"sessionStorage\.setItem\(['\"](?:token|access_token|refresh_token|api_key)['\"]"),
]

TEXT_SUFFIXES = {
    ".env",
    ".example",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".conf",
    ".service",
    ".html",
    ".css",
    ".csv",
}


def git_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return [line for line in output.splitlines() if line]


def is_text_candidate(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or path.name.startswith(".env")


def main() -> int:
    failures: list[str] = []

    for rel in git_files():
        normalized = rel.replace("\\", "/")
        path = ROOT / rel

        for pattern in BANNED_PATH_PATTERNS:
            if pattern.search(normalized):
                failures.append(f"banned path still tracked: {rel}")
                break

        if normalized.startswith("frontend/src/"):
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern in BANNED_FRONTEND_STORAGE_PATTERNS:
                if pattern.search(content):
                    failures.append(f"browser-readable auth storage pattern in {rel}")
                    break

        if not is_text_candidate(path):
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                failures.append(f"secret-like value in {rel}")
                break

    if failures:
        print("Security check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Security check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
