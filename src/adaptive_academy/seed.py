from sqlmodel import Session, select

from adaptive_academy.db import create_db_and_tables, engine
from adaptive_academy.models import Concept, KnowledgeEstimate, Topic, Track

_CONCEPTS = [
    ("self-attention", True),
    ("backpropagation", True),
    ("tokenization (BPE)", True),
    ("LoRA / low-rank adaptation", False),
]


def seed() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        if session.exec(select(Topic)).first():
            print("Already seeded.")
            return
        topic = Topic(title="Build LLMs from scratch")
        session.add(topic)
        session.commit()
        track = Track(topic_id=topic.id, title="Core track")
        session.add(track)
        session.commit()
        for name, load_bearing in _CONCEPTS:
            concept = Concept(track_id=track.id, name=name, is_load_bearing=load_bearing)
            session.add(concept)
            session.commit()
            session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
        session.commit()
        print(f"Seeded topic {topic.id} with {len(_CONCEPTS)} concepts.")
