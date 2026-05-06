from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.llm import LLM

COMPRESS_PROMPT = """\
You are a semantic compressor. Compress the following text WITHOUT losing meaning.
Keep only:
- key facts
- decisions
- entities and relationships
- action items

Remove repetition, filler words, and redundant phrasing.
Output compact JSON or bullet points.
"""


def semantic_compress(llm: LLM, text: str) -> str:
    """Compress text semantically using a lightweight LLM model."""
    return llm.call("openai/gpt-4o-mini", COMPRESS_PROMPT + "\n\n" + text)
