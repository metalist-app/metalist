"""Which models a vault can use: the ones MetaList ships (ai_catalog.py) and the ones
it added, kept in its preferences (ai_models.py)."""

from __future__ import annotations

import asyncio

import pytest

import app.api.routes.ai as ai_routes
import app.services.ai_models as ai_models_module
from app.services.ai_catalog import AI_CATALOG, parse_added_models, serialize_added_models
from app.services.ai_models import available_models, require_available_model
from app.services.ai_setup import AiSetup
from app.services.client_state_service import _validate_client_preferences
from app.services.input_errors import InputRejected

_SHIPPED_OPENAI = AI_CATALOG["openai"].models


@pytest.fixture
def vault_preferences(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    preferences: dict[str, str] = {}
    monkeypatch.setattr(ai_models_module, "load_client_preferences", lambda *, token: dict(preferences))
    return preferences


def test_a_vault_without_added_models_offers_the_shipped_ones(vault_preferences) -> None:
    assert available_models("openai", token="token") == _SHIPPED_OPENAI
    assert AI_CATALOG["openai"].default_model in _SHIPPED_OPENAI


def test_added_models_come_after_the_shipped_ones_and_can_be_used(vault_preferences) -> None:
    vault_preferences["pref.ai.openai.added_models"] = '["gpt-5.7-nova","ft:gpt-5.6-luna:me::abc"]'
    assert available_models("openai", token="token") == (*_SHIPPED_OPENAI, "gpt-5.7-nova", "ft:gpt-5.6-luna:me::abc")
    assert require_available_model("openai", " gpt-5.7-nova ", token="token") == "gpt-5.7-nova"


def test_a_model_the_vault_has_not_added_is_rejected_politely(vault_preferences) -> None:
    with pytest.raises(InputRejected, match="add it in AI Agent Settings"):
        require_available_model("openai", "gpt-9", token="token")


@pytest.mark.parametrize(("value", "message"), [
    ('["gpt-5.7-nova","gpt-5.7-nova"]', "listed twice"),
    ('["gpt-5.6-luna"]', "already one of OpenAI's models"),
    ('["gpt 5.7"]', "Not a model name"),
    ('[' + ",".join(f'"m{index}"' for index in range(21)) + ']', "At most 20"),
])
def test_an_added_models_list_that_cannot_be_one_is_rejected(value: str, message: str) -> None:
    with pytest.raises(InputRejected, match=message):
        parse_added_models("openai", value)


def test_the_added_models_preference_is_saved_canonically() -> None:
    saved = _validate_client_preferences({"pref.ai.openai.added_models": '[ " gpt-5.7-nova " ]'})
    assert saved == {"pref.ai.openai.added_models": serialize_added_models(("gpt-5.7-nova",))}
    # The picked model only has to be a model name: a later release may drop a shipped one.
    assert _validate_client_preferences({"pref.ai.openai_model": "gpt-5.7-nova"}) == {"pref.ai.openai_model": "gpt-5.7-nova"}
    with pytest.raises(InputRejected):
        _validate_client_preferences({"pref.ai.openai_model": "not a model"})


def test_the_model_list_route_offers_shipped_and_added_models_and_the_default(vault_preferences, monkeypatch) -> None:
    vault_preferences["pref.ai.openai.added_models"] = '["gpt-5.7-nova"]'
    monkeypatch.setattr(ai_routes, "added_models", ai_models_module.added_models)
    response = asyncio.run(ai_routes.list_ai_models(payload=ai_routes.AiModelsRequest(provider="openai"), token="token"))
    assert response.model_dump() == {
        "label": "OpenAI",
        "billing_url": "https://platform.openai.com/usage",
        "models": [*_SHIPPED_OPENAI, "gpt-5.7-nova"],
        "added_models": ["gpt-5.7-nova"],
    }


@pytest.mark.parametrize("ready_providers", [("openai",), ()])
def test_the_chat_picker_lists_the_models_of_each_provider_with_a_key(vault_preferences, monkeypatch, ready_providers) -> None:
    # Without a key, the provider picked last is still listed, so its model stays shown.
    vault_preferences["pref.ai.openai.added_models"] = '["gpt-5.7-nova"]'
    monkeypatch.setattr(ai_routes, "added_models", ai_models_module.added_models)
    monkeypatch.setattr(ai_routes.token_service, "get_session_key", lambda token: "session")
    monkeypatch.setattr(ai_routes, "describe_ai_setup", lambda *, token, session_key: AiSetup(ready_providers=ready_providers))
    response = asyncio.run(ai_routes.list_ai_model_choices(
        payload=ai_routes.AiModelChoicesRequest(current_provider="openai"), token="token"))
    assert response.model_dump() == {"groups": [
        {"provider": "openai", "label": "OpenAI", "models": [*_SHIPPED_OPENAI, "gpt-5.7-nova"]},
    ]}
