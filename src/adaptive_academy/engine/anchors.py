import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.llm.anchor_types import AnchorBrief, AnchorClient, RawAnchor
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    ReferenceAnchor,
    SourceDoc,
    TopicFoundation,
    Track,
)

_WS = re.compile(r"\s+")


def anchor_key(question: str) -> str:
    """Stable dedup signature for an anchor question (lowercased, ws-collapsed, trimmed)."""
    return _WS.sub(" ", question.strip().lower())


def match_concept(name: str, concepts: list[str]) -> str | None:
    """Case-insensitive exact match; returns the canonical concept name or None."""
    target = name.strip().lower()
    for c in concepts:
        if c.strip().lower() == target:
            return c
    return None


def dedupe_anchors(pairs: list[tuple[int, RawAnchor]]) -> list[tuple[int, RawAnchor]]:
    """Collapse duplicates on (source_doc_id, anchor_key(question)); keep first; stable order."""
    seen: set[tuple[int, str]] = set()
    out: list[tuple[int, RawAnchor]] = []
    for source_id, a in pairs:
        if not a.question.strip():
            continue
        key = (source_id, anchor_key(a.question))
        if key in seen:
            continue
        seen.add(key)
        out.append((source_id, a))
    return out


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def parse_anchors_json(text: str) -> list[RawAnchor]:
    data = json.loads(_strip_fences(text))
    out: list[RawAnchor] = []
    for a in (data.get("anchors", []) or []):
        out.append(RawAnchor(
            question=str(a.get("question", "")),
            reference_answer=str(a.get("reference_answer", "")),
            key_points=list(a.get("key_points", []) or []),
            concept_name=str(a.get("concept", a.get("concept_name", "")) or ""),
        ))
    return out


def build_anchor_brief(source, key_concepts: list[str]) -> AnchorBrief:
    """Build a fan-out brief from a SourceDoc row + the topic's key concepts."""
    return AnchorBrief(source_doc_id=source.id, title=source.title,
                       summary=source.summary, url=source.url,
                       key_concepts=list(key_concepts))


class AnchorGenError(Exception):
    """No accepted sources to generate anchors from (route maps to HTTP 400)."""


@dataclass
class AnchorGenResult:
    anchors: list[ReferenceAnchor]
    events: list[AgentEvent]


def _concept_names(session: Session, topic_id: int) -> list[str]:
    rows = session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)).all()
    return [c.name for c in rows]


def _concept_by_name(session: Session, topic_id: int, name: str) -> Concept | None:
    rows = session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)).all()
    for c in rows:
        if c.name.strip().lower() == name.strip().lower():
            return c
    return None


def _existing_keys(session: Session, topic_id: int) -> set[tuple[int, str]]:
    rows = session.exec(
        select(ReferenceAnchor).join(SourceDoc)
        .where(SourceDoc.topic_id == topic_id)).all()
    return {(r.source_doc_id, anchor_key(r.question)) for r in rows}


def generate_anchors(session: Session, topic, *, anchor_client: AnchorClient,
                     max_workers: int = 5) -> AnchorGenResult:
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    sources = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic.id,
                                SourceDoc.status == "accepted")).all()
    sources.sort(key=lambda s: s.rank)
    if not sources:
        raise AnchorGenError("no accepted sources to generate anchors from")

    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)).first()
    key_concepts = foundation.key_concepts if foundation else _concept_names(session, topic.id)

    briefs = [build_anchor_brief(s, key_concepts) for s in sources]
    emit("anchors:plan", f"{len(briefs)} source(s)")

    per_source: list[list[RawAnchor]] = [[] for _ in briefs]
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(briefs)))) as ex:
        futures = {ex.submit(anchor_client.generate, b): i for i, b in enumerate(briefs)}
        for fut in as_completed(futures):
            per_source[futures[fut]] = fut.result()

    pairs: list[tuple[int, RawAnchor]] = []
    for i, brief in enumerate(briefs):
        found = per_source[i]
        emit("anchors:subagent", f"source {brief.source_doc_id}: {len(found)} anchor(s)")
        pairs.extend((brief.source_doc_id, a) for a in found)

    existing = _existing_keys(session, topic.id)
    created: list[ReferenceAnchor] = []
    for source_id, a in dedupe_anchors(pairs):
        if (source_id, anchor_key(a.question)) in existing:
            continue
        concept = _concept_by_name(session, topic.id, a.concept_name) if a.concept_name else None
        row = ReferenceAnchor(
            source_doc_id=source_id, concept_id=concept.id if concept else None,
            question=a.question, reference_answer=a.reference_answer,
            key_points=list(a.key_points))
        session.add(row)
        created.append(row)

    emit("anchors:done", f"{len(created)} anchor(s) created")
    session.commit()
    for r in created:
        session.refresh(r)
    return AnchorGenResult(anchors=created, events=events)
