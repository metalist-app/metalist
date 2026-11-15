"""The vault's one AI conversation, live in every view (multi-view editing step 5;
docs/ready-to-build/multi-view-editing.md, "Step 5's cases"): one answer at a time in the order
sent, Stop and Clear from any view, the AI's question shown everywhere."""

from __future__ import annotations

import asyncio

from app.services.ai_chat_live import AiChatLive

MAC = "view-mac"
PHONE = "view-phone"


def _never_summarizing() -> bool:
    return False


async def _answer(live: AiChatLive, *, content: str, view_id: str, log: list[str], hold: asyncio.Event) -> None:
    ticket = live.enqueue(content=content, view_id=view_id)
    async for _ in live.wait_for_turn(ticket=ticket, is_answer_written=_never_summarizing):
        log.append(f"{content} waits")
    if not live.take_turn(ticket=ticket):
        log.append(f"{content} dropped")
        return
    log.append(f"{content} answered")
    await hold.wait()
    live.end_answer()


async def _stopped(live: AiChatLive, answer: asyncio.Task, *, content: str, log: list[str]) -> None:
    """Stop cancels the answer's task, as a real answer's; its ending is done here, as the real
    one does it in its own finally."""
    await asyncio.wait([answer])
    assert answer.cancelled(), f"{content} should have been stopped"
    log.append(f"{content} stopped")
    live.end_answer()


def test_a_question_sent_while_an_answer_is_written_waits_its_turn_in_order() -> None:
    async def scenario() -> list[str]:
        live = AiChatLive()
        log: list[str] = []
        first_done, second_done = asyncio.Event(), asyncio.Event()
        first = asyncio.create_task(_answer(live, content="first", view_id=MAC, log=log, hold=first_done))
        await asyncio.sleep(0)
        second = asyncio.create_task(_answer(live, content="second", view_id=PHONE, log=log, hold=second_done))
        await asyncio.sleep(0.05)
        assert [waiting["content"] for waiting in live.state(view_id=MAC)["waiting"]] == ["second"]
        assert live.state(view_id=PHONE)["waiting"][0]["isOwn"] is True
        first_done.set()
        await first
        await asyncio.sleep(0.5)
        second_done.set()
        await second
        return log

    assert asyncio.run(scenario()) == ["first answered", "second waits", "second answered"]


def test_stop_from_any_view_ends_the_answer_and_the_waiting_one_starts() -> None:
    async def scenario() -> list[str]:
        live = AiChatLive()
        log: list[str] = []
        never, second_done = asyncio.Event(), asyncio.Event()
        first = asyncio.create_task(_answer(live, content="first", view_id=MAC, log=log, hold=never))
        await asyncio.sleep(0)
        second = asyncio.create_task(_answer(live, content="second", view_id=PHONE, log=log, hold=second_done))
        await asyncio.sleep(0.05)
        live.stop(drops_waiting=False)
        await _stopped(live, first, content="first", log=log)
        await asyncio.sleep(0.5)
        second_done.set()
        await second
        return log

    assert asyncio.run(scenario()) == ["first answered", "second waits", "first stopped", "second answered"]


def test_clear_chat_drops_the_waiting_questions_too() -> None:
    async def scenario() -> list[str]:
        live = AiChatLive()
        log: list[str] = []
        never = asyncio.Event()
        first = asyncio.create_task(_answer(live, content="first", view_id=MAC, log=log, hold=never))
        await asyncio.sleep(0)
        second = asyncio.create_task(_answer(live, content="second", view_id=PHONE, log=log, hold=never))
        await asyncio.sleep(0.05)
        live.stop(drops_waiting=True)
        await _stopped(live, first, content="first", log=log)
        await second
        assert live.is_answering() is False
        return log

    assert asyncio.run(scenario()) == ["first answered", "second waits", "first stopped", "second dropped"]


def test_the_ais_question_shows_in_every_view_until_answered() -> None:
    live = AiChatLive()
    question = {"type": "bulk_question", "question_id": "q-1", "kind": "change_confirmation"}

    live.show_question(question)
    assert live.state(view_id=PHONE)["question"] == question

    live.end_question()
    assert live.state(view_id=PHONE)["question"] is None
