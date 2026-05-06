from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.agents import AGENTS
from core.compressor import semantic_compress

if TYPE_CHECKING:
    from core.llm import LLM

logger = logging.getLogger(__name__)


def route(llm: LLM, user_input: str) -> str:
    """Run the full multi-agent pipeline on user input.

    Pipeline:
        1. Semantic compression of input
        2. Planner agent breaks task into steps
        3. Analyst agent extracts insights from the plan
        4. Coder agent produces code/output from the analysis
        5. Validator agent checks correctness
    """
    logger.info("Starting pipeline for input: %.100s...", user_input)

    compressed = semantic_compress(llm, user_input)
    logger.debug("Compressed input: %.200s...", compressed)

    plan = AGENTS["planner"].run(llm, compressed)
    logger.debug("Plan: %.200s...", plan)

    analysis = AGENTS["analyst"].run(llm, plan)
    logger.debug("Analysis: %.200s...", analysis)

    code = AGENTS["coder"].run(llm, analysis)
    logger.debug("Code output: %.200s...", code)

    validated = AGENTS["validator"].run(llm, code)
    logger.info("Pipeline complete.")

    return validated
