"""Build the current Records manual from USER-MANUAL.md.

The original fixed-content technical-document generator is preserved in
docs/history/pre-naming-2026-11/generate_pdf.py. Historical output stays intact.
Current rendering uses the coordinated Townlight documentation builder.
"""
from pathlib import Path
import subprocess
import sys


def main() -> int:
    records = Path(__file__).resolve().parents[2]
    builder = records.parent / "townlight/scripts/build-candidate-docs.py"
    if not builder.is_file():
        print("Current manual rendering requires the pinned sibling townlight checkout. "
              "Use USER-MANUAL.md as the owning source.", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, str(builder), "--products", "records",
                            "--docx", "--pdf", "--sync-owner", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
