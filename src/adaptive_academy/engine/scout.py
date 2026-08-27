"""Evidence-backed topic scouting for a Program.

Candidate generation is deterministic and read-only. One structured LLM call ranks
the resulting digest. Only reviewable ``TopicSuggestion`` rows are persisted here.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from sqlalchemy import func
from sqlmodel import Session, col, select

from adaptive_academy.engine import graph
from adaptive_academy.engine.aliases import normalize_name
from adaptive_academy.engine.memory import escape_markers
from adaptive_academy.llm.structured import SCOUT_SCHEMA, structured_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Chunk,
    ChunkConcept,
    Concept,
    ConceptAlias,
    Milestone,
    Program,
    ProgramTopicLink,
    TopicSuggestion,
    Track,
    now_utc,
)
from adaptive_academy.prompts import SCOUT_RANK

logger = logging.getLogger(__name__)

SCOUT_DISMISS_COOLDOWN_DAYS = 30
SCOUT_EVERY_N_ASSESSMENTS = 25
SCOUT_DEADLINE_S = 10.0
SCOUT_CHECK_EVERY = 64  # rows between deadline checks inside a generator


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline
SCOUT_DIGEST_MAX_CHARS = 12_000
SCOUT_FIELD_MAX_CHARS = 200
SCOUT_GOAL_MAX_CHARS = 2000
SCOUT_MAX_MILESTONES = 40
SCOUT_MAX_SUGGESTIONS = 5

FRONTIER_WEIGHT = 4.0
ORPHAN_NOTE_WEIGHT = 1.0
EXTENSION_WEIGHT = 3.0

SCOUT_KINDS = ("frontier", "orphan_term", "orphan_note", "extension")
_CAPITALIZED_TERM_RE = re.compile(
    r"(?<!\w)([A-Z][\w'-]*(?:[ \t]+[A-Z][\w'-]*)+)(?!\w)"
)
_BACKTICK_IDENTIFIER_RE = re.compile(r"`([^`\s]+)`")
_PAPER_PROBE_REF_RE = re.compile(r"^paperprobe:(\d+)(?:#.*)?$")


@dataclass(frozen=True)
class Candidate:
    kind: str
    label: str
    evidence: list[dict]
    weight: float


@dataclass(frozen=True)
class ScoutResult:
    suggestions: list[TopicSuggestion]
    counts: dict[str, int]
    truncated: bool


def _program_topic_ids(
    session: Session, program_id: int, *, deadline: float | None = None
) -> list[int]:
    if _expired(deadline):
        return []
    topic_ids = session.exec(
        select(ProgramTopicLink.topic_id)
        .join(Milestone, ProgramTopicLink.milestone_id == Milestone.id)
        .where(
            Milestone.program_id == program_id,
            col(Milestone.archived).is_(False),
            ProgramTopicLink.status != "pruned",
            col(ProgramTopicLink.topic_id).is_not(None),
        )
        .order_by(ProgramTopicLink.id)
    ).all()
    return list(dict.fromkeys(int(topic_id) for topic_id in topic_ids if topic_id is not None))


def _program_tracks(
    session: Session, program_id: int, *, deadline: float | None = None
) -> list[Track]:
    topic_ids = _program_topic_ids(session, program_id, deadline=deadline)
    if not topic_ids or _expired(deadline):
        return []
    return session.exec(
        select(Track).where(Track.topic_id.in_(topic_ids)).order_by(Track.id)
    ).all()


def _append_unique_evidence(target: list[dict], entries: list[dict]) -> None:
    seen = {json.dumps(entry, sort_keys=True, default=str) for entry in target}
    for entry in entries:
        key = json.dumps(entry, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            target.append(entry)


def frontier_candidates(
    session: Session, program_id: int, *, deadline: float | None = None
) -> list[Candidate]:
    """Return outside graph neighbors reached from verified Program concepts."""
    grouped: dict[str, Candidate] = {}
    for track in _program_tracks(session, program_id, deadline=deadline):
        if track.id is None or _expired(deadline):
            break
        for concept_id, outside_names in graph.frontier(
            session,
            track.id,
            deadline=deadline,
        ):
            if _expired(deadline):
                break
            for outside_name in outside_names:
                key = normalize_name(outside_name)
                evidence = [
                    {"kind": "concept", "id": concept_id},
                    {"kind": "neighbor", "name": outside_name},
                ]
                existing = grouped.get(key)
                if existing is None:
                    grouped[key] = Candidate(
                        kind="frontier",
                        label=outside_name,
                        evidence=evidence,
                        weight=FRONTIER_WEIGHT,
                    )
                    continue
                merged_evidence = list(existing.evidence)
                _append_unique_evidence(merged_evidence, evidence)
                grouped[key] = Candidate(
                    kind=existing.kind,
                    label=existing.label,
                    evidence=merged_evidence,
                    weight=existing.weight + FRONTIER_WEIGHT,
                )
    return sorted(grouped.values(), key=lambda item: (-item.weight, normalize_name(item.label)))


def _known_concept_names(session: Session, *, deadline: float | None = None) -> list[str]:
    if _expired(deadline):
        return []
    names = [name for name in session.exec(select(Concept.name)).all() if name.strip()]
    if _expired(deadline):
        return list(dict.fromkeys(names))
    names.extend(
        name
        for name in session.exec(select(ConceptAlias.canonical_name)).all()
        if name.strip()
    )
    return list(dict.fromkeys(names))


def _matches_known_name(term: str, known_names: list[str]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(name)}(?!\w)", term, flags=re.IGNORECASE)
        for name in known_names
    )


def _extract_terms(text: str) -> list[str]:
    identifiers = [match.group(1).strip() for match in _BACKTICK_IDENTIFIER_RE.finditer(text)]
    prose = _BACKTICK_IDENTIFIER_RE.sub(" ", text)
    capitalized = [match.group(1).strip() for match in _CAPITALIZED_TERM_RE.finditer(prose)]
    return [term for term in [*capitalized, *identifiers] if term]


def orphan_term_candidates(
    session: Session, program_id: int, *, deadline: float | None = None
) -> list[Candidate]:
    """Find repeated learner or tutor terms not represented in the concept graph."""
    topic_ids = _program_topic_ids(session, program_id, deadline=deadline)
    if not topic_ids:
        return []
    if _expired(deadline):
        return []
    known_names = _known_concept_names(session, deadline=deadline)
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    refs: dict[str, set[str]] = {}
    last_id = 0
    while True:
        if _expired(deadline):
            break
        chunks = session.exec(
            select(Chunk)
            .where(
                Chunk.id > last_id,
                Chunk.topic_id.in_(topic_ids),
                Chunk.kind.in_(("learner_output", "tutor_turn")),
            )
            .order_by(Chunk.id)
            .limit(SCOUT_CHECK_EVERY)
        ).all()
        if not chunks:
            break
        for chunk in chunks:
            for term in _extract_terms(chunk.text):
                if _matches_known_name(term, known_names):
                    continue
                key = normalize_name(term)
                if not key:
                    continue
                labels.setdefault(key, term)
                counts[key] = counts.get(key, 0) + 1
                refs.setdefault(key, set()).add(chunk.source_ref)
        last_id = int(chunks[-1].id or last_id)
        if len(chunks) < SCOUT_CHECK_EVERY:
            break

    candidates = [
        Candidate(
            kind="orphan_term",
            label=labels[key],
            evidence=[
                {"kind": "chunk", "ref": source_ref}
                for source_ref in sorted(refs[key])
            ],
            weight=float(count),
        )
        for key, count in counts.items()
        if count >= 3 and len(refs[key]) >= 2
    ]
    return sorted(candidates, key=lambda item: (-item.weight, normalize_name(item.label)))


def _note_label(chunk: Chunk) -> str:
    if chunk.context:
        title = chunk.context.split(" > ", 1)[0].strip()
        if title:
            return title
    parsed = urlsplit(chunk.source_ref)
    path = unquote(parsed.path) if parsed.scheme else chunk.source_ref
    stem = PurePosixPath(path).stem
    return stem or chunk.source_ref


def orphan_note_candidates(
    session: Session, *, deadline: float | None = None
) -> list[Candidate]:
    """Return one candidate for each vault note with no concept links."""
    by_source: dict[str, list[Chunk]] = {}
    linked_ids: set[int] = set()
    last_id = 0
    while True:
        if _expired(deadline):
            break
        chunks = session.exec(
            select(Chunk)
            .where(
                Chunk.id > last_id,
                Chunk.kind == "vault_note",
            )
            .order_by(Chunk.id)
            .limit(SCOUT_CHECK_EVERY)
        ).all()
        if not chunks:
            break
        chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
        if _expired(deadline):
            break
        linked_ids.update(
            session.exec(
                select(ChunkConcept.chunk_id).where(
                    ChunkConcept.chunk_id.in_(chunk_ids)
                )
            ).all()
        )
        for chunk in chunks:
            by_source.setdefault(chunk.source_ref, []).append(chunk)
        last_id = int(chunks[-1].id or last_id)
        if len(chunks) < SCOUT_CHECK_EVERY:
            break

    candidates = []
    for position, (source_ref, note_chunks) in enumerate(by_source.items()):
        if position % SCOUT_CHECK_EVERY == 0 and _expired(deadline):
            break
        if any(chunk.id in linked_ids for chunk in note_chunks):
            continue
        candidates.append(
            Candidate(
                kind="orphan_note",
                label=_note_label(note_chunks[0]),
                evidence=[{"kind": "chunk", "ref": source_ref}],
                weight=ORPHAN_NOTE_WEIGHT * len(note_chunks),
            )
        )
    return candidates


def _extension_evidence(source_ref: str) -> dict:
    match = _PAPER_PROBE_REF_RE.match(source_ref)
    if match is None:
        return {"kind": "chunk", "ref": source_ref}
    return {
        "kind": "paper_probe",
        "id": int(match.group(1)),
        "ref": source_ref,
    }


def extension_candidates(
    session: Session, program_id: int, *, deadline: float | None = None
) -> list[Candidate]:
    """Return learner-proposed paper extensions for Program topics."""
    topic_ids = _program_topic_ids(session, program_id, deadline=deadline)
    if not topic_ids:
        return []
    by_source: dict[str, list[Chunk]] = {}
    last_id = 0
    while True:
        if _expired(deadline):
            break
        chunks = session.exec(
            select(Chunk)
            .where(
                Chunk.id > last_id,
                Chunk.topic_id.in_(topic_ids),
                Chunk.kind.in_(("paper", "learner_output")),
            )
            .order_by(Chunk.id)
            .limit(SCOUT_CHECK_EVERY)
        ).all()
        if not chunks:
            break
        for chunk in chunks:
            if (chunk.meta or {}).get("role") == "extension":
                by_source.setdefault(chunk.source_ref, []).append(chunk)
        last_id = int(chunks[-1].id or last_id)
        if len(chunks) < SCOUT_CHECK_EVERY:
            break

    candidates = []
    for position, (source_ref, source_chunks) in enumerate(by_source.items()):
        if position % SCOUT_CHECK_EVERY == 0 and _expired(deadline):
            break
        label = " ".join(
            part
            for chunk in source_chunks
            if (part := " ".join(chunk.text.split()))
        )
        if not label:
            continue
        candidates.append(
            Candidate(
                kind="extension",
                label=label,
                evidence=[_extension_evidence(source_ref)],
                weight=EXTENSION_WEIGHT * len(source_chunks),
            )
        )
    return candidates


def _render_digest(
    candidates: list[Candidate],
    program: Program,
    milestones: list[Milestone],
) -> str:
    # Program text is learner-authored: it lives inside its own untrusted block and is
    # capped so it can never crowd out the candidate delimiters.
    lines = [
        "<<<PROGRAM>>>",
        f"PROGRAM: {escape_markers(program.title)[:SCOUT_FIELD_MAX_CHARS]}",
        f"GOAL: {escape_markers(program.goal_statement or program.title)[:SCOUT_GOAL_MAX_CHARS]}",
        "MILESTONES:",
    ]
    lines.extend(
        f"- {escape_markers(milestone.title)[:SCOUT_FIELD_MAX_CHARS]}"
        for milestone in milestones[:SCOUT_MAX_MILESTONES]
    )
    lines.append("<<<END_PROGRAM>>>")
    lines.append("<<<CANDIDATES>>>")
    for index, candidate in enumerate(candidates):
        lines.append(
            f"[{index}] "
            + json.dumps(
                {
                    "kind": escape_markers(candidate.kind)[:SCOUT_FIELD_MAX_CHARS],
                    "label": escape_markers(candidate.label)[:SCOUT_FIELD_MAX_CHARS],
                    "weight": candidate.weight,
                    "evidence": _escape_prompt_value(candidate.evidence),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    lines.append("<<<END_CANDIDATES>>>")
    return "\n".join(lines)


def _escape_prompt_value(value: object) -> object:
    if isinstance(value, str):
        return escape_markers(value)
    if isinstance(value, list):
        return [_escape_prompt_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_escape_prompt_value(item) for item in value)
    if isinstance(value, dict):
        return {
            escape_markers(str(key)): _escape_prompt_value(item)
            for key, item in value.items()
        }
    return value


def build_digest(
    candidates: list[Candidate],
    program: Program,
    milestones: list[Milestone],
    *,
    max_chars: int = SCOUT_DIGEST_MAX_CHARS,
) -> tuple[str, list[Candidate]]:
    """Build an indexed digest, removing the lowest-weight candidates first."""
    limit = max(0, max_chars)
    indexed = list(enumerate(candidates))
    digest = _render_digest([candidate for _, candidate in indexed], program, milestones)
    while indexed and len(digest) > limit:
        drop_position = min(
            range(len(indexed)),
            key=lambda position: (indexed[position][1].weight, indexed[position][0]),
        )
        indexed.pop(drop_position)
        digest = _render_digest([candidate for _, candidate in indexed], program, milestones)

    dropped = len(candidates) - len(indexed)
    if dropped:
        logger.info("Scout digest dropped %d candidate(s)", dropped)
    # Never slice through a delimiter: with every field capped and all candidates dropped
    # the digest is bounded, so a remaining overflow means the limit is smaller than the
    # fixed frame — keep the frame intact rather than emit a truncated block.
    return digest, [candidate for _, candidate in indexed]


def _program_milestones(session: Session, program_id: int) -> list[Milestone]:
    return session.exec(
        select(Milestone)
        .where(
            Milestone.program_id == program_id,
            col(Milestone.archived).is_(False),
        )
        .order_by(Milestone.order_index, Milestone.id)
    ).all()


def _valid_evidence_indexes(raw_indexes: object, candidate_count: int) -> list[int] | None:
    if not isinstance(raw_indexes, list) or not raw_indexes:
        return None
    if any(type(index) is not int for index in raw_indexes):
        return None
    indexes = list(dict.fromkeys(raw_indexes))
    if any(index < 0 or index >= candidate_count for index in indexes):
        return None
    return indexes


def _resolved_evidence(candidates: list[Candidate], indexes: list[int]) -> list[dict]:
    evidence: list[dict] = []
    for index in indexes:
        _append_unique_evidence(evidence, candidates[index].evidence)
    return evidence


def _score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score):
        return 0.0
    return min(max(score, 0.0), 1.0)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _in_dismiss_cooldown(suggestion: TopicSuggestion, now: datetime) -> bool:
    if suggestion.status != "dismissed":
        return False
    decided_at = suggestion.decided_at or suggestion.created_at
    return _naive_utc(decided_at) >= _naive_utc(
        now - timedelta(days=SCOUT_DISMISS_COOLDOWN_DAYS)
    )


def rank(
    session: Session,
    program: Program,
    candidates: list[Candidate],
    *,
    llm: LLMClient,
) -> list[TopicSuggestion]:
    """Rank candidates once, validate citations, and upsert reviewable suggestions."""
    if not candidates:
        return []

    if program.id is None:
        raise ValueError("program must be persisted before scouting")
    digest, kept_candidates = build_digest(
        candidates,
        program,
        _program_milestones(session, program.id),
    )
    session.add(AgentEvent(program_id=program.id, kind="prompt", detail=SCOUT_RANK.tag))
    data = structured_json(
        llm,
        SCOUT_RANK,
        [{"role": "user", "content": digest}],
        schema=SCOUT_SCHEMA,
        tool_name="emit_scout_rank",
    )

    existing_rows = session.exec(
        select(TopicSuggestion)
        .where(TopicSuggestion.program_id == program.id)
        .order_by(TopicSuggestion.id)
    ).all()
    existing_by_title = {
        normalize_name(suggestion.title): suggestion for suggestion in existing_rows
    }
    now = now_utc()
    suggestions: list[TopicSuggestion] = []
    seen_titles: set[str] = set()
    raw_items = data.get("items", []) if isinstance(data, dict) else []
    if not isinstance(raw_items, list):
        raw_items = []
    for raw_item in raw_items:
        if len(suggestions) >= SCOUT_MAX_SUGGESTIONS:
            break
        if not isinstance(raw_item, dict):
            continue
        title = escape_markers(str(raw_item.get("title", "")).strip())
        title_key = normalize_name(title)
        candidate_kind = str(raw_item.get("candidate_kind", ""))
        if not title_key or title_key in seen_titles or candidate_kind not in SCOUT_KINDS:
            continue
        indexes = _valid_evidence_indexes(
            raw_item.get("evidence_indexes"),
            len(kept_candidates),
        )
        if indexes is None:
            continue
        evidence = _resolved_evidence(kept_candidates, indexes)
        if not evidence:
            continue

        existing = existing_by_title.get(title_key)
        if existing is not None and (
            existing.status == "accepted" or _in_dismiss_cooldown(existing, now)
        ):
            seen_titles.add(title_key)
            continue
        suggestion = existing or TopicSuggestion(
            program_id=program.id,
            title=title,
            rationale="",
            candidate_kind=candidate_kind,
        )
        suggestion.title = title
        suggestion.rationale = escape_markers(
            str(raw_item.get("rationale", "")).strip()
        )
        suggestion.candidate_kind = candidate_kind
        suggestion.evidence = evidence
        suggestion.score = _score(raw_item.get("score", 0.0))
        suggestion.status = "proposed"
        suggestion.decided_at = None
        if existing is not None and existing.status == "dismissed":
            suggestion.created_at = now
        session.add(suggestion)
        session.flush()
        existing_by_title[title_key] = suggestion
        seen_titles.add(title_key)
        suggestions.append(suggestion)

    session.commit()
    for suggestion in suggestions:
        session.refresh(suggestion)
    return suggestions


def run_scout(
    session: Session,
    program: Program,
    *,
    llm: LLMClient,
    deadline_s: float = SCOUT_DEADLINE_S,
) -> ScoutResult:
    """Generate candidates within the deadline, then rank them once."""
    if program.id is None:
        raise ValueError("program must be persisted before scouting")
    started = time.monotonic()
    deadline = started + max(deadline_s, 0.0)
    counts = {kind: 0 for kind in SCOUT_KINDS}
    candidates: list[Candidate] = []
    generators = (
        ("frontier", lambda: frontier_candidates(session, program.id, deadline=deadline)),
        ("orphan_term", lambda: orphan_term_candidates(session, program.id, deadline=deadline)),
        ("orphan_note", lambda: orphan_note_candidates(session, deadline=deadline)),
        ("extension", lambda: extension_candidates(session, program.id, deadline=deadline)),
    )
    truncated = False
    for kind, generate in generators:
        if _expired(deadline):
            truncated = True
            break
        generated = generate()
        counts[kind] = len(generated)
        candidates.extend(generated)
        if _expired(deadline):
            # The generator stopped early at its next deadline check; report it.
            truncated = True
            break

    milestones = _program_milestones(session, program.id)
    _digest, kept_candidates = build_digest(candidates, program, milestones)
    truncated = truncated or len(kept_candidates) < len(candidates)
    suggestions = rank(session, program, kept_candidates, llm=llm)
    session.add(
        AgentEvent(
            program_id=program.id,
            kind="scout:ranked",
            detail=(
                f"candidates={len(kept_candidates)} "
                f"suggestions={len(suggestions)}"
            ),
        )
    )
    session.commit()
    return ScoutResult(suggestions=suggestions, counts=counts, truncated=truncated)


def _assessment_count_since_last_scout(session: Session, program_id: int) -> int:
    latest_event = session.exec(
        select(AgentEvent)
        .where(
            AgentEvent.program_id == program_id,
            AgentEvent.kind == "scout:ranked",
        )
        .order_by(AgentEvent.created_at.desc(), AgentEvent.id.desc())
    ).first()
    statement = (
        select(func.count(func.distinct(Assessment.id)))
        .select_from(Assessment)
        .join(Concept, Assessment.concept_id == Concept.id)
        .join(Track, Concept.track_id == Track.id)
        .join(ProgramTopicLink, ProgramTopicLink.topic_id == Track.topic_id)
        .join(Milestone, ProgramTopicLink.milestone_id == Milestone.id)
        .where(
            Milestone.program_id == program_id,
            col(Milestone.archived).is_(False),
            ProgramTopicLink.status != "pruned",
        )
    )
    if latest_event is not None:
        statement = statement.where(Assessment.created_at > latest_event.created_at)
    return int(session.exec(statement).one())


def maybe_scout(
    session: Session,
    program_id: int,
    *,
    llm: LLMClient,
) -> ScoutResult | None:
    """Run Scout after each batch of 25 new Program assessments."""
    if _assessment_count_since_last_scout(session, program_id) < SCOUT_EVERY_N_ASSESSMENTS:
        return None
    program = session.get(Program, program_id)
    if program is None:
        return None
    return run_scout(session, program, llm=llm)
