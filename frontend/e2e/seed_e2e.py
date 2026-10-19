"""Deterministic seed for the Playwright e2e run.

One topic shaped like a real learner's: a phased track whose first item is long enough to
truncate, a 19-concept prerequisite graph with long names (the Constellation stress case),
and a handful of graded assessments so the dashboard has a score history. No LLM calls —
the LLMUsage rows below are recorded-looking fixtures so the Usage page shows real numbers.
"""

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from adaptive_academy.db import engine
from adaptive_academy.models import (
    Assessment,
    Concept,
    ConceptEdge,
    Item,
    KnowledgeEstimate,
    LLMUsage,
    Phase,
    Topic,
    Track,
)

TOPIC_TITLE = "Build LLMs from Scratch including the math"
SECOND_TOPIC_TITLE = "Linear Algebra Refresher"

CONCEPTS = [
    ("Backpropagation and Autograd", True),
    ("Computational Graphs", False),
    ("Chain Rule for Vector Functions", True),
    ("Tokenization and Vocabulary Construction", True),
    ("Byte Pair Encoding", False),
    ("Token Embeddings", True),
    ("Positional Encodings (sinusoidal and RoPE)", False),
    ("Language Modeling Objective", True),
    ("Scaled Dot-Product Attention", True),
    ("Causal (Masked) Self-Attention", True),
    ("Multi-Head Attention", True),
    ("Feed-Forward Sublayer (FFN)", False),
    ("Residual Connections and LayerNorm", False),
    ("Transformer Architecture (GPT-style)", True),
    ("Weight Tying", False),
    ("AdamW and Learning-Rate Schedules", False),
    ("Supervised Fine-Tuning", False),
    ("LoRA", False),
    ("KV Cache", False),
]

# (prerequisite, dependent) by index into CONCEPTS.
EDGES = [
    (1, 0), (2, 0), (2, 1), (4, 3), (3, 5), (5, 6), (5, 7), (0, 7),
    (5, 8), (8, 9), (9, 10), (8, 10), (10, 13), (11, 13), (12, 13), (6, 13),
    (7, 13), (5, 14), (13, 14), (0, 15), (15, 16), (13, 16), (16, 17), (13, 17),
    (9, 18), (13, 18), (2, 8), (7, 9), (12, 11), (15, 13),
]

PHASES = [
    ("Phase 1 — Autograd from First Principles", "50–60 hours (~5–6 weeks)", [
        "Clone micrograd (Karpathy). Delete the engine. Rebuild Value, __add__, __mul__, "
        "__pow__, relu, and backward() from scratch using only the chain rule on paper "
        "first, then code. Cover all ops needed to train an MLP on a toy XOR dataset.",
        "Karpathy Zero-to-Hero episodes 1–2 (micrograd + makemore bigram) — watch AFTER "
        "your own rebuild attempt.",
    ]),
    ("Phase 2 — Tokenization, Embeddings, and the Embedding Table in Detail",
     "45–55 hours (~4–5 weeks)", [
        "Implement byte-level BPE training and encoding; compare against tiktoken.",
    ]),
    ("Phase 3 — Attention Mechanism: Derive, Implement, Ablate", "55–65 hours", [
        "Derive scaled dot-product attention and implement causal masking.",
    ]),
]

# (days ago, feature, model, input, output, web searches, cost_usd; None = price unknown)
USAGE = [
    (0, "tutor", "claude-sonnet-4-6", 12_000, 900, 0, 0.0495),
    (0, "research", "claude-sonnet-4-6", 48_000, 6_000, 5, 0.284),
    (0, "assess", "claude-custom-finetune-with-a-very-long-model-identifier", 3_000, 400, 0, None),
    (3, "curriculum", "claude-sonnet-4-6", 20_000, 12_000, 0, 0.24),
    (12, "tutor", "claude-haiku-4-5", 8_000, 700, 0, 0.0115),
]

# (concept index, kind, score)
ASSESSMENTS = [
    (0, "self_explanation", 0.35),
    (0, "recall", 0.6),
    (8, "self_explanation", 0.8),
    (3, "calibration", 0.5),
]


def seed() -> None:
    with Session(engine) as session:
        topic = Topic(title=TOPIC_TITLE)
        session.add(topic)
        session.flush()
        track = Track(topic_id=topic.id, title="Core track", overview="E2E fixture track.")
        session.add(track)
        session.flush()

        for p, (title, hours, items) in enumerate(PHASES):
            phase = Phase(track_id=track.id, title=title, position=p, est_hours=hours)
            session.add(phase)
            session.flush()
            for i, text in enumerate(items):
                session.add(Item(phase_id=phase.id, text=text, type="build", position=i))

        concepts = []
        for name, load_bearing in CONCEPTS:
            concept = Concept(track_id=track.id, name=name, is_load_bearing=load_bearing)
            session.add(concept)
            session.flush()
            session.add(KnowledgeEstimate(concept_id=concept.id, level="medium"))
            concepts.append(concept)

        for src, dst in EDGES:
            session.add(ConceptEdge(
                src_concept_id=concepts[src].id,
                dst_concept_id=concepts[dst].id,
                kind="prerequisite",
                origin="researcher",
            ))

        for idx, kind, score in ASSESSMENTS:
            session.add(Assessment(
                concept_id=concepts[idx].id,
                kind=kind,
                prompt=f"Explain {concepts[idx].name}.",
                response="fixture",
                score=score,
            ))
        now = datetime.now(timezone.utc)
        for days, feature, model, inp, out, searches, cost in USAGE:
            session.add(LLMUsage(
                created_at=now - timedelta(days=days, minutes=1),
                backend="anthropic", model=model, role="reasoning", operation="complete",
                feature=feature, input_tokens=inp, output_tokens=out,
                web_search_requests=searches, cost_usd=cost,
            ))
        # A second, minimal topic so topic-switching can be exercised. Created last, so the
        # main topic stays first in GET /api/topics.
        other = Topic(title=SECOND_TOPIC_TITLE)
        session.add(other)
        session.flush()
        other_track = Track(topic_id=other.id, title="Core track")
        session.add(other_track)
        session.flush()
        session.add(Concept(track_id=other_track.id, name="Eigenvectors", is_load_bearing=True))

        session.commit()
        print(f"e2e seed: topic {topic.id}, {len(concepts)} concepts, {len(EDGES)} edges")


if __name__ == "__main__":
    seed()
