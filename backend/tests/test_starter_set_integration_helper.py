from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("TOWNLIGHT_RECORDS_REPO_ROOT", Path(__file__).resolve().parents[2]))


def _write_umbrella_fixture(root: Path) -> None:
    installer = root / "installer"
    dist = installer / "dist"
    docs = root / "docs" / "installer"
    dist.mkdir(parents=True)
    docs.mkdir(parents=True)
    (installer / "modules.json").write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "clerk-core",
                        "modules": ["townlight_core", "townlight_records", "townlight_meetings"],
                    }
                ],
                "modules": [
                    {"id": "townlight_core", "current_version": "1.3.0.dev2", "selectable": False},
                    {
                        "id": "townlight_records",
                        "current_version": "1.8.0.dev2",
                        "selectable": True,
                        "townlight_core_requirement": "1.3.0.dev2",
                        "dependencies": ["townlight_core"],
                    },
                    {
                        "id": "townlight_meetings",
                        "current_version": "1.0.5",
                        "selectable": True,
                        "dependencies": ["townlight_core"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (docs / "starter-set-release-contract.md").write_text(
        "\n".join(
            [
                "| Records | townlight-records | 1.8.0.dev2 |",
                "Townlight Meetings reports version 1.0.5 with Townlight Core 1.3.0.dev2",
                "Package workflow proof and source-only checks do not certify an installer.",
                "new empty database and fresh profile",
                "No in-place upgrade or import shim is supported.",
                "Meetings → Station → Records",
            ]
        ),
        encoding="utf-8",
    )
    (dist / "Townlight-clerk-core-linux-0.1.0.tar.gz").write_text("linux\n", encoding="utf-8")
    (dist / "Townlight-clerk-core-windows-0.1.0.zip").write_text("windows\n", encoding="utf-8")


def test_starter_set_integration_passes_with_umbrella_contract(tmp_path: Path) -> None:
    _write_umbrella_fixture(tmp_path)
    report = tmp_path / "starter-set.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_starter_set_integration.py",
            "--umbrella-root",
            str(tmp_path),
            "--require-archives",
            "--output",
            str(report),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "starter_set_ready=true" in result.stdout
    assert "release_evidence_ready=false" in result.stdout
    assert "[PASS] clerk-core profile order" in result.stdout
    assert "[PASS] Townlight Records module contract" in result.stdout
    assert "[PASS] Townlight Meetings pairing" in result.stdout
    assert "[PASS] starter-set release contract" in result.stdout
    assert "[PASS] starter-set archives" in result.stdout
    assert "STARTER-SET-INTEGRATION: SOURCE-READY" in result.stdout
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["release_evidence_ready"] is False
    assert payload["installed_acceptance_verified"] is False


def test_starter_set_integration_print_only_documents_contract() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_starter_set_integration.py", "--print-only"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Umbrella clerk-core profile installs Townlight Core" in result.stdout
    assert "package workflow proof" in result.stdout
    assert "STARTER-SET-INTEGRATION: PLAN" in result.stdout


def test_starter_set_integration_fails_when_manifest_is_missing(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_starter_set_integration.py",
            "--umbrella-root",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "[FAIL] umbrella checkout" in result.stdout
    assert "STARTER-SET-INTEGRATION: FAILED" in result.stdout
