"""Site icons beside fetched link titles (docs/ui/content-formatting.md, Link icons).

Once per site (origin), the server reads the icons the site's front page declares (a
small one first, the apple-touch-icon after), else /favicon.ico; sites whose titles come
from oEmbed go straight to /favicon.ico. Requests take the same guards and per-site
turns as title lookups. SVG is refused; an icon must be a small decodable image (ICO
included) and is kept as one ICON_PIXELS-square PNG, encrypted like the titles. A site
without one is asked again after 1, 7, then every 30 days, and nothing is shown for it.
The store is loaded, unlocked and cleared with the link titles (a LinkTitleCompanion).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http import HTTPStatus
from io import BytesIO
import re
from threading import Lock, RLock
from typing import Mapping
from urllib.parse import urljoin, urlsplit
import warnings

import httpcore
import httpx
from PIL import IcoImagePlugin, Image, ImageOps, UnidentifiedImageError

import app.services.link_titles as link_titles
from app.config import TEST_MODE
from app.db.link_icons_sql import StoredLinkIconRow, fetch_all_link_icon_rows, insert_link_icon_row, update_link_icon_row
from app.db.session import begin_writer
from app.services.bulk_operation import bulk_operation_guard
from app.services.exception_capture import CapturedExceptionContext
from app.services.link_titles import (
    _FETCH_TIMEOUT_SECONDS,
    _MAX_REDIRECTS,
    _MAX_RESPONSE_BYTES,
    _OEMBED_ENDPOINTS,
    _USER_AGENT,
    _HostTurn,
    _SerializedTextField,
    _coerce_encryption_service,
    _coerce_optional_encryption_service,
    _decrypt_text_field,
    _encrypt_optional_text,
    _encryption_can_decrypt,
    _pacing_host,
    _rate_limit_cooldown_seconds,
    _serialize_text_with_service,
    link_title_fetcher,
    link_title_store,
    normalize_url_for_link_title,
)
from app.services.public_http import PinnedPublicHTTPTransport, PublicHttpTargetRejected, ResolvedPublicHttpTarget
from app.services.public_http import resolve_public_http_target as _resolve_public_http_target
from app.services.runtime_generation import current_generation
from app.utils.sent_fields import sent_or_none

_PinnedHTTPTransport = PinnedPublicHTTPTransport

# The stored icon's width and height: twice the text it sits beside, for sharp screens.
ICON_PIXELS = 32
# Sites often declare a full-size logo as their icon (a 454 KB PNG, a 4501-pixel square:
# 2026-10-25), so these are generous; only the shrunk PNG is kept.
_MAX_ICON_BYTES = 1024 * 1024
_MAX_ICON_SOURCE_PIXELS = 25_000_000
# Modes shrunk as they are; others (palette, 1-bit, CMYK...) become RGBA first.
_SHRINKABLE_MODES = frozenset({"L", "LA", "RGB", "RGBA"})
# A big image is first box-reduced to about this side, a band of rows at a time: Pillow's
# reduce and resize copy an RGBA image whole (to premultiply it), and a palette image becomes
# RGBA, so done at once either would double the memory the decoded image takes.
_REDUCED_SIDE = 128
_REDUCED_ROWS_PER_BAND = 8
# One image is opened at a time: a big one briefly takes tens of MB.
_SHRINK_LOCK = Lock()
# Declared icons tried per site before /favicon.ico.
_MAX_DECLARED_ATTEMPTS = 3
_FIRST_RETRY_DAYS = 1
_SECOND_RETRY_DAYS = 7
_LATER_RETRY_DAYS = 30
_MISSING_RETRY_DELAYS = (
    timedelta(days=_FIRST_RETRY_DAYS),
    timedelta(days=_SECOND_RETRY_DAYS),
    timedelta(days=_LATER_RETRY_DAYS),
)
_ICON_FORMATS = frozenset({"BMP", "GIF", "ICO", "JPEG", "PNG", "WEBP"})
_TRANSPARENT = (0, 0, 0, 0)
_HTTP_DEFAULT_PORT = 80
_HTTPS_DEFAULT_PORT = 443
_DEFAULT_PORTS = {"http": _HTTP_DEFAULT_PORT, "https": _HTTPS_DEFAULT_PORT}
_UNSAVED_ROW_ID = -1
_APPLE_TOUCH_ICON_RELS = frozenset({"apple-touch-icon", "apple-touch-icon-precomposed"})
_SIZE_RE = re.compile(r"(\d+)x(\d+)")
_DARK_SCHEME_MEDIA = "prefers-color-scheme:dark"
# Declared icons in groups: plain icons, then apple-touch-icons, then icons declared only
# for dark colour schemes (drawn light, for dark pages; MetaList's dark theme puts icons on
# a light tile, so a light one suits both themes).
_ICON_GROUP = 0
_APPLE_TOUCH_ICON_GROUP = 1
_DARK_SCHEME_ICON_GROUP = 2
# Declared icons in order: the smallest at least ICON_PIXELS wide, then those without
# sizes, then smaller ones, largest first.
_LARGE_ENOUGH_RANK = 0
_UNSIZED_RANK = 1
_TOO_SMALL_RANK = 2


@dataclass(frozen=True, slots=True)
class LinkIconFetchResult:
    origin: str
    icon_png_base64: str | None
    # "ok", "missing", or "deferred" (the site is cooling down: nothing is recorded).
    status: str
    last_error_kind: str | None


@dataclass(frozen=True, slots=True)
class LinkIconRecord:
    id: int
    origin: str
    icon_png_base64: str | None
    status: str
    last_error_kind: str | None
    failure_count: int
    last_checked_at: datetime
    next_check_after: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class _LinkIconState:
    stored_rows: tuple[StoredLinkIconRow, ...]
    records_by_origin: Mapping[str, LinkIconRecord]
    is_decrypted: bool


def icon_origin_for_url(url: str) -> str | None:
    """The site a link's icon belongs to: scheme, host and any non-default port."""
    normalized_url = normalize_url_for_link_title(url)
    if normalized_url is None:
        return None
    parts = urlsplit(normalized_url)
    hostname = parts.hostname
    if hostname is None or hostname == "":
        return None
    if ":" in hostname:
        hostname = f"[{hostname}]"
    if parts.port is None or _DEFAULT_PORTS[parts.scheme] == parts.port:
        return f"{parts.scheme}://{hostname}"
    return f"{parts.scheme}://{hostname}:{parts.port}"


class LinkIconStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._state: _LinkIconState | None = None
        self._in_flight: set[str] = set()

    def bootstrap(self, *, connection) -> None:
        rows = tuple(fetch_all_link_icon_rows(connection))
        state = _state_from_rows(stored_rows=rows, token="")
        with self._lock:
            self._state = state
            self._in_flight.clear()

    def ensure_decrypted(self, *, token: str) -> None:
        with self._lock:
            state = self._state
            if state is None:
                raise RuntimeError("LinkIconStore is not bootstrapped")
            if state.is_decrypted:
                return
            self._state = _state_from_rows(stored_rows=state.stored_rows, token=token)

    def reset(self) -> None:
        with self._lock:
            self._state = None
            self._in_flight.clear()

    def get_icon_base64(self, url: str) -> str | None:
        origin = icon_origin_for_url(url)
        if origin is None:
            return None
        with self._lock:
            state = self._state
            if state is None or not state.is_decrypted or origin not in state.records_by_origin:
                return None
            record = state.records_by_origin[origin]
        if record.status != "ok":
            return None
        assert record.icon_png_base64, f"ok link icon record missing its icon: {origin}"
        return record.icon_png_base64

    def maybe_enqueue_fetch(self, url: str) -> None:
        generation = current_generation()
        origin = icon_origin_for_url(url)
        if origin is None:
            return
        if TEST_MODE:
            return
        with self._lock:
            if not self._is_fetch_eligible_locked(origin=origin):
                return
            self._in_flight.add(origin)
        _submit_fetch(origin, generation)

    def discard_in_flight(self, origin: str) -> None:
        with self._lock:
            self._in_flight.discard(origin)

    def apply_current_fetch_result(self, result: LinkIconFetchResult, generation: int) -> None:
        with bulk_operation_guard.lock:
            if generation != current_generation():
                return
            self.apply_fetch_result(result)

    def apply_fetch_result(self, result: LinkIconFetchResult) -> None:
        if result.status not in {"ok", "missing"}:
            raise ValueError(f"Only found or missing icons are recorded, not {result.status}")
        assert icon_origin_for_url(result.origin) == result.origin, f"not an origin: {result.origin}"
        now = datetime.now(timezone.utc)
        with self._lock:
            state = self._state
            if state is None or not state.is_decrypted:
                self._in_flight.discard(result.origin)
                return
            previous = None
            if result.origin in state.records_by_origin:
                previous = state.records_by_origin[result.origin]
            record = _next_record(previous=previous, result=result, now=now)
            stored = _stored_row(record)
            with begin_writer() as connection:
                if previous is None:
                    record = replace(record, id=insert_link_icon_row(connection, stored))
                else:
                    update_link_icon_row(connection, stored)
            rows_by_id = {row.id: row for row in state.stored_rows}
            rows_by_id[record.id] = _plain_row(record)
            records_by_origin = dict(state.records_by_origin)
            records_by_origin[record.origin] = record
            self._state = _LinkIconState(
                stored_rows=tuple(rows_by_id[row_id] for row_id in sorted(rows_by_id)),
                records_by_origin=records_by_origin,
                is_decrypted=True,
            )
            self._in_flight.discard(result.origin)
        link_title_store.note_companion_change()

    def _is_fetch_eligible_locked(self, *, origin: str) -> bool:
        state = self._state
        if state is None or not state.is_decrypted or origin in self._in_flight:
            return False
        if origin not in state.records_by_origin:
            return True
        record = state.records_by_origin[origin]
        if record.status == "ok":
            return False
        assert record.next_check_after is not None, f"missing link icon without a next check: {origin}"
        return datetime.now(timezone.utc) >= record.next_check_after


def _submit_fetch(origin: str, generation: int) -> None:
    link_title_fetcher.submit_job(_run_fetch_job, origin, generation)


def _run_fetch_job(origin: str, generation: int) -> None:
    if generation != current_generation():
        return
    result = fetch_link_icon(origin)
    if result.status == "deferred":
        link_icon_store.discard_in_flight(origin)
        return
    link_icon_store.apply_current_fetch_result(result, generation)


def _next_record(*, previous: LinkIconRecord | None, result: LinkIconFetchResult, now: datetime) -> LinkIconRecord:
    row_id = _UNSAVED_ROW_ID
    created_at = now
    previous_failures = 0
    if previous is not None:
        row_id = previous.id
        created_at = previous.created_at
        previous_failures = previous.failure_count
    if result.status == "ok":
        assert result.icon_png_base64, "a found icon carries its image"
        return LinkIconRecord(
            id=row_id, origin=result.origin, icon_png_base64=result.icon_png_base64, status="ok",
            last_error_kind=None, failure_count=0, last_checked_at=now, next_check_after=None,
            created_at=created_at, updated_at=now,
        )
    assert result.icon_png_base64 is None, "a missing icon carries no image"
    failure_count = previous_failures + 1
    delay = _MISSING_RETRY_DELAYS[min(failure_count, len(_MISSING_RETRY_DELAYS)) - 1]
    return LinkIconRecord(
        id=row_id, origin=result.origin, icon_png_base64=None, status="missing",
        last_error_kind=result.last_error_kind, failure_count=failure_count, last_checked_at=now,
        next_check_after=now + delay, created_at=created_at, updated_at=now,
    )


def _stored_row(record: LinkIconRecord) -> StoredLinkIconRow:
    """The record as stored: origin and icon encrypted when the namespace has a key."""
    return _row_with_fields(
        record,
        origin=_encrypt_optional_text(record.origin),
        icon=_encrypt_optional_text(record.icon_png_base64),
    )


def _row_with_fields(record: LinkIconRecord, *, origin: _SerializedTextField, icon: _SerializedTextField) -> StoredLinkIconRow:
    if origin.value is None:
        raise RuntimeError("Link icon origin serialization produced None")
    return StoredLinkIconRow(
        id=record.id,
        origin=origin.value,
        origin_encryption_nonce=origin.nonce,
        origin_encryption_tag=origin.tag,
        icon_png=icon.value,
        icon_png_encryption_nonce=icon.nonce,
        icon_png_encryption_tag=icon.tag,
        status=record.status,
        last_error_kind=record.last_error_kind,
        failure_count=record.failure_count,
        last_checked_at=record.last_checked_at,
        next_check_after=record.next_check_after,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _plain_row(record: LinkIconRecord) -> StoredLinkIconRow:
    """The stored row of an unlocked record, as a reload in plaintext would read it."""
    return _row_with_fields(
        record,
        origin=_SerializedTextField(value=record.origin, nonce=None, tag=None),
        icon=_SerializedTextField(value=record.icon_png_base64, nonce=None, tag=None),
    )


def _state_from_rows(*, stored_rows: tuple[StoredLinkIconRow, ...], token: str) -> _LinkIconState:
    contains_encrypted = any(row.origin_encryption_nonce is not None for row in stored_rows)
    if contains_encrypted and not _encryption_can_decrypt(token=token):
        return _LinkIconState(stored_rows=stored_rows, records_by_origin={}, is_decrypted=False)
    records_by_origin: dict[str, LinkIconRecord] = {}
    for row in stored_rows:
        record = _record_from_row(row, token=token)
        records_by_origin[record.origin] = record
    return _LinkIconState(stored_rows=stored_rows, records_by_origin=records_by_origin, is_decrypted=True)


def _stored_text(
    *, row_id: int, column: str, value: str | None, nonce: bytes | None, tag: bytes | None, token: str,
) -> str | None:
    if value is None:
        if nonce is not None or tag is not None:
            raise RuntimeError(f"link_icons row {row_id} has encryption metadata but no {column}")
        return None
    return _decrypt_text_field(stored_value=value, nonce=nonce, tag=tag, token=token, field_name=column)


def _record_from_row(row: StoredLinkIconRow, *, token: str) -> LinkIconRecord:
    if row.status not in {"ok", "missing"}:
        raise RuntimeError(f"link_icons row {row.id} has an unknown status: {row.status!r}")
    origin = _stored_text(
        row_id=row.id, column="origin", value=row.origin,
        nonce=row.origin_encryption_nonce, tag=row.origin_encryption_tag, token=token,
    )
    if origin is None or icon_origin_for_url(origin) != origin:
        raise RuntimeError(f"link_icons row {row.id} has an invalid origin")
    icon = _stored_text(
        row_id=row.id, column="icon_png", value=row.icon_png,
        nonce=row.icon_png_encryption_nonce, tag=row.icon_png_encryption_tag, token=token,
    )
    if (row.status == "ok") != (icon is not None):
        raise RuntimeError(f"link_icons row {row.id} has status {row.status} with icon present: {icon is not None}")
    return LinkIconRecord(
        id=row.id, origin=origin, icon_png_base64=icon, status=row.status,
        last_error_kind=row.last_error_kind, failure_count=row.failure_count,
        last_checked_at=row.last_checked_at, next_check_after=row.next_check_after,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def rewrite_persisted_link_icons(*, connection, encryption_service: object | None, force_plaintext: bool) -> int:
    """Encrypt (a password added) or decrypt (removed) every stored icon and origin."""
    should_be_encrypted = not force_plaintext and encryption_service is not None
    service = None
    if not force_plaintext:
        service = _coerce_optional_encryption_service(encryption_service)
    rewritten_count = 0
    for row in fetch_all_link_icon_rows(connection):
        if _is_stored_as(row, should_be_encrypted=should_be_encrypted):
            continue
        origin = _decrypted_for_rewrite(
            value=row.origin, nonce=row.origin_encryption_nonce, tag=row.origin_encryption_tag,
            encryption_service=encryption_service,
        )
        icon = _decrypted_for_rewrite(
            value=row.icon_png, nonce=row.icon_png_encryption_nonce, tag=row.icon_png_encryption_tag,
            encryption_service=encryption_service,
        )
        origin_field = _serialize_text_with_service(value=origin, encryption_service=service)
        icon_field = _serialize_text_with_service(value=icon, encryption_service=service)
        if origin_field.value is None:
            raise RuntimeError(f"link_icons row {row.id} has no origin to rewrite")
        update_link_icon_row(connection, replace(
            row,
            origin=origin_field.value,
            origin_encryption_nonce=origin_field.nonce,
            origin_encryption_tag=origin_field.tag,
            icon_png=icon_field.value,
            icon_png_encryption_nonce=icon_field.nonce,
            icon_png_encryption_tag=icon_field.tag,
            updated_at=datetime.now(timezone.utc),
        ))
        rewritten_count += 1
    return rewritten_count


def _is_stored_as(row: StoredLinkIconRow, *, should_be_encrypted: bool) -> bool:
    if (row.origin_encryption_nonce is not None) != should_be_encrypted:
        return False
    if row.icon_png is None:
        return True
    return (row.icon_png_encryption_nonce is not None) == should_be_encrypted


def _decrypted_for_rewrite(
    *, value: str | None, nonce: bytes | None, tag: bytes | None, encryption_service: object | None,
) -> str | None:
    if value is None or nonce is None:
        return value
    service = _coerce_encryption_service(encryption_service)
    return service.decrypt_from_storage(value, nonce, tag)


# Fetching


@dataclass(frozen=True, slots=True)
class _Download:
    content: bytes | None
    final_url: str
    error_kind: str | None


@dataclass(frozen=True, slots=True)
class _DeclaredIcon:
    href: str
    is_apple_touch_icon: bool
    is_dark_scheme_only: bool
    is_svg: bool
    sizes: str


class _IconLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.icons: list[_DeclaredIcon] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "link":
            return
        attrs_by_name = {
            name.casefold(): value for name, value in attrs if isinstance(name, str) and isinstance(value, str)
        }
        rel = sent_or_none(attrs_by_name, "rel")
        href = sent_or_none(attrs_by_name, "href")
        if rel is None or href is None or href.strip() == "":
            return
        rel_tokens = set(rel.casefold().split())
        is_apple_touch_icon = not rel_tokens.isdisjoint(_APPLE_TOUCH_ICON_RELS)
        if "icon" not in rel_tokens and not is_apple_touch_icon:
            return
        sizes = sent_or_none(attrs_by_name, "sizes")
        if sizes is None:
            sizes = ""
        self.icons.append(_DeclaredIcon(
            href=href.strip(),
            is_apple_touch_icon=is_apple_touch_icon,
            is_dark_scheme_only=_is_dark_scheme_media(sent_or_none(attrs_by_name, "media")),
            is_svg=_is_declared_svg(declared_type=sent_or_none(attrs_by_name, "type"), href=href.strip()),
            sizes=sizes,
        ))


def _is_dark_scheme_media(media: str | None) -> bool:
    if media is None:
        return False
    return _DARK_SCHEME_MEDIA in "".join(media.casefold().split())


def _icon_group(icon: _DeclaredIcon) -> int:
    if icon.is_dark_scheme_only:
        return _DARK_SCHEME_ICON_GROUP
    if icon.is_apple_touch_icon:
        return _APPLE_TOUCH_ICON_GROUP
    return _ICON_GROUP


def _is_declared_svg(*, declared_type: str | None, href: str) -> bool:
    if urlsplit(href).path.casefold().endswith(".svg"):
        return True
    return declared_type is not None and "svg" in declared_type.casefold()


def _size_rank(sizes: str) -> tuple[int, int]:
    widths = [max(int(width), int(height)) for width, height in _SIZE_RE.findall(sizes.casefold())]
    if len(widths) == 0:
        return (_UNSIZED_RANK, 0)
    large_enough = [width for width in widths if width >= ICON_PIXELS]
    if large_enough:
        return (_LARGE_ENOUGH_RANK, min(large_enough))
    return (_TOO_SMALL_RANK, -max(widths))


def declared_icon_urls(content: bytes, *, base_url: str) -> list[str]:
    """The icons a page declares, in the order to try them; never SVG."""
    parser = _IconLinkParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    usable = [icon for icon in parser.icons if not icon.is_svg]
    ordered = sorted(
        usable, key=lambda icon: (_icon_group(icon), _size_rank(icon.sizes)),
    )
    urls: list[str] = []
    for icon in ordered:
        url = normalize_url_for_link_title(urljoin(base_url, icon.href))
        if url is not None and url not in urls:
            urls.append(url)
    return urls


def fetch_link_icon(origin: str) -> LinkIconFetchResult:
    if icon_origin_for_url(origin) != origin:
        raise ValueError(f"fetch_link_icon requires an origin: {origin}")
    declared: list[str] = []
    favicon_origin = origin
    if _pacing_host(origin) not in _OEMBED_ENDPOINTS:
        page = _download(f"{origin}/", accept="text/html,application/xhtml+xml", is_page=True)
        if page.error_kind == "rate_limited":
            return LinkIconFetchResult(origin=origin, icon_png_base64=None, status="deferred", last_error_kind="rate_limited")
        if page.content is not None:
            declared = declared_icon_urls(page.content, base_url=page.final_url)
            page_origin = icon_origin_for_url(page.final_url)
            assert page_origin is not None, f"a fetched page has an origin: {page.final_url}"
            favicon_origin = page_origin
    candidates = declared[:_MAX_DECLARED_ATTEMPTS]
    if f"{favicon_origin}/favicon.ico" not in candidates:
        candidates.append(f"{favicon_origin}/favicon.ico")
    # Why each candidate failed, best first: the reason recorded is the site's own icon's,
    # not the 404 of the /favicon.ico tried after it.
    refusals: list[str] = []
    for url in candidates:
        download = _download(url, accept="image/*", is_page=False)
        if download.error_kind == "rate_limited":
            return LinkIconFetchResult(origin=origin, icon_png_base64=None, status="deferred", last_error_kind="rate_limited")
        if download.error_kind is not None:
            refusals.append(download.error_kind)
            continue
        assert download.content is not None, "a download without an error has content"
        png = normalized_icon_png(download.content)
        if png is None:
            refusals.append("invalid_image")
            continue
        return LinkIconFetchResult(
            origin=origin, icon_png_base64=base64.b64encode(png).decode("ascii"), status="ok", last_error_kind=None,
        )
    assert len(refusals) == len(candidates), "every candidate failed for a reason"
    return LinkIconFetchResult(origin=origin, icon_png_base64=None, status="missing", last_error_kind=refusals[0])


def _download(url: str, *, accept: str, is_page: bool) -> _Download:
    """One guarded GET with its redirects, each request in the site's turn."""
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        target_capture = CapturedExceptionContext(
            PublicHttpTargetRejected, boundary='app/services/link_icons.py:_download:target_capture')
        target = None
        with target_capture:
            target = _resolve_public_http_target(current_url)
        if target_capture.captured_exception is not None:
            rejection = target_capture.captured_exception
            if not isinstance(rejection, PublicHttpTargetRejected):
                raise RuntimeError("Link icon target rejection has an unexpected type")
            return _Download(content=None, final_url=current_url, error_kind=rejection.reason)
        if target is None:
            raise RuntimeError("Link icon target resolution returned no target")
        host = _pacing_host(current_url)
        if not link_titles._host_pacer.acquire(host):
            return _Download(content=None, final_url=current_url, error_kind="rate_limited")
        with _HostTurn(link_titles._host_pacer, host):
            content, redirect_url, error_kind = _request_once(current_url, target, accept=accept, is_page=is_page)
        if redirect_url is None:
            return _Download(content=content, final_url=current_url, error_kind=error_kind)
        current_url = redirect_url
    return _Download(content=None, final_url=current_url, error_kind="too_many_redirects")


def _request_once(
    url: str, target: ResolvedPublicHttpTarget, *, accept: str, is_page: bool,
) -> tuple[bytes | None, str | None, str | None]:
    transport_capture = CapturedExceptionContext(
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPError,
        httpcore.TimeoutException,
        httpcore.NetworkError,
        httpcore.ProtocolError,
    boundary='app/services/link_icons.py:_request_once:transport_capture')
    response: tuple[bytes | None, str | None, str | None] | None = None
    with transport_capture:
        response = _get(url, target, accept=accept, is_page=is_page)
    if transport_capture.captured_exception is not None:
        if isinstance(transport_capture.captured_exception, (httpx.TimeoutException, httpcore.TimeoutException)):
            return None, None, "timeout"
        return None, None, "network_error"
    if response is None:
        raise RuntimeError("Link icon request returned without a result or exception")
    return response


# (body, None, None), (None, redirect URL, None) or (None, None, error kind); transport
# failures propagate. A page is read up to the title limit (icons are declared early);
# an icon over its limit is refused.
def _get(
    url: str, target: ResolvedPublicHttpTarget, *, accept: str, is_page: bool,
) -> tuple[bytes | None, str | None, str | None]:
    with httpx.Client(
        timeout=_FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        transport=_PinnedHTTPTransport(target=target, network_backend=httpcore.SyncBackend()),
        headers={"User-Agent": _USER_AGENT, "Accept": accept},
    ) as client:
        with client.stream("GET", url) as response:
            if httpx.codes.is_redirect(response.status_code):
                location = sent_or_none(response.headers, "location")
                if location is None or location.strip() == "":
                    return None, None, "redirect_without_location"
                next_url = normalize_url_for_link_title(str(httpx.URL(url).join(location)))
                if next_url is None:
                    return None, None, "unsupported_redirect"
                return None, next_url, None
            if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                link_titles._host_pacer.cool_down(
                    _pacing_host(url),
                    _rate_limit_cooldown_seconds(sent_or_none(response.headers, "retry-after")),
                )
            if response.status_code >= HTTPStatus.BAD_REQUEST:
                return None, None, f"http_{response.status_code}"
            limit = _MAX_ICON_BYTES
            if is_page:
                limit = _MAX_RESPONSE_BYTES
            chunks: list[bytes] = []
            total_bytes = 0
            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > limit and not is_page:
                    return None, None, "too_large"
                chunks.append(chunk)
                if total_bytes >= limit:
                    break
            content = b"".join(chunks)
            if content == b"":
                return None, None, "empty_response"
            return content, None, None


# The stored image


def normalized_icon_png(content: bytes) -> bytes | None:
    """The icon as an ICON_PIXELS-square PNG, centred on transparency; None for anything
    that is not a small decodable bitmap (SVG included)."""
    if not isinstance(content, bytes) or content == b"":
        raise TypeError("content must be non-empty bytes")
    image_capture = CapturedExceptionContext(
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    boundary='app/services/link_icons.py:normalized_icon_png:image_capture')
    converted: _ConvertedIcon | None = None
    with _SHRINK_LOCK, image_capture:
        converted = _icon_png(content)
    if image_capture.captured_exception is not None:
        return None
    if converted is None:
        raise RuntimeError("Link icon conversion returned without a result or exception")
    return converted.png


@dataclass(frozen=True, slots=True)
class _ConvertedIcon:
    # None when the image is not one MetaList shows (its format or its size).
    png: bytes | None


def _icon_png(content: bytes) -> _ConvertedIcon:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as image:
            if image.format not in _ICON_FORMATS:
                return _ConvertedIcon(png=None)
            picture: Image.Image = image
            if isinstance(image, IcoImagePlugin.IcoImageFile):
                picture = image.ico.getimage(_best_ico_size(set(image.ico.sizes())))
            width, height = picture.size
            if width <= 0 or height <= 0 or width * height > _MAX_ICON_SOURCE_PIXELS:
                return _ConvertedIcon(png=None)
            reduce_factor = min(picture.size) // _REDUCED_SIDE
            shrinkable = picture
            if reduce_factor > 1:
                shrinkable = _box_reduced(picture, reduce_factor)
            elif picture.mode not in _SHRINKABLE_MODES:
                shrinkable = picture.convert("RGBA")
            shrinkable.thumbnail((ICON_PIXELS, ICON_PIXELS), Image.Resampling.LANCZOS)
            rgba = shrinkable.convert("RGBA")
    square = ImageOps.pad(rgba, (ICON_PIXELS, ICON_PIXELS), method=Image.Resampling.LANCZOS, color=_TRANSPARENT)
    out = BytesIO()
    square.save(out, "PNG", optimize=True)
    return _ConvertedIcon(png=out.getvalue())


def _box_reduced(image: Image.Image, factor: int) -> Image.Image:
    """The image box-reduced by factor, a band of rows at a time, so no step copies it whole.
    Up to factor - 1 trailing rows and columns are left out."""
    assert factor > 1, "a reduction shrinks"
    width, height = image.size
    reduced_width = width // factor
    reduced_height = height // factor
    bands: list[tuple[int, Image.Image]] = []
    for top in range(0, reduced_height, _REDUCED_ROWS_PER_BAND):
        rows = min(_REDUCED_ROWS_PER_BAND, reduced_height - top)
        band = image.crop((0, top * factor, reduced_width * factor, (top + rows) * factor))
        if band.mode not in _SHRINKABLE_MODES:
            band = band.convert("RGBA")
        bands.append((top, band.reduce(factor)))
    reduced = Image.new(bands[0][1].mode, (reduced_width, reduced_height))
    for top, band in bands:
        reduced.paste(band, (0, top))
    return reduced


def _best_ico_size(sizes: set[tuple[int, int]]) -> tuple[int, int]:
    """The smallest size at least ICON_PIXELS wide an ICO holds, else its largest."""
    assert len(sizes) > 0, "an ICO holds at least one image"
    large_enough = [size for size in sizes if min(size) >= ICON_PIXELS]
    if large_enough:
        return min(large_enough, key=max)
    return max(sizes, key=max)


link_icon_store = LinkIconStore()
link_title_store.add_companion(link_icon_store)
