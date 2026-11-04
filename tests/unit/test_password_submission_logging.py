from __future__ import annotations

import ast
import logging
from pathlib import Path

from fastapi import HTTPException
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import Response
import pytest

import app.api.routes.auth as auth_route
from app.api.routes.auth import LoginRequest
from app.api.routes.auth import PasswordChangeRequest
from app.api.routes.auth import PasswordCreateRequest
from app.api.routes.auth import PasswordRemoveRequest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PASSWORD_CANARY = "Never-Log-This-Password-7!zQ"


def _login_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api2/auth/login",
            "raw_path": b"/api2/auth/login",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8000),
        }
    )


def test_password_request_models_never_render_submitted_passwords() -> None:
    requests = (
        LoginRequest(password=PASSWORD_CANARY),
        PasswordCreateRequest(password=PASSWORD_CANARY, keeps_window_logged_in=False),
        PasswordChangeRequest(
            current_password=PASSWORD_CANARY,
            new_password=f"new-{PASSWORD_CANARY}",
        ),
        PasswordRemoveRequest(current_password=PASSWORD_CANARY),
    )

    for request in requests:
        assert PASSWORD_CANARY not in repr(request)
        assert PASSWORD_CANARY not in request.model_dump_json()
        for value in request.__dict__.values():
            if isinstance(value, SecretStr):
                assert PASSWORD_CANARY not in repr(value)


def test_application_code_never_passes_password_values_to_logging_or_print() -> None:
    paths = sorted((PROJECT_ROOT / "app").rglob("*.py"))
    forbidden_callees = {"debug", "info", "warning", "error", "critical", "exception", "log", "print"}

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Attribute):
                callee = call.func.attr
            elif isinstance(call.func, ast.Name):
                callee = call.func.id
            else:
                continue
            if callee not in forbidden_callees:
                continue
            submitted_nodes = [*call.args, *(keyword.value for keyword in call.keywords)]
            submitted_names = {
                identifier.id.casefold()
                for submitted_node in submitted_nodes
                for identifier in ast.walk(submitted_node)
                if isinstance(identifier, ast.Name)
            }
            submitted_attributes = {
                attribute.attr.casefold()
                for submitted_node in submitted_nodes
                for attribute in ast.walk(submitted_node)
                if isinstance(attribute, ast.Attribute)
            }
            assert not any("password" in name for name in submitted_names | submitted_attributes), (
                path,
                call.lineno,
            )


def test_failed_login_never_logs_submitted_password(monkeypatch, caplog, capsys) -> None:
    class RejectingAuthService:
        def has_password(self) -> bool:
            return True

        def verify_password(self, submitted_password: str) -> bool:
            assert submitted_password == PASSWORD_CANARY
            logging.getLogger("password-canary-test").info("Login rejected")
            return False

    monkeypatch.setattr(auth_route, "AuthService", lambda db: RejectingAuthService())
    monkeypatch.setattr(auth_route.login_rate_limiter, "check_allowed", lambda key: (True, 0))
    monkeypatch.setattr(auth_route.login_rate_limiter, "record_failure", lambda key: None)

    with caplog.at_level(logging.INFO), pytest.raises(HTTPException, match="Invalid password"):
        auth_route.login.__wrapped__(
            request=_login_request(),
            response=Response(),
            payload=LoginRequest(password=PASSWORD_CANARY),
            tab_id="tab-id",
            db=object(),
        )

    captured = capsys.readouterr()
    rendered_diagnostics = caplog.text + captured.out + captured.err
    assert PASSWORD_CANARY not in rendered_diagnostics


def test_password_change_never_logs_current_or_new_password(monkeypatch, caplog, capsys) -> None:
    new_password_canary = f"new-{PASSWORD_CANARY}"

    class RejectingAuthService:
        def change_password(
            self,
            current_password: str,
            new_password: str,
            time_cost: int,
        ) -> tuple[bool, str]:
            assert current_password == PASSWORD_CANARY
            assert new_password == new_password_canary
            assert time_cost == auth_route.KDF_TIME_COST
            logging.getLogger("password-canary-test").info("Password change rejected")
            return False, "Password change rejected"

    monkeypatch.setattr(auth_route, "AuthService", lambda db: RejectingAuthService())

    with caplog.at_level(logging.INFO), pytest.raises(HTTPException, match="Password change rejected"):
        auth_route.change_password.__wrapped__(
            payload=PasswordChangeRequest(
                current_password=PASSWORD_CANARY,
                new_password=new_password_canary,
            ),
            db=object(),
            token="token",
        )

    captured = capsys.readouterr()
    rendered_diagnostics = caplog.text + captured.out + captured.err
    assert PASSWORD_CANARY not in rendered_diagnostics
    assert new_password_canary not in rendered_diagnostics
