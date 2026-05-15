"""AI Router — Multi-agent pipeline with semantic compression and Redis memory."""

from __future__ import annotations

import logging
import os
import sys

from core.llm import LLM
from core.router import route
from storage.redis_client import RedisMemory
from core.memory import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error(
            "OPENROUTER_API_KEY environment variable is not set. "
            "Please set it before running the router."
        )
        sys.exit(1)

    llm = LLM(api_key=api_key)

    redis_host = os.environ.get("REDIS_HOST", "localhost")
    redis_port = int(os.environ.get("REDIS_PORT", "6379"))

    try:
        redis_mem = RedisMemory(host=redis_host, port=redis_port)
        if redis_mem.ping():
            logger.info("Redis connection established")
        else:
            logger.warning("Redis not reachable — running without state persistence")
            redis_mem = None
    except Exception:
        logger.warning("Redis not available — running without state persistence")
        redis_mem = None

    state_mgr = StateManager(redis_mem) if redis_mem else None

    user_id = os.environ.get("USER_ID", "default_user")

    print("\n=== AI Router — Multi-Agent Pipeline ===")
    print("Type your request below. Press Ctrl+C to exit.\n")

    while True:
        try:
            user_input = input("INPUT: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not user_input:
            continue

        try:
            result = route(llm, user_input)

            if state_mgr:
                state_mgr.update_memory(
                    user_id,
                    {
                        "last_input": user_input,
                        "last_output": result[:500],
                    },
                )

            print("\n--- OUTPUT ---")
            print(result)
            print()

        except Exception as exc:
            logger.error("Pipeline error: %s", exc)
            print(f"\nError: {exc}\n")


if __name__ == "__main__":
    main()
