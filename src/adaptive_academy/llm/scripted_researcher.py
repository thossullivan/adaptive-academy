import threading

from adaptive_academy.llm.researcher_types import RawSource, SearchBrief


class ScriptedResearcherClient:
    """Test double: returns canned RawSources keyed by brief angle. Thread-safe."""

    def __init__(self, by_angle: dict[str, list[RawSource]]):
        self._by_angle = by_angle
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def search(self, brief: SearchBrief) -> list[RawSource]:
        with self._lock:
            self.calls.append(brief.angle)
        return list(self._by_angle.get(brief.angle, []))
