"""A PDF's first page drawn as a JPEG, in a process of its own (python -m
app.services.pdf_first_page_worker, the PDF on stdin, the JPEG on stdout): a gallery shows it as the
PDF's picture (docs/future-plans/gallery.md, "PDF first pages"). PDFium runs here at low priority,
as for the PDF's text (file_text_worker.py), so drawing never holds up the server's requests. A PDF
behind a password or one PDFium can't read answers nothing: it keeps its card."""

from __future__ import annotations

import io
import os
import sys
from contextlib import closing

import pypdfium2 as pdfium
from PIL import Image

from app.services.exception_capture import CapturedExceptionContext

# Below everything visible: the server's requests, images.
_LOW_PRIORITY = 10
_EXPECTED_ARGV_LENGTH = 1
# Wide enough for full screen on most windows, small enough for a grid of them (about 100 KB).
DRAWN_WIDTH_PIXELS = 900
# A page far taller than wide (a receipt, a poster strip) is drawn no taller than this.
_MAX_DRAWN_HEIGHT_PIXELS = 2400
_JPEG_QUALITY = 82
_JPEG = "JPEG"
_RGB = "RGB"
_FIRST_PAGE = 0


def draw_first_page(content: bytes) -> bytes:
    """The first page as a JPEG; b"" for a PDF behind a password, one PDFium can't read, or one
    with no pages."""
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    capture = CapturedExceptionContext(pdfium.PdfiumError, ValueError, boundary='app/services/pdf_first_page_worker.py:draw_first_page:pdf_capture')
    drawn = b""
    with capture:
        drawn = _draw(content)
    return drawn


def _draw(content: bytes) -> bytes:
    with closing(pdfium.PdfDocument(content)) as document:
        if len(document) == 0:
            return b""
        with closing(document[_FIRST_PAGE]) as page:
            width, height = page.get_size()
            scale = min(DRAWN_WIDTH_PIXELS / width, _MAX_DRAWN_HEIGHT_PIXELS / height)
            bitmap = page.render(scale=scale)
            picture: Image.Image = bitmap.to_pil().convert(_RGB)
    encoded = io.BytesIO()
    picture.save(encoded, format=_JPEG, quality=_JPEG_QUALITY, optimize=True)
    return encoded.getvalue()


def main() -> None:
    if len(sys.argv) != _EXPECTED_ARGV_LENGTH:
        raise SystemExit("usage: python -m app.services.pdf_first_page_worker < file.pdf")
    if hasattr(os, "nice"):
        os.nice(_LOW_PRIORITY)
    sys.stdout.buffer.write(draw_first_page(sys.stdin.buffer.read()))


if __name__ == "__main__":
    main()
