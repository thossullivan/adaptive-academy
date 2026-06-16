import threading

from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor


class ScriptedAnchorClient:
    """Test double: returns canned RawAnchors keyed by source_doc_id. Thread-safe."""

    def __init__(self, by_source: dict[int, list[RawAnchor]]):
        self._by_source = by_source
        self._lock = threading.Lock()
        self.calls: list[int] = []

    def generate(self, brief: AnchorBrief) -> list[RawAnchor]:
        with self._lock:
            self.calls.append(brief.source_doc_id)
        return list(self._by_source.get(brief.source_doc_id, []))
