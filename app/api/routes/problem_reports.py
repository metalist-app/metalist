"""Problem reports (docs/ready-to-build/error-reports.md): the page sends its draft, the server
fills in the notes, redacts, checks and keeps the report, and gives it back to be saved.

Neither POST waits for its turn to change the vault: a report is often made because a change
is stuck, and keeping one writes a file in the vault's `reports` folder, never the vault.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
import re

from app.api.request_auth import require_request_auth_token
from app.api.transactions import read_only_route
from app.services import problem_report_store, request_history, safe_log
from app.services.note_store import store as note_store
from app.services.problem_report_builder import (
    Draft,
    DraftCommand,
    DraftInput,
    DraftNote,
    DraftRequest,
    build_report,
)
from app.services.problem_report_check import MADE_BY_OVERLAY, MAX_DESCRIPTION_CHARACTERS

router = APIRouter(prefix="/problem-reports", tags=["problem-reports"])

MAX_ENTRIES = 5000
MAX_NOTES = 200
MAX_TEXT = 10000
MAX_SHORT = 200
MAX_FRAMES = 50
MAX_KEPT_IDS = 20

Short = Annotated[str, Field(max_length=MAX_SHORT)]
LongText = Annotated[str, Field(max_length=MAX_TEXT)]
Count = Annotated[float, Field(ge=0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DraftErrorBody(_Strict):
    className: Short
    message: LongText
    frames: list[Short] = Field(max_length=MAX_FRAMES)


class DraftWindowBody(_Strict):
    w: Annotated[int, Field(ge=0)]
    h: Annotated[int, Field(ge=0)]


class DraftViewBody(_Strict):
    notesInList: Annotated[int, Field(ge=0)]
    notesOnScreen: Annotated[int, Field(ge=0)]
    scrollY: Count


class DraftInputBody(_Strict):
    t: Count
    kind: Short
    note: Short
    part: Short
    control: Short
    command: Short
    code: Short
    mods: list[Short] = Field(max_length=MAX_FRAMES)
    typed: LongText


class DraftCommandBody(_Strict):
    t: Count
    label: Short
    ms: Count
    outcome: Short


class DraftRequestBody(_Strict):
    t: Count
    method: Short
    path: LongText
    status: Annotated[int, Field(ge=0)]
    ms: Count
    requestId: Short


class DraftBody(_Strict):
    madeBy: Literal["overlay", "user"]
    description: Annotated[str, Field(max_length=MAX_DESCRIPTION_CHARACTERS)]
    error: DraftErrorBody
    window: DraftWindowBody
    view: DraftViewBody
    theme: Short
    skin: Short
    preferences: list[Short] = Field(max_length=MAX_SHORT)
    editingNote: Short
    search: LongText
    noteIds: list[Short] = Field(max_length=MAX_NOTES)
    inputs: list[DraftInputBody] = Field(max_length=MAX_ENTRIES)
    commands: list[DraftCommandBody] = Field(max_length=MAX_ENTRIES)
    requests: list[DraftRequestBody] = Field(max_length=MAX_ENTRIES)


class ExportBody(_Strict):
    reportIds: list[Short] = Field(min_length=1, max_length=MAX_KEPT_IDS)


_TEMPLATE_PARAMETER = re.compile(r"\{[^}/]+\}")


def _template_pattern(template: str) -> re.Pattern[str]:
    pattern = re.escape(template)
    pattern = re.sub(r"\\\{[^}/]+:path\\\}", ".+", pattern)
    pattern = re.sub(r"\\\{[^}/]+\\\}", "[^/]+", pattern)
    return re.compile(pattern)


def _route_of(*, path: str) -> str:
    """The route the app declares for a path the page requested: what the safe log writes,
    never the path itself (it can hold a vault's or a file's name). A literal route wins over
    one with parameters (`/notes/new` over `/notes/{note_id}`)."""
    if path.startswith("/static/"):
        return safe_log.STATIC_ROUTE
    candidates = [
        template for template in safe_log.declared_routes()
        if template.startswith("/") and _template_pattern(template).fullmatch(path) is not None
    ]
    if not candidates:
        return safe_log.NO_ROUTE
    return min(candidates, key=lambda template: (len(_TEMPLATE_PARAMETER.findall(template)), template))


def _draft(request: Request, body: DraftBody) -> Draft:
    return Draft(
        made_by=body.madeBy,
        description=body.description,
        error_class=body.error.className,
        error_message=body.error.message,
        error_frames=tuple(body.error.frames),
        window_width=body.window.w,
        window_height=body.window.h,
        notes_in_list=body.view.notesInList,
        notes_on_screen=body.view.notesOnScreen,
        scroll_y=body.view.scrollY,
        theme=body.theme,
        skin=body.skin,
        preferences=tuple(body.preferences),
        editing_note=body.editingNote,
        search=body.search,
        note_ids=tuple(dict.fromkeys(body.noteIds)),
        inputs=tuple(DraftInput(
            t=item.t, kind=item.kind, note=item.note, part=item.part, control=item.control,
            command=item.command, code=item.code, mods=tuple(item.mods), typed=item.typed,
        ) for item in body.inputs),
        commands=tuple(DraftCommand(t=item.t, label=item.label, ms=item.ms, outcome=item.outcome) for item in body.commands),
        requests=tuple(DraftRequest(
            t=item.t, method=safe_log.method_for_log(item.method),
            route=_route_of(path=item.path),
            status=item.status, ms=item.ms, request_id=item.requestId,
        ) for item in body.requests),
    )


def _read_note(note_id: str) -> DraftNote | None:
    """A note the server holds, or None for one deleted since the page showed it."""
    if not note_store.has_note(note_id):
        return None
    record = note_store.get_note(note_id)
    return DraftNote(
        note_id=record.id,
        parent_id=record.parent_id,
        previous_id=record.prev_id,
        is_folded=record.is_collapsed,
        tags=tuple(sorted(record.tag_terms)),
        text=note_store.kept_text(note_id),
    )


def _vault_tags() -> frozenset[str]:
    return frozenset(tag.casefold() for record in note_store.snapshot().values() for tag in record.tag_terms)


@router.post("")
@read_only_route
def make_problem_report(request: Request, body: DraftBody) -> dict[str, object]:
    """Builds, checks and keeps a report; answers it to be saved."""
    require_request_auth_token(request)
    # A report the final check refuses raises ReportRefused, rejected input: the calm banner.
    report = build_report(
        _draft(request, body), read_note=_read_note, real_tags=_vault_tags(), now=request_history.now(),
    )
    report_id = problem_report_store.keep_report(report)
    return {"reportId": report_id, "report": report}


@router.post("/unsaved")
@read_only_route
def make_unsaved_problem_report(request: Request, body: DraftBody) -> dict[str, object]:
    """A report from the login page (decided 2026-11-12): no vault is open, so it has no notes
    and is kept nowhere; the page holds it in memory to be saved."""
    if body.noteIds or body.search != "" or body.editingNote != "":
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="A report from the login page holds no notes or search")
    report = build_report(
        _draft(request, body), read_note=_read_note, real_tags=frozenset(), now=request_history.now(),
    )
    return {"report": report}


@router.get("")
def list_problem_reports(request: Request) -> dict[str, object]:
    """The kept reports, newest first: id, when made, and what made it."""
    require_request_auth_token(request)
    return {"reports": [
        {
            "reportId": kept.report_id,
            "madeAt": kept.report["madeAt"],
            "madeBy": kept.report["madeBy"],
            "errorClass": kept.report["error"]["class"] if kept.report["madeBy"] == MADE_BY_OVERLAY else "",
        }
        for kept in problem_report_store.kept_reports()
    ]}


@router.post("/export")
@read_only_route
def export_problem_reports(request: Request, body: ExportBody) -> dict[str, object]:
    require_request_auth_token(request)
    return {"reports": [kept.report for kept in problem_report_store.reports_by_id(body.reportIds)]}
