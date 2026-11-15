from __future__ import annotations

from datetime import timedelta

import pytest

import app.services.tokens as tokens_module
from app.services.tokens import TokenService


@pytest.fixture(autouse=True)
def reset_timeout_provider(monkeypatch: pytest.MonkeyPatch):
    timeout_minutes = {"value": 30}
    monkeypatch.setattr(
        tokens_module,
        "get_session_timeout_minutes",
        lambda: timeout_minutes["value"],
    )
    return timeout_minutes


def test_create_token_uses_configured_idle_timeout(reset_timeout_provider) -> None:
    reset_timeout_provider["value"] = 45
    service = TokenService()

    token = service.create_token(
        client_info="test-client",
        dek=None,
    )

    token_info = service.get_token_info(token)

    assert token_info is not None
    assert token_info["expires_at"] - token_info["created_at"] == timedelta(minutes=45)


def test_refresh_token_uses_latest_configured_idle_timeout(reset_timeout_provider) -> None:
    reset_timeout_provider["value"] = 15
    service = TokenService()
    token = service.create_token(
        client_info="test-client",
        dek=None,
    )

    reset_timeout_provider["value"] = 90
    refreshed = service.refresh_token(token)
    token_info = service.get_token_info(token)

    assert refreshed == token
    assert token_info is not None
    assert token_info["expires_at"] - token_info["last_activity"] == timedelta(minutes=90)


def test_refresh_active_tokens_for_current_timeout_rebases_existing_session(
    reset_timeout_provider,
) -> None:
    reset_timeout_provider["value"] = 20
    service = TokenService()
    token = service.create_token(
        client_info="test-client",
        dek=None,
    )

    reset_timeout_provider["value"] = 120
    service.refresh_active_tokens_for_current_timeout()
    token_info = service.get_token_info(token)

    assert token_info is not None
    assert token_info["expires_at"] - token_info["last_activity"] == timedelta(minutes=120)


def test_create_token_with_disabled_timeout_has_no_expiry(reset_timeout_provider) -> None:
    reset_timeout_provider["value"] = 0
    service = TokenService()

    token = service.create_token(
        client_info="test-client",
        dek=None,
    )
    token_info = service.get_token_info(token)

    assert token_info is not None
    assert token_info["expires_at"] is None
    assert service.verify_token(token) is True


def test_list_active_sessions_marks_disabled_timeout(reset_timeout_provider) -> None:
    reset_timeout_provider["value"] = 0
    service = TokenService()
    service.create_token(
        client_info="test-client",
        dek=None,
    )

    sessions = service.list_active_sessions()

    assert len(sessions) == 1
    assert sessions[0]["timeout_disabled"] is True
    assert sessions[0]["expires_in_minutes"] is None


def test_session_key_is_stable_and_unavailable_after_revocation(reset_timeout_provider) -> None:
    service = TokenService()
    token = service.create_token(
        client_info="test-client",
        dek=None,
    )

    other_device = service.create_token(client_info="phone", dek=None)

    session_key = service.get_session_key(token)

    # The AI's working state is the vault's, one for every sign-in (multi-view editing step 5).
    assert session_key != token
    assert service.get_session_key(token) == session_key
    assert service.get_session_key(other_device) == session_key
    assert service.revoke_token(token) is True
    with pytest.raises(RuntimeError, match="valid authentication token"):
        service.get_session_key(token)
