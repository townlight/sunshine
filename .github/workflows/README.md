# CI Workflows

This directory holds the GitHub Actions workflows that gate merges into
`master`.

## `ci.yml`

The single mandatory workflow. Runs on every push to `master`, every pull
request targeting `master`, and on manual dispatch from the Actions tab.

### What it does

Two jobs run in parallel:

**`backend`** - pytest via `docker compose`, matching AGENTS.md Hard Rule 1a
exactly. Three gates, in order:

1. **Collection gate** (`pytest --collect-only`). Fails on any import error,
   syntax error, or missing fixture.
2. **Full suite** (`pytest -q`). Every test must pass.
3. **Cross-check** (`collected == passed`). If the collected count and passed
   count disagree, the delta is skipped tests, xfails, errors, or tests that
   exited early. None of those are acceptable.

On failure, `collect.log`, `run.log`, and `compose.log` are uploaded as
artifacts and kept for 14 days.

**`frontend`** - `npm ci && npm test && npm run build` on Node 22.

### Hermetic environment

The backend and release workflows generate fresh Docker secret files on every
run: `data/secrets/jwt_secret` and `data/secrets/first_admin_password`. The
`.env` file contains only `JWT_SECRET_FILE` and
`FIRST_ADMIN_PASSWORD_FILE` pointers. Nothing is carried between runs; nothing
secret is stored in the workflow or in GitHub Actions secrets.

Ollama is skipped via `docker compose run --no-deps` because tests mock the
Ollama client. If a future test genuinely needs Ollama, either mock it or add
the service to the `docker compose up -d --wait` line.

### Reproducing a CI failure locally

The backend commands are identical to AGENTS.md Rule 1a:

```bash
# One-time setup
cp .env.example .env
mkdir -p data/secrets
openssl rand -hex 32 > data/secrets/jwt_secret
openssl rand -hex 16 > data/secrets/first_admin_password
chmod 0400 data/secrets/jwt_secret data/secrets/first_admin_password

docker compose up -d --wait postgres redis
docker compose exec -T postgres createdb -U townlight_records townlight_records_test

# Reproduce the CI checks
docker compose build api
docker compose run --rm --no-deps api python -m pytest tests --collect-only -q
docker compose run --rm --no-deps api python -m pytest tests -q
```

Frontend:

```bash
cd frontend
npm ci
npm test
npm run build
```

### Why this is PR 0

Every downstream fix in `docs/REMEDIATION-PLAN-2026-04-19.md` is silently
reversible without a ratchet. CI lands alone, first, so the rest of the
remediation work has a regression guard.

Branch protection is a one-time GitHub repository setting and is not managed by
this repository.
