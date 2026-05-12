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
