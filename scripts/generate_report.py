"""Historical fixed completion-report generator has been retired."""
import sys

if __name__ == '__main__':
    print('A completion report requires exact candidate acceptance evidence. '
          'Use the coordinated ACCEPTANCE.md; no report was generated. '
          'The original report generator is preserved under docs/history/pre-naming-2026-11/scripts/.',
          file=sys.stderr)
    raise SystemExit(2)
