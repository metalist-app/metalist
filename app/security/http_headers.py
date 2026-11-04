from __future__ import annotations

import re

from starlette.responses import Response


_CSP_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32}$")


def build_content_security_policy(*, nonce: str) -> str:
    if not isinstance(nonce, str) or _CSP_NONCE_PATTERN.fullmatch(nonce) is None:
        raise ValueError("CSP nonce must be a 32-character URL-safe token")
    directives = (
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "media-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self' data: blob:",
        "object-src 'none'",
        # Only a blob: MetaList makes itself from a decrypted PDF, shown by the browser's own
        # viewer inside the file viewer (docs/ready-to-build/files-shown-not-copied.md §4).
        "frame-src blob:",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    )
    return "; ".join(directives)


def apply_security_headers(*, response: Response, nonce: str) -> None:
    if not isinstance(response, Response):
        raise TypeError("response must be a Starlette Response")
    response.headers["Content-Security-Policy"] = build_content_security_policy(nonce=nonce)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
    )
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
