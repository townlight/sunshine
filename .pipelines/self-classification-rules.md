# Self-classification rules - pre-authorized for agents

These are the rules the executor role applies to every grep hit, every test failure, every workflow alert, and every "should I halt or fix forward?" judgment call. They're pre-authorized so the agent doesn't halt-and-ask on routine cases. The townlight_records sweep wasted ~25% of its time on halt-and-ask cycles that should have been mechanical decisions.

## Grep-hit classification (during edit phases)

Every line returned by a release-sweep grep gets exactly ONE classification:

### LIVE-STATE - UPDATE without asking

- `pyproject.toml` dependency pin lines
- `.github/workflows/*.yml` lines that pip-install a versioned URL
- `README.md`, `USER-MANUAL.md`, install-instruction snippets describing current state
- Test files asserting current pin URL or current version constant
- Test fixture dicts like `{"townlight_core": "1.0.0"}` (update value to new version)
- Compatibility matrix entries describing current pin
- Source files with `EXPECTED_<DEP>_VERSION = "X.Y.Z"` constants

### FROZEN-EVIDENCE - DO NOT UPDATE

- `docs/audits/*-YYYY-MM-DD.md` - historical audit records
- `docs/qa/*` - past release-gate evidence
- `docs/evidence/*` - past release artifacts
- `docs/browser-qa-*-summary.md` and the `.png` screenshots they reference
- `docs/release-recovery-status.md` historical statements (e.g., "the existing 1.0.0 package version")
- CHANGELOG.md prior version entries (only ADD new entry; never edit historical entries)
- `.agent-workflows/HANDOFF_*.md` from prior dates

### SHAPE-GUARD - DO NOT UPDATE (negative assertions)

A grep hit is SHAPE-GUARD when ALL of these hold:
- The line is a NEGATIVE assertion: `assert "X" not in <thing>`
- The string X encodes a format/shape pattern, not a specific version
- Updating X to the new version would pass trivially with no real coverage

Examples:
- `assert "townlight_core==1.0.0" not in dependencies` - asserts no `==` pinning, version-independent
- `assert "1.0.0.dev0" not in text` - asserts no stale dev marker, version-unrelated

### OWN-MODULE-VERSION - SKIP (do not edit during a dependency-bump sweep)

A hardcoded version literal in production source that is the MODULE's OWN package version, not a dependency reference. Identified by ALL:
- Line is `__version__ = "X.Y.Z"` or `VERSION = "X.Y.Z"`
- Located in `<module>/<module>/__init__.py` or `_version.py`
- The string is the module's own published version
- Surrounding context does NOT mention the dependency being swept

The module's own version moves in the same PR as the dependency sweep, but it's a separate edit governed by the release sequence - not part of the dependency-string grep classification.

### AMBIGUOUS - halt and ask

If a line genuinely doesn't fit any of the above categories after applying all rules, mark it AMBIGUOUS and halt. Genuine ambiguity is rare.

## Failure-class classification (during CI/test phases)

When a test or CI step fails, classify before reacting:

### MECHANICAL-CI-BUG - FIX FORWARD (do not halt)

Pre-authorized fix-forward categories. These are bounded, low-risk, no-product-impact fixes that historically caused halt-and-ask cycles in our sweeps:

- YAML parse error in a workflow file (file:line + scanner error are explicit)
- Missing or wrong-encoding escape in a shell heredoc
- Indentation error in YAML block scalar
- Env-var format mismatch the validator rejects (e.g., reserved-domain email, weak password length)
- Missing required env var in workflow's `.env` synthesis that the app reads at startup
- Shell-vs-bash quirk on the wrong runner (`shell: bash` needed on windows-latest job)
- Hardcoded URL pointing at a moved release asset

The fix-forward bound is: changes must touch only `.github/workflows/`, `scripts/`, `Dockerfile*`, `docker-compose*.yml`, or test fixtures that exist purely for the CI flow. **Production source code changes ALWAYS halt-and-ask** regardless of how obvious the fix looks.

### CONTRACT-CHANGE - HALT AND REPORT

- Any source code change required
- Any test asserting on dependency-removed behavior (e.g., townlight_meetings tests asserting on townlight_core-removed `token_roles` field) - the auditor must approve the test update before the agent applies it
- Any cross-module dependency conflict
- Any failure whose root cause requires a design decision

### ENVIRONMENTAL - DOCUMENT AND CONTINUE

- macOS-only step on Linux runner with no available macOS host - document the trust gap and continue
- Paid-service signing step with no credentials provisioned - document and continue
- Third-party service outage (GitHub Actions, package registry, Sigstore) - wait + retry, document

### NOVEL - HALT AND REPORT

A failure that doesn't fit any category above. Genuine novelty is the trigger for halt. Pattern-matching against prior halts in the same project should rule out most "novel" cases.

## Bundling discipline

When fix-forward catches multiple MECHANICAL-CI-BUG issues in a single workflow file or workflow run:

- Bundle them into ONE commit on a single fix-forward branch
- Branch name format: `fix/<scope>-<class>-<date>` (e.g. `fix/release-yml-preflight-2026-05-11`)
- One PR per fix-forward bundle, not one PR per bug
- The townlight_records sweep opened 4 PRs (#70/#71/#72/#73) for what should have been 1 bundled PR. This is the explicit anti-pattern.

## Tag-move budget

A `<module> v<X.Y.Z>` tag may be moved at most ONCE per release sprint, and only when:
- No GitHub Release exists yet for that tag
- The move is to include a CI-only fix (no product wheel diff between source and target SHA)
- The move is documented in the eventual completion handoff's tag-move table

A second tag move is a signal that Phase 2 local rehearsal didn't catch what it should have. After the second move, halt and reassess Phase 2 instrumentation rather than continuing to chase remote bugs with more tag pushes.

Townlight v1.5.0 moved 4 times during recovery. The new pipeline targets ZERO moves per sprint; 1 move is acceptable for genuine environmental surprise.

## What this preserves vs. what changes

These rules ARE NOT a relaxation of the safety gates. The original agent-pipeline-codex's halt-on-novelty is preserved for genuine novelty. The original lockstep-gate, allowed_paths, frozen-evidence skips, and append-only run log are all unchanged.

What changes: the agent no longer halts on the long tail of mechanical CI fixes that humans would just apply without asking. The judgment is delegated, the scope is bounded, the audit trail is preserved.
