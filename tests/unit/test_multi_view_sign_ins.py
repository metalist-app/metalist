"""Several sign-ins (multi-view editing, step 1; docs/ready-to-build/multi-view-editing.md §9):
every browser and device stays signed in, every tab of a browser works at once, Log Out signs
out this device or, ticked, every device, and changing the password keeps the device it was
changed on. Before, signing in ended every other sign-in and one tab owned it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import Response

import app.api.routes.auth as auth_route
from app.services.tokens import TokenService


@pytest.fixture
def tokens(monkeypatch: pytest.MonkeyPatch) -> TokenService:
    service = TokenService()
    monkeypatch.setattr(auth_route, "token_service", service)
    return service


@pytest.fixture
def lock_down(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the last sign-in's end does to the vault, recorded instead of done."""
    events: list[str] = []
    monkeypatch.setattr(auth_route, "purge_decrypted_runtime_state", lambda: events.append("vault-locked") or True)
    monkeypatch.setattr(auth_route, "deactivate_authenticated_logging", lambda: events.append("logging-off"))
    monkeypatch.setattr(auth_route, "reset_all_undo_state", lambda: events.append("undo-cleared"))
    monkeypatch.setattr(auth_route, "reset_sync_state", lambda: events.append("sync-cleared"))
    monkeypatch.setattr(auth_route.shell_session_service, "reset", lambda: events.append("shell-reset"))
    monkeypatch.setattr(auth_route, "stop_link_title_retry", lambda: None)
    return events


def _log_out(token: str, *, every_device: bool) -> dict:
    return auth_route.logout.__wrapped__(
        response=Response(), payload=auth_route.LogoutRequest(every_device=every_device), token=token,
    )


def test_signing_in_on_another_device_keeps_the_first_signed_in(tokens: TokenService) -> None:
    mac = tokens.create_token("mac", dek=None)
    phone = tokens.create_token("phone", dek=None)

    assert tokens.verify_token(mac)
    assert tokens.verify_token(phone)


def _request_from_tab(token: str) -> Request:
    return Request({
        "type": "http", "method": "GET", "scheme": "http", "path": "/api2/notes/tab-state",
        "raw_path": b"/api2/notes/tab-state", "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8000),
    })


def test_every_tab_of_a_browser_works_at_once(tokens: TokenService) -> None:
    # The tabs share the browser's sign-in; none owns it (no "Take Over Session").
    shared = tokens.create_token("browser", dek=None)

    assert auth_route._verify_token(_request_from_tab(shared), tab_id="first-tab") == shared
    assert auth_route._verify_token(_request_from_tab(shared), tab_id="second-tab") == shared


def test_logging_out_signs_out_this_device_and_keeps_the_vault_open_for_the_others(
    tokens: TokenService, lock_down: list[str],
) -> None:
    mac = tokens.create_token("mac", dek=None)
    phone = tokens.create_token("phone", dek=None)

    _log_out(mac, every_device=False)

    assert not tokens.verify_token(mac)
    assert tokens.verify_token(phone)
    assert lock_down == [], "the phone keeps the vault, its undo and its shell"


def test_the_last_device_logging_out_locks_the_vault(tokens: TokenService, lock_down: list[str]) -> None:
    mac = tokens.create_token("mac", dek=None)
    phone = tokens.create_token("phone", dek=None)
    _log_out(mac, every_device=False)

    _log_out(phone, every_device=False)

    assert not tokens.has_active_tokens()
    assert "vault-locked" in lock_down and "logging-off" in lock_down


def test_signing_out_every_device_signs_out_all_and_locks_the_vault(tokens: TokenService, lock_down: list[str]) -> None:
    mac = tokens.create_token("mac", dek=None)
    phone = tokens.create_token("phone", dek=None)

    _log_out(mac, every_device=True)

    assert not tokens.verify_token(mac)
    assert not tokens.verify_token(phone)
    assert "vault-locked" in lock_down


class _PasswordChanged:
    def __init__(self, db) -> None:
        pass

    def change_password(self, current: str, new: str, time_cost: int) -> tuple[bool, str]:
        return True, "Password changed"


def test_changing_the_password_keeps_this_device_and_signs_out_the_others(
    tokens: TokenService, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_route, "AuthService", _PasswordChanged)
    mac = tokens.create_token("mac", dek=None)
    phone = tokens.create_token("phone", dek=None)
    payload = SimpleNamespace(current_password=SecretStr("old"), new_password=SecretStr("new"))

    auth_route.change_password.__wrapped__(payload=payload, db=None, token=mac)

    assert tokens.verify_token(mac), "changed on the Mac: it stays signed in"
    assert not tokens.verify_token(phone), "someone else may have had the old password"
