import asyncio
from app.services import sync
from app.services.bulk_operation import BulkOperationGuard, BulkOperationBusy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException

from app.models.database import SafeSession
from app.db.session import GuardedConnection
from app.api.transactions import transactional_route


def test_read_permissions_are_isolated_across_overlapping_threads():
    entered, release, first_exited = Event(), Event(), Event()
    def second():
        connection = sqlite3.connect(':memory:')
        try:
            with SafeSession.allow_reads('second'):
                entered.set()
                assert first_exited.wait(2)
                assert GuardedConnection(connection).execute('SELECT 1').fetchone() == (1,)
                assert release.wait(2)
        finally:
            connection.close()
    SafeSession.enable_read_guard()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                with SafeSession.allow_reads('first'):
                    future = executor.submit(second)
                    assert entered.wait(2)
                first_exited.set()
                with sqlite3.connect(':memory:') as connection:
                    with pytest.raises(RuntimeError, match='read forbidden'):
                        GuardedConnection(connection).execute('SELECT 1')
            finally:
                release.set()
                first_exited.set()
            future.result()
        assert not SafeSession._reads_enabled
    finally:
        SafeSession.disable_read_guard()


# A change that arrives while another runs waits for it, never overlapping it: refused with 409,
# a note save failed (2026-10-24) and so did the edit preview, shown as a fatal error (the
# maintainer, 2026-11-11). A while for a waiting change to show it is not let in.
_STILL_WAITING_SECONDS = 0.2


def test_async_changes_wait_for_each_other_without_overlapping():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        events = []
        @transactional_route
        async def first():
            entered.set()
            await release.wait()
            events.append('first done')
        @transactional_route
        async def second():
            events.append('second ran')
        running = asyncio.create_task(first())
        await entered.wait()
        waiting = asyncio.create_task(second())
        await asyncio.sleep(_STILL_WAITING_SECONDS)
        assert not waiting.done()
        release.set()
        await running
        await waiting
        assert events == ['first done', 'second ran']
    asyncio.run(scenario())


def test_a_sync_change_waits_for_an_async_one_instead_of_being_refused():
    # An image uploading (an async route) while the note is saved (a sync one).
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        events = []
        @transactional_route
        async def upload():
            entered.set()
            await release.wait()
            events.append('upload done')
        @transactional_route
        def save():
            events.append('save ran')
            return 'saved'
        running = asyncio.create_task(upload())
        await entered.wait()
        saving = asyncio.create_task(asyncio.to_thread(save))
        await asyncio.sleep(_STILL_WAITING_SECONDS)
        assert not saving.done()
        release.set()
        await running
        assert await saving == 'saved'
        assert events == ['upload done', 'save ran']
    asyncio.run(scenario())


def test_an_async_change_waits_for_a_sync_one_instead_of_being_refused():
    async def scenario():
        entered, release = Event(), Event()
        events = []
        @transactional_route
        def save():
            entered.set()
            assert release.wait(_STILL_WAITING_SECONDS * 10)
            events.append('save done')
        @transactional_route
        async def upload():
            events.append('upload ran')
        saving = asyncio.create_task(asyncio.to_thread(save))
        await asyncio.to_thread(entered.wait)
        uploading = asyncio.create_task(upload())
        await asyncio.sleep(_STILL_WAITING_SECONDS)
        assert not uploading.done()
        release.set()
        await saving
        await uploading
        assert events == ['save done', 'upload ran']
    asyncio.run(scenario())


def test_clipboard_and_recovery_snapshots_do_not_share_nested_records():
    records = [{'content': {'text': 'original'}}]
    sync.set_clipboard('fixture', records)
    snapshot = sync.capture_sync_state()
    records[0]['content']['text'] = 'caller mutation'
    returned = sync.get_clipboard('fixture')
    returned[0]['content']['text'] = 'reader mutation'
    assert sync.get_clipboard('fixture')[0]['content']['text'] == 'original'
    sync.restore_sync_state(snapshot)
    snapshot[2]['fixture'][0]['content']['text'] = 'snapshot mutation'
    assert sync.get_clipboard('fixture')[0]['content']['text'] == 'original'
    sync.reset_state()


def test_bulk_answer_from_worker_is_delivered_on_owning_loop():
    async def scenario():
        guard = BulkOperationGuard()
        with guard.acquire('session'):
            question, future = guard.question(('yes', 'no'))
            await asyncio.to_thread(guard.answer, 'session', question, 'yes')
            assert await asyncio.wait_for(future, 1) == 'yes'
            with pytest.raises(ValueError):
                guard.answer('session', question, 'no')
    asyncio.run(scenario(), debug=True)


def test_bulk_admission_is_denied_during_mutation():
    guard = BulkOperationGuard()
    with guard.track_mutation():
        with pytest.raises(BulkOperationBusy):
            with guard.acquire('session'):
                raise AssertionError('Concurrent bulk operation admitted')
    with guard.acquire('session'):
        assert guard.operation_id
