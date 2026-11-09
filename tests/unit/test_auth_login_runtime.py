from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import Response
import pytest

import app.api.routes.auth as auth_route


def test_login_rate_limit_key_ignores_untrusted_forwarded_for_header() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api2/auth/login",
            "raw_path": b"/api2/auth/login",
            "query_string": b"",
            "headers": [(b"x-forwarded-for", b"203.0.113.45")],
            "client": ("198.51.100.20", 1234),
            "server": ("127.0.0.1", 8000),
        }
    )

    rate_limit_key = auth_route._login_rate_limit_key(request)

    assert rate_limit_key == "ip:198.51.100.20"


def test_login_rate_limit_key_requires_client_metadata() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api2/auth/login",
            "raw_path": b"/api2/auth/login",
            "query_string": b"",
            "headers": [(b"user-agent", b"attacker-controlled")],
            "client": None,
            "server": ("127.0.0.1", 8000),
        }
    )

    with pytest.raises(RuntimeError, match="client metadata"):
        auth_route._login_rate_limit_key(request)


def test_login_does_not_decrypt_file_metadata_before_hydration(monkeypatch) -> None:
    logging_events: list[str] = []

    class _AuthService:
        def has_password(self) -> bool:
            return True

        def verify_password(self, password: str) -> bool:
            return password == "abcd"

        def unwrap_dek_for_password(self, password: str) -> bytes:
            assert password == "abcd"
            return b"d" * 32

        def run_authenticated_database_migrations(self, *, dek: bytes) -> SimpleNamespace:
            assert dek == b"d" * 32
            return SimpleNamespace(applied_versions=())

    monkeypatch.setattr(auth_route, "AuthService", lambda db: _AuthService())
    monkeypatch.setattr(auth_route.login_rate_limiter, "check_allowed", lambda key: (True, 0))
    monkeypatch.setattr(auth_route.login_rate_limiter, "record_success", lambda key: None)
    monkeypatch.setattr(
        auth_route,
        "set_session_dek",
        lambda dek: logging_events.append("dek-set"),
    )
    monkeypatch.setattr(
        auth_route,
        "activate_authenticated_logging",
        lambda *, namespace, dek: logging_events.append(f"logging-active:{namespace}"),
        raising=False,
    )
    monkeypatch.setattr(
        auth_route,
        "ensure_rules_decrypted_and_compiled",
        lambda *, token: logging_events.append("decryption-started"),
    )
    monkeypatch.setattr(auth_route.tab_state_store, "ensure_decrypted", lambda *, token: None)
    monkeypatch.setattr(auth_route.link_title_store, "ensure_decrypted", lambda *, token: None)
    monkeypatch.setattr(auth_route.reminder_store, "ensure_decrypted", lambda *, token: None)
    monkeypatch.setattr(auth_route.search_history_store, "bootstrap", lambda *, connection: None)
    monkeypatch.setattr(auth_route.search_history_store, "ensure_decrypted", lambda *, token: None)
    monkeypatch.setattr(
        auth_route,
        "bootstrap_file_registry",
        lambda: (_ for _ in ()).throw(AssertionError("file metadata belongs to hydration")),
    )
    monkeypatch.setattr(auth_route.token_service, "create_token", lambda *args, **kwargs: "token")
    monkeypatch.setattr(auth_route, "set_auth_cookie", lambda **kwargs: None)
    monkeypatch.setattr(auth_route, "clear_all_locks", lambda: None)
    request = Request(
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

    login_impl = auth_route.login.__wrapped__
    result = login_impl(
        request=request,
        response=Response(),
        payload=auth_route.LoginRequest(password="abcd"),
        tab_id="tab-id",
        db=type("_Database", (), {"connection": lambda self: object()})(),
    )

    assert result.message == "Login successful"
    assert logging_events[:3] == [
        "dek-set",
        f"logging-active:{auth_route._active_diagnostics_namespace()}",
        "decryption-started",
    ]


def test_logout_keeps_encrypted_logging_active_until_plaintext_state_is_purged(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(auth_route.token_service, "get_session_key", lambda token: "session-key")
    monkeypatch.setattr(auth_route.token_service, "revoke_token", lambda token: events.append("token-revoked"))
    monkeypatch.setattr(
        auth_route.ai_chat_store,
        "clear_session",
        lambda *, session_key: events.append(f"chat-cleared:{session_key}"),
    )
    monkeypatch.setattr(
        auth_route,
        "purge_decrypted_runtime_state",
        lambda: events.append("plaintext-purged") or True,
    )
    monkeypatch.setattr(
        auth_route,
        "deactivate_authenticated_logging",
        lambda: events.append("logging-deactivated"),
        raising=False,
    )
    monkeypatch.setattr(auth_route, "clear_auth_cookie", lambda **kwargs: events.append("cookie-cleared"))

    logout_impl = auth_route.logout.__wrapped__
    result = logout_impl(response=Response(), token="token")

    assert result == {"message": "Logout successful"}
    assert events == [
        "chat-cleared:session-key",
        "token-revoked",
        "plaintext-purged",
        "logging-deactivated",
        "cookie-cleared",
    ]
