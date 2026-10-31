"""Ticking a task in a Markdown note (docs/ui/content-formatting.md, Tasks; agreed
2026-10-31): a click on box N changes that task's mark in the stored HTML, and nothing
else; a note that changed under the box is refused, never ticked on the wrong line."""

from __future__ import annotations

import pytest

import app.usecases.toggle_markdown_task as module
from app.services.input_errors import InputRejected
from app.services.markdown_tasks import toggle_task_in_note_html

NOTE_HTML = (
    "<div>Groceries</div><div>-&nbsp;[ ] milk</div><div>- [x] <b>bread</b></div>"
    "<div>&nbsp; - [X] nested</div><div>&gt; - [&nbsp;] quoted</div>"
    "<div>```</div><div>- [ ] in code</div><div>```</div><div>1. [ ] last</div>"
)


@pytest.mark.parametrize(("task_index", "is_ticked", "before", "after"), [
    (0, True, "-&nbsp;[ ] milk", "-&nbsp;[x] milk"),
    (1, False, "- [x] <b>bread</b>", "- [ ] <b>bread</b>"),
    (2, False, "&nbsp; - [X] nested", "&nbsp; - [ ] nested"),
    (3, True, "&gt; - [&nbsp;] quoted", "&gt; - [x] quoted"),
    # The task in the code fence is not one: box 4 is the last line.
    (4, True, "1. [ ] last", "1. [x] last"),
])
def test_a_click_changes_only_its_tasks_mark(task_index: int, is_ticked: bool, before: str, after: str) -> None:
    toggled = toggle_task_in_note_html(content_html=NOTE_HTML, task_index=task_index, is_ticked=is_ticked)
    assert toggled == NOTE_HTML.replace(before, after)


@pytest.mark.parametrize(("task_index", "is_ticked"), [
    # Already as asked: a second click before the first one's redraw.
    (0, False),
    (1, True),
    # No such box any more.
    (5, True),
])
def test_a_note_changed_under_the_box_is_refused(task_index: int, is_ticked: bool) -> None:
    with pytest.raises(InputRejected, match="try the box again"):
        toggle_task_in_note_html(content_html=NOTE_HTML, task_index=task_index, is_ticked=is_ticked)


def test_leading_blank_lines_do_not_shift_the_boxes() -> None:
    html = "<div><br></div><div><br></div><div>- [ ] first</div><div>- [ ] second</div>"
    toggled = toggle_task_in_note_html(content_html=html, task_index=1, is_ticked=True)
    assert toggled == html.replace("- [ ] second", "- [x] second")


class _Record:
    def __init__(self, content: str, tags: str):
        self.content = content
        self.tags = tags


def _command(monkeypatch: pytest.MonkeyPatch, *, tags: str) -> tuple[object, list, list]:
    record = _Record("<div>- [ ] milk</div>", tags)
    saved: list = []
    undo: list = []
    monkeypatch.setattr(module, "store", type("Store", (), {"get": staticmethod(lambda note_id: record)})())
    monkeypatch.setattr(module, "apply_update_content", lambda note_id, content, tags, token: saved.append(content))
    monkeypatch.setattr(module.undo_state, "record_update", lambda *args, **kwargs: undo.append(kwargs))
    command = module.CmdToggleMarkdownTask(
        note_id="n", task_index=0, is_ticked=True, token="t", client_id="c", undo_context="u", viewport={},
    )
    return command, saved, undo


def test_a_click_saves_the_note_as_one_undo_step(monkeypatch: pytest.MonkeyPatch) -> None:
    command, saved, undo = _command(monkeypatch, tags="@markdown")
    command.execute()
    assert saved == ["<div>- [x] milk</div>"]
    assert [(step["before"], step["after"]) for step in undo] == [("<div>- [ ] milk</div>", "<div>- [x] milk</div>")]


def test_a_note_no_longer_markdown_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    command, saved, undo = _command(monkeypatch, tags="groceries")
    with pytest.raises(InputRejected, match="no longer Markdown"):
        command.execute()
    assert saved == [] and undo == []
