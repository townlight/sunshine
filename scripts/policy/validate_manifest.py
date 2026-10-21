#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Validate a pipeline manifest before starting or resuming a run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from check_manifest_schema import _check, _read_manifest
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - source-tree test import
    from scripts.check_manifest_schema import _check, _read_manifest
    from scripts.policy_utils import find_repo_root


REPO_ROOT = find_repo_root(__file__)


def _manifest_path(run: str | None, manifest: str | None) -> Path:
    if manifest:
        return Path(manifest).expanduser().resolve()
    if run:
        return REPO_ROOT / ".agent-runs" / run / "manifest.yaml"
    raise ValueError("provide --run <run-id> or --manifest <path>")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", help="Pipeline run id under .agent-runs/.")
    parser.add_argument("--manifest", help="Direct path to a manifest.yaml file.")
    args = parser.parse_args()

    try:
        path = _manifest_path(args.run, args.manifest)
    except ValueError as exc:
        print(f"validate-manifest: FAIL - {exc}", file=sys.stderr)
        return 2

    fields = _read_manifest(path)
    violations = _check(fields)
    if violations:
        print("validate-manifest: FAIL")
        print(f"  manifest: {path}")
        print("  fix: edit manifest.yaml, address each violation, then rerun validate-manifest.")
        print("  violations:")
        for violation in violations:
            print(f"    - {violation}")
        return 1

    print(f"validate-manifest: PASS - {path} satisfies the v0.5 schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

