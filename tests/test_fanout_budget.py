"""When one research angle trips the daily limit, angles not yet started are cancelled
instead of running (and billing) only to be discarded."""

import threading
import time

import pytest

from adaptive_academy.engine.fanout import fan_out_briefs, fan_out_with_retry
from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.llm.usage import BudgetExceededError


class _BudgetTrippingResearcher:
    def __init__(self):
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def search(self, brief: SearchBrief) -> list[RawSource]:
        with self._lock:
            self.calls.append(brief.angle)
        if brief.angle == "a0":
            raise BudgetExceededError(5.0, 5.0)
        time.sleep(0.05)  # a real search takes a while: the cancel lands while this runs
        return [RawSource(title=brief.angle, url=f"https://e.com/{brief.angle}", tier=1)]


BRIEFS = [SearchBrief(angle=f"a{i}", query="q") for i in range(8)]


@pytest.mark.parametrize("fan_out", [fan_out_briefs, fan_out_with_retry])
def test_pending_angles_are_cancelled_once_the_budget_trips(fan_out):
    researcher = _BudgetTrippingResearcher()
    with pytest.raises(BudgetExceededError):
        fan_out(BRIEFS, researcher, 1)
    # One worker: a0 trips the limit; at most the angle the worker had already picked up
    # in the meantime still runs. Without cancellation all 8 would run.
    assert researcher.calls[0] == "a0"
    assert len(researcher.calls) <= 2, researcher.calls


def test_a_normal_fan_out_still_runs_every_angle():
    class _Ok:
        def search(self, brief):
            return [RawSource(title=brief.angle, url="https://e.com/x", tier=1)]

    per_brief, failures = fan_out_briefs(BRIEFS, _Ok(), 3)
    assert failures == {}
    assert [len(p) for p in per_brief] == [1] * len(BRIEFS)


def test_anchor_generation_cancels_pending_sources_once_the_budget_trips(session):
    # Anchor generation fans out the same way; any failure aborts the whole run, so the
    # sources not yet started are cancelled rather than billed and discarded.
    from adaptive_academy.engine.anchors import generate_anchors
    from adaptive_academy.models import SourceDoc, Topic

    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    for i in range(6):
        session.add(SourceDoc(topic_id=topic.id, title=f"s{i}", url=f"u{i}", rank=i,
                              status="accepted"))
    session.commit()
    calls: list[str] = []

    class _Client:
        def generate(self, brief):
            calls.append(brief.title)
            if brief.title == "s0":
                raise BudgetExceededError(5.0, 5.0)
            time.sleep(0.05)
            return []

    with pytest.raises(BudgetExceededError):
        generate_anchors(session, topic, anchor_client=_Client(), max_workers=1)
    assert calls[0] == "s0"
    assert len(calls) <= 2, calls
