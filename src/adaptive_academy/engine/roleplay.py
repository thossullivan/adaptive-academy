import json
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.engine.assess import assess_concept
from adaptive_academy.engine.gates import milestone_load_bearing
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.memory import (
    ALREADY_COVERED_MARKER,
    GROUNDING_K,
    MEMORY_MARKER,
    append_block_entry,
    avoid_block_for_concepts,
    index_question,
    index_roleplay_turn,
    is_near_duplicate,
    remove_source,
    render_block,
    retrieve,
    topic_id_for_concept,
)
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.retriever_types import Hit, Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent, Assessment, Milestone, RoleplaySession, RoleplayTurn,
)
from adaptive_academy.prompts import (
    ROLEPLAY_DIRECTOR, ROLEPLAY_GRADE, ROLEPLAY_PERSONA, build_roleplay_persona_prompt,
)
from adaptive_academy.engine.untrusted import escape_markers

_TURN_CAP = 15
_END = "[[END]]"


def _emit(session: Session, rp: RoleplaySession, kind: str, detail: str = "") -> None:
    session.add(AgentEvent(program_id=rp.program_id, roleplay_session_id=rp.id,
                           kind=kind, detail=detail))


def direct(
    session: Session,
    rp: RoleplaySession,
    *,
    llm: LLMClient,
    retriever: Retriever | None = None,
) -> RoleplaySession:
    """Generate the persona brief from the milestone + load-bearing concepts; activate."""
    milestone = session.get(Milestone, rp.milestone_id)
    concepts = milestone_load_bearing(session, milestone)
    lines = [f"MILESTONE: {escape_markers(milestone.title)}",
             f"SUCCESS CRITERIA: {escape_markers(milestone.success_criteria)}",
             "", "LOAD-BEARING CONCEPTS (name — learner level):"]
    for c in concepts:
        level = compute_levels(c.estimate)
        lines.append(f"- {c.name} — challenge={level.challenge}")
    base_user = "<<<MILESTONE>>>\n" + "\n".join(lines) + "\n<<<END_MILESTONE>>>"
    concept_ids = [concept.id for concept in concepts if concept.id is not None]
    memory_block = ""
    covered_block = ""
    prior_questions: list[Hit] = []
    if retriever is not None:
        grounding_hits: list[Hit] = []
        for concept in concepts:
            if concept.id is None:
                continue
            grounding_hits.extend(
                retrieve(
                    session,
                    retriever,
                    concept.name,
                    kinds=("vault_note", "source_doc"),
                    concept_id=concept.id,
                    k=GROUNDING_K,
                    event_target={
                        "program_id": rp.program_id,
                        "roleplay_session_id": rp.id,
                    },
                )
            )
        grounding_hits = _unique_hits(grounding_hits, limit=GROUNDING_K)
        memory_block = render_block(grounding_hits, marker=MEMORY_MARKER)
        covered_block, prior_questions = avoid_block_for_concepts(
            session,
            retriever,
            concept_ids,
        )
    user = _with_blocks(base_user, memory_block, covered_block)

    _emit(session, rp, "prompt", ROLEPLAY_DIRECTOR.tag)
    resp = llm.complete(system=ROLEPLAY_DIRECTOR,
                        messages=[{"role": "user", "content": user}], tools=[])
    brief = json.loads(extract_json(resp.text))
    embedder = getattr(retriever, "embedder", None)
    duplicate = is_near_duplicate(
        str(brief.get("situation", "")),
        prior_questions,
        embedder=embedder,
    )
    if duplicate is not None:
        _emit(
            session,
            rp,
            "memory:neardup_reject",
            f"source_ref={duplicate.chunk.source_ref}",
        )
        retry_block = append_block_entry(
            covered_block,
            str(brief.get("situation", "")),
            marker=ALREADY_COVERED_MARKER,
            label="rejected_generation",
        )
        retry_user = _with_blocks(base_user, memory_block, retry_block)
        resp = llm.complete(
            system=ROLEPLAY_DIRECTOR,
            messages=[{"role": "user", "content": retry_user}],
            tools=[],
        )
        brief = json.loads(extract_json(resp.text))
    rp.persona_brief = brief
    rp.status = "active"
    _emit(session, rp, "roleplay:brief", brief.get("persona", ""))
    session.add(rp)
    topic_id = topic_id_for_concept(session, concept_ids[0]) if concept_ids else None
    index_question(
        session,
        text=str(brief.get("situation", "")),
        source_ref=f"roleplaysession:{rp.id}#opening",
        topic_id=topic_id,
        concept_id=concept_ids[0] if len(concept_ids) == 1 else None,
        retriever=retriever,
    )
    session.commit()
    session.refresh(rp)
    return rp


def _with_blocks(base: str, *blocks: str) -> str:
    present = [block for block in blocks if block]
    if not present:
        return base
    return base + "\n\n" + "\n\n".join(present)


def _unique_hits(hits: list[Hit], *, limit: int) -> list[Hit]:
    unique: list[Hit] = []
    hashes: set[str] = set()
    for hit in sorted(hits, key=lambda candidate: -candidate.score):
        if len(unique) >= limit:
            break
        if hit.chunk.content_hash in hashes:
            continue
        hashes.add(hit.chunk.content_hash)
        unique.append(hit)
    return unique


@dataclass
class TurnResult:
    reply: str
    status: str
    # False when the persona gave no usable reply: nothing was stored for this turn and
    # `reply` is a notice for the learner, not the persona speaking.
    recorded: bool = True


# Shown (never stored) when a persona reply is unusable. Storing an empty assistant turn
# would make every later turn fail with a 400, and keeping the declined learner turn would
# resend it — likely declined again — on every later turn and stall the session.
_NO_REPLY_REFUSAL = (
    "(The model declined to respond to that message, so this turn wasn't recorded. "
    "Try rephrasing it, or end the session to be scored on what you have so far.)"
)
_NO_REPLY_EMPTY = (
    "(The persona returned an empty reply, so this turn wasn't recorded. "
    "Please send your message again.)"
)
_ENDED_SILENTLY = "(The persona ended the conversation.)"


def _unusable_reply(resp) -> str | None:
    """Why a persona reply can't be stored as a turn, or None if it can."""
    if resp.stop_reason == "refusal":
        return "refusal"
    if not resp.text.strip():
        return f"empty reply (stop_reason={resp.stop_reason})"
    return None


def _history(session: Session, rp: RoleplaySession) -> list[dict]:
    role_map = {"user": "user", "persona": "assistant"}
    turns = session.exec(
        select(RoleplayTurn).where(RoleplayTurn.session_id == rp.id).order_by(RoleplayTurn.id)
    ).all()
    return [{"role": role_map[t.role], "content": t.content} for t in turns]


def run_roleplay_turn(
    session: Session,
    rp: RoleplaySession,
    user_text: str,
    *,
    llm: LLMClient,
    retriever: Retriever | None = None,
) -> TurnResult:
    milestone = session.get(Milestone, rp.milestone_id)
    concepts = milestone_load_bearing(session, milestone)
    concept_ids = [concept.id for concept in concepts if concept.id is not None]
    topic_id = topic_id_for_concept(session, concept_ids[0]) if concept_ids else None

    # The new user turn is sent from memory and persisted only once the persona has given a
    # usable reply (see _unusable_reply).
    messages = [*_history(session, rp), {"role": "user", "content": user_text}]
    system = build_roleplay_persona_prompt(rp.persona_brief)
    _emit(session, rp, "prompt", ROLEPLAY_PERSONA.tag)
    session.commit()  # release the write lock before the LLM call (F5)
    resp = llm.complete(system=system, messages=messages, tools=[])

    unusable = _unusable_reply(resp)
    if unusable is not None:
        _emit(session, rp, "roleplay:no_reply", unusable)
        session.commit()
        session.refresh(rp)
        notice = _NO_REPLY_REFUSAL if unusable == "refusal" else _NO_REPLY_EMPTY
        return TurnResult(reply=notice, status=rp.status, recorded=False)

    user_turn = RoleplayTurn(session_id=rp.id, role="user", content=user_text)
    session.add(user_turn)
    session.flush()
    index_roleplay_turn(
        session,
        user_turn,
        topic_id=topic_id,
        concept_ids=concept_ids,
        retriever=retriever,
    )

    reply = resp.text
    ended = False
    if _END in reply:
        reply = reply.replace(_END, "").strip()
        ended = True
    if not reply:
        # Only the end token: never store an empty persona turn. The session is ending, so
        # this line is never resent to the persona model.
        reply = _ENDED_SILENTLY

    persona_turn = RoleplayTurn(session_id=rp.id, role="persona", content=reply)
    session.add(persona_turn)
    session.flush()
    index_roleplay_turn(
        session,
        persona_turn,
        topic_id=topic_id,
        concept_ids=concept_ids,
        retriever=retriever,
    )

    user_turns = len(session.exec(
        select(RoleplayTurn).where(RoleplayTurn.session_id == rp.id,
                                   RoleplayTurn.role == "user")).all())
    if user_turns >= _TURN_CAP:
        ended = True

    if ended:
        rp.status = "ended"
        _emit(session, rp, "roleplay:ended")
        session.add(rp)
    session.commit()
    session.refresh(rp)
    return TurnResult(reply=reply, status=rp.status)


def _transcript_text(session: Session, rp: RoleplaySession) -> str:
    turns = session.exec(
        select(RoleplayTurn).where(RoleplayTurn.session_id == rp.id).order_by(RoleplayTurn.id)
    ).all()
    speaker = {"user": "LEARNER", "persona": "PERSONA"}
    return "\n".join(f"{speaker[t.role]}: {t.content}" for t in turns)


def grade_roleplay(
    session: Session,
    rp: RoleplaySession,
    *,
    llm: LLMClient,
    retriever: Retriever | None = None,
) -> list[Assessment]:
    """Blind grade: reuse assess_concept per load-bearing concept, then write an outcome."""
    milestone = session.get(Milestone, rp.milestone_id)
    concepts = milestone_load_bearing(session, milestone)
    transcript = _transcript_text(session, rp)

    # Idempotent re-grade (a prior grade may have partially written then failed): clear any
    # existing roleplay evidence for this session so retries never double-count.
    for old in session.exec(
            select(Assessment).where(Assessment.roleplay_session_id == rp.id)).all():
        remove_source(session, f"assessment:{old.id}#q")
        remove_source(session, f"assessment:{old.id}#r")
        session.delete(old)

    graded: list[Assessment] = []
    for c in concepts:
        result = assess_concept(
            session,
            c,
            "roleplay",
            transcript,
            llm=llm,
            retriever=retriever,
        )
        result.assessment.roleplay_session_id = rp.id
        session.add(result.assessment)
        graded.append(result.assessment)

    _emit(session, rp, "prompt", ROLEPLAY_GRADE.tag)
    user = "<<<TRANSCRIPT>>>\n" + escape_markers(transcript) + "\n<<<END_TRANSCRIPT>>>"
    resp = llm.complete(system=ROLEPLAY_GRADE,
                        messages=[{"role": "user", "content": user}], tools=[])
    rp.outcome = json.loads(extract_json(resp.text))
    rp.status = "graded"
    _emit(session, rp, "roleplay:graded", f"{len(graded)} concept(s)")
    session.add(rp)
    session.commit()
    for a in graded:
        session.refresh(a)
    session.refresh(rp)
    return graded
