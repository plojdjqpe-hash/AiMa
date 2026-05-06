from __future__ import annotations

import json
import logging
from typing import Any

import redis

logger = logging.getLogger(__name__)


class RedisMemory:
    """Redis-backed key-value store for per-user state and memory."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
    ) -> None:
        self.client = redis.Redis(
            host=host, port=port, db=db, decode_responses=True
        )
        logger.info("Connected to Redis at %s:%d/%d", host, port, db)

    def save_state(self, user_id: str, state: dict[str, Any]) -> None:
        key = f"state:{user_id}"
        self.client.set(key, json.dumps(state))
        logger.debug("Saved state for %s", user_id)

    def load_state(self, user_id: str) -> dict[str, Any]:
        key = f"state:{user_id}"
        data = self.client.get(key)
        if data is None:
            return {}
        return json.loads(data)

    def update_memory(self, user_id: str, new_info: dict[str, Any]) -> None:
        state = self.load_state(user_id)
        state.update(new_info)
        self.save_state(user_id, state)

    def delete_state(self, user_id: str) -> None:
        key = f"state:{user_id}"
        self.client.delete(key)
        logger.debug("Deleted state for %s", user_id)

    def ping(self) -> bool:
        try:
            return self.client.ping()
        except redis.ConnectionError:
            return False
