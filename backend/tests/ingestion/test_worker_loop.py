"""Regression: Celery prefork + asyncio event-loop reuse in task_ingest_file.

The bug
-------
`backend/app/ingestion/tasks.py` (v1.6.0) constructs a module-global async
engine inside the ``worker_process_init`` Celery signal. That hook fires
once per forked worker process, *before* any event loop exists. asyncpg's
``Connection`` objects bind their internal ``_loop`` / ``_waiter`` machinery
to **whichever loop first awaited I/O on them** — i.e. the loop owned by
the first Celery task. ``_run_async`` then closes that loop. Every later
task on the same prefork worker tries to schedule asyncpg callbacks on
the closed loop and raises one of:

  RuntimeError: Event loop is closed
  RuntimeError: ... got Future <...> attached to a different loop

The first task on a fresh worker succeeds; the second always retries until
``max_retries=2`` is exhausted and the document is left at chunk_count=0.

Why this test does not need a real Postgres
-------------------------------------------
The defect is purely about asyncio event-loop identity, not about SQL.
A self-contained ``_FakeAsyncEngine`` reproduces asyncpg's loop-binding
contract exactly: each engine records the loop that first opened a
session, and any later session opened on a different loop raises the
same ``RuntimeError: Event loop is closed`` asyncpg raises. With the
current buggy ``tasks.py`` (engine built once in ``worker_process_init``
+ ``_run_async`` builds a fresh loop per task) this test fails on the
second ``task_ingest_file.apply()`` call. With the fix (engine built
inside the per-task coroutine and disposed before the loop closes) the
test passes both calls.

This matches the test design in
``.agent-runs/2026-05-14-celery-asyncio-worker-fix/research.md``:
two sequential ``task_ingest_file`` invocations in the same Python
process, asserting neither raises the two diagnostic RuntimeErrors.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
import weakref
from pathlib import Path

import pytest

# Importing app.ingestion.tasks pulls celery_app + the worker_process_init
# hook in. We must import after the asyncio environment is ready, so the
# import happens lazily inside the fixtures below.


# ---------------------------------------------------------------------------
# Fake async engine + session that mirror asyncpg's loop-binding contract
# ---------------------------------------------------------------------------

# The two diagnostic strings that the regression test must NOT see. Both
# are the verbatim asyncpg messages described in research.md.
_LOOP_CLOSED = "Event loop is closed"
_DIFFERENT_LOOP = "attached to a different loop"


class _FakeAsyncSession:
    """Minimal AsyncSession stand-in.

    Behaves as an async context manager that yields itself. Records on
    entry which event loop is running. Used as the ``session`` argument
    passed to the patched ``ingest_file`` / ``write_audit_log`` callables.
    """

    def __init__(self, engine: "_FakeAsyncEngine") -> None:
        self._engine = engine

    async def __aenter__(self) -> "_FakeAsyncSession":
        # This is the moment asyncpg would bind its protocol to the loop.
        # Delegate to the engine so cross-loop reuse raises the same way.
        self._engine._bind_or_check_loop()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:  # pragma: no cover — unused
        return None

    async def rollback(self) -> None:  # pragma: no cover — unused
        return None

    async def close(self) -> None:  # pragma: no cover — unused
        return None


class _FakeSessionMaker:
    """Stand-in for the ``async_sessionmaker(engine)`` callable."""

    def __init__(self, engine: "_FakeAsyncEngine", **_kwargs) -> None:
        self._engine = engine

    def __call__(self) -> _FakeAsyncSession:
        return _FakeAsyncSession(self._engine)


class _FakeAsyncEngine:
    """Stand-in for ``create_async_engine(url, ...)``.

    On the first session-open the engine captures the running event loop
    via a weak reference (asyncpg's Protocol._loop has the same lifecycle:
    it lives as long as the connection does). On every later session-open
    the engine compares the running loop to the captured one:

      - If the captured loop is still running and matches → fine.
      - If the captured loop is closed or different → raise
        ``RuntimeError("Event loop is closed")`` (asyncpg's exact wording).

    This is precisely the failure mode described in research.md §Symptom.
    """

    # Strong refs so engines disposed inside ``worker_session_scope`` aren't
    # garbage-collected before the test's structural assertion can inspect
    # them. (weakref was the original choice; under the fix the engines go
    # out of scope on dispose, which makes the weakref tracker see 0
    # engines and miss the invariant.)
    _all_engines: "list[_FakeAsyncEngine]" = []

    def __init__(self, url: str = "", **_kwargs) -> None:
        self.url = url
        self._bound_loop_ref: "weakref.ref[asyncio.AbstractEventLoop] | None" = None
        # ``ever_bound`` is True once any session has opened on this engine,
        # regardless of subsequent ``dispose()``. The structural-invariant
        # test inspects this so the post-fix path (which disposes the
        # engine before the loop closes, mirroring scheduler.py:30-44)
        # still has two observable engines per two task invocations.
        self.ever_bound = False
        self.disposed = False
        _FakeAsyncEngine._all_engines.append(self)

    def _bind_or_check_loop(self) -> None:
        current = asyncio.get_running_loop()
        if self._bound_loop_ref is None:
            self._bound_loop_ref = weakref.ref(current)
            self.ever_bound = True
            return
        bound = self._bound_loop_ref()
        if bound is None or bound.is_closed():
            raise RuntimeError(_LOOP_CLOSED)
        if bound is not current:
            raise RuntimeError(
                f"got Future <...> {_DIFFERENT_LOOP} (bound={id(bound)} current={id(current)})"
            )

    async def dispose(self) -> None:
        self.disposed = True
        self._bound_loop_ref = None


def _fake_create_async_engine(*args, **kwargs) -> _FakeAsyncEngine:
    return _FakeAsyncEngine(*args, **kwargs)


def _fake_async_sessionmaker(engine: _FakeAsyncEngine, **kwargs) -> _FakeSessionMaker:
    return _FakeSessionMaker(engine, **kwargs)


# ---------------------------------------------------------------------------
# Patch surface
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _patched_ingestion_runtime(monkeypatch_target_session):
    """Install all the patches needed to run task_ingest_file without a real DB.

    - ``app.ingestion.tasks.create_async_engine`` → returns ``_FakeAsyncEngine``.
    - ``app.ingestion.tasks.async_sessionmaker`` → returns ``_FakeSessionMaker``.
    - ``townlight_records.database.async_session_maker`` → also a ``_FakeSessionMaker``
       so the fallback path in ``get_worker_session()`` also goes through
       the fake (covers the eager-mode case where ``worker_process_init``
       did not fire).
    - ``townlight_core.ingest.pipeline.ingest_file`` → returns a fake Document.
    - ``townlight_records.audit.logger.write_audit_log`` → no-op.
    - ``app.ingestion.tasks._engine`` / ``_session_maker`` → reset to None
       between tests so each test starts in the prefork-pristine state.

    The fix moves engine creation inside the per-task coroutine. The
    same set of patches works for both states of the code: each call to
    ``create_async_engine`` returns a fresh ``_FakeAsyncEngine``, and the
    cross-loop check fires only when an engine is shared across loops.
    """
    from townlight_records.ingestion import tasks as tasks_mod
    from townlight_records.audit import logger as audit_logger_mod
    from townlight_records import database as database_mod

    class _FakeDoc:
        id = uuid.uuid4()
        filename = "fake.txt"
        chunk_count = 1

        class _Status:
            value = "completed"

        ingestion_status = _Status()

    async def _fake_ingest_file(session, file_path, source_id, **_kw):
        # Touch the session so the fake engine's loop-check fires under
        # an "await ... on this session" pattern. asyncpg's real
        # connection.execute() is what triggers the cross-loop callback.
        await asyncio.sleep(0)
        return _FakeDoc()

    async def _fake_write_audit_log(session, **_kw):
        await asyncio.sleep(0)
        return None

    # Snapshot the originals so we can restore them on exit. We patch the
    # *bindings inside ``app.ingestion.tasks``* — that module did
    # ``from townlight_core.ingest.pipeline import ingest_file`` and
    # ``from townlight_records.audit.logger import write_audit_log``, so the names
    # ``tasks_mod.ingest_file`` / ``tasks_mod.write_audit_log`` are what
    # the ``_ingest()`` closures actually resolve. Patching the source
    # modules is too late — the import already bound the originals.
    # Snapshot with getattr() defaults — the pre-fix module had `_engine`
    # and `_session_maker` globals plus a `worker_process_init` hook; the
    # post-fix module deletes both globals and builds the engine inside a
    # per-task `worker_session_scope()`. The test must collect and pass
    # under either shape, so missing attributes are tolerated.
    _SENTINEL = object()
    originals = {
        "tasks.create_async_engine": tasks_mod.create_async_engine,
        "tasks.async_sessionmaker": tasks_mod.async_sessionmaker,
        "tasks._engine": getattr(tasks_mod, "_engine", _SENTINEL),
        "tasks._session_maker": getattr(tasks_mod, "_session_maker", _SENTINEL),
        "tasks.ingest_file": tasks_mod.ingest_file,
        "tasks.write_audit_log": tasks_mod.write_audit_log,
        "audit.write_audit_log": audit_logger_mod.write_audit_log,
        "database.async_session_maker": database_mod.async_session_maker,
    }

    # Reset module globals so each test starts pristine (pre-fix shape).
    # Under the fix these names are unused but harmless if present.
    tasks_mod._engine = None
    tasks_mod._session_maker = None
    tasks_mod.create_async_engine = _fake_create_async_engine
    tasks_mod.async_sessionmaker = _fake_async_sessionmaker
    tasks_mod.ingest_file = _fake_ingest_file
    tasks_mod.write_audit_log = _fake_write_audit_log
    audit_logger_mod.write_audit_log = _fake_write_audit_log
    # Database fallback path — also rewire so the eager-mode fallback in
    # the pre-fix ``get_worker_session()`` hits the fake engine instead of
    # the real asyncpg pool against an unreachable Postgres host. Under
    # the fix, ``worker_session_scope()`` builds its own engine so this
    # rewire is a defense-in-depth no-op.
    _fallback_engine = _FakeAsyncEngine(url="fallback://test")
    database_mod.async_session_maker = _FakeSessionMaker(_fallback_engine)

    try:
        yield {"fallback_engine": _fallback_engine}
    finally:
        tasks_mod.create_async_engine = originals["tasks.create_async_engine"]
        tasks_mod.async_sessionmaker = originals["tasks.async_sessionmaker"]
        if originals["tasks._engine"] is _SENTINEL:
            try:
                del tasks_mod._engine
            except AttributeError:
                pass
        else:
            tasks_mod._engine = originals["tasks._engine"]
        if originals["tasks._session_maker"] is _SENTINEL:
            try:
                del tasks_mod._session_maker
            except AttributeError:
                pass
        else:
            tasks_mod._session_maker = originals["tasks._session_maker"]
        tasks_mod.ingest_file = originals["tasks.ingest_file"]
        tasks_mod.write_audit_log = originals["tasks.write_audit_log"]
        audit_logger_mod.write_audit_log = originals["audit.write_audit_log"]
        database_mod.async_session_maker = originals["database.async_session_maker"]


@pytest.fixture
def eager_celery():
    """Run Celery tasks synchronously in the calling process."""
    from townlight_records.worker import celery_app

    prior_eager = celery_app.conf.task_always_eager
    prior_prop = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        yield celery_app
    finally:
        celery_app.conf.task_always_eager = prior_eager
        celery_app.conf.task_eager_propagates = prior_prop


@pytest.fixture
def tmp_text_files(tmp_path: Path) -> tuple[Path, Path]:
    p1 = tmp_path / "doc-one.txt"
    p2 = tmp_path / "doc-two.txt"
    p1.write_text("first ingest payload", encoding="utf-8")
    p2.write_text("second ingest payload", encoding="utf-8")
    return p1, p2


# ---------------------------------------------------------------------------
# The regression test
# ---------------------------------------------------------------------------

def test_task_ingest_file_runs_twice_same_process_prefork_pattern(
    eager_celery, tmp_text_files
):
    """Two sequential ``task_ingest_file.apply()`` calls must both succeed.

    Reproduces the exact failure described in research.md:

      worker-1 | RuntimeError: Event loop is closed
      worker-1 | got Future <...> attached to a different loop

    Currently FAILS on the second call. After the fix in
    ``backend/app/ingestion/tasks.py`` (engine built inside the per-task
    coroutine, disposed before the loop closes), this test passes.

    The test fires the ``worker_process_init`` signal explicitly so the
    code path traversed is the actual prefork bug surface, not the
    eager-mode fallback.
    """
    from townlight_records.ingestion import tasks as tasks_mod
    from celery.signals import worker_process_init

    p1, p2 = tmp_text_files
    source_id = str(uuid.uuid4())

    with _patched_ingestion_runtime(None):
        # Simulate what Celery prefork does: fire ``worker_process_init``
        # so the module-global ``_engine`` / ``_session_maker`` are built
        # OUTSIDE any running event loop, exactly as in production.
        worker_process_init.send(sender=None)

        # Sanity: the buggy code installed a global session maker.
        # (After the fix, this assertion can either remain — the fix may
        # keep the hook as a no-op or remove it — or be relaxed; what the
        # next test below actually checks is the two-task outcome.)
        # We intentionally do NOT assert on the existence of the global
        # here so the test stays valid post-fix even if the hook is gone.

        # First call: succeeds today (primes the bug for call #2).
        result1 = tasks_mod.task_ingest_file.apply(
            args=[str(p1), source_id],
        )

        # Second call on a brand new event loop in the same process.
        # Under the current buggy code, the inner _ingest() raises
        # ``RuntimeError("Event loop is closed")`` (asyncpg cross-loop
        # symptom). ``task_ingest_file`` catches that and calls
        # ``self.retry()``, which under eager mode + ``task_eager_propagates``
        # raises ``celery.exceptions.Retry`` carrying the original
        # RuntimeError on its ``.exc`` attribute.
        from celery.exceptions import Retry

        runtime_err: RuntimeError | None = None
        result2 = None
        try:
            result2 = tasks_mod.task_ingest_file.apply(
                args=[str(p2), source_id],
            )
        except Retry as retry_exc:
            # Unwrap to find the asyncpg / asyncio symptom we care about.
            underlying = retry_exc.exc if isinstance(retry_exc.exc, BaseException) else None
            if isinstance(underlying, RuntimeError):
                runtime_err = underlying
            else:
                runtime_err = RuntimeError(str(retry_exc))
        except RuntimeError as direct:
            runtime_err = direct

        # First call must always succeed (the bug never affects call #1).
        assert result1.successful(), (
            f"First task_ingest_file failed unexpectedly: {result1.traceback}"
        )

        if runtime_err is not None:
            msg = str(runtime_err)
            assert _LOOP_CLOSED in msg or _DIFFERENT_LOOP in msg, (
                f"Got an unrelated RuntimeError on second apply(): {msg!r}"
            )
            pytest.fail(
                "Regression reproduced: second task_ingest_file.apply() failed "
                f"with RuntimeError({msg!r}). This is exactly the bug described "
                "in research.md — engine bound to first task's now-closed loop. "
                "After the fix in backend/app/ingestion/tasks.py, both calls "
                "must succeed without raising 'Event loop is closed' or "
                "'attached to a different loop'."
            )

        # Post-fix path: result2 returned, both EagerResults are successful.
        assert result2 is not None and result2.successful(), (
            "Post-fix expectation: second task_ingest_file.apply() must "
            "complete successfully. "
            f"Traceback:\n{result2.traceback if result2 is not None else 'no result'}"
        )
        payload1 = result1.result
        payload2 = result2.result
        assert payload1["status"] == "completed", payload1
        assert payload2["status"] == "completed", payload2


def test_run_async_does_not_reuse_engine_across_loops(eager_celery, tmp_text_files):
    """Stronger structural assertion of the same defect.

    Even if the prefork test above somehow passed (e.g. because Celery
    eager-mode short-circuits the failure), this test asserts the
    underlying invariant: every ``task_ingest_file.apply()`` call must
    create its session bound to its own event loop. We record the
    captured loop id from each ``_FakeAsyncEngine`` and demand they are
    *not* the same closed object.

    Under the buggy code, exactly one fake engine is built (via
    ``worker_process_init``) and is reused across both loops. Under the
    fix, two fake engines are built — one per call, each bound to its
    own loop.
    """
    from townlight_records.ingestion import tasks as tasks_mod
    from celery.signals import worker_process_init

    p1, p2 = tmp_text_files
    source_id = str(uuid.uuid4())

    # Reset the all-engines tracker so this test sees only its own.
    _FakeAsyncEngine._all_engines.clear()

    with _patched_ingestion_runtime(None):
        worker_process_init.send(sender=None)

        from celery.exceptions import Retry

        tasks_mod.task_ingest_file.apply(args=[str(p1), source_id])
        # Tolerate a RuntimeError / Retry on the second call — that's the
        # bug, and the OTHER test already asserts against it. This test
        # focuses on the structural invariant.
        try:
            result2 = tasks_mod.task_ingest_file.apply(args=[str(p2), source_id])
            second_succeeded = result2.successful()
        except (RuntimeError, Retry):
            second_succeeded = False

        engines = list(_FakeAsyncEngine._all_engines)
        # Discard engines that were never bound to a loop (e.g. the
        # fallback engine created at patch-install time, untouched by
        # eager-mode if ``worker_process_init`` populated the global).
        # ``ever_bound`` survives ``dispose()`` so the post-fix engines —
        # which are intentionally disposed before each task's loop closes
        # — still count toward the structural assertion.
        bound_engines = [e for e in engines if e.ever_bound]

        if not second_succeeded:
            pytest.fail(
                "Regression reproduced: second task_ingest_file.apply() did not "
                "complete successfully under the prefork pattern. "
                f"Engines bound to a loop: {len(bound_engines)}. "
                "Under the current buggy code exactly one engine is reused "
                "across both per-task loops; the fix must make each task "
                "build (and dispose) its own engine inside its own loop."
            )

        # Post-fix expectation: each task built its own engine inside its
        # own loop. Two distinct loop ids, two engines, neither bound
        # to the OTHER engine's loop.
        assert len(bound_engines) >= 2, (
            "Post-fix expectation: each task_ingest_file invocation must "
            "create its own AsyncEngine inside its per-task coroutine "
            "(mirroring scheduler.py:30-44). Saw "
            f"{len(bound_engines)} bound engines instead of >= 2."
        )
