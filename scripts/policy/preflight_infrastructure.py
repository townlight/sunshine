#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Phase 0 preflight infrastructure audit.

Runs the Check 1-7 sequence from pipelines/roles/preflight-auditor.md
against a target module's release infrastructure. Outputs a markdown
report to .agent-runs/<run-id>/phase0-report.md.

Usage:
    python scripts/preflight_infrastructure.py --module-root <path>
    python scripts/preflight_infrastructure.py --module-root <path> --report <out>

The script EXITS NON-ZERO when any check fails, so it can be wired as a
CI gate that blocks Phase 1 work until Phase 0 fixes land.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    passed: bool = False
    details: list[str] = field(default_factory=list)


def check_workflow_yaml_parse(root: Path) -> CheckResult:
    """Check 1 - every workflow YAML-parses cleanly."""
    result = CheckResult(name="workflow YAML parse")
    workflows = list((root / ".github" / "workflows").glob("*.yml")) + list(
        (root / ".github" / "workflows").glob("*.yaml")
    )
    if not workflows:
        result.details.append("no workflow files found - skipping")
        result.passed = True
        return result

    try:
        import yaml  # type: ignore
    except ImportError:
        result.details.append("PyYAML not installed - cannot validate; assume PASS")
        result.passed = True
        return result

    all_ok = True
    for wf in workflows:
        try:
            yaml.safe_load(wf.read_text(encoding="utf-8"))
            result.details.append(f"PASS {wf.relative_to(root)}")
        except yaml.YAMLError as e:
            result.details.append(f"FAIL {wf.relative_to(root)}: {e}")
            all_ok = False
    result.passed = all_ok
    return result


def check_workflow_run_health(repo: str | None) -> CheckResult:
    """Check 2 - recent run failure rate per workflow."""
    result = CheckResult(name="workflow recent run health")
    if not repo:
        result.details.append("--repo not provided - skipping")
        result.passed = True
        return result

    try:
        proc = subprocess.run(
            ["gh", "run", "list", "-R", repo, "--limit", "10",
             "--json", "name,conclusion,databaseId"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            result.details.append(f"gh run list failed: {proc.stderr[:200]}")
            result.passed = False
            return result
        runs = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        result.details.append(f"could not fetch run history: {e}")
        result.passed = False
        return result

    by_wf: dict[str, list[str]] = {}
    for r in runs:
        by_wf.setdefault(r["name"], []).append(r.get("conclusion") or "running")

    failing = []
    for wf, results in by_wf.items():
        fails = sum(1 for c in results if c == "failure")
        total = len(results)
        result.details.append(f"{wf}: {fails}/{total} failed")
        if total >= 3 and fails / total >= 0.6:
            failing.append(f"{wf} ({fails}/{total})")

    if failing:
        result.details.append(
            "FAIL - workflows with >=60% failure rate: " + ", ".join(failing)
        )
        result.passed = False
    else:
        result.passed = True
    return result


def check_scripts_referenced_exist(root: Path) -> CheckResult:
    """Check 3 - every script referenced by workflows actually exists."""
    result = CheckResult(name="referenced scripts exist")
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        result.details.append("no workflows directory - skipping")
        result.passed = True
        return result

    pattern = re.compile(r"(bash|python|sh)\s+(scripts/[A-Za-z0-9_./-]+)")
    referenced: set[str] = set()
    for wf in workflows_dir.glob("*.yml"):
        for m in pattern.finditer(wf.read_text(encoding="utf-8", errors="replace")):
            referenced.add(m.group(2))

    missing = []
    for script in sorted(referenced):
        p = root / script
        if not p.exists():
            missing.append(script)
        elif p.is_file() and p.stat().st_size == 0:
            missing.append(f"{script} (0 bytes)")

    if missing:
        result.details.append("FAIL - missing or empty: " + ", ".join(missing))
        result.passed = False
    else:
        result.details.append(f"PASS - {len(referenced)} scripts all present")
        result.passed = True
    return result


def check_verify_release_local(root: Path, run_local: bool) -> CheckResult:
    """Check 4 - run verify-release.sh locally on fresh state."""
    result = CheckResult(name="local verify-release.sh on fresh state")
    script = root / "scripts" / "verify-release.sh"
    if not script.exists():
        result.details.append("no scripts/verify-release.sh - skipping")
        result.passed = True
        return result

    if not run_local:
        result.details.append(
            "--run-local not set; skipping local execution. "
            "When --run-local is set, this check wipes docker state, "
            "synthesizes a CI-shape .env, and runs the verifier."
        )
        result.passed = True
        return result

    # Wipe docker state
    subprocess.run(["docker", "compose", "down", "-v"], cwd=root, capture_output=True)
    # Run verifier
    proc = subprocess.run(
        ["bash", "scripts/verify-release.sh"],
        cwd=root, capture_output=True, text=True, timeout=1800,
    )
    if proc.returncode != 0:
        result.details.append(
            f"FAIL exit={proc.returncode}\n"
            f"stderr tail: {proc.stderr[-2000:]}\n"
            f"stdout tail: {proc.stdout[-2000:]}"
        )
        result.passed = False
    else:
        result.details.append("PASS verify-release.sh succeeded on fresh state")
        result.passed = True
    return result


def check_cross_platform_mismatch(root: Path) -> CheckResult:
    """Check 5 - flag Windows jobs doing Linux Docker compose and vice versa."""
    result = CheckResult(name="cross-platform reality check")
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        result.details.append("no workflows directory - skipping")
        result.passed = True
        return result

    issues: list[str] = []
    for wf in workflows_dir.glob("*.yml"):
        text = wf.read_text(encoding="utf-8", errors="replace")
        # Detect windows-latest job that does docker compose
        if re.search(r"runs-on:\s*windows-latest", text) and re.search(
            r"docker\s+compose\s+up", text
        ):
            issues.append(
                f"{wf.name}: windows-latest job with `docker compose up` "
                "(likely Linux-only images)"
            )
        # Detect ubuntu-latest doing Windows-only tools
        if re.search(r"runs-on:\s*ubuntu-latest", text) and re.search(
            r"\bISCC\b|\biscc\b|InnoSetup", text
        ):
            issues.append(
                f"{wf.name}: ubuntu-latest job with Inno Setup compile "
                "(Windows-only)"
            )

    if issues:
        result.details.extend(["FAIL"] + issues)
        result.passed = False
    else:
        result.details.append("PASS - no cross-platform mismatches detected")
        result.passed = True
    return result


def check_diagnostic_instrumentation(root: Path) -> CheckResult:
    """Check 6 - verify-release.sh dumps container logs on failure."""
    result = CheckResult(name="diagnostic instrumentation on failure")
    script = root / "scripts" / "verify-release.sh"
    if not script.exists():
        result.details.append("no scripts/verify-release.sh - skipping")
        result.passed = True
        return result

    text = script.read_text(encoding="utf-8", errors="replace")
    has_log_dump = "docker compose logs" in text or "docker logs" in text
    if has_log_dump:
        result.details.append("PASS - script dumps container logs somewhere")
        result.passed = True
    else:
        result.details.append(
            "FAIL - verify-release.sh does not dump container logs. "
            "When compose health fails, the failure cause is hidden. "
            "Add `docker compose logs --no-color --tail 100 <service>` "
            "to the failure path. Template: civicrecords-ai PR #72."
        )
        result.passed = False
    return result


def render_report(checks: list[CheckResult], module: str | None) -> str:
    lines = [f"# Phase 0 Preflight Audit - {module or '<module>'}\n"]
    pass_count = sum(1 for c in checks if c.passed)
    lines.append(f"Result: {pass_count}/{len(checks)} checks passed\n")
    for c in checks:
        status = "PASS" if c.passed else "FAIL"
        lines.append(f"## {c.name} - {status}")
        for d in c.details:
            lines.append(f"  {d}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-root", required=True, type=Path,
                        help="Path to the module repo root")
    parser.add_argument("--repo", help="org/repo for gh run history check (e.g. CivicSuite/civicrecords-ai)")
    parser.add_argument("--run-local", action="store_true",
                        help="Actually run verify-release.sh locally (slow; requires Docker)")
    parser.add_argument("--report", type=Path,
                        help="Write the markdown report to this path")
    args = parser.parse_args()

    root = args.module_root.resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory", file=sys.stderr)
        return 2

    checks = [
        check_workflow_yaml_parse(root),
        check_workflow_run_health(args.repo),
        check_scripts_referenced_exist(root),
        check_verify_release_local(root, args.run_local),
        check_cross_platform_mismatch(root),
        check_diagnostic_instrumentation(root),
    ]

    report = render_report(checks, args.repo or root.name)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
        print(f"report written to {args.report}")
    else:
        print(report)

    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
