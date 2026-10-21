#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Check manifest/scope-lock conformance against an optional directive contract."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

try:
    from directive_utils import (
        DirectiveError,
        compare_preapproved,
        directive_bound_line,
        ensure_hash_integrity,
        load_directive,
    )
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover
    from scripts.directive_utils import (
        DirectiveError,
        compare_preapproved,
        directive_bound_line,
        ensure_hash_integrity,
        load_directive,
    )
    from scripts.policy_utils import find_repo_root


REPO_ROOT = find_repo_root(__file__)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="agent-pipeline-codex 0.9.1")
    parser.add_argument("--run", required=True)
    parser.add_argument(
        "--bind",
        action="store_true",
        help="Append the directive-bound run.log line when no binding exists.",
    )
    args = parser.parse_args()

    try:
        ctx = load_directive(REPO_ROOT, args.run)
        if ctx is None:
            print("directive_conformance: NO_DIRECTIVE - use existing interactive manifest gate.")
            return 1
        ensure_hash_integrity(ctx)
        checks = [
            ("manifest", "manifest.yaml", "manifest"),
            ("scope-lock", "scope-lock.yaml", "scope_lock"),
        ]
        diffs: list[str] = []
        for label, artifact, key in checks:
            matched, diff = compare_preapproved(ctx, artifact, key)
            if not matched:
                diffs.append(f"--- {label} mismatch ---\n{diff}")

        if diffs:
            if ctx.bound_hash is not None:
                print(
                    "directive_conformance: CONTRACT_DIVERGED - directive was bound to this run "
                    "but manifest/scope-lock no longer match the preapproved contract. "
                    "STOP and require explicit operator acknowledgment."
                )
                print("".join(diffs))
                return 3
            print("directive_conformance: MISMATCH - interactive manifest gate required.")
            print("".join(diffs))
            return 1

        if ctx.bound_hash is None:
            if not args.bind:
                raise DirectiveError("directive is not bound in run.log yet")
            line = directive_bound_line(ctx, _timestamp())
            run_log = ctx.run_dir / "run.log"
            with run_log.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            print(f"directive_conformance: BOUND hash={ctx.current_hash}")

        print(
            "directive_conformance: AUTO_APPROVE manifest/scope-lock "
            f"hash={ctx.current_hash} author={ctx.author} authority={ctx.authority}"
        )
        return 0
    except DirectiveError as exc:
        print(f"directive_conformance: FALLBACK - {exc}")
        if "hash changed" in str(exc):
            return 2
        return 1


if __name__ == "__main__":
    sys.exit(main())
