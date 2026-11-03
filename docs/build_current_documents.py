"""Render current Records documents from owning Markdown, never dated templates.

Historical versioned specifications and reports are not output targets.
PDF conversion uses a private LibreOffice profile and fresh staging files.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {
    'readme': (ROOT / 'README.md', ROOT / 'README.docx'),
    'manual': (ROOT / 'USER-MANUAL.md', ROOT / 'USER-MANUAL.docx'),
    'spec': (ROOT / 'docs/UNIFIED-SPEC.md', ROOT / 'docs/UNIFIED-SPEC.docx'),
}


def run(arguments: list[str]) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def replace_current(source: Path, target: Path) -> None:
    if target.exists():
        target.chmod(stat.S_IREAD | stat.S_IWRITE)
    shutil.copyfile(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--documents', nargs='+', choices=DOCUMENTS, default=list(DOCUMENTS))
    parser.add_argument('--pdf', action='store_true')
    parser.add_argument('--text', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='townlight-records-docs-') as temporary:
        staging = Path(temporary)
        documents = []
        for name in args.documents:
            source, target = DOCUMENTS[name]
            staged = staging / target.name
            run(['pandoc', str(source), '--standalone', '-o', str(staged)])
            replace_current(staged, target)
            if name == 'manual':
                replace_current(staged, ROOT / 'docs/townlight_records-manual.docx')
            documents.append((name, staged, target))
            if args.text:
                run(['pandoc', str(source), '-t', 'plain', '--wrap=none', '-o', str(target.with_suffix('.txt'))])
        if args.pdf:
            executable = shutil.which('soffice.com')
            installed = Path('C:/Program Files/LibreOffice/program/soffice.com')
            if not executable and installed.is_file():
                executable = str(installed)
            if not executable:
                raise RuntimeError('LibreOffice soffice.com is required for PDF rendering')
            output = staging / 'pdf'
            output.mkdir()
            profile = staging / 'office-profile'
            run([executable, '-env:UserInstallation=' + profile.as_uri(), '--headless',
                 '--convert-to', 'pdf:writer_pdf_Export:{"UseTaggedPDF":{"type":"boolean","value":"true"}}',
                 '--outdir', str(output), *(str(item[1]) for item in documents)])
            for name, staged, target in documents:
                pdf = output / staged.with_suffix('.pdf').name
                if not pdf.is_file() or not pdf.stat().st_size:
                    raise RuntimeError(f'No PDF produced for {name}')
                replace_current(pdf, target.with_suffix('.pdf'))
                if name == 'readme':
                    replace_current(pdf, ROOT / 'README-FULL.pdf')
                elif name == 'manual':
                    replace_current(pdf, ROOT / 'docs/townlight_records-manual.pdf')
        for name, _, target in documents:
            print(f'Rendered current {name} from {DOCUMENTS[name][0]} to {target}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
