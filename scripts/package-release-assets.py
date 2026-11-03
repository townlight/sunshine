#!/usr/bin/env python3
"""Build Python distribution assets and checksum them for a tagged release."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: package-release-assets.py <output-dir>", file=sys.stderr)
        return 2

    output_dir = (ROOT / sys.argv[1]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import build  # noqa: F401
    except ModuleNotFoundError:
        _run([sys.executable, "-m", "pip", "install", "--upgrade", "build"])

    _run(
        [
            sys.executable,
            "-m",
            "build",
            str(BACKEND),
            "--wheel",
            "--sdist",
            "--outdir",
            str(output_dir),
        ]
    )

    assets = sorted(output_dir.glob("townlight_records-*-py3-none-any.whl"))
    assets.extend(sorted(output_dir.glob("townlight_records-*.tar.gz")))
    if len(assets) != 2:
        print("expected exactly one wheel and one sdist, found:", file=sys.stderr)
        for asset in assets:
            print(f"  {asset.name}", file=sys.stderr)
        return 1

    sums_path = output_dir / "SHA256SUMS.txt"
    sums_path.write_text(
        "".join(f"{_sha256(asset)}  {asset.name}\n" for asset in assets),
        encoding="utf-8",
    )
    print(sums_path.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
