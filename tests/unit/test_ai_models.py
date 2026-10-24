"""Which models a vault can use: only the ones MetaList ships (ai_catalog.py), each
tested with MetaList's prompts. A user never types a model in."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

import app.api.routes.ai as ai_routes
import app.services.ai_setup as ai_setup_module
from app.services.ai_catalog import AI_CATALOG, require_shipped_model
from app.services.ai_credentials import AiCredentialStatus
from app.services.ai_setup import AI_PROVIDERS, AiSetup
from app.services.bulk_operation import bulk_operation_guard
from app.services.client_state_service import _validate_client_preferences
from app.services.input_errors import InputRejected


def test_a_request_names_one_of_the_offered_models_or_is_refused_politely() -> None:
    assert require_shipped_model("openai", " gpt-5.6-luna ") == "gpt-5.6-luna"
    assert require_shipped_model("anthropic", "claude-sonnet-5-5") == "claude-sonnet-5-5"
    with pytest.raises(InputRejected, match="gpt-5.7-nova is not one of the OpenAI models MetaList offers"):
        require_shipped_model("openai", "gpt-5.7-nova")
    with pytest.raises(InputRejected, match="Not a model name"):
        require_shipped_model("gemini", "gemini 3.8")


@pytest.mark.parametrize("ready_providers", [("openai",), ()])
def test_the_chat_picker_lists_the_models_of_each_provider_with_a_key(monkeypatch, ready_providers) -> None:
    # Without a key, the provider picked last is still listed, so its model stays shown.
    monkeypatch.setattr(ai_routes.token_service, "get_session_key", lambda token: "session")
    monkeypatch.setattr(ai_routes, "describe_ai_setup", lambda *, token, session_key: AiSetup(ready_providers=ready_providers))
    response = asyncio.run(ai_routes.list_ai_model_choices(
        current_provider="openai", token="token"))
    assert response.model_dump() == {"groups": [
        {"provider": "openai", "label": "OpenAI", "models": list(AI_CATALOG["openai"].models)},
    ]}


def test_the_chat_picker_lists_every_provider_with_a_key_in_order(monkeypatch) -> None:
    monkeypatch.setattr(ai_routes.token_service, "get_session_key", lambda token: "session")
    monkeypatch.setattr(ai_routes, "describe_ai_setup",
                        lambda *, token, session_key: AiSetup(ready_providers=("anthropic", "gemini")))
    response = asyncio.run(ai_routes.list_ai_model_choices(
        current_provider="gemini", token="token"))
    assert [(group.label, group.models) for group in response.groups] == [
        ("Anthropic", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]),
        ("Google", ["gemini-4-argon", "gemini-3.8-flash", "gemini-3.5-flash-lite"]),
    ]


def test_listing_the_models_works_while_another_request_changes_the_vault(monkeypatch) -> None:
    # The chat refreshes its picker while the user edits; a read that took the one
    # mutation slot made a note save at that moment fail with 409 (2026-10-24).
    route = next(route for route in ai_routes.router.routes if route.path.endswith("/model-choices"))
    assert route.methods == {"GET"}
    monkeypatch.setattr(ai_routes.token_service, "get_session_key", lambda token: "session")
    monkeypatch.setattr(ai_routes, "describe_ai_setup", lambda *, token, session_key: AiSetup(ready_providers=("openai",)))
    with bulk_operation_guard.track_mutation():
        response = asyncio.run(ai_routes.list_ai_model_choices(current_provider="openai", token="token"))
    assert [group.provider for group in response.groups] == ["openai"]


def test_the_browsers_provider_list_matches_the_catalog() -> None:
    # ai-providers.js copies each provider's label, default model and billing page, in the catalog's order.
    source = (Path(__file__).resolve().parents[2] / "app/static/js/modules/ai-chat/ai-providers.js").read_text()
    listed = re.findall(
        r"\{ provider: '([a-z]+)', label: '([^']+)', defaultModel: '([^']+)', billingUrl: '([^']+)' \}", source)
    assert listed == [(provider, entry.label, entry.default_model, entry.billing_url) for provider, entry in AI_CATALOG.items()]
    assert tuple(AI_CATALOG) == AI_PROVIDERS


@pytest.mark.parametrize(("provider", "adapter_class"), [
    ("openai", "OpenAIInferenceAdapter"),
    ("anthropic", "AnthropicInferenceAdapter"),
    ("gemini", "OpenAICompatibleInferenceAdapter"),
])
def test_each_provider_connects_through_its_own_adapter(monkeypatch, provider, adapter_class) -> None:
    class KeyStore:
        def status(self, **kwargs):
            return AiCredentialStatus(configured=True, persistent=False)

        def resolve(self, **kwargs):
            return "test-key"

    monkeypatch.setattr(ai_setup_module, "ai_credential_store", lambda name: KeyStore())
    connection = ai_setup_module.connect_to_ai(provider=provider, token="token", session_key="session")
    entry = AI_CATALOG[provider]
    assert (connection.label, connection.base_url) == (entry.label, entry.base_url)
    assert connection.ready_label == f"{entry.label} API ready · {entry.context_tokens:,}-token context"
    assert type(connection.inference._inner).__name__ == adapter_class


def test_a_vault_saves_the_picked_provider_and_drops_models_it_once_typed_in() -> None:
    saved = _validate_client_preferences({
        "pref.ai.provider": "anthropic",
        "pref.ai.anthropic_model": "claude-sonnet-5-5",
        # Typed-in models (removed 2026-10-23): a vault that saved some loads without them.
        "pref.ai.openai.added_models": '["gpt-5.7-nova"]',
        "pref.ai.gemini.added_models": '["gemini-3.9-flash"]',
    })
    assert saved == {"pref.ai.provider": "anthropic", "pref.ai.anthropic_model": "claude-sonnet-5-5"}
