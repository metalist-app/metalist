from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.responses import HTMLResponse

from app.security.http_headers import apply_security_headers
from app.security.http_headers import build_content_security_policy


NONCE = "A" * 32


def test_content_security_policy_allows_only_nonce_or_self_scripts() -> None:
    policy = build_content_security_policy(nonce=NONCE)

    assert f"script-src 'self' 'nonce-{NONCE}'" in policy
    assert "script-src 'self' 'unsafe-inline'" not in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "base-uri 'none'" in policy


# A PDF opens in the file viewer through the browser's own viewer, from a blob: MetaList makes of
# the decrypted file (docs/ready-to-build/files-shown-not-copied.md §4): frames of blob: only.
def test_content_security_policy_frames_only_blob_addresses() -> None:
    policy = build_content_security_policy(nonce=NONCE)

    frame_sources = [directive for directive in policy.split("; ") if directive.startswith("frame-src")]
    assert frame_sources == ["frame-src blob:"]


def test_content_security_policy_blocks_direct_remote_images() -> None:
    policy = build_content_security_policy(nonce=NONCE)

    assert "img-src 'self' data: blob:" in policy
    assert "img-src 'self' data: blob: https: http:" not in policy


def test_content_security_policy_blocks_direct_remote_connections() -> None:
    policy = build_content_security_policy(nonce=NONCE)

    assert "connect-src 'self' data: blob:" in policy
    assert "connect-src 'self' data: blob: https: http:" not in policy


def test_apply_security_headers_sets_browser_defenses() -> None:
    response = HTMLResponse("<html></html>")

    apply_security_headers(response=response, nonce=NONCE, is_static_file=False)

    assert response.headers["content-security-policy"] == build_content_security_policy(nonce=NONCE)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"


# MetaList's own files say how long the browser keeps them (app/services/static_files_version.py):
# a versioned script for good, so a later visit downloads none of them. The browser defenses
# still apply; only their caching is theirs (the maintainer, 2026-11-12).
def test_a_static_file_keeps_its_own_caching_and_gets_the_defenses() -> None:
    response = HTMLResponse("export const A = 1;")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    apply_security_headers(response=response, nonce=NONCE, is_static_file=True)

    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "pragma" not in response.headers and "expires" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == build_content_security_policy(nonce=NONCE)


def test_a_static_file_without_its_own_caching_is_refused() -> None:
    with pytest.raises(RuntimeError, match="caching"):
        apply_security_headers(response=HTMLResponse(""), nonce=NONCE, is_static_file=True)


def test_a_missing_static_file_is_never_stored() -> None:
    # Starlette answers a missing file through its error handler, which sets no caching.
    response = HTMLResponse("Not Found", status_code=404)

    apply_security_headers(response=response, nonce=NONCE, is_static_file=True)

    assert response.headers["cache-control"] == "no-store, private"


@pytest.mark.parametrize("nonce", ["", "too-short", "!" * 32])
def test_content_security_policy_rejects_invalid_nonces(nonce: str) -> None:
    with pytest.raises(ValueError, match="CSP nonce"):
        build_content_security_policy(nonce=nonce)


def test_inline_template_scripts_carry_the_response_nonce() -> None:
    template_directory = Path(__file__).resolve().parents[2] / "app" / "templates"
    template_names = (
        "base.html",
        "locked.html",
        "maintenance.html",
        "namespace_deleted.html",
        "namespace_renamed.html",
    )

    for template_name in template_names:
        template_text = (template_directory / template_name).read_text(encoding="utf-8")
        inline_script_tags = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", template_text)
        if template_name == "maintenance.html":
            assert 'src="/static/js/modules/maintenance.js?v=${asset_version}"' in template_text
            assert not inline_script_tags
        elif template_name != "base.html":
            # base.html no longer needs an inline script; any it gains must carry the nonce.
            assert inline_script_tags, template_name
        assert all('nonce="${request.state.csp_nonce}"' in tag for tag in inline_script_tags)
