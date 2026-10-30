"""Load agent prompt resources shipped with the application package."""

from __future__ import annotations

from importlib.resources import files


def load_prompt(name: str) -> str:
    assert isinstance(name, str) and name != ""
    prompt = files(__package__).joinpath(name).read_text(encoding="utf-8")
    assert prompt.strip() != "", f"Agent prompt resource is empty: {name}"
    return prompt.rstrip("\n")


AGENT_SYSTEM_PROMPT = load_prompt("system.md")
AGENT_LOOP_INSTRUCTIONS = load_prompt("agent.md")
FINAL_RESPONSE_REQUEST_PROMPT = load_prompt("final-response.md")
CONVERSATION_SUMMARY_PROMPT = load_prompt("conversation-summary.md")
