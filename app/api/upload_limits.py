"""The limit on uploads held whole in memory: an edited diagram's content and previews. A file
brought in goes straight to storage instead (streaming_upload.py)."""

from http import HTTPStatus

from fastapi import HTTPException, UploadFile
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from app.upload_limits import MAX_IN_MEMORY_FILE_BYTES, MAX_IN_MEMORY_REQUEST_BYTES, UPLOAD_CHUNK_BYTES


async def read_attachment(file: UploadFile) -> bytes:
    content = bytearray()
    try:
        while True:
            chunk = await file.read(min(UPLOAD_CHUNK_BYTES, MAX_IN_MEMORY_FILE_BYTES + 1 - len(content)))
            if not chunk:
                return bytes(content)
            content.extend(chunk)
            if len(content) > MAX_IN_MEMORY_FILE_BYTES:
                raise HTTPException(status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, detail='Attachment exceeds the configured size limit')
    finally:
        await file.close()


def _is_in_memory_upload(scope) -> bool:
    """In-place updates of MetaList-edited files (Excalidraw scenes and their previews)."""
    path = scope['path']
    if '/files/' not in path:
        return False
    if not path.endswith('/content') and not path.endswith('/previews'):
        return False
    return scope['method'] == 'PUT'


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not _is_in_memory_upload(scope):
            await self.app(scope, receive, send)
            return
        await self._receive_upload(scope, receive, send)

    async def _receive_upload(self, scope, receive, send):
        lengths = [value for key, value in scope['headers'] if key == b'content-length']
        if len(lengths) == 1 and lengths[0].isdigit() and int(lengths[0]) > MAX_IN_MEMORY_REQUEST_BYTES:
            await JSONResponse({'detail': 'Upload exceeds the configured size limit'}, status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)(scope, receive, send)
            return
        received = 0
        exceeded = False
        async def limited_receive():
            nonlocal received, exceeded
            message = await receive()
            if message['type'] == 'http.request':
                if 'body' in message:
                    received += len(message['body'])
                if received > MAX_IN_MEMORY_REQUEST_BYTES:
                    exceeded = True
                    # Starlette closes all partially spooled files on this exception.
                    raise MultiPartException('Upload exceeds the configured size limit')
            return message
        async def limited_send(message):
            if exceeded and message['type'] == 'http.response.start':
                message = dict(message, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            await send(message)
        await self.app(scope, limited_receive, limited_send)
