import json

from sqlmodel import Session, select

from adaptive_academy.engine.assess import assess_concept
from adaptive_academy.engine.gates import milestone_load_bearing
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.memory import (
    ALREADY_COVERED_MARKER,
    append_block_entry,
    avoid_block_for_concepts,
    index_question,
    is_near_duplicate,
    remove_source,
    topic_id_for_concept,
)
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent, Assessment, Milestone, PaperProbe, PaperProbeAnswer,
)
from adaptive_academy.prompts import PAPER_PROBE_DIRECTOR, PAPER_PROBE_OUTCOME
from adaptive_academy.engine.untrusted import escape_markers


def _emit(session: Session, pp: PaperProbe, kind: str, detail: str = "") -> None:
    session.add(AgentEvent(program_id=pp.program_id, paper_probe_id=pp.id,
                           kind=kind, detail=detail))


def direct(
    session: Session,
    pp: PaperProbe,
    *,
    llm: LLMClient,
    retriever: Retriever | None = None,
) -> PaperProbe:
    """Generate the critical-reading question set from the paper + load-bearing concepts."""
    milestone = session.get(Milestone, pp.milestone_id)
    concepts = milestone_load_bearing(session, milestone)
    lines = ["LOAD-BEARING CONCEPTS ([id=N] name — learner level):"]
    for c in concepts:
        level = compute_levels(c.estimate)
        lines.append(f"[id={c.id}] {c.name} — challenge={level.challenge}")
    base_user = paper_block(pp) + "\n\n" + "\n".join(lines)
    concept_ids = [concept.id for concept in concepts if concept.id is not None]
    covered_block = ""
    prior_questions = []
    if retriever is not None:
        covered_block, prior_questions = avoid_block_for_concepts(
            session,
            retriever,
            concept_ids,
        )
    user = _with_covered_block(base_user, covered_block)

    _emit(session, pp, "prompt", PAPER_PROBE_DIRECTOR.tag)
    resp = llm.complete(system=PAPER_PROBE_DIRECTOR,
                        messages=[{"role": "user", "content": user}], tools=[])
    data = json.loads(extract_json(resp.text))
    rejected: list[str] = []
    embedder = getattr(retriever, "embedder", None)
    for question in data.get("questions", []):
        prompt = str(question.get("prompt", ""))
        duplicate = is_near_duplicate(prompt, prior_questions, embedder=embedder)
        if duplicate is None:
            continue
        rejected.append(prompt)
        _emit(
            session,
            pp,
            "memory:neardup_reject",
            f"source_ref={duplicate.chunk.source_ref}",
        )
    if rejected:
        retry_block = covered_block
        for prompt in rejected:
            retry_block = append_block_entry(
                retry_block,
                prompt,
                marker=ALREADY_COVERED_MARKER,
                label="rejected_generation",
            )
        retry_user = _with_covered_block(base_user, retry_block)
        resp = llm.complete(
            system=PAPER_PROBE_DIRECTOR,
            messages=[{"role": "user", "content": retry_user}],
            tools=[],
        )
        data = json.loads(extract_json(resp.text))
    valid_ids = {c.id for c in concepts}
    questions: list[dict] = []
    for i, q in enumerate(data.get("questions", [])):
        cids = [cid for cid in q.get("concept_ids", []) if cid in valid_ids]
        questions.append({"index": i, "axis": q.get("axis", ""),
                          "prompt": q.get("prompt", ""), "concept_ids": cids})
    pp.questions = questions
    pp.status = "answering"
    _emit(session, pp, "paper_probe:questions", f"{len(questions)} question(s)")
    session.add(pp)
    topic_id = topic_id_for_concept(session, concept_ids[0]) if concept_ids else None
    for question in questions:
        question_concept_ids = question["concept_ids"]
        question_topic_id = (
            topic_id_for_concept(session, question_concept_ids[0])
            if question_concept_ids
            else topic_id
        )
        index_question(
            session,
            text=question["prompt"],
            source_ref=f"paperprobe:{pp.id}#q:{question['index']}",
            topic_id=question_topic_id,
            concept_id=(
                question_concept_ids[0]
                if len(question_concept_ids) == 1
                else None
            ),
            retriever=retriever,
        )
    session.commit()
    session.refresh(pp)
    return pp


def _with_covered_block(base: str, covered_block: str) -> str:
    if not covered_block:
        return base
    return f"{base}\n\n{covered_block}"


def _answers(session: Session, pp: PaperProbe) -> dict[int, str]:
    rows = session.exec(
        select(PaperProbeAnswer).where(PaperProbeAnswer.probe_id == pp.id)
        .order_by(PaperProbeAnswer.question_index)).all()
    return {a.question_index: a.content for a in rows}


def paper_block(pp: PaperProbe) -> str:
    """The untrusted paper block; the paper text can never forge its own delimiters."""
    return "<<<PAPER>>>\n" + escape_markers(pp.paper_text) + "\n<<<END_PAPER>>>"


def _qa_text(pp: PaperProbe, answers: dict[int, str],
             concept_id: int | None = None) -> str:
    parts = []
    for q in pp.questions:
        if concept_id is not None and concept_id not in q.get("concept_ids", []):
            continue
        a = escape_markers(answers.get(q["index"], "(no answer)"))
        parts.append(f"Q ({q.get('axis', '')}): {escape_markers(q.get('prompt', ''))}\nA: {a}")
    return "\n\n".join(parts)


def grade_paper_probe(
    session: Session,
    pp: PaperProbe,
    *,
    llm: LLMClient,
    retriever: Retriever | None = None,
) -> list[Assessment]:
    """Blind grade: reuse assess_concept per exercised load-bearing concept, then an outcome."""
    milestone = session.get(Milestone, pp.milestone_id)
    concepts = milestone_load_bearing(session, milestone)
    answers = _answers(session, pp)

    # Idempotent re-grade: clear any prior evidence for this probe so retries never double-count.
    for old in session.exec(
            select(Assessment).where(Assessment.paper_probe_id == pp.id)).all():
        remove_source(session, f"assessment:{old.id}#q")
        remove_source(session, f"assessment:{old.id}#r")
        session.delete(old)

    graded: list[Assessment] = []
    for c in concepts:
        text = _qa_text(pp, answers, c.id)
        if not text:
            continue  # the paper's questions never exercised this concept — no evidence
        result = assess_concept(
            session,
            c,
            "paper_probe",
            text,
            llm=llm,
            retriever=retriever,
        )
        result.assessment.paper_probe_id = pp.id
        session.add(result.assessment)
        graded.append(result.assessment)

    _emit(session, pp, "prompt", PAPER_PROBE_OUTCOME.tag)
    user = "<<<ANSWERS>>>\n" + _qa_text(pp, answers) + "\n<<<END_ANSWERS>>>"
    resp = llm.complete(system=PAPER_PROBE_OUTCOME,
                        messages=[{"role": "user", "content": user}], tools=[])
    pp.outcome = json.loads(extract_json(resp.text))
    pp.status = "graded"
    _emit(session, pp, "paper_probe:graded", f"{len(graded)} concept(s)")
    session.add(pp)
    session.commit()
    for a in graded:
        session.refresh(a)
    session.refresh(pp)
    return graded
