from __future__ import annotations

import os
import subprocess
import sys

from fastapi import FastAPI
import pytest

from app.api.transactions import assert_mutation_routes_wrapped, assert_read_routes_declared
from app.api.transactions import one_step_read_route, read_only_route, serialized_read_route, transactional_route


def test_transaction_audit_accepts_decorated_mutation_routes() -> None:
    app = FastAPI()

    @app.post("/mutate")
    @transactional_route
    def mutate() -> dict[str, bool]:
        return {"ok": True}

    assert_mutation_routes_wrapped(app)


def test_transaction_audit_rejects_undecorated_mutation_routes() -> None:
    app = FastAPI()

    def mutate() -> dict[str, bool]:
        return {"ok": True}

    app.add_api_route("/mutate", mutate, methods=["POST"])

    with pytest.raises(RuntimeError, match="POST /mutate"):
        assert_mutation_routes_wrapped(app)


def test_transaction_audit_ignores_read_only_routes() -> None:
    app = FastAPI()

    @app.get("/read")
    def read() -> dict[str, bool]:
        return {"ok": True}

    assert_mutation_routes_wrapped(app)


_REAL_APP_TIMEOUT_SECONDS = 60


def test_every_data_changing_route_of_the_real_app_runs_in_a_transaction(tmp_path) -> None:
    # The audit was only ever run on made-up apps, so a new MetaList route without
    # @transactional_route would have gone unnoticed (found by ShockHarness DEAD002).
    # The real app starts in its own process: importing it starts services that must
    # not run inside the test process.
    script = (
        "import sys\n"
        "from app.api.transactions import assert_mutation_routes_wrapped\n"
        "from app.main import app\n"
        # MetaList's log keeps only where an error was raised: the routes it names are printed.
        "try:\n"
        "    assert_mutation_routes_wrapped(app)\n"
        "except RuntimeError as failure:\n"
        "    print(failure, file=sys.stderr)\n"
        "    sys.exit(1)\n"
    )
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path), METALIST_ENVIRONMENT="production")
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=_REAL_APP_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr[-3000:]


def test_transaction_audit_accepts_a_post_marked_read_only() -> None:
    app = FastAPI()

    @app.post("/preview")
    @read_only_route
    def preview() -> dict[str, bool]:
        return {"ok": True}

    assert_mutation_routes_wrapped(app)


def test_every_read_route_of_the_real_app_says_how_it_reads_the_notes(tmp_path) -> None:
    # A read that checked a note was there and then read it, beside a delete, failed (the Password
    # Audit, the preview card, full screen; 2026-11-14). Each read now says whether it reads the
    # notes in one step or runs one at a time with the changes; a new one must say too.
    script = (
        "import sys\n"
        "from app.api.transactions import assert_read_routes_declared\n"
        "from app.main import app\n"
        # MetaList's log keeps only where an error was raised: the routes it names are printed.
        "try:\n"
        "    assert_read_routes_declared(app)\n"
        "except RuntimeError as failure:\n"
        "    print(failure, file=sys.stderr)\n"
        "    sys.exit(1)\n"
    )
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path), METALIST_ENVIRONMENT="production")
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=_REAL_APP_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr[-6000:]


def test_the_read_audit_refuses_a_read_that_says_nothing() -> None:
    app = FastAPI()

    @app.get("/note")
    def read_note() -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match="GET /note"):
        assert_read_routes_declared(app)


def test_the_read_audit_accepts_each_way_of_reading() -> None:
    app = FastAPI()

    @app.get("/one")
    @one_step_read_route
    def one_step() -> dict[str, str]:
        return {}

    @app.get("/serialized")
    @serialized_read_route
    def serialized() -> dict[str, str]:
        return {}

    assert_read_routes_declared(app)


def test_both_audits_look_inside_included_routers() -> None:
    # FastAPI 0.141 keeps an included router as one entry: the audits saw only the app's own few
    # routes and none of MetaList's API (2026-11-14).
    from fastapi import APIRouter

    router = APIRouter()

    def change() -> dict[str, str]:
        return {}

    def read() -> dict[str, str]:
        return {}

    router.add_api_route("/change", change, methods=["POST"])
    router.add_api_route("/read", read, methods=["GET"])

    app = FastAPI()
    app.include_router(router, prefix="/api2")

    with pytest.raises(RuntimeError, match="POST /api2/change"):
        assert_mutation_routes_wrapped(app)
    with pytest.raises(RuntimeError, match="GET /api2/read"):
        assert_read_routes_declared(app)
