from __future__ import annotations

from http import HTTPStatus
from io import BytesIO
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.api.note_requests import DiscardFileEditSessionRequest, FinishFileEditSessionRequest, RenameFileRequest
from app.api.transactions import serialized_read_route, transactional_route
from app.api.byte_ranges import UNSATISFIABLE_RANGE, resolve_byte_range
from app.api.streaming_upload import declared_body_bytes, receive_upload
from app.api.upload_limits import read_attachment
from app.api.request_auth import require_request_auth_token
from app.services.disk_space import full_disk_is_rejected, require_room_for_files
from app.services.file_registry import file_registry
from app.upload_limits import MAX_IN_MEMORY_FILE_BYTES
from app.services.email_files import email_attachment, is_email_file, read_email
from app.services.file_view import (
    NO_VIEW, STATUS_READY, STATUS_TOO_LARGE, VIEW_EMAIL, VIEW_PAGE, VIEW_PDF, build_email_view, build_file_view, view_kind_of,
)
from app.services.note_fullscreen import build_file_view_markup
from app.services.note_store import store as note_store
from app.services.unused_files import trim as trim_unused_and_unrestorable_files, unused_files
from app.db.file_schema import FILE_PREVIEW_VARIANTS
from app.services.file_storage import (
    download_file,
    get_file_preview,
    get_file_reference_record,
    open_file_range,
    open_file_upload,
    rename_file,
    replace_file_content,
    store_file_previews,
)
from app.utils.sent_fields import sent_or_none
from app.usecases.file_edit_session import (
    CmdDiscardFileEditSession,
    CmdFinishFileEditSession,
    CmdStartFileEditSession,
)

router = APIRouter(prefix="/files", tags=["files"])

FILE_REVISION_HEADER = "X-MetaList-File-Revision"


class UploadedFileResponse(BaseModel):
    file_id: str
    reference_token: str
    title: str
    original_filename: str
    mime_type: str
    size_bytes: int
    thumbnail_kind: str


class FileContentUpdatedResponse(BaseModel):
    file_id: str
    content_revision: int
    size_bytes: int


class FilePreviewsStoredResponse(BaseModel):
    file_id: str
    content_revision: int


# A file's name, as read or just given by Rename File….
class FileRenamedResponse(BaseModel):
    file_id: str
    name: str


class TrimUnusedFilesResponse(BaseModel):
    deleted_count: int
    deleted_file_ids: list[str]


def _require_bearer_token(request: Request) -> str:
    return require_request_auth_token(request)


def _require_known_file(file_id: str) -> None:
    if not file_registry.has_file(file_id):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File not found: {file_id}")


@router.post("/upload", response_model=UploadedFileResponse)
@transactional_route
async def upload_file_endpoint(request: Request):
    """A file of any size, encrypted and written as it arrives (docs/ready-to-build/streaming-no-file-cap.md)."""
    token = _require_bearer_token(request)
    declared_bytes = declared_body_bytes(request)
    if declared_bytes is not None:
        require_room_for_files([declared_bytes])
    with full_disk_is_rejected(), open_file_upload(token=token) as upload:
        file_part, _fields = await receive_upload(request, open_sink=lambda _part, _sent: upload)
        record = await run_in_threadpool(upload.finish, original_filename=file_part.filename, mime_type=file_part.content_type)
    return UploadedFileResponse(
        file_id=record.id,
        reference_token=f"![[{record.id}]]",
        title=record.title,
        original_filename=record.original_filename,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        thumbnail_kind=record.thumbnail_kind,
    )


@router.get("/{file_id}/download")
def download_file_endpoint(request: Request, file_id: str):
    token = _require_bearer_token(request)
    if not file_registry.has_file(file_id):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File not found: {file_id}")

    record = get_file_reference_record(file_id, token)
    byte_range = resolve_byte_range(sent_or_none(request.headers, "range"), file_size=record.size_bytes)
    if byte_range is UNSATISFIABLE_RANGE:
        return Response(
            status_code=HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{record.size_bytes}"},
        )
    start, length = 0, record.size_bytes
    if byte_range is not None:
        start, length = byte_range.start, byte_range.length
    opened = open_file_range(file_id=file_id, token=token, start=start, length=length)
    quoted_filename = quote(record.original_filename, safe="")
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}",
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        FILE_REVISION_HEADER: str(record.content_revision),
    }
    if byte_range is None:
        return StreamingResponse(opened.pieces, media_type=record.mime_type, headers=headers)
    headers["Content-Range"] = f"bytes {start}-{start + length - 1}/{record.size_bytes}"
    return StreamingResponse(
        opened.pieces, status_code=HTTPStatus.PARTIAL_CONTENT, media_type=record.mime_type, headers=headers,
    )


def _downloaded_email(request: Request, file_id: str):
    token = _require_bearer_token(request)
    if not file_registry.has_file(file_id):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File not found: {file_id}")
    downloaded = download_file(file_id, token)
    if not is_email_file(mime_type=downloaded.record.mime_type, original_filename=downloaded.record.original_filename):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File is not an email: {file_id}")
    return downloaded


@router.get("/{file_id}/view")
@serialized_read_route
def view_file_endpoint(request: Request, file_id: str) -> dict[str, object]:
    """A file as the viewer shows it (docs/ready-to-build/files-shown-not-copied.md §4), made
    now and never stored: its name; "pdf" (the browser's viewer shows the downloaded file), or
    "page" with its status and its note HTML (`isCut`: a text file's first 5 MB only)."""
    token = _require_bearer_token(request)
    file_name = file_registry.title_of(file_id)
    if file_name is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File not found: {file_id}")
    kind = view_kind_of(file_name)
    if kind == VIEW_PDF:
        return {"name": file_name, "kind": VIEW_PDF, "status": STATUS_READY, "html": "", "isCut": False}
    if get_file_reference_record(file_id, token).size_bytes > MAX_IN_MEMORY_FILE_BYTES:
        return {"name": file_name, "kind": VIEW_PAGE, "status": STATUS_TOO_LARGE, "html": "", "isCut": False}
    downloaded = download_file(file_id, token)
    record = downloaded.record
    # An email (or a web page saved whole) by its type or name, as its card is (2026-11-03).
    if is_email_file(mime_type=record.mime_type, original_filename=record.original_filename):
        return _email_view(file_id, file_name, downloaded.content_bytes)
    if kind == NO_VIEW:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"File has no viewer: {file_id}")
    view = build_file_view(original_filename=record.original_filename, content_bytes=downloaded.content_bytes)
    if view.status != STATUS_READY:
        return {"name": file_name, "kind": VIEW_PAGE, "status": view.status, "html": "", "isCut": False}
    return {
        "name": file_name, "kind": VIEW_PAGE, "status": STATUS_READY, "html": build_file_view_markup(file_id, view),
        "isCut": view.is_cut,
    }


def _email_view(file_id: str, file_name: str, content_bytes: bytes) -> dict[str, object]:
    """An email in the viewer: its subject, From, To, Cc and Date, its body drawn as a note's,
    and its attachments by name and size (each downloaded by its index)."""
    view, email = build_email_view(content_bytes)
    body = ""
    if view.status == STATUS_READY:
        body = build_file_view_markup(file_id, view)
    return {
        "name": file_name, "kind": VIEW_EMAIL, "status": view.status, "html": body, "isCut": False,
        "email": {
            "subject": email.subject, "from": email.sender, "to": email.to, "cc": email.cc, "date": email.date,
            "attachments": [{"name": attachment.name, "sizeBytes": attachment.size_bytes} for attachment in email.attachments],
        },
    }


@router.get("/{file_id}/email")
def read_email_endpoint(request: Request, file_id: str) -> dict[str, object]:
    """An email file as its card shows it (docs/ui/references.md, "Email files")."""
    downloaded = _downloaded_email(request, file_id)
    email = read_email(downloaded.content_bytes)
    return {
        "isReadable": email.is_readable,
        "from": email.sender, "fromName": email.sender_name, "to": email.to, "cc": email.cc, "date": email.date, "subject": email.subject,
        "html": email.body_html, "text": email.body_text,
        "attachments": [
            {"name": attachment.name, "contentType": attachment.content_type, "sizeBytes": attachment.size_bytes}
            for attachment in email.attachments
        ],
        "revision": downloaded.record.content_revision,
    }


@router.get("/{file_id}/email/attachments/{index}")
def download_email_attachment_endpoint(request: Request, file_id: str, index: int):
    downloaded = _downloaded_email(request, file_id)
    attachments_count = len(read_email(downloaded.content_bytes).attachments)
    if not 0 <= index < attachments_count:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"The email has no attachment {index}")
    attachment, payload = email_attachment(downloaded.content_bytes, index)
    return StreamingResponse(
        BytesIO(payload), media_type=attachment.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(attachment.name, safe='')}"},
    )


@router.put("/{file_id}/content", response_model=FileContentUpdatedResponse)
@transactional_route
async def replace_file_content_endpoint(
    request: Request,
    file_id: str,
    file: Annotated[UploadFile, File()],
    expected_revision: Annotated[int, Form()],
):
    token = _require_bearer_token(request)
    _require_known_file(file_id)
    content_bytes = await read_attachment(file)
    record = replace_file_content(
        file_id=file_id,
        content_bytes=content_bytes,
        expected_revision=expected_revision,
        token=token,
    )
    return FileContentUpdatedResponse(
        file_id=record.id,
        content_revision=record.content_revision,
        size_bytes=record.size_bytes,
    )


@router.get("/{file_id}/name", response_model=FileRenamedResponse)
def read_file_name_endpoint(request: Request, file_id: str):
    token = _require_bearer_token(request)
    _require_known_file(file_id)
    record = get_file_reference_record(file_id, token)
    return FileRenamedResponse(file_id=record.id, name=record.title)


@router.put("/{file_id}/name", response_model=FileRenamedResponse)
@transactional_route
def rename_file_endpoint(request: Request, file_id: str, body: RenameFileRequest):
    token = _require_bearer_token(request)
    _require_known_file(file_id)
    record = rename_file(file_id=file_id, name=body["name"], token=token)
    return FileRenamedResponse(file_id=record.id, name=record.title)


@router.put("/{file_id}/previews", response_model=FilePreviewsStoredResponse)
@transactional_route
async def store_file_previews_endpoint(
    request: Request,
    file_id: str,
    light: Annotated[UploadFile, File()],
    dark: Annotated[UploadFile, File()],
    content_revision: Annotated[int, Form()],
):
    token = _require_bearer_token(request)
    _require_known_file(file_id)
    previews_by_variant = {
        "light": await read_attachment(light),
        "dark": await read_attachment(dark),
    }
    record = store_file_previews(
        file_id=file_id,
        previews_by_variant=previews_by_variant,
        content_revision=content_revision,
        token=token,
    )
    return FilePreviewsStoredResponse(file_id=record.id, content_revision=record.content_revision)


@router.get("/{file_id}/previews/{variant}")
def download_file_preview_endpoint(request: Request, file_id: str, variant: str):
    token = _require_bearer_token(request)
    _require_known_file(file_id)
    if variant not in FILE_PREVIEW_VARIANTS:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"Unknown preview variant: {variant}")
    preview = get_file_preview(file_id=file_id, variant=variant, token=token)
    return Response(
        content=preview.content_bytes,
        media_type=preview.mime_type,
        headers={FILE_REVISION_HEADER: str(preview.content_revision)},
    )


# A diagram editing session: opened with the editor, finished by Done (one undo step), or discarded.
@router.post("/{file_id}/edit-sessions")
@transactional_route
def start_file_edit_session_endpoint(request: Request, file_id: str) -> dict[str, object]:
    token = _require_bearer_token(request)
    _require_known_file(file_id)
    return CmdStartFileEditSession(file_id=file_id, token=token).execute()


@router.post("/{file_id}/edit-sessions/{session_id}/finish")
@transactional_route
def finish_file_edit_session_endpoint(
    request: Request,
    file_id: str,
    session_id: str,
    body: FinishFileEditSessionRequest,
) -> dict[str, object]:
    token = _require_bearer_token(request)
    _require_known_file(file_id)
    host_note_id = body["hostNoteId"]
    if not note_store.has_note(host_note_id):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"Note not found: {host_note_id}")
    return CmdFinishFileEditSession(
        file_id=file_id,
        session_id=session_id,
        host_note_id=host_note_id,
        content_revision=body["contentRevision"],
        is_new_diagram=body["isNewDiagram"],
        token=token,
        client_id=body["clientId"],
        undo_context=body["undoContext"],
        viewport=body["viewport"],
    ).execute()


@router.post("/{file_id}/edit-sessions/{session_id}/discard")
@transactional_route
def discard_file_edit_session_endpoint(
    request: Request,
    file_id: str,
    session_id: str,
    body: DiscardFileEditSessionRequest,
) -> dict[str, object]:
    token = _require_bearer_token(request)
    _require_known_file(file_id)
    return CmdDiscardFileEditSession(
        file_id=file_id,
        session_id=session_id,
        content_revision=body["contentRevision"],
        token=token,
    ).execute()


class UnusedFilesResponse(BaseModel):
    count: int
    size_bytes: int


# What Trim Unused Files would delete now: the trim reminder's total and the confirmation's.
@router.get("/unused", response_model=UnusedFilesResponse)
def list_unused_files(request: Request):
    _require_bearer_token(request)
    summary = unused_files()
    return UnusedFilesResponse(count=summary.count, size_bytes=summary.size_bytes)


@router.post("/trim-unused", response_model=TrimUnusedFilesResponse)
@transactional_route
def trim_unused_files_endpoint(request: Request):
    _require_bearer_token(request)
    result = trim_unused_and_unrestorable_files()
    return TrimUnusedFilesResponse(
        deleted_count=result.deleted_count,
        deleted_file_ids=result.deleted_file_ids,
    )
