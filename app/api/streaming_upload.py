"""A multipart upload read as it arrives, so its file goes straight to where it is kept: never
whole in memory, and never in the plaintext temporary file a parsed form would spool it to."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import contextvars
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import ClientDisconnect

from app.services.input_errors import InputRejected
from app.utils.sent_fields import sent_or_none

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

# A form's text fields and a part's headers are short; only the file is unbounded.
_MAX_TEXT_BYTES = 64 * 1024
_END_OF_BODY = b""
_PART_HEADERS = "headers"
_PART_DATA = "data"
_PART_END = "end"


class UploadSink(Protocol):
    def write(self, content: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class FilePart:
    filename: str
    content_type: str


@dataclass(slots=True)
class _CurrentPart:
    field_name: str
    is_file: bool
    text: bytearray


class _PartEvents:
    """What the parser found in one chunk, in order, to be acted on outside its callbacks."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.is_complete = False
        self._headers: dict[bytes, bytes] = {}
        self._field = bytearray()
        self._value = bytearray()

    def callbacks(self) -> MultipartCallbacks:
        return {
            "on_part_begin": self._on_part_begin, "on_header_field": self._on_header_field, "on_header_value": self._on_header_value,
            "on_header_end": self._on_header_end, "on_headers_finished": self._on_headers_finished,
            "on_part_data": self._on_part_data, "on_part_end": self._on_part_end, "on_end": self._on_end,
        }

    def _on_part_begin(self) -> None:
        self._headers = {}

    def _on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._field += data[start:end]

    def _on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._value += data[start:end]
        if len(self._field) + len(self._value) > _MAX_TEXT_BYTES:
            raise InputRejected("That upload isn't one this server can read.")

    def _on_header_end(self) -> None:
        self._headers[bytes(self._field).lower()] = bytes(self._value)
        self._field.clear()
        self._value.clear()

    def _on_headers_finished(self) -> None:
        self.events.append((_PART_HEADERS, self._headers))

    def _on_part_data(self, data: bytes, start: int, end: int) -> None:
        self.events.append((_PART_DATA, bytes(data[start:end])))

    def _on_part_end(self) -> None:
        self.events.append((_PART_END, None))

    def _on_end(self) -> None:
        self.is_complete = True


def _new_parser(request: Request, events: _PartEvents) -> MultipartParser:
    content_type, options = parse_options_header(sent_or_none(request.headers, "content-type"))
    if content_type != b"multipart/form-data" or b"boundary" not in options:
        raise InputRejected("That upload isn't one this server can read.")
    return MultipartParser(options[b"boundary"], events.callbacks())


async def _read_chunk(stream) -> bytes:
    return await anext(stream, _END_OF_BODY)


async def _read_chunk_in_its_own_context(stream) -> bytes:
    return await asyncio.create_task(_read_chunk(stream), context=contextvars.Context())


async def _next_chunk(stream) -> bytes:
    """The next piece of the body, read in a context of its own. Reading can resume the
    connection's reader, and the event loop keeps the context it was resumed in for every later
    request on that connection, so the upload's open transaction must not be in it."""
    # lint: allow-PY001 rationale="a person cancelling an upload or losing the connection is expected, not a defect"
    try:
        return await _read_chunk_in_its_own_context(stream)
    # lint: allow-PY001 rationale="a person cancelling an upload or losing the connection is expected, not a defect"
    except ClientDisconnect as exc:
        raise InputRejected("The upload was interrupted before it finished.") from exc


def _parse(parser: MultipartParser, chunk: bytes) -> None:
    # lint: allow-PY001 rationale="a malformed upload body is rejected user input"
    try:
        parser.write(chunk)
    # lint: allow-PY001 rationale="a malformed upload body is rejected user input"
    except MultipartParseError as exc:
        raise InputRejected("That upload isn't one this server can read.") from exc


def _file_part(options: Mapping[bytes, bytes], headers: Mapping[bytes, bytes]) -> FilePart:
    filename = options[b"filename"].decode("utf-8", errors="replace")
    if filename == "":
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Uploaded file must include a filename")
    if b"content-type" not in headers or headers[b"content-type"] == b"":
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Uploaded file must include a non-empty MIME type")
    return FilePart(filename=filename, content_type=headers[b"content-type"].decode("latin-1"))


class _Receiver:
    def __init__(self, *, open_sink: Callable[[FilePart, Mapping[str, str]], UploadSink]) -> None:
        self._open_sink = open_sink
        self.fields: dict[str, str] = {}
        self.file_part: FilePart | None = None
        self._sink: UploadSink | None = None
        self._part: _CurrentPart | None = None

    def _begin(self, headers: Mapping[bytes, bytes]) -> None:
        if b"content-disposition" not in headers:
            raise InputRejected("That upload isn't one this server can read.")
        _disposition, options = parse_options_header(headers[b"content-disposition"])
        if b"name" not in options:
            raise InputRejected("That upload isn't one this server can read.")
        field_name = options[b"name"].decode("utf-8", errors="replace")
        is_file = b"filename" in options
        if is_file:
            if self.file_part is not None:
                raise InputRejected("Send one file at a time.")
            self.file_part = _file_part(options, headers)
            self._sink = self._open_sink(self.file_part, self.fields)
        self._part = _CurrentPart(field_name=field_name, is_file=is_file, text=bytearray())

    async def act_on(self, events: list[tuple[str, object]]) -> None:
        for kind, value in events:
            if kind == _PART_HEADERS:
                assert isinstance(value, dict)
                self._begin(value)
            elif kind == _PART_DATA:
                assert isinstance(value, bytes) and self._part is not None
                await self._take(value)
            else:
                assert self._part is not None
                if not self._part.is_file:
                    self.fields[self._part.field_name] = self._part.text.decode("utf-8", errors="replace")
                self._part = None

    async def _take(self, data: bytes) -> None:
        assert self._part is not None
        if self._part.is_file:
            assert self._sink is not None
            await run_in_threadpool(self._sink.write, data)
            return
        self._part.text += data
        if len(self._part.text) > _MAX_TEXT_BYTES:
            raise InputRejected("That upload isn't one this server can read.")


async def receive_upload(
    request: Request, *, open_sink: Callable[[FilePart, Mapping[str, str]], UploadSink],
) -> tuple[FilePart, dict[str, str]]:
    """Read the request's form as it arrives. Its one file goes to the sink open_sink returns, given
    the fields sent before it. Answers the file's name and type, and the form's text fields."""
    events = _PartEvents()
    parser = _new_parser(request, events)
    receiver = _Receiver(open_sink=open_sink)
    stream = request.stream()
    while True:
        chunk = await _next_chunk(stream)
        if chunk == _END_OF_BODY:
            break
        _parse(parser, chunk)
        pending = events.events
        events.events = []
        await receiver.act_on(pending)
    if not events.is_complete:
        raise InputRejected("The upload was interrupted before it finished.")
    if receiver.file_part is None:
        raise HTTPException(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail="The form must include a file")
    return receiver.file_part, receiver.fields


def declared_body_bytes(request: Request) -> int | None:
    """What the request says it will send, when it says so plainly."""
    declared = sent_or_none(request.headers, "content-length")
    if declared is None or not declared.isdigit():
        return None
    return int(declared)
