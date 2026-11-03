from __future__ import annotations

import os
import re
from pathlib import Path


def _repo_root() -> Path:
    env_root = os.environ.get("TOWNLIGHT_RECORDS_REPO_ROOT")
    if env_root:
        root = Path(env_root)
        if (root / "docker-compose.yml").is_file():
            return root

    for candidate in Path(__file__).resolve().parents:
        if (candidate / "docker-compose.yml").is_file():
            return candidate
    raise AssertionError("Could not locate repository root with docker-compose.yml")


REPO_ROOT = _repo_root()

# B2 literal directive grep: container env must contain no name matching
# this regex. Mirror the same shape in .env.example so that env_file: .env
# cannot reintroduce a matching name into the container env.
_B2_DIRECTIVE_PATTERN = re.compile(
    r"^[A-Z]*(JWT_SECRET|FIRST_ADMIN_PASSWORD)[A-Z_]*=",
    re.MULTILINE,
)


def test_env_example_declares_no_b2_secret_env_names():
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    matches = _B2_DIRECTIVE_PATTERN.findall(env_example)
    assert not matches, (
        ".env.example must not declare any JWT_SECRET*, FIRST_ADMIN_PASSWORD*, "
        "or *_FILE pointer env name (B2 literal directive grep "
        "'JWT_SECRET|FIRST_ADMIN_PASSWORD' must return zero matches against "
        "the container env that env_file produces). "
        f"Found: {matches}"
    )


def test_compose_mounts_secrets_via_docker_secret_block():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "secrets:" in compose
    assert "file: ${TOWNLIGHT_RECORDS_SECRET_DIR:-./data/secrets}/jwt_secret" in compose
    assert (
        "file: ${TOWNLIGHT_RECORDS_SECRET_DIR:-./data/secrets}/first_admin_password"
        in compose
    )


def test_release_gate_uses_literal_directive_grep():
    verifier = (REPO_ROOT / "scripts" / "verify-release.sh").read_text(encoding="utf-8")
    # Must use the literal directive predicate (unanchored, no `=` suffix).
    assert "grep -E 'JWT_SECRET|FIRST_ADMIN_PASSWORD'" in verifier, (
        "verify-release.sh must run the literal B2 directive grep"
    )
    # Must NOT use the anchored predicate that previously hid _FILE names.
    assert "^(JWT_SECRET|FIRST_ADMIN_PASSWORD)=" not in verifier, (
        "verify-release.sh must not use the anchored predicate; it hides "
        "JWT_SECRET_FILE / FIRST_ADMIN_PASSWORD_FILE env names that satisfy "
        "the literal B2 acceptance grep with non-zero matches"
    )
    assert "api container env hides JWT_SECRET and FIRST_ADMIN_PASSWORD" in verifier
