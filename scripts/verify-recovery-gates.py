#!/usr/bin/env python3
"""Release-truth gates added after the 2026-05-07 external audit."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "docs/release-recovery-status.md",
    "docs/audits/civicrecords-ai-audit-full-2026-05-07.md",
    "frontend/playwright.config.ts",
    "frontend/e2e/civicrecords-user-flows.spec.ts",
    "scripts/verify-secret-scan.py",
    "scripts/verify-runtime-install.py",
    "scripts/check_starter_set_integration.py",
    "docs/ops/starter-set-integration.md",
]

OVERCLAIM_PATTERNS = [
    re.compile(r"\bproduct-ready\b", re.IGNORECASE),
    re.compile(r"\bproduction-ready\b", re.IGNORECASE),
    re.compile(r"\bsubstantially complete\b", re.IGNORECASE),
    re.compile(r"\bwell beyond a simple MVP\b", re.IGNORECASE),
]

CLAIM_SURFACES = [
    "README.md",
    "README.txt",
    "USER-MANUAL.md",
    "USER-MANUAL.txt",
    "docs/index.html",
    "docs/UNIFIED-SPEC.md",
]


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def tracked_files() -> set[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT, text=False)
    return {p.decode("utf-8") for p in output.split(b"\0") if p}


def read_text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    failures: list[str] = []
    tracked = tracked_files()

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            fail(f"missing required recovery artifact: {rel}", failures)

    for rel in CLAIM_SURFACES:
        path = ROOT / rel
        if not path.is_file():
            fail(f"missing claim surface: {rel}", failures)
            continue
        text = read_text(rel)
        lower = text.lower()
        has_do_not_promote_warning = (
            "do-not-promote" in lower
            or "must not be promoted" in lower
            or "do not republish or promote" in lower
        )
        has_legacy_warning = (
            "v1.4.10" in lower
            and ("provisional" in lower or "pre-gate" in lower)
            and has_do_not_promote_warning
        )
        has_current_recovery_label = (
            ("v1.5.0" in lower and "civiccore v1.0.1" in lower)
            or ("v1.6.0" in lower and "qa-002" in lower)
            or ("v1.7.3" in lower and "release-asset convention" in lower)
            or ("v1.7.2" in lower and "civiccore v1.2.0" in lower)
            or ("v1.7.1" in lower and "civiccore v1.2.0" in lower)
        )
        has_beta_label = (
            "Townlight Beta 1" in text
            and "1.8.0.dev1" in text
            and "AGPL-3.0-only" in text
            and (
                "98bcdef11ebdf5c767f620c904ff49f85115fde3b5c23f62703b111e645aaf86" in text
                or (rel == "docs/index.html" and 'href="./versions.html"' in text)
            )
        )
        if not (has_beta_label or (has_legacy_warning and has_current_recovery_label)):
            fail(
                f"{rel}: missing exact Beta 1 identity or historical recovery warning/label",
                failures,
            )
        for pattern in OVERCLAIM_PATTERNS:
            if pattern.search(text):
                fail(f"{rel}: blocked public overclaim pattern {pattern.pattern}", failures)

    # Keep the historical prohibition explicit without repeating obsolete
    # installation instructions in every current staff manual and landing page.
    recovery = read_text("docs/release-recovery-status.md").lower()
    if not all(token in recovery for token in ("v1.4.10", "provisional", "do-not-promote")):
        fail("historical v1.4.10 prohibition missing from recovery status", failures)

    package_json = read_text("frontend/package.json")
    if '"test:e2e"' not in package_json:
        fail("frontend/package.json: missing test:e2e script", failures)
    if '"node": ">=20"' not in package_json:
        fail("frontend/package.json: missing explicit Node >=20 engine", failures)

    verify_release = read_text("scripts/verify-release.sh")
    for token in [
        "verify-recovery-gates.py",
        "verify-secret-scan.py",
        "npm audit --audit-level=moderate",
        "npm run test:e2e",
        "verify-runtime-install.py",
    ]:
        if token not in verify_release:
            fail(f"scripts/verify-release.sh: missing gate command containing {token}", failures)

    if ".env" in tracked:
        fail(".env is tracked; remove runtime secrets from git", failures)

    if failures:
        print("RECOVERY-GATES: FAILED")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("RECOVERY-GATES: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
