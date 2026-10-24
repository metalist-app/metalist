"""Which AI MetaList can use, without features knowing any one provider.

Features ask whether an AI is set up (describe_ai_setup) and for a connection
to it (connect_to_ai); they never look for a particular provider's key. Each
provider is registered here, with how to tell it is set up and how to talk to
it: OpenAI, Claude (Anthropic) and Gemini.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.agent.inference import InferenceAdapter
from app.services.agent.openai_cost_tracking import openai_cost_tracker
from app.services.ai_catalog import catalog_entry
from app.services.ai_credentials import ai_credential_store
from app.services.agent.privacy_guard import PrivacyGuardedInference, cloud_privacy_revision


AiProvider = Literal["openai", "anthropic", "gemini"]

# The providers MetaList can use, in the order it prefers them (and lists them).
AI_PROVIDERS: tuple[AiProvider, ...] = ("openai", "anthropic", "gemini")


class AiNotSetUp(RuntimeError):
    """The AI a request named has no credentials (the user removed them, or never added any)."""


@dataclass(frozen=True, slots=True)
class AiSetup:
    # Set up and usable now, in preference order.
    ready_providers: tuple[AiProvider, ...]

    def is_ready_for(self, provider: AiProvider) -> bool:
        assert provider in AI_PROVIDERS, f"Unregistered AI provider: {provider}"
        return provider in self.ready_providers


@dataclass(frozen=True, slots=True)
class AiConnection:
    provider: AiProvider
    # How the provider is named on screen ("Connecting to OpenAI API").
    label: str
    # Shown once connected, with the model's context size.
    ready_label: str
    base_url: str
    inference: InferenceAdapter


def _is_provider_ready(provider: AiProvider, *, token: str, session_key: str) -> bool:
    assert provider in AI_PROVIDERS, f"Unregistered AI provider: {provider}"
    return ai_credential_store(provider).status(token=token, session_key=session_key).configured


def describe_ai_setup(*, token: str, session_key: str) -> AiSetup:
    if not isinstance(token, str) or token == "":
        raise TypeError("token must be a non-empty string")
    return AiSetup(ready_providers=tuple(
        provider for provider in AI_PROVIDERS
        if _is_provider_ready(provider, token=token, session_key=session_key)
    ))


def connect_to_ai(*, provider: AiProvider, token: str, session_key: str) -> AiConnection:
    """A connection to the named AI; AiNotSetUp when it has no credentials."""
    if not describe_ai_setup(token=token, session_key=session_key).is_ready_for(provider):
        raise AiNotSetUp(f"{provider} is not set up")
    entry = catalog_entry(provider)
    api_key = ai_credential_store(provider).resolve(token=token, session_key=session_key)
    return AiConnection(
        provider=provider,
        label=entry.label,
        ready_label=f"{entry.label} API ready · {entry.context_tokens:,}-token context",
        base_url=entry.base_url,
        # Stops sending once the cloud privacy settings change during the request.
        inference=PrivacyGuardedInference(
            inner=_adapter(provider, api_key=api_key),
            privacy_revision_at_start=cloud_privacy_revision.current(),
        ),
    )


def _adapter(provider: AiProvider, *, api_key: str) -> InferenceAdapter:
    # Each SDK is imported on first use, not at the top: loading one takes hundreds of
    # milliseconds, and every namespace server would pay for all of them at startup.
    if provider == "openai":
        from app.services.agent.openai_inference import OpenAIInferenceAdapter
        return OpenAIInferenceAdapter(api_key=api_key, cost_tracker=openai_cost_tracker)
    if provider == "anthropic":
        from app.services.agent.anthropic_inference import AnthropicInferenceAdapter
        return AnthropicInferenceAdapter(api_key=api_key)
    if provider == "gemini":
        from app.services.agent.openai_compatible_inference import GEMINI, OpenAICompatibleInferenceAdapter
        return OpenAICompatibleInferenceAdapter(api_key=api_key, provider=GEMINI)
    raise AssertionError(f"Unregistered AI provider: {provider}")
