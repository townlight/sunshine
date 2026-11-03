# backend/tests/test_sync_notifications.py
"""P7 notification rate-limit + digest tests.

These tests run without a DB — they patch _queue_individual_circuit_open and
_queue_digest_notification at the module level.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest


def _make_source():
    source = MagicMock()
    source.id = uuid.uuid4()
    source.name = f"source-{source.id}"
    source.consecutive_failure_count = 5
    source.sync_paused_reason = "5 consecutive failures"
    return source


@pytest.mark.asyncio
async def test_single_circuit_open_sends_individual_notification():
    """A lone circuit-open queues one individual notification, no digest."""
    from townlight_records.notifications.sync_notifications import notify_circuit_open, _PENDING_CIRCUIT_OPENS

    _PENDING_CIRCUIT_OPENS.clear()
    source = _make_source()
    individual_calls = []
    digest_calls = []

    async def fake_individual(session, src):
        individual_calls.append(str(src.id))

    async def fake_digest(session, source_ids, window_start):
        digest_calls.append(list(source_ids))

    with patch(
        "townlight_records.notifications.sync_notifications._queue_individual_circuit_open",
        side_effect=fake_individual,
    ), patch(
        "townlight_records.notifications.sync_notifications._queue_digest_notification",
        side_effect=fake_digest,
    ):
        await notify_circuit_open(None, source)

    assert individual_calls == [str(source.id)]
    assert digest_calls == []


@pytest.mark.asyncio
async def test_multiple_circuit_opens_batched_to_digest():
    """3 sources circuit-open within the same 5-min window → at most 1 individual email
    (the first open) plus a digest that covers all 3 source IDs. Must NOT produce
    3 separate individual notifications.

    Spec ref: 'D12 — 3 sources circuit-open within 5-min window → 1 digest email, not 3'
    """
    from townlight_records.notifications.sync_notifications import notify_circuit_open, _PENDING_CIRCUIT_OPENS

    _PENDING_CIRCUIT_OPENS.clear()
    sources = [_make_source() for _ in range(3)]
    individual_calls = []
    digest_calls = []

    async def fake_individual(session, src):
        individual_calls.append(str(src.id))

    async def fake_digest(session, source_ids, window_start):
        digest_calls.append(list(source_ids))

    with patch(
        "townlight_records.notifications.sync_notifications._queue_individual_circuit_open",
        side_effect=fake_individual,
    ), patch(
        "townlight_records.notifications.sync_notifications._queue_digest_notification",
        side_effect=fake_digest,
    ):
        for source in sources:
            await notify_circuit_open(None, source)

    assert len(individual_calls) <= 1, (
        f"Expected ≤1 individual notification for 3 circuit opens in one window, "
        f"got {len(individual_calls)}: {individual_calls}"
    )
    assert digest_calls, "Expected at least one digest call for 3 simultaneous circuit opens"
    all_digest_ids = {sid for call in digest_calls for sid in call}
    for source in sources:
        assert str(source.id) in all_digest_ids, (
            f"Source {source.id} missing from digest notification"
        )
