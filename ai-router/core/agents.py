from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.llm import LLM


class Agent:
    """A single-purpose agent that processes input through an LLM with a role-specific prompt."""

    def __init__(self, name: str, prompt: str, model: str) -> None:
        self.name = name
        self.prompt = prompt
        self.model = model

    def run(self, llm: LLM, input_text: str) -> str:
        return llm.call(self.model, self.prompt + "\n\n" + input_text)

    def __repr__(self) -> str:
        return f"Agent(name={self.name!r}, model={self.model!r})"


AGENTS: dict[str, Agent] = {
    "planner": Agent(
        "planner",
        "Break the following task into clear, actionable steps.",
        "openai/gpt-4o",
    ),
    "coder": Agent(
        "coder",
        "Write optimized, production-ready code for the following task.",
        "openai/gpt-4o",
    ),
    "analyst": Agent(
        "analyst",
        "Analyze the following and extract key insights, patterns, and recommendations.",
        "openai/gpt-4o-mini",
    ),
    "summarizer": Agent(
        "summarizer",
        "Compress the following text into its key points without losing meaning.",
        "openai/gpt-4o-mini",
    ),
    "validator": Agent(
        "validator",
        "Check the following for correctness, errors, and potential improvements.",
        "openai/gpt-4o",
    ),
}
