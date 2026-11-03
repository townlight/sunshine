"""Current document renderer; original fixed template is preserved under docs/history."""
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    raise SystemExit(subprocess.call([sys.executable,
        str(Path(__file__).with_name('build_current_documents.py')), *['--documents', 'readme', 'manual'], *sys.argv[1:]]))
