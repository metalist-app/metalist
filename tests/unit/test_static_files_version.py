"""MetaList's own files are kept by the browser under a versioned folder, so a visit after the
first downloads none of the 318 scripts the page imports (the maintainer, 2026-11-12: over
Wi-Fi the vault list came a second or more later than on the computer running MetaList).
app/services/static_files_version.py."""

from __future__ import annotations

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.services.static_files_version import (
    MetaListStaticFiles,
    StaticFilesVersion,
    fingerprint_static_files,
)
from app.presentation.templates import get_templates

TEMPLATES = get_templates(template_directory=Path(__file__).resolve().parents[2] / "app" / "templates")
KEPT_FOR_GOOD = "public, max-age=31536000, immutable"
# A change time the file did not have, in nanoseconds.
LATER_NS = 10**18


def _static_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "static"
    (folder / "js" / "modules").mkdir(parents=True)
    (folder / "js" / "main.js").write_text("import './modules/config.js';\n", encoding="utf-8")
    (folder / "js" / "modules" / "config.js").write_text("export const A = 1;\n", encoding="utf-8")
    return folder


def _client(folder: Path, version: StaticFilesVersion) -> TestClient:
    app = Starlette(routes=[Mount("/static", MetaListStaticFiles(directory=str(folder), version=version))])
    return TestClient(app)


def test_the_fingerprint_changes_with_any_file_and_only_then(tmp_path: Path) -> None:
    folder = _static_folder(tmp_path)
    first = fingerprint_static_files(folder)
    assert fingerprint_static_files(folder) == first
    config = folder / "js" / "modules" / "config.js"
    os.utime(config, ns=(LATER_NS, LATER_NS))
    saved = fingerprint_static_files(folder)
    assert saved != first
    (folder / "js" / "added.js").write_text("", encoding="utf-8")
    added = fingerprint_static_files(folder)
    assert added not in {first, saved}
    (folder / "js" / "added.js").unlink()
    assert fingerprint_static_files(folder) == saved


def test_only_the_version_last_given_to_a_page_is_kept_for_good(tmp_path: Path) -> None:
    folder = _static_folder(tmp_path)
    version = StaticFilesVersion(folder)
    before = fingerprint_static_files(folder)
    assert not version.is_current(before), "no page made yet"
    given = version.for_page()
    assert given == before and version.is_current(given)
    os.utime(folder / "js" / "main.js", ns=(LATER_NS, LATER_NS))
    assert version.is_current(given), "until the next page is made"
    newer = version.for_page()
    assert newer != given
    assert version.is_current(newer) and not version.is_current(given)


def test_a_versioned_file_is_kept_for_good_and_an_old_version_never(tmp_path: Path) -> None:
    folder = _static_folder(tmp_path)
    version = StaticFilesVersion(folder)
    given = version.for_page()
    client = _client(folder, version)

    current = client.get(f"/static/v/{given}/js/modules/config.js")
    assert current.status_code == 200
    assert current.text == "export const A = 1;\n"
    assert current.headers["cache-control"] == KEPT_FOR_GOOD

    old = client.get("/static/v/0123456789abcdef/js/modules/config.js")
    assert old.status_code == 200
    assert old.headers["cache-control"] == "no-store"

    assert client.get(f"/static/v/{given}/js/missing.js").status_code == 404


def test_an_unversioned_file_is_asked_about_again_and_answered_not_modified(tmp_path: Path) -> None:
    folder = _static_folder(tmp_path)
    client = _client(folder, StaticFilesVersion(folder))
    plain = client.get("/static/js/main.js")
    assert plain.status_code == 200
    assert plain.headers["cache-control"] == "no-cache"
    again = client.get("/static/js/main.js", headers={"If-None-Match": plain.headers["etag"]})
    assert again.status_code == 304


def test_the_page_loads_its_scripts_from_the_version_and_maps_static_js_there() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []})
    request.state.csp_nonce = "n" * 32
    page = TEMPLATES.get_template("index.html").render(
        request=request, version="0", asset_version="abc", page_title="MetaList", needs_auth=True,
        shows_login_at_once=True, shows_ai_cost_estimate=False, vault_name="thomas",
    )
    importmap = f'<script type="importmap" nonce="{"n" * 32}">{{"imports": {{"/static/js/": "/static/v/abc/js/"}}}}</script>'
    assert importmap in page
    assert '<script type="module" src="/static/v/abc/js/main.js"></script>' in page
    assert page.index(importmap) < page.index('type="module"'), "an import map must come before any module"
    assert '<link rel="stylesheet" href="/static/v/abc/css/main.css">' in page
