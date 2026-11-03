#!/usr/bin/env python3
"""Build and install Townlight Records in a fresh virtualenv, then prove app import."""

from __future__ import annotations

import os
import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=cwd, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-wheel', type=Path, required=True,
                        help='Exact new Core wheel built for this coordinated candidate')
    args = parser.parse_args()
    core_wheel = args.core_wheel.resolve(strict=True)
    if core_wheel.name != 'townlight_core-1.3.0.dev2-py3-none-any.whl':
        parser.error('Expected the coordinated townlight-core 1.3.0.dev2 wheel')
    print('Core wheel SHA256:', hashlib.sha256(core_wheel.read_bytes()).hexdigest())
    with tempfile.TemporaryDirectory(prefix="townlight_records-runtime-install-") as tmp:
        tmpdir = Path(tmp)
        build_venv = tmpdir / "build-venv"
        install_venv = tmpdir / "install-venv"
        venv.EnvBuilder(with_pip=True).create(build_venv)
        venv.EnvBuilder(with_pip=True).create(install_venv)

        build_python = build_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install_python = install_venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

        dist = BACKEND / "dist"
        if dist.exists():
            shutil.rmtree(dist)

        run([str(build_python), "-m", "pip", "install", "--upgrade", "pip", "build"], cwd=BACKEND)
        run([str(build_python), "-m", "build"], cwd=BACKEND)

        wheels = sorted(dist.glob("*.whl"))
        if not wheels:
            print("RUNTIME-INSTALL-PROOF: FAILED - no wheel produced")
            return 1

        run([str(install_python), "-m", "pip", "install", str(core_wheel)], cwd=tmpdir)
        run([str(install_python), "-m", "pip", "install", str(wheels[-1])], cwd=tmpdir)

        env = os.environ.copy()
        # Prove installed bytes, without sibling/source imports from the caller.
        env.pop('PYTHONPATH', None)
        env.update(
            {
                "DATABASE_URL": "postgresql+asyncpg://townlight_records:townlight_records@127.0.0.1:5432/townlight_records_runtime_proof",
                "JWT_SECRET": "runtimeproof" * 4,
                "FIRST_ADMIN_EMAIL": "admin@example.gov",
                "FIRST_ADMIN_PASSWORD": "RuntimeProofPassword2026",
                "ENCRYPTION_KEY": "7_NU0Qmw5LeUDWM1PNvFNQzOA-qI5sU-NWbYUkRSCIM=",
                "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
                "REDIS_URL": "redis://127.0.0.1:6379/0",
                "AUDIT_RETENTION_DAYS": "1095",
                "PORTAL_MODE": "private",
                "TESTING": "1",
            }
        )
        run(
            [
                str(install_python),
                "-c",
                "from townlight_records.main import app; "
                "from townlight_records.config import APP_VERSION; "
                "from importlib.metadata import version; "
                "assert APP_VERSION == version('townlight-records') == '1.8.0.dev2'; "
                "assert version('townlight-core') == '1.3.0.dev2'; "
                "from fastapi.testclient import TestClient; "
                "r=TestClient(app).get('/health'); "
                "assert r.status_code == 200, r.text; "
                "print('RUNTIME-INSTALL-PROOF: health', r.json())",
            ],
            cwd=tmpdir,
            env=env,
        )

    print("RUNTIME-INSTALL-PROOF: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
