"""Turns the page's draft of a problem report into the report itself
(docs/ready-to-build/error-reports.md, sections 1-3). The page keeps no note text, so the
server, which holds the notes, fills them in and redacts everything here; the final check
(app/services/problem_report_check.py) then decides whether the report may be kept.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.services import request_history
from app.services.problem_report_check import MADE_BY_USER, UNLISTED_COMMAND, check_report
from app.services.problem_report_redaction import (
    SEARCH_MARKS,
    SPEC,
    StandInMap,
    hide_credential_values,
    make_stand_ins,
    shape,
    shape_note_text,
    shape_search,
)
from app.version import __version__


@dataclass(frozen=True)
class DraftNote:
    """A note as the server holds it, read for a report."""

    note_id: str
    parent_id: str | None
    previous_id: str | None
    is_folded: bool
    tags: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class DraftInput:
    t: float
    kind: str
    note: str
    part: str
    control: str
    command: str
    code: str
    mods: tuple[str, ...]
    typed: str


@dataclass(frozen=True)
class DraftCommand:
    t: float
    label: str
    ms: float
    outcome: str


@dataclass(frozen=True)
class DraftRequest:
    t: float
    method: str
    route: str
    status: int
    ms: float
    request_id: str


@dataclass(frozen=True)
class Draft:
    made_by: str
    description: str
    error_class: str
    error_message: str
    error_frames: tuple[str, ...]
    window_width: int
    window_height: int
    notes_in_list: int
    notes_on_screen: int
    scroll_y: float
    theme: str
    skin: str
    preferences: tuple[str, ...]
    editing_note: str
    search: str
    note_ids: tuple[str, ...]
    inputs: tuple[DraftInput, ...]
    commands: tuple[DraftCommand, ...]
    requests: tuple[DraftRequest, ...]


def _search_tags(search: str, *, real_tags: frozenset[str]) -> frozenset[str]:
    words = (word.strip(SEARCH_MARKS).casefold() for word in search.split())
    return frozenset(word for word in words if word in real_tags)


def build_report(
    draft: Draft,
    *,
    read_note: Callable[[str], DraftNote | None],
    real_tags: frozenset[str],
    now: float,
) -> dict:
    """The report, redacted and checked; ReportRefused if any value is not one MetaList vouches
    for. read_note gives a note the server holds, or None for one no longer there."""
    notes = [note for note in (read_note(note_id) for note_id in draft.note_ids) if note is not None]
    report_tags = {tag for note in notes for tag in note.tags} | _search_tags(draft.search, real_tags=real_tags)
    stand_ins = make_stand_ins(report_tags)
    answered = request_history.REQUEST_HISTORY.answered_by_id(
        (request.request_id for request in draft.requests if request.request_id != ""), now=now,
    )
    report = {
        "metalist": __version__,
        "madeAt": now,
        "madeBy": draft.made_by,
        "description": draft.description,
        "window": {"w": draft.window_width, "h": draft.window_height},
        "view": {"notesInList": draft.notes_in_list, "notesOnScreen": draft.notes_on_screen, "scrollY": draft.scroll_y},
        "theme": draft.theme,
        "skin": draft.skin,
        "preferences": list(draft.preferences),
        "editingNote": draft.editing_note,
        "search": {
            "text": {"redacted": shape_search(draft.search, stand_ins=stand_ins)},
            "standIns": sorted(stand_ins.stand_ins - SPEC.meta_tags),
        },
        "notes": [_note(note, stand_ins) for note in notes],
        "inputs": [_input(item) for item in draft.inputs],
        "commands": [_command(item) for item in draft.commands],
        "requests": [_request(item, answered) for item in draft.requests],
        "slow": [_slow(item, now=now) for item in request_history.REQUEST_HISTORY.slow_requests(now=now)],
        "error": None if draft.made_by == MADE_BY_USER else {
            "class": draft.error_class,
            "message": {"redacted": shape(draft.error_message)},
            "frames": list(draft.error_frames),
        },
    }
    check_report(report, real_tags=real_tags)
    return report


def _note(note: DraftNote, stand_ins: StandInMap) -> dict:
    return {
        "id": note.note_id,
        "parent": note.parent_id,
        "previous": note.previous_id,
        "folded": note.is_folded,
        "tags": sorted(stand_ins.stand_in(tag) for tag in note.tags),
        "text": {"redacted": _note_text(note)},
    }


def _note_text(note: DraftNote) -> str:
    """A @password or @username note shows only the fixed hidden value, as in exports; any
    other note keeps its shape."""
    hidden = hide_credential_values(note.text, tags=note.tags)
    if hidden != note.text:
        return hidden
    return shape_note_text(note.text)


def _listed_label(label: str) -> str:
    """A command label MetaList lists, as it is; any other becomes `unlisted`, so a label built
    from a value at run time can never carry text into a report."""
    if label in SPEC.command_labels:
        return label
    return UNLISTED_COMMAND


def _input(item: DraftInput) -> dict:
    command = item.command
    if command != "":
        command = _listed_label(command)
    return {
        "t": item.t, "kind": item.kind, "note": item.note, "part": item.part, "control": item.control,
        "command": command, "code": item.code, "mods": sorted(item.mods),
        "typed": {"redacted": shape(item.typed)},
    }


def _command(item: DraftCommand) -> dict:
    return {"t": item.t, "label": _listed_label(item.label), "ms": item.ms, "outcome": item.outcome}


def _request(item: DraftRequest, answered: Mapping[str, request_history.AnsweredRequest]) -> dict:
    """A request as the page saw it, with the server's own record of it when it still has one
    (it keeps 10 minutes; a request refused before its middleware has none)."""
    server = {"found": False, "waitedMs": 0.0, "errorType": "", "codeLocation": ""}
    if item.request_id in answered:
        record = answered[item.request_id]
        server = {
            "found": True, "waitedMs": record.waited_ms,
            "errorType": record.error_type, "codeLocation": record.code_location,
        }
    return {
        "t": item.t, "method": item.method, "route": item.route, "status": item.status, "ms": item.ms,
        "requestId": item.request_id, "server": server,
    }


def _slow(item: request_history.SlowRequest, *, now: float) -> dict:
    return {
        "secondsAgo": max(now - item.answered_at, 0.0), "method": item.method, "route": item.route,
        "status": item.status, "ms": item.duration_ms, "waitedMs": item.waited_ms, "requestId": item.request_id,
        "machineCpuPercent": item.busy.machine_cpu_percent,
        "machineAvailableBytes": item.busy.machine_available_bytes,
        "swapUsedBytes": item.busy.swap_used_bytes,
        "metalistCpuPercent": item.busy.metalist_cpu_percent,
        "metalistMemoryBytes": item.busy.metalist_memory_bytes,
    }

