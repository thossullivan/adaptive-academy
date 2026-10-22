"""Spaced revisits are bounded, deduplicated, and placed where they help.

Live evidence (DeepSeek via OpenRouter, "Gradient descent for linear regression"): 7 phases
with 29, 3, 6, 4, 4, 4, 28 items — about 25 app-injected "Revisit & self-explain: <concept>"
items in each of the first and last phases. The fixture below has that shape: 12 key concepts,
a prerequisite map dense with links (including prerequisites that are not key concepts, e.g.
"Big-O complexity of matrix operations"), and a curriculum whose concept_refs spell the key
concepts in a different case, so an exact-string match sees them as never referenced.
"""

import json
from collections import Counter

from sqlmodel import Session, select

from adaptive_academy.engine.curriculum import generate_curriculum
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent, Concept, Item, Phase, SourceDoc, Topic, TopicFoundation, TopicIntent, Track,
)

KEY = [
    "Least-squares cost", "Gradient of the cost", "Batch gradient descent update",
    "Learning rate", "Stability threshold", "Convexity", "Condition number",
    "Feature scaling", "Normal equations", "Stochastic gradient descent",
    "Convergence rate", "Momentum",
]
PREREQ = {
    "Least-squares cost": ["Vector norms", "Matrix transpose"],
    "Gradient of the cost": ["Least-squares cost", "Matrix calculus", "Partial derivatives"],
    "Batch gradient descent update": ["Gradient of the cost", "Learning rate",
                                      "1-D minimization along a direction"],
    "Learning rate": ["Taylor expansion"],
    "Stability threshold": ["Learning rate", "Eigenvalues", "Lipschitz continuity",
                            "Condition number"],
    "Convexity": ["Least-squares cost", "Positive semidefinite matrices"],
    "Condition number": ["Eigenvalues", "Convexity"],
    "Feature scaling": ["Condition number", "Variance"],
    "Normal equations": ["Gradient of the cost", "Linear systems",
                         "Big-O complexity of matrix operations"],
    "Stochastic gradient descent": ["Batch gradient descent update", "Expectation", "Variance"],
    "Convergence rate": ["Stability threshold", "Condition number", "Convexity"],
    "Momentum": ["Batch gradient descent update", "Convergence rate"],
}
# Key concepts something depends on: the only ones that are Concept rows AND load-bearing.
LOAD_BEARING = {"Least-squares cost", "Gradient of the cost", "Batch gradient descent update",
                "Learning rate", "Stability threshold", "Convexity", "Condition number",
                "Convergence rate"}


def _item(text, *refs, kind="build"):
    return {"type": kind, "text": text, "concept_refs": list(refs)}


def _phase(title, *items):
    return {"title": title, "est_hours": "1 wk", "items": list(items),
            "deliverable": {"kind": "blog", "text": "write-up", "acceptance_criteria": ["ok"]}}


def _curriculum() -> str:
    lo = str.lower
    return json.dumps({"overview": "GD for linear regression", "phases": [
        _phase("Setup", _item("Derive the cost", lo("Least-squares cost")),
               _item("Plot the bowl", lo("Convexity")), _item("Read ch. 3"),
               _item("Notation drill", kind="write")),
        _phase("Gradient", _item("Derive the gradient", lo("Gradient of the cost")),
               _item("Check numerically"), _item("Write it up", kind="write")),
        _phase("Batch GD", _item("Implement batch GD", lo("Batch gradient descent update")),
               _item("Sweep step sizes", lo("Learning rate")), _item("a"), _item("b"),
               _item("c"), _item("d")),
        _phase("Stability", _item("Find the threshold", lo("Stability threshold")),
               _item("Eigen-analysis", lo("Condition number")), _item("e"), _item("f")),
        _phase("Scaling", _item("Standardize features", lo("Feature scaling")),
               _item("Compare to normal equations", lo("Normal equations")),
               _item("g"), _item("h")),
        _phase("SGD", _item("Implement SGD", lo("Stochastic gradient descent")),
               _item("Measure rates", lo("Convergence rate")), _item("i"), _item("j")),
        _phase("Momentum", _item("Add momentum", lo("Momentum")), _item("k"), _item("l")),
    ]})


def _run(session: Session):
    topic = Topic(title="Gradient descent for linear regression")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="g", prior_knowledge="p", time_budget="t")
    fnd = TopicFoundation(topic_id=topic.id, overview="ov", key_concepts=list(KEY),
                          prerequisite_map=dict(PREREQ))
    src = SourceDoc(topic_id=topic.id, title="S", url="u", tier=1, summary="s",
                    status="accepted", rank=0)
    session.add_all([intent, fnd, src])
    session.commit()
    llm = ScriptedLLMClient([LLMResponse(text=_curriculum())])
    generate_curriculum(session, topic, intent, fnd, [src], llm=llm)
    track = session.exec(select(Track).where(Track.topic_id == topic.id)).one()
    phases = sorted(session.exec(select(Phase).where(Phase.track_id == track.id)).all(),
                    key=lambda p: p.position)
    items = {p.position: sorted(session.exec(select(Item).where(Item.phase_id == p.id)).all(),
                                key=lambda i: i.position) for p in phases}
    return topic, track, items


def _revisits(items):
    return {pos: [it for it in its if it.text.startswith("Revisit & self-explain: ")]
            for pos, its in items.items()}


def test_evidence_shaped_curriculum_does_not_flood(session: Session):
    _, _, items = _run(session)
    per_phase = {pos: len(r) for pos, r in _revisits(items).items()}
    assert max(per_phase.values()) <= 2, per_phase
    total_items = [len(its) for _, its in sorted(items.items())]
    assert max(total_items) <= 8, total_items  # the model's <=6 plus at most 2 revisits


def test_revisits_only_name_key_concepts_once_per_phase(session: Session):
    _, _, items = _run(session)
    for pos, rs in _revisits(items).items():
        assert all(len(r.concept_refs) == 1 for r in rs)
        refs = [r.concept_refs[0] for r in rs]
        assert set(refs) <= set(KEY), refs  # never "Big-O complexity of ..." etc.
        assert len(refs) == len(set(refs)), refs
        # never a revisit of a concept in a phase that already covers it
        covered = {c for it in items[pos] if it not in rs for c in it.concept_refs}
        assert not set(refs) & covered


def test_concept_refs_are_canonical_names(session: Session):
    _, _, items = _run(session)
    refs = {c for its in items.values() for it in its for c in it.concept_refs}
    assert refs <= set(KEY), refs - set(KEY)


def test_every_load_bearing_concept_is_spaced(session: Session):
    _, track, items = _run(session)
    phases_of: Counter = Counter()
    for its in items.values():
        for c in {c for it in its for c in it.concept_refs}:
            phases_of[c] += 1
    assert all(phases_of[c] >= 2 for c in LOAD_BEARING), {c: phases_of[c] for c in LOAD_BEARING}
    concepts = session.exec(select(Concept).where(Concept.track_id == track.id)).all()
    assert {c.name for c in concepts if c.is_load_bearing} == LOAD_BEARING


def test_spacing_event_reports_the_bounded_count(session: Session):
    topic, _, items = _run(session)
    injected = sum(len(r) for r in _revisits(items).values())
    assert injected <= 2 * len(LOAD_BEARING)
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    spaced = [e.detail for e in events if e.kind == "curriculum:spaced"]
    assert spaced == [f"{injected} revisit item(s) injected"]
