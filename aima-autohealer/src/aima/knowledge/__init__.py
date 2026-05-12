"""Knowledge base used as context for the future LLM-driven decision layer."""

from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent


def blocking_methods_md() -> str:
    return (KNOWLEDGE_DIR / "blocking_methods.md").read_text(encoding="utf-8")


def recipe_catalog_md() -> str:
    return (KNOWLEDGE_DIR / "recipes.md").read_text(encoding="utf-8")
