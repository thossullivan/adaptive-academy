import json

from sqlmodel import select

import adaptive_academy.engine.tutor_sdk as tutor_sdk
from adaptive_academy.api.routes_paper_probe import post_answer
from adaptive_academy.api.schemas import PaperProbeAnswerIn
from adaptive_academy.engine import memory
from adaptive_academy.engine.assess import assess_concept
from adaptive_academy.engine.decay import grade_decay_check, schedule_decay_check
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.paper_probe import direct as direct_paper_probe
from adaptive_academy.engine.productive_failure import consolidate, generate_challenge
from adaptive_academy.engine.roleplay import direct as direct_roleplay
from adaptive_academy.engine.roleplay import run_roleplay_turn
from adaptive_academy.engine.teach import grade_teaching
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Chunk,
    Concept,
    Conversation,
    KnowledgeEstimate,
    Milestone,
    PaperProbe,
    Program,
    ProgramTopicLink,
    RoleplaySession,
    RoleplayTurn,
    Rubric,
    Topic,
    Track,
)


def _seed_concept(session) -> tuple[Topic, Concept]:
    topic = Topic(title="Memory retrieval")
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="contextual retrieval", is_load_bearing=True)
    session.add(concept)
    session.flush()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="medium"))
    session.add(
        Rubric(
            concept_id=concept.id,
            criteria=["explains retrieval"],
            must_include=[],
            weak_signs=[],
        )
    )
    session.commit()
    session.refresh(topic)
    session.refresh(concept)
    return topic, concept


def _seed_milestone(session) -> tuple[Topic, Concept, Milestone]:
    topic, concept = _seed_concept(session)
    program = Program(title="Memory program", goal_statement="Build durable retrieval")
    session.add(program)
    session.flush()
    milestone = Milestone(
        program_id=program.id,
        title="Retrieval milestone",
        success_criteria="Explain and apply retrieval",
    )
    session.add(milestone)
    session.flush()
    session.add(
        ProgramTopicLink(
            milestone_id=milestone.id,
            topic_id=topic.id,
            status="started",
        )
    )
    session.commit()
    session.refresh(milestone)
    return topic, concept, milestone


def _grade_response(*, score: float = 0.8, verdict: str = "solid") -> LLMResponse:
    return LLMResponse(
        text=json.dumps(
            {
                "score": score,
                "verdict": verdict,
                "gaps": [],
                "mechanism_present": True,
            }
        )
    )


def _chunks(session) -> list[Chunk]:
    return session.exec(select(Chunk).order_by(Chunk.source_ref, Chunk.ordinal)).all()


def test_tutor_indexes_messages_and_skips_short_tutor_reply(session):
    topic, concept = _seed_concept(session)
    conversation = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)

    long_reply = "A detailed tutor explanation. " + ("grounded reasoning " * 14)
    run_tutor_turn(
        session,
        conversation,
        "My learner explanation of retrieval.",
        ScriptedLLMClient([LLMResponse(text=long_reply)]),
    )

    session.refresh(conversation)
    user_message, tutor_message = conversation.messages
    indexed = {chunk.source_ref: chunk for chunk in _chunks(session)}
    assert indexed[f"message:{user_message.id}"].kind == "learner_output"
    assert indexed[f"message:{user_message.id}"].concept_id == concept.id
    assert indexed[f"message:{tutor_message.id}"].kind == "tutor_turn"
    assert indexed[f"message:{tutor_message.id}"].meta == {
        "assistance": "medium",
        "challenge": "medium",
    }

    short_reply = "x" * 40
    run_tutor_turn(
        session,
        conversation,
        "A second learner attempt.",
        ScriptedLLMClient([LLMResponse(text=short_reply)]),
    )
    session.refresh(conversation)
    short_tutor_message = conversation.messages[-1]
    assert short_tutor_message.content == short_reply
    assert not session.exec(
        select(Chunk).where(Chunk.source_ref == f"message:{short_tutor_message.id}")
    ).all()

    levels = compute_levels(concept.estimate)
    memory.index_message(
        session,
        tutor_message,
        concept_id=concept.id,
        topic_id=topic.id,
        levels=levels,
    )
    memory.index_message(
        session,
        tutor_message,
        concept_id=concept.id,
        topic_id=topic.id,
        levels=levels,
    )
    session.flush()
    assert len(
        session.exec(
            select(Chunk).where(Chunk.source_ref == f"message:{tutor_message.id}")
        ).all()
    ) == 1


def test_tutor_sdk_indexes_both_messages(session, monkeypatch):
    topic, concept = _seed_concept(session)
    conversation = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    reply = "SDK tutor explanation. " + ("retrieval evidence " * 14)

    class FakeResult:
        def __init__(self, result: str):
            self.result = result
            self.is_error = False

    async def fake_query(prompt, options):  # noqa: ANN001
        yield FakeResult(reply)

    monkeypatch.setattr(tutor_sdk, "ResultMessage", FakeResult)
    monkeypatch.setattr(tutor_sdk, "query", fake_query)

    tutor_sdk.run_tutor_turn_sdk(session, conversation, "My SDK learner response.")

    session.refresh(conversation)
    rows = {
        chunk.source_ref: chunk
        for chunk in session.exec(
            select(Chunk).where(Chunk.source_ref.startswith("message:"))
        ).all()
    }
    assert rows[f"message:{conversation.messages[0].id}"].kind == "learner_output"
    assert rows[f"message:{conversation.messages[1].id}"].kind == "tutor_turn"
    assert all(chunk.concept_id == concept.id for chunk in rows.values())


def test_assess_concept_indexes_question_and_learner_response(session):
    topic, concept = _seed_concept(session)
    result = assess_concept(
        session,
        concept,
        "self_explanation",
        "Retrieval ranks local evidence before generation.",
        llm=ScriptedLLMClient([_grade_response(score=0.7, verdict="clear")]),
    )

    assessment = result.assessment
    rows = {
        chunk.source_ref: chunk
        for chunk in session.exec(
            select(Chunk).where(Chunk.source_ref.startswith(f"assessment:{assessment.id}"))
        ).all()
    }
    assert rows[f"assessment:{assessment.id}#q"].kind == "question"
    response = rows[f"assessment:{assessment.id}#r"]
    assert response.kind == "learner_output"
    assert response.concept_id == concept.id
    assert response.meta == {
        "assessment_kind": "self_explanation",
        "score": 0.7,
        "verdict": "clear",
    }

    memory.index_assessment(session, assessment, topic_id=topic.id)
    memory.index_assessment(session, assessment, topic_id=topic.id)
    session.flush()
    assert len(rows) == 2
    assert len(
        session.exec(
            select(Chunk).where(Chunk.source_ref.startswith(f"assessment:{assessment.id}"))
        ).all()
    ) == 2


def test_teach_indexes_its_assessment(session):
    _, concept = _seed_concept(session)
    result = grade_teaching(
        session,
        concept,
        "I would teach retrieval as local evidence selection before generation.",
        llm=ScriptedLLMClient(
            [
                LLMResponse(
                    text=json.dumps(
                        {
                            "score": 0.75,
                            "feedback": "specific",
                            "strengths": ["clear"],
                            "gaps": [],
                        }
                    )
                )
            ]
        ),
    )

    refs = {
        chunk.source_ref: chunk.kind
        for chunk in session.exec(
            select(Chunk).where(
                Chunk.source_ref.startswith(f"assessment:{result.assessment.id}")
            )
        ).all()
    }
    assert refs == {
        f"assessment:{result.assessment.id}#q": "question",
        f"assessment:{result.assessment.id}#r": "learner_output",
    }


def test_decay_indexes_recall_question_and_graded_response(session):
    topic, concept = _seed_concept(session)
    prompt = schedule_decay_check(session, concept.id, days=0)
    schedule_decay_check(session, concept.id, days=2)

    recall_chunks = session.exec(
        select(Chunk).where(Chunk.source_ref == f"recallprompt:{prompt.id}")
    ).all()
    assert len(recall_chunks) == 1
    assert (recall_chunks[0].kind, recall_chunks[0].concept_id) == (
        "question",
        concept.id,
    )

    result = grade_decay_check(
        session,
        prompt.id,
        "I recalled how local ranking grounds the generation step.",
        llm=ScriptedLLMClient([_grade_response(score=0.6, verdict="partial")]),
    )
    refs = {
        chunk.source_ref: chunk
        for chunk in session.exec(
            select(Chunk).where(
                Chunk.source_ref.startswith(f"assessment:{result.assessment.id}")
            )
        ).all()
    }
    assert refs[f"assessment:{result.assessment.id}#q"].kind == "question"
    assert refs[f"assessment:{result.assessment.id}#r"].kind == "learner_output"
    assert all(chunk.topic_id == topic.id for chunk in refs.values())


def test_productive_failure_indexes_generated_question_and_assessment(session):
    topic, concept = _seed_concept(session)
    problem = "Design a local retrieval ranking for a learner with conflicting notes."
    generated = generate_challenge(
        session,
        concept,
        llm=ScriptedLLMClient(
            [LLMResponse(text=json.dumps({"problem": problem}))]
        ),
    )
    assert generated == problem
    generated_ref = (
        f"productive_failure:{concept.id}:{memory.content_hash(problem)}"
    )
    question = session.exec(
        select(Chunk).where(Chunk.source_ref == generated_ref)
    ).one()
    assert (question.kind, question.topic_id, question.concept_id) == (
        "question",
        topic.id,
        concept.id,
    )

    memory.index_question(
        session,
        text=problem,
        source_ref=generated_ref,
        topic_id=topic.id,
        concept_id=concept.id,
    )
    result = consolidate(
        session,
        concept,
        problem,
        "I would rank exact terms and then inspect contradictions.",
        llm=ScriptedLLMClient(
            [
                LLMResponse(
                    text=json.dumps(
                        {"canonical": "Use BM25.", "feedback": "Good.", "score": 0.65}
                    )
                )
            ]
        ),
    )
    refs = {
        chunk.source_ref: chunk.kind
        for chunk in session.exec(
            select(Chunk).where(
                Chunk.source_ref.startswith(f"assessment:{result.assessment.id}")
            )
        ).all()
    }
    assert refs == {
        f"assessment:{result.assessment.id}#q": "question",
        f"assessment:{result.assessment.id}#r": "learner_output",
    }
    assert len(
        session.exec(select(Chunk).where(Chunk.source_ref == generated_ref)).all()
    ) == 1


def test_roleplay_indexes_opening_and_both_turn_roles(session):
    topic, concept, milestone = _seed_milestone(session)
    roleplay = RoleplaySession(
        program_id=milestone.program_id,
        milestone_id=milestone.id,
        status="briefing",
    )
    session.add(roleplay)
    session.commit()
    session.refresh(roleplay)
    situation = "You must defend the retrieval design during a skeptical review."
    brief = {
        "persona": "Skeptical reviewer",
        "goal": "Find unsupported choices",
        "situation": situation,
        "hidden_objections": ["ranking quality"],
        "win_conditions": ["justify BM25"],
        "difficulty": "medium",
    }
    direct_roleplay(
        session,
        roleplay,
        llm=ScriptedLLMClient([LLMResponse(text=json.dumps(brief))]),
    )
    opening = session.exec(
        select(Chunk).where(
            Chunk.source_ref == f"roleplaysession:{roleplay.id}#opening"
        )
    ).one()
    assert (opening.kind, opening.concept_id, opening.text) == (
        "question",
        concept.id,
        situation,
    )

    run_roleplay_turn(
        session,
        roleplay,
        "I chose local BM25 because records remain private.",
        llm=ScriptedLLMClient(
            [LLMResponse(text="How will exact-term ranking handle related language?")]
        ),
    )
    turns = session.exec(
        select(RoleplayTurn)
        .where(RoleplayTurn.session_id == roleplay.id)
        .order_by(RoleplayTurn.id)
    ).all()
    indexed = {
        chunk.source_ref: chunk
        for chunk in session.exec(
            select(Chunk).where(Chunk.source_ref.startswith("roleplayturn:"))
        ).all()
    }
    assert indexed[f"roleplayturn:{turns[0].id}"].kind == "learner_output"
    assert indexed[f"roleplayturn:{turns[1].id}"].kind == "tutor_turn"
    assert all(chunk.topic_id == topic.id for chunk in indexed.values())
    assert all(chunk.concept_id == concept.id for chunk in indexed.values())


def test_paper_probe_indexes_questions(session):
    topic, concept, milestone = _seed_milestone(session)
    probe = PaperProbe(
        program_id=milestone.program_id,
        milestone_id=milestone.id,
        paper_title="Contextual Retrieval",
        paper_text="The paper compares local ranking methods.",
        status="drafting",
    )
    session.add(probe)
    session.commit()
    session.refresh(probe)
    questions = [
        {
            "axis": "method",
            "prompt": "How does the paper rank local evidence?",
            "concept_ids": [concept.id],
        },
        {
            "axis": "extension",
            "prompt": "What would you change in the retrieval design?",
            "concept_ids": [concept.id],
        },
    ]
    direct_paper_probe(
        session,
        probe,
        llm=ScriptedLLMClient(
            [LLMResponse(text=json.dumps({"questions": questions}))]
        ),
    )

    indexed = {
        chunk.source_ref: chunk
        for chunk in session.exec(
            select(Chunk).where(Chunk.source_ref.startswith(f"paperprobe:{probe.id}#q:"))
        ).all()
    }
    assert set(indexed) == {
        f"paperprobe:{probe.id}#q:0",
        f"paperprobe:{probe.id}#q:1",
    }
    assert all(chunk.kind == "question" for chunk in indexed.values())
    assert all(chunk.topic_id == topic.id for chunk in indexed.values())
    assert all(chunk.concept_id == concept.id for chunk in indexed.values())


def test_paper_answer_indexes_and_updates_without_duplication(session):
    topic, concept, milestone = _seed_milestone(session)
    probe = PaperProbe(
        program_id=milestone.program_id,
        milestone_id=milestone.id,
        paper_title="Contextual Retrieval",
        paper_text="The paper compares local ranking methods.",
        status="answering",
        questions=[
            {
                "index": 0,
                "axis": "extension",
                "prompt": "What would you extend?",
                "concept_ids": [concept.id],
            }
        ],
    )
    session.add(probe)
    session.commit()
    session.refresh(probe)

    post_answer(
        probe.id,
        PaperProbeAnswerIn(
            question_index=0,
            content="I would add alias-aware query expansion.",
        ),
        session,
    )
    post_answer(
        probe.id,
        PaperProbeAnswerIn(
            question_index=0,
            content="I would add alias-aware query expansion and recency ordering.",
        ),
        session,
    )

    rows = session.exec(
        select(Chunk).where(Chunk.source_ref == f"paperprobe:{probe.id}#0")
    ).all()
    assert len(rows) == 1
    assert rows[0].kind == "learner_output"
    assert rows[0].topic_id == topic.id
    assert rows[0].concept_id == concept.id
    assert rows[0].meta == {"role": "extension"}
    assert rows[0].text.endswith("recency ordering.")


def test_topic_id_for_concept_promotes_shared_resolution_helper(session):
    topic, concept = _seed_concept(session)
    assert memory.topic_id_for_concept(session, concept.id) == topic.id
