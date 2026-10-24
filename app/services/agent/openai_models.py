"""OpenAI's endpoint and context size, without the OpenAI SDK (its models are in
app/services/ai_catalog.py, with the other providers').

Settings, routes and the login path need these; importing the SDK (about 250 ms) for
them made every namespace server pay for it at startup. Only openai_inference.py, which
talks to OpenAI, imports the SDK, and only when an AI connection is first made.
"""

from __future__ import annotations

OPENAI_API_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL_CONTEXT_TOKENS = 1_050_000
