# Windows component testing

The Windows component workflow collects and runs the full Python tests directory.
SQL, configuration, dependency and script changes trigger the job alongside Python changes.
JUnit results retain exact passes, failures and explicit platform/dependency skips.
The existing hosted database/browser checks remain; component tests do not establish signed MSI installed acceptance.
The obsolete manual release-preflight workflow is preserved under docs/history/retired-workflows-2026-11, not used to describe current release readiness.
