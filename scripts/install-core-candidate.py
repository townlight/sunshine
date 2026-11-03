"""Build/install the exact renamed Core dependency without a package-index release.

Requires the standard Python build tool. A local source checkout must be clean
and at the exact recorded commit. Otherwise fetch that commit, never a branch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def validate_source(source, pin):
    commit = pin['commit']
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Core dependency requires a full source commit')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if actual != commit:
        raise ValueError(f'Core source commit mismatch: expected {commit}, found {actual}')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source).strip():
        raise ValueError('Core source has modified tracked files')
    project = tomllib.loads((source / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    if (project['name'], project['version']) != (pin['distribution'], pin['version']):
        raise ValueError('Core package metadata differs from the dependency pin')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-source', type=Path, help='Already checked-out exact local Core source')
    parser.add_argument('--wheel-output', type=Path, help='Keep the built Core wheel for the clean-install proof')
    args = parser.parse_args()
    pin = json.loads((ROOT / 'config/core-source.json').read_text(encoding='utf-8'))
    if pin['repository'] != 'https://github.com/townlight/core.git':
        raise ValueError('Unexpected Core source repository')
    if not re.fullmatch('[0-9a-f]{40}', pin['commit']):
        raise ValueError('Core dependency requires a full source commit')
    project = tomllib.loads((ROOT / 'backend/pyproject.toml').read_text(encoding='utf-8'))['project']
    if f"{pin['distribution']}=={pin['version']}" not in project['dependencies']:
        raise ValueError('Records dependency differs from the Core source pin')
    with tempfile.TemporaryDirectory(prefix='tl-core-') as temporary:
        temporary = Path(temporary)
        source = args.core_source.resolve() if args.core_source else temporary / 'core'
        if not args.core_source:
            subprocess.run(['git', 'init', str(source)], check=True)
            subprocess.run(['git', 'remote', 'add', 'origin', pin['repository']], cwd=source, check=True)
            subprocess.run(['git', 'fetch', '--depth', '1', 'origin', pin['commit']], cwd=source, check=True)
            subprocess.run(['git', 'checkout', '--detach', 'FETCH_HEAD'], cwd=source, check=True)
        validate_source(source, pin)
        output = temporary / 'wheels'
        subprocess.run([sys.executable, '-m', 'build', '--wheel', '--outdir', str(output), str(source)], check=True)
        wheel = output / f"townlight_core-{pin['version']}-py3-none-any.whl"
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if args.wheel_output:
            args.wheel_output.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(wheel, args.wheel_output.resolve() / wheel.name)
        subprocess.run([sys.executable, '-m', 'pip', 'install', str(wheel)], check=True)
        # A same-version editable/older local candidate must not survive pip's
        # already-satisfied optimization. Resolve dependencies normally above,
        # then replace only Core with these exact built bytes.
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--force-reinstall',
                        '--no-deps', str(wheel)], check=True)
        print(json.dumps({'source_commit': pin['commit'], 'distribution': pin['distribution'],
                          'version': pin['version'], 'wheel': wheel.name, 'sha256': digest}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
