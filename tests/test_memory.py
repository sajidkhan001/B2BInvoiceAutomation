from __future__ import annotations

import pickle

import pytest

from b2bdoc.memory import BoundedMemoryManager, MemoryPolicyViolation


def test_envelope_cannot_be_pickled_and_wipe_releases_memory():
    manager = BoundedMemoryManager(max_item_bytes=100, max_total_bytes=100)
    envelope = manager.create_envelope(
        [b"%PDF-1.7\nsecret-bytes"],
        source_type="test",
        source_id="1",
        filename="invoice.pdf",
    )
    assert manager.inflight_bytes > 0
    with pytest.raises(TypeError):
        pickle.dumps(envelope)
    envelope.wipe()
    assert envelope.buffer.is_wiped
    assert manager.inflight_bytes == 0


def test_memory_manager_rejects_over_budget_file():
    manager = BoundedMemoryManager(max_item_bytes=4, max_total_bytes=10)
    with pytest.raises(MemoryPolicyViolation):
        manager.create_envelope([b"12345"], source_type="test", source_id="1", filename="x.pdf")
