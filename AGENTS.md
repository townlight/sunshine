# Townlight Records — Development Standards

## Governing contract and current candidate

Scott's bounded completion contract governs. Legacy skills, pipeline profiles,
automatic delegation and repeated generic audits apply only when explicitly
invoked. Preserve the actual product specification, required CI, security/data
safeguards, signatures/recovery and exact installed acceptance. Agent reports
and source tests do not establish installed behavior or delivery.

The principal distribution is `townlight-records` 1.8.0.dev2, imported as
`townlight_records` from `backend/townlight_records`. The public ASGI object is
`townlight_records.main:app`; Celery uses `townlight_records.worker`.
Core is `townlight-core==1.3.0.dev2`, pinned by full commit in
`config/core-source.json`. `scripts/install-core-candidate.py` builds that source
wheel before package installation. Never relabel an old release artifact.

The selected Windows native runtime and standalone React/Docker application
remain separate deployment paths. This candidate supports fresh branded
databases/profiles and refuses unmarked legacy city data. It supplies no
in-place naming upgrade or old import shim. The sole approved retained old
active identifier is `%LOCALAPPDATA%\CivicSuite` for that profile path only.
Historical receipts, ADRs and tagged releases keep original identities.
Other old active names require Scott's approval in the single exception registry.

Run affected backend/frontend checks and required CI/recovery/provenance gates.
Preserve the requirement to collect and execute the actual backend suite;
record skips/failures and actual Docker/installed limits explicitly. Reuse
unaffected evidence. Test data must remain isolated; no production data mutation
is authorized by this file. Remote publication requires its separate approval.

## Project

Open-source, locally-hosted AI system for municipal open records request processing.
AGPL-3.0 licensed. Python/FastAPI backend, React/shadcn/ui frontend, PostgreSQL+pgvector, Ollama.

## Testing Requirements

Every sub-project must pass ALL verification gates before merge:

### Unit Tests
- Run with `cd backend && python -m pytest tests/ -v` (no Docker required for pure unit tests)
- Parser, chunker, embedder tests must pass without a database
- Integration tests (auth, audit, admin, datasources, documents) require PostgreSQL

### Integration Tests
- Require Docker: `docker compose up -d postgres redis`
- Run inside the api container (postgres is not exposed to localhost): `docker compose run --rm api python -m pytest tests/ -v`

#### Testing Prerequisites (PostgreSQL permissions and cleanup)

The test runner's `setup_db` fixture drops and recreates `townlight_records_test` per test, so PostgreSQL must grant DROP/CREATE DATABASE privileges to the `townlight_records` user (the default docker compose config does — this matters only for custom deployments).

**First-run cleanup:** If a previous test run died mid-fixture, `townlight_records_test` may already exist. That surfaces as a cryptic `DuplicateDatabaseError` in the first test. Drop it manually before rerunning:

```bash
docker compose exec postgres dropdb -U townlight_records townlight_records_test
```

The suite expects to own `townlight_records_test` exclusively. Do not run tests against a shared test database.

**Accepted warning baseline:** The suite emits `RuntimeWarning: coroutine 'Connection._cancel' was never awaited` and related `SAWarning: garbage collector is trying to clean up non-checked-in connection` in teardown. These are a known limitation of NullPool + asyncpg event-loop timing: when pytest-asyncio closes a per-function event loop, any `Connection._cancel` coroutines scheduled by asyncpg's cleanup have no loop to run on. The conftest mitigates this with `asyncio.sleep + gc.collect` in client/db_session teardown, but cannot eliminate it entirely. Current baseline is **~110 warnings per full run of 432 tests** (see `backend/test_results_full.txt`). Counts materially above ~150 indicate a new leak — investigate before shipping.

### Docker Verification
- `docker compose build` must succeed with no errors
- `docker compose up -d` must start all services healthy
- `curl http://localhost:8000/health` must return `{"status": "ok"}`
- `curl http://localhost:8000/docs` must serve OpenAPI docs

### Frontend Verification
- `cd frontend && npm install && npm run build` must succeed
- No TypeScript errors
- Login page renders, dashboard loads, navigation works

### QA Checklist (before merge)
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Docker Compose starts all services
- [ ] API health endpoint responds
- [ ] Frontend builds without errors
- [ ] Spec/docs match implemented code (feature counts, endpoint names, etc.)
- [ ] No hardcoded secrets or credentials in code
- [ ] Audit logging verified (actions create log entries)

## Post-Push Verification

After every `git push`, verify the remote state matches what you expect — not the git output, the actual result:
- `git log origin/master --oneline -3` to confirm commits landed
- `git diff HEAD origin/master` to confirm nothing diverged
- If a specific file matters, verify it exists on remote

For authorized deployment, verify the actual result. Never seed or change a production database merely to satisfy a generic workflow instruction. Existing integrations require meaningful caller and integration evidence; source presence alone is insufficient.

## Code Standards

- Python: Follow existing patterns. Use async/await consistently. Type hints on all public functions.
- TypeScript: Strict mode. No `any` types except in catch blocks.
- Tests: Unit tests for pure logic, integration tests for API endpoints, mocked external services (Ollama).
- Commits: Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`).

## Architecture

See `docs/UNIFIED-SPEC.md` for the canonical spec (single source of truth).

### Key Constraints
- All dependencies must be permissive or weak-copyleft licensed (MIT, Apache 2.0, BSD, LGPL, MPL)
- Redis pinned to <8.0.0 (BSD licensed; 8.x changed licensing)
- No telemetry, analytics, or outbound data transmission
- Human-in-the-loop enforced at API layer (no auto-redaction, no auto-denial)
- Audit logging is a legal compliance requirement, not optional

## Docker Services

1. `postgres` — PostgreSQL 17 + pgvector
2. `redis` — Redis 7.2 (BSD)
3. `ollama` — Local LLM runtime
4. `api` — FastAPI backend (port 8000)
5. `worker` — Celery async tasks
6. `beat` — Celery beat scheduler
7. `frontend` — React admin panel (port 8080)
