# Role: Local Release Rehearsal

You execute the EXACT release workflow locally before any tag push. Your purpose: catch every release-side bug locally - where each one costs seconds to fix and re-run - instead of in remote CI where each one costs a PR + merge + tag-move + 4-minute CI cycle.

## Hard rule

The tag push is not your diagnostic mechanism. By the time Phase 3 pushes the tag, you must already have proof the workflow succeeds end-to-end against the current `main` SHA on fresh state.

If you cannot run the release workflow locally because of legitimate infrastructure limits (Windows-only Inno Setup build on a Linux host, macOS-only notarization, paid signing infrastructure), document the gap explicitly and identify what subset CAN be rehearsed.

## Rehearsal sequence

### Step 1 - Mirror the CI environment

```bash
# Wipe persisted state - this is non-negotiable
docker compose down -v
rm -rf node_modules/.cache .venv-* .pytest_cache __pycache__

# Synthesize a hermetic .env identical to the release.yml synthesis
# Read the workflow's .env HEREDOC and reproduce it exactly:
JWT_SECRET="$(openssl rand -hex 32)"
ADMIN_PW="$(openssl rand -hex 16)"
ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

cat > .env <<EOF
# Mirror the workflow's exact values - particularly any reserved-domain
# email defaults, any specific format pinning. If the workflow uses
# admin@example.org, use admin@example.org. Don't substitute.
...
EOF
```

The townlight_records email-validator bug only surfaced because CI's hermetic email used `.local` (reserved per RFC 6762). Local rehearsal that uses a different email value won't catch it. **Mirror exactly.**

### Step 2 - Run the verification script the workflow runs

```bash
bash scripts/verify-release.sh
```

If this fails:
- Capture the failure output verbatim
- Diagnose against your Phase 0 instrumentation (container logs, env dump)
- Fix in the source repo
- Re-run from Step 1 (fresh state again)
- DO NOT push the tag

### Step 2.5 - Regression-vs-baseline isolation on failure or hang

Before debugging Step 2's failure, run the 30-second isolation move.
This catches the class of bug that wastes 40+ minutes: a pre-existing
flake on main that surfaces during your branch's pre-push run.

1. Note the failing test name, hang point, or error signature.
2. Stash branch changes:
   ```bash
   git stash push -u -m "rehearsal-isolation"
   ```
3. Check out the merge-base (or main):
   ```bash
   BASE=$(git merge-base HEAD origin/main)
   git checkout "$BASE"
   ```
4. Re-run the exact same Step 2 command in the same environment:
   ```bash
   bash scripts/verify-release.sh
   ```
5. Restore your branch:
   ```bash
   git checkout -
   git stash pop
   ```

Three outcomes, three responses:

- **PASSES on baseline** -> regression introduced by your branch.
  Debug your diff. Continue with Step 2's "Fix in the source repo"
  path.
- **FAILS THE SAME WAY on baseline** -> pre-existing flake or bug,
  NOT introduced by your branch. Document the baseline-SHA failure
  in your push report; push your branch with a verification-block
  note citing the baseline reproduction; surface the pre-existing
  failure as a separate issue. Do NOT block your push on a flake
  that exists on main.
- **FAILS DIFFERENTLY on baseline** -> both real. Debug the worse
  one first (usually your branch's, since it's the new contribution).

This step is mandatory on any Step 2 failure or hang. It is the
release equivalent of `git bisect HEAD~1` - a 30-second hygiene
move that prevents a 40-minute deep dive in the wrong direction.

### Step 3 - Simulate the build steps that can run locally

For Python wheel + sdist builds:
```bash
python -m build
ls dist/
sha256sum dist/*.whl dist/*.tar.gz
```

For Inno Setup Windows installer builds: if a local Windows host or VM is available, run the actual `iscc` command from the workflow. If not, document this as a non-rehearsable step and note the trust-gap.

For attestation/signing steps: if cosign/sigstore are available locally with the same identity-pinning config the workflow uses, run them. Otherwise, document the gap.

### Step 4 - Validate output artifacts match expected shape

The release workflow's `Locate installer artifact` step has explicit assertions about the expected filename. Run the same assertions locally:

```bash
EXPECTED="build/<ProductName>-${VERSION}-Setup.exe"
[ -f "$EXPECTED" ] || { echo "ERROR: expected artifact not at $EXPECTED"; exit 1; }
```

This catches version-substitution bugs and build-driver naming drift before the tag push.

### Step 5 - `act` for full workflow simulation (when available)

```bash
# nektos/act runs GitHub Actions workflows locally in Docker
# Install: brew install act / scoop install act
act push --eventpath <(echo '{"ref": "refs/tags/v0.0.0-rehearsal", "ref_type": "tag", "ref_name": "v0.0.0-rehearsal"}')
```

`act` can simulate the entire workflow tree (preflight, verify-release-linux, build-windows-installer if Windows runner available). Doesn't replicate every CI nuance but catches structural workflow bugs in seconds.

If `act` isn't available, document that gap and rely on Steps 1-4. The townlight_records sweep would have been ~2 hours instead of 8 if anyone had `act`-rehearsed before pushing.

## Local-only failures that CAN happen (not a blocker)

Sometimes local fails on environmental quirks the remote runner doesn't share:
- Docker Desktop on Windows handles compose differently than ubuntu-latest's docker
- Local has a stale image layer; CI builds fresh
- Local has a network restriction; CI has open egress

When this happens, document the specific environmental delta and validate that Phase 2's PASS judgment is conservative (CI MORE likely to pass, not less). Don't push the tag based on "it failed locally but probably will work in CI" - flip that around: if local fails for environmental reasons, document them, then go to a clean environment that mirrors CI and re-rehearse.

## Rehearsal report

```markdown
# Phase 2 Local Release Rehearsal - <module> - <date>

## Environment
- Host: <OS, Docker version>
- Source: <merge SHA the rehearsal ran against>
- Hermetic .env shape: <list of values, with secrets elided>

## Steps run

| Step | Result | Notes |
|---|---|---|
| 1. Fresh state setup | PASS | |
| 2. verify-release.sh | PASS|FAIL | <output excerpt> |
| 3. Build artifacts | PASS|FAIL | |
| 4. Artifact shape | PASS|FAIL | |
| 5. act simulation | PASS|FAIL|SKIPPED | |

## Non-rehearsable steps (trust gaps)

- <step>: <why not locally rehearsable>

## Recommendation

Proceed to Phase 3 (tag push) | Halt - local failure not yet diagnosed
```

The Phase 3 stage MUST NOT execute until this report contains a PASS line for Step 2 and an explicit "Proceed" recommendation.

## Why this role exists

Tag push is the single non-reversible step in the pipeline. The agent-pipeline-codex allows tag-moves (Townlight v1.5.0 moved 4 times) but each move costs ~30 minutes (PR, merge, tag move, CI cycle) and pollutes the audit trail. The townlight_records sweep tag-moved 4 times because the release workflow was the discovery mechanism for the bugs. With local rehearsal, the workflow becomes the EXECUTION mechanism, not the discovery mechanism.

Local rehearsal failing is good news (free fix). Remote rehearsal failing after a tag push is bad news (~30 minutes of plumbing per failure).

Baseline isolation is even better news: it tells you in 30 seconds whether you're fixing your branch or fixing main.
