"""Each model's context window, from the provider where it says (the maintainer, 2026-11-08):
Claude's Models API and Gemini's models.get report it; OpenAI's models endpoint does not, so
its size stays in the catalog. Asked once per model while MetaList runs."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import anyio
import httpx
import pytest
from anthropic import APIConnectionError
from fastapi import HTTPException

from app.api.routes import ai as ai_routes
from app.services.agent import anthropic_inference, openai_compatible_inference
from app.services.agent.anthropic_inference import AnthropicInferenceAdapter, AnthropicProviderError
from app.services.agent.inference import InferenceProviderError
from app.services.agent.openai_compatible_inference import GEMINI, OpenAICompatibleInferenceAdapter
from app.services.agent.openai_cost_tracking import OpenAICostTracker
from app.services.agent.openai_inference import OpenAIInferenceAdapter
from app.services.agent.openai_models import OPENAI_API_BASE_URL, OPENAI_MODEL_CONTEXT_TOKENS
from app.services.ai_catalog import catalog_entry

CLAUDE_URL = catalog_entry("anthropic").base_url
GEMINI_URL = catalog_entry("gemini").base_url


@pytest.fixture(autouse=True)
def nothing_remembered(monkeypatch):
    monkeypatch.setattr(anthropic_inference, "_CONTEXT_TOKENS_BY_MODEL", {})
    monkeypatch.setattr(openai_compatible_inference, "_CONTEXT_TOKENS_BY_MODEL", {})


def _claude_adapter(monkeypatch, retrieve) -> AnthropicInferenceAdapter:
    adapter = AnthropicInferenceAdapter(api_key="test-key")
    monkeypatch.setattr(adapter, "_client", lambda on_wire_request, *, model: SimpleNamespace(models=SimpleNamespace(retrieve=retrieve)))
    return adapter


def test_claude_reports_its_window_and_is_asked_once_per_model(monkeypatch) -> None:
    asked: list[str] = []

    async def retrieve(model: str):
        asked.append(model)
        return SimpleNamespace(max_input_tokens={"claude-haiku-5-5": 200_000, "claude-opus-5-5": 1_000_000}[model])

    adapter = _claude_adapter(monkeypatch, retrieve)

    async def inspect(model: str) -> int:
        return (await adapter.inspect_context_window(base_url=CLAUDE_URL, model=model)).maximum_tokens

    assert asyncio.run(inspect("claude-haiku-5-5")) == 200_000
    assert asyncio.run(inspect("claude-haiku-5-5")) == 200_000
    assert asyncio.run(inspect("claude-opus-5-5")) == 1_000_000
    assert asked == ["claude-haiku-5-5", "claude-opus-5-5"]


def test_a_failed_claude_lookup_says_so(monkeypatch) -> None:
    async def retrieve(model: str):
        raise APIConnectionError(request=httpx.Request("GET", CLAUDE_URL))

    adapter = _claude_adapter(monkeypatch, retrieve)
    with pytest.raises(AnthropicProviderError, match="Anthropic"):
        asyncio.run(adapter.inspect_context_window(base_url=CLAUDE_URL, model="claude-opus-5-5"))


def _gemini_adapter(monkeypatch, handler) -> OpenAICompatibleInferenceAdapter:
    monkeypatch.setattr(
        openai_compatible_inference, "_model_info_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return OpenAICompatibleInferenceAdapter(api_key="test-key", provider=GEMINI)


def test_gemini_reports_its_window_and_is_asked_once_per_model(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"name": "models/gemini-3.8-flash", "inputTokenLimit": 2_000_000})

    adapter = _gemini_adapter(monkeypatch, handler)

    async def inspect() -> int:
        return (await adapter.inspect_context_window(base_url=GEMINI_URL, model="gemini-3.8-flash")).maximum_tokens

    assert asyncio.run(inspect()) == 2_000_000
    assert asyncio.run(inspect()) == 2_000_000
    assert len(requests) == 1
    assert str(requests[0].url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash"
    assert requests[0].headers["x-goog-api-key"] == "test-key"


@pytest.mark.parametrize("answer", [
    httpx.Response(403, json={"error": {"message": "denied"}}),
    httpx.Response(200, json={"name": "models/gemini-3.8-flash"}),
], ids=["refused", "no limit in the answer"])
def test_a_failed_gemini_lookup_says_so(monkeypatch, answer: httpx.Response) -> None:
    adapter = _gemini_adapter(monkeypatch, lambda request: answer)
    with pytest.raises(InferenceProviderError, match="Google"):
        asyncio.run(adapter.inspect_context_window(base_url=GEMINI_URL, model="gemini-3.8-flash"))


def test_openai_uses_the_catalog() -> None:
    adapter = OpenAIInferenceAdapter(api_key="test-key", cost_tracker=OpenAICostTracker())
    window = asyncio.run(adapter.inspect_context_window(base_url=OPENAI_API_BASE_URL, model="gpt-5.6-sol"))
    assert window.maximum_tokens == OPENAI_MODEL_CONTEXT_TOKENS


def _connection(inference) -> SimpleNamespace:
    return SimpleNamespace(inference=inference, base_url="https://provider.example")


def _context_tokens_from_a_route(connection) -> int:
    """As a sync route calls it: from a worker thread, while the server's event loop runs."""
    async def scenario() -> int:
        return await anyio.to_thread.run_sync(lambda: ai_routes._model_context_tokens(connection=connection, model="any-model"))
    return anyio.run(scenario)


def test_a_route_reads_the_models_window() -> None:
    class Reporting:
        async def inspect_context_window(self, *, base_url: str, model: str):
            assert (base_url, model) == ("https://provider.example", "any-model")
            return SimpleNamespace(maximum_tokens=200_000)

    assert _context_tokens_from_a_route(_connection(Reporting())) == 200_000


def test_a_route_says_when_the_provider_could_not_report_its_window() -> None:
    class Failing:
        async def inspect_context_window(self, *, base_url: str, model: str):
            raise InferenceProviderError("Claude could not say how large the model's window is")

    with pytest.raises(HTTPException, match="could not say") as raised:
        _context_tokens_from_a_route(_connection(Failing()))
    assert raised.value.status_code == 502
