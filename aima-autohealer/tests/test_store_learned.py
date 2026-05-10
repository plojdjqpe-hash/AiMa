"""Tests for the learned_rules table on Store."""

from __future__ import annotations

from pathlib import Path

import pytest

from aima.store import Store
from aima.types import BlockType


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "t.db")


def test_record_outcome_increments_counters(store: Store) -> None:
    store.record_recipe_outcome(
        asn=8359, block_type=BlockType.SNI_BLOCK, recipe_id="rotate_sni_pool", success=True
    )
    store.record_recipe_outcome(
        asn=8359, block_type=BlockType.SNI_BLOCK, recipe_id="rotate_sni_pool", success=True
    )
    store.record_recipe_outcome(
        asn=8359, block_type=BlockType.SNI_BLOCK, recipe_id="rotate_sni_pool", success=False
    )
    pri = store.learned_priority_map()
    score = pri[(8359, BlockType.SNI_BLOCK, "rotate_sni_pool")]
    # 2 success, 1 failure -> (2-1)/3 ≈ 0.333
    assert abs(score - (1 / 3)) < 1e-6


def test_global_asn_round_trips_as_none(store: Store) -> None:
    store.record_recipe_outcome(
        asn=None, block_type=BlockType.QUIC_DROP, recipe_id="force_tcp_only", success=True
    )
    pri = store.learned_priority_map()
    assert (None, BlockType.QUIC_DROP, "force_tcp_only") in pri


def test_priority_map_filters_zero_total(store: Store) -> None:
    # No outcomes -> empty map
    assert store.learned_priority_map() == {}


def test_record_observation_increments_only_observed_count(store: Store) -> None:
    store.record_observation(
        asn=8359, block_type=BlockType.SNI_BLOCK, recipe_id="rotate_sni_pool"
    )
    store.record_observation(
        asn=8359, block_type=BlockType.SNI_BLOCK, recipe_id="rotate_sni_pool"
    )
    cur = store._conn.cursor()  # noqa: SLF001
    row = cur.execute(
        "SELECT success_count, failure_count, observed_count "
        "FROM learned_rules "
        "WHERE asn=? AND block_type=? AND recipe_id=?",
        (8359, BlockType.SNI_BLOCK.value, "rotate_sni_pool"),
    ).fetchone()
    cur.close()

    assert row["success_count"] == 0
    assert row["failure_count"] == 0
    assert row["observed_count"] == 2


def test_observation_does_not_pollute_priority_map(store: Store) -> None:
    """``learned_priority_map`` should still ignore rows with zero outcomes,
    even after passive observations bumped ``observed_count``."""

    store.record_observation(
        asn=None, block_type=BlockType.QUIC_DROP, recipe_id="force_tcp_only"
    )
    assert store.learned_priority_map() == {}

    # but a single real outcome must surface immediately
    store.record_recipe_outcome(
        asn=None,
        block_type=BlockType.QUIC_DROP,
        recipe_id="force_tcp_only",
        success=True,
    )
    pri = store.learned_priority_map()
    assert (None, BlockType.QUIC_DROP, "force_tcp_only") in pri
