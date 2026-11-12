from __future__ import annotations

from concurrent.futures import Future
from loguru import logger

from app.api.routes import auth as auth_routes


def test_hydration_worker_failure_keeps_type_without_exception_message(
    monkeypatch,
) -> None:
    captured_messages: list[str] = []
    monkeypatch.setattr(auth_routes.hydration_state, "fail", captured_messages.append)
    future: Future[None] = Future()
    future.set_exception(AssertionError("PRIVATE_NOTE_CONTENT"))

    records: list[str] = []
    sink_id = logger.add(lambda message: records.append(str(message)), level="ERROR")
    try:
        auth_routes._on_hydration_done(future)
    finally:
        logger.remove(sink_id)

    assert captured_messages == ["AssertionError"]
    assert any("hydration.failed error_type=AssertionError" in record for record in records)
    assert "PRIVATE_NOTE_CONTENT" not in "".join(records)
