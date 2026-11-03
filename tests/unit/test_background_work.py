"""Work the server does beside the requests is shown to the user as it goes (the maintainer,
2026-11-02: "if there's stuff being computed in the background, I would like the user to have
some awareness of that"): each piece of work says what it is and how far it got."""

from __future__ import annotations

import pytest

from app.services.background_work import BackgroundWork


def test_work_is_listed_while_it_runs_with_how_far_it_got() -> None:
    work = BackgroundWork()
    assert work.snapshot() == []
    with work.track("file-texts", "Reading PDF text", total=3) as progress:
        assert work.snapshot() == [{"key": "file-texts", "label": "Reading PDF text", "done": 0, "total": 3, "elapsedSeconds": 0}]
        progress.advance()
        progress.advance()
        assert work.snapshot()[0]["done"] == 2
    assert work.snapshot() == []


def test_work_that_fails_leaves_the_list_and_the_failure_goes_on() -> None:
    work = BackgroundWork()
    with pytest.raises(RuntimeError, match="broke"):
        with work.track("import", "Importing files", total=2):
            raise RuntimeError("broke")
    assert work.snapshot() == []


def test_progress_never_passes_its_total_and_one_key_runs_once() -> None:
    work = BackgroundWork()
    with work.track("import", "Importing files", total=1) as progress:
        progress.advance()
        with pytest.raises(AssertionError):
            progress.advance()
        with pytest.raises(AssertionError):
            with work.track("import", "Importing files", total=1):
                pass
    with pytest.raises(ValueError):
        with work.track("import", "Importing files", total=-1):
            pass


def test_work_says_how_long_it_has_run(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("app.services.background_work.time.monotonic", lambda: clock[0])
    work = BackgroundWork()
    with work.track("import", "Importing files", total=4):
        clock[0] = 112.7
        assert work.snapshot()[0]["elapsedSeconds"] == 12
