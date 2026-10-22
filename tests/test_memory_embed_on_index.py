import importlib.util
import json
import struct
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from adaptive_academy.api import (
    routes_assess,
    routes_decay,
    routes_paper_probe,
    routes_practice,
    routes_roleplay,
    routes_teach,
)
from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_fetcher, get_llm, get_retriever, get_session
from adaptive_academy.api.schemas import (
    AssessIn,
    ConsolidateIn,
    DecayGradeIn,
    PaperProbeAnswerIn,
    PaperProbeStartIn,
    RoleplayTurnIn,
    TeachIn,
)
from adaptive_academy.db import ensure_fts, ensure_vec
from adaptive_academy.engine.assess import assess_concept
from adaptive_academy.engine.decay import grade_decay_check, schedule_decay_check
from adaptive_academy.engine.memory import (
    ChunkFilter,
    content_hash,
    index_assessment,
    index_message,
    index_paper,
    index_paper_answer,
    index_question,
    index_roleplay_turn,
    index_source_doc,
    index_text,
    is_near_duplicate,
    jaccard,
    reindex_topic,
    remove_source,
    split_plain,
)
from adaptive_academy.engine.paper_probe import direct as direct_paper_probe
from adaptive_academy.engine.paper_probe import grade_paper_probe
from adaptive_academy.engine.productive_failure import consolidate, generate_challenge
from adaptive_academy.engine.roleplay import direct as direct_roleplay
from adaptive_academy.engine.roleplay import grade_roleplay, run_roleplay_turn
from adaptive_academy.engine.teach import grade_teaching
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.hybrid_retriever import HybridRetriever
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.retriever_types import Hit
from adaptive_academy.llm.scripted_embedder import ScriptedEmbedder
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Chunk,
    Concept,
    Conversation,
    KnowledgeEstimate,
    Message,
    Milestone,
    PaperProbe,
    PaperProbeAnswer,
    Program,
    ProgramTopicLink,
    RecallPrompt,
    RoleplaySession,
    RoleplayTurn,
    Rubric,
    SourceDoc,
    Topic,
    TopicFoundation,
    Track,
)

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("sqlite_vec") is None,
    reason="sqlite-vec optional extra is unavailable",
)


@pytest.fixture
def vec_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    assert ensure_fts(engine) is True
    assert ensure_vec(engine) is True
    with Session(engine) as session:
        yield session


def _split_small(value: str):
    return split_plain(value, target=15)


def _vector_row(session: Session, chunk_id: int) -> list[float]:
    blob = session.execute(
        text("SELECT embedding FROM chunk_vec WHERE chunk_id = :chunk_id"),
        {"chunk_id": chunk_id},
    ).scalar_one()
    return list(struct.unpack("<384f", blob))


def _colliding_token(embedder: ScriptedEmbedder, token: str) -> str:
    target = embedder.embed([token])[0]
    for index in range(10_000):
        candidate = f"different{index}"
        if candidate != token and embedder.embed([candidate])[0] == target:
            return candidate
    raise AssertionError("could not find a deterministic hashing collision")


def _seed_embedding_site(session: Session) -> tuple[Topic, Concept, Milestone]:
    topic = Topic(title="Embedding propagation")
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.flush()
    concept = Concept(
        track_id=track.id,
        name="hybrid retrieval",
        is_load_bearing=True,
    )
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
    program = Program(title="Embedding program")
    session.add(program)
    session.flush()
    milestone = Milestone(
        program_id=program.id,
        title="Embedding milestone",
        success_criteria="Explain hybrid retrieval",
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
    return topic, concept, milestone


def _grade_response() -> LLMResponse:
    return LLMResponse(
        text=json.dumps(
            {
                "score": 0.8,
                "verdict": "solid",
                "gaps": [],
                "mechanism_present": True,
                "missing_required": [],
                "misconceptions_committed": [],
            }
        )
    )


def _teaching_response() -> LLMResponse:
    return LLMResponse(
        text=json.dumps(
            {
                "score": 0.8,
                "feedback": "clear",
                "strengths": ["specific"],
                "gaps": [],
            }
        )
    )


def _roleplay_brief() -> LLMResponse:
    return LLMResponse(
        text=json.dumps(
            {
                "persona": "Reviewer",
                "goal": "Test the design",
                "situation": "Defend hybrid retrieval under review.",
                "hidden_objections": [],
                "win_conditions": [],
                "difficulty": "medium",
            }
        )
    )


def _paper_questions(concept_id: int) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(
            {
                "questions": [
                    {
                        "axis": "method",
                        "prompt": "How does hybrid retrieval combine evidence?",
                        "concept_ids": [concept_id],
                    }
                ]
            }
        )
    )


def _outcome_response() -> LLMResponse:
    return LLMResponse(text=json.dumps({"result": "complete", "summary": "clear"}))


_ENGINE_WRITE_SITES = (
    "index_message",
    "index_assessment",
    "index_roleplay_turn",
    "index_question",
    "index_paper_answer",
    "index_paper",
    "index_source_doc",
    "assess_concept",
    "grade_teaching",
    "schedule_decay_check",
    "grade_decay_check",
    "generate_challenge",
    "consolidate",
    "roleplay_direct",
    "run_roleplay_turn",
    "grade_roleplay",
    "paper_probe_direct",
    "grade_paper_probe",
    "run_tutor_turn",
)


@pytest.mark.parametrize("site", _ENGINE_WRITE_SITES)
def test_engine_write_site_embeds_every_produced_chunk(vec_session, site):
    session = vec_session
    topic, concept, milestone = _seed_embedding_site(session)
    embedder = ScriptedEmbedder()
    retriever = HybridRetriever(FtsRetriever(), embedder)

    if site == "index_message":
        conversation = Conversation(topic_id=topic.id, concept_id=concept.id)
        session.add(conversation)
        session.flush()
        message = Message(
            conversation_id=conversation.id,
            role="user",
            content="The learner combines lexical and semantic evidence.",
        )
        session.add(message)
        session.flush()
        index_message(
            session,
            message,
            concept_id=concept.id,
            topic_id=topic.id,
            retriever=retriever,
        )
    elif site == "index_assessment":
        assessment = Assessment(
            concept_id=concept.id,
            kind="self_explanation",
            prompt="Explain hybrid retrieval.",
            response="It combines lexical and semantic evidence.",
        )
        session.add(assessment)
        session.flush()
        index_assessment(
            session,
            assessment,
            topic_id=topic.id,
            retriever=retriever,
        )
    elif site == "index_roleplay_turn":
        roleplay = RoleplaySession(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            status="active",
        )
        session.add(roleplay)
        session.flush()
        turn = RoleplayTurn(
            session_id=roleplay.id,
            role="user",
            content="I defend the hybrid retrieval design.",
        )
        session.add(turn)
        session.flush()
        index_roleplay_turn(
            session,
            turn,
            topic_id=topic.id,
            concept_ids=[concept.id],
            retriever=retriever,
        )
    elif site == "index_question":
        index_question(
            session,
            text="How does hybrid retrieval work?",
            source_ref="test:question",
            topic_id=topic.id,
            concept_id=concept.id,
            retriever=retriever,
        )
    elif site == "index_paper_answer":
        probe = PaperProbe(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
        )
        session.add(probe)
        session.flush()
        answer = PaperProbeAnswer(
            probe_id=probe.id,
            question_index=0,
            content="The paper combines two retrieval signals.",
        )
        session.add(answer)
        session.flush()
        index_paper_answer(
            session,
            answer,
            topic_id=topic.id,
            concept_ids=[concept.id],
            retriever=retriever,
        )
    elif site == "index_paper":
        probe = PaperProbe(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            paper_title="Hybrid Retrieval",
            paper_text="Lexical retrieval and semantic retrieval provide complementary evidence.",
        )
        session.add(probe)
        session.flush()
        index_paper(session, probe, retriever=retriever)
    elif site == "index_source_doc":
        source = SourceDoc(
            topic_id=topic.id,
            title="Hybrid source",
            url="https://example.test/hybrid",
            status="accepted",
        )
        session.add(source)
        session.flush()
        index_source_doc(
            session,
            source,
            fetch=lambda _: "Lexical and semantic retrieval are complementary.",
            retriever=retriever,
        )
    elif site == "assess_concept":
        assess_concept(
            session,
            concept,
            "self_explanation",
            "Hybrid retrieval combines lexical and semantic evidence.",
            llm=ScriptedLLMClient([_grade_response()]),
            retriever=retriever,
        )
    elif site == "grade_teaching":
        grade_teaching(
            session,
            concept,
            "Teach hybrid retrieval as two complementary evidence channels.",
            llm=ScriptedLLMClient([_teaching_response()]),
            retriever=retriever,
        )
    elif site == "schedule_decay_check":
        schedule_decay_check(session, concept.id, retriever=retriever)
    elif site == "grade_decay_check":
        prompt = schedule_decay_check(session, concept.id, days=0, retriever=retriever)
        grade_decay_check(
            session,
            prompt.id,
            "Hybrid retrieval combines two evidence channels.",
            llm=ScriptedLLMClient([_grade_response()]),
            retriever=retriever,
        )
    elif site == "generate_challenge":
        generate_challenge(
            session,
            concept,
            llm=ScriptedLLMClient(
                [LLMResponse(text=json.dumps({"problem": "Design a hybrid retriever."}))]
            ),
            retriever=retriever,
        )
    elif site == "consolidate":
        consolidate(
            session,
            concept,
            "Design a hybrid retriever.",
            "I would combine two ranked lists.",
            llm=ScriptedLLMClient(
                [
                    LLMResponse(
                        text=json.dumps(
                            {"canonical": "Use RRF.", "feedback": "Good.", "score": 0.8}
                        )
                    )
                ]
            ),
            retriever=retriever,
        )
    elif site == "roleplay_direct":
        roleplay = RoleplaySession(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            status="briefing",
        )
        session.add(roleplay)
        session.commit()
        direct_roleplay(
            session,
            roleplay,
            llm=ScriptedLLMClient([_roleplay_brief()]),
            retriever=retriever,
        )
    elif site == "run_roleplay_turn":
        roleplay = RoleplaySession(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            status="active",
            persona_brief={"persona": "Reviewer"},
        )
        session.add(roleplay)
        session.commit()
        run_roleplay_turn(
            session,
            roleplay,
            "I combine lexical and semantic ranking.",
            llm=ScriptedLLMClient([LLMResponse(text="Why combine them?")]),
            retriever=retriever,
        )
    elif site == "grade_roleplay":
        roleplay = RoleplaySession(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            status="ended",
            persona_brief={"persona": "Reviewer"},
        )
        session.add(roleplay)
        session.flush()
        session.add(
            RoleplayTurn(
                session_id=roleplay.id,
                role="user",
                content="I combine lexical and semantic ranking.",
            )
        )
        session.commit()
        grade_roleplay(
            session,
            roleplay,
            llm=ScriptedLLMClient([_grade_response(), _outcome_response()]),
            retriever=retriever,
        )
    elif site == "paper_probe_direct":
        probe = PaperProbe(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            paper_title="Hybrid Retrieval",
            paper_text="The paper combines lexical and semantic retrieval.",
        )
        session.add(probe)
        session.commit()
        direct_paper_probe(
            session,
            probe,
            llm=ScriptedLLMClient([_paper_questions(concept.id)]),
            retriever=retriever,
        )
    elif site == "grade_paper_probe":
        probe = PaperProbe(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            paper_title="Hybrid Retrieval",
            paper_text="The paper combines lexical and semantic retrieval.",
            status="answering",
            questions=[
                {
                    "index": 0,
                    "axis": "method",
                    "prompt": "How are retrieval signals combined?",
                    "concept_ids": [concept.id],
                }
            ],
        )
        session.add(probe)
        session.flush()
        session.add(
            PaperProbeAnswer(
                probe_id=probe.id,
                question_index=0,
                content="The system fuses lexical and semantic rankings.",
            )
        )
        session.commit()
        grade_paper_probe(
            session,
            probe,
            llm=ScriptedLLMClient([_grade_response(), _outcome_response()]),
            retriever=retriever,
        )
    elif site == "run_tutor_turn":
        conversation = Conversation(topic_id=topic.id, concept_id=concept.id)
        session.add(conversation)
        session.commit()
        run_tutor_turn(
            session,
            conversation,
            "How does hybrid retrieval work?",
            ScriptedLLMClient(
                [LLMResponse(text="Hybrid retrieval combines evidence. " + "Detail. " * 20)]
            ),
            retriever=retriever,
        )
    else:  # pragma: no cover - the parameter list is exhaustive
        raise AssertionError(site)

    chunks = session.exec(
        select(Chunk).where(
            Chunk.kind.in_(
                ("learner_output", "tutor_turn", "question", "paper", "source_doc")
            )
        )
    ).all()
    assert chunks
    assert all(chunk.embedding_model == embedder.name for chunk in chunks)


_ROUTE_WRITE_SITES = (
    "assess",
    "teach",
    "practice_consolidate",
    "decay_grade",
    "roleplay_turn",
    "roleplay_grade",
    "paper_start",
    "paper_answer",
    "paper_grade",
)


@pytest.mark.parametrize("site", _ROUTE_WRITE_SITES)
def test_route_write_site_injects_retriever_into_every_chunk(vec_session, site):
    session = vec_session
    topic, concept, milestone = _seed_embedding_site(session)
    embedder = ScriptedEmbedder()
    retriever = HybridRetriever(FtsRetriever(), embedder)

    if site == "assess":
        routes_assess.assess(
            concept.id,
            AssessIn(
                kind="self_explanation",
                response="Hybrid retrieval combines two evidence channels.",
            ),
            session=session,
            llm=ScriptedLLMClient([_grade_response()]),
            retriever=retriever,
        )
    elif site == "teach":
        routes_teach.teach(
            concept.id,
            TeachIn(explanation="Teach lexical and semantic retrieval together."),
            session=session,
            llm=ScriptedLLMClient([_teaching_response()]),
            retriever=retriever,
        )
    elif site == "practice_consolidate":
        routes_practice.do_consolidate(
            concept.id,
            ConsolidateIn(problem="Design retrieval.", attempt="Fuse ranked lists."),
            session=session,
            llm=ScriptedLLMClient(
                [
                    LLMResponse(
                        text=json.dumps(
                            {"canonical": "Use RRF.", "feedback": "Good.", "score": 0.8}
                        )
                    )
                ]
            ),
            retriever=retriever,
        )
    elif site == "decay_grade":
        prompt = RecallPrompt(
            concept_id=concept.id,
            prompt="Recall hybrid retrieval.",
            status="active",
        )
        session.add(prompt)
        session.commit()
        routes_decay.grade(
            prompt.id,
            DecayGradeIn(response="It combines lexical and semantic evidence."),
            session=session,
            llm=ScriptedLLMClient([_grade_response()]),
            retriever=retriever,
        )
    elif site == "roleplay_turn":
        roleplay = RoleplaySession(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            status="active",
            persona_brief={"persona": "Reviewer"},
        )
        session.add(roleplay)
        session.commit()
        routes_roleplay.post_turn(
            roleplay.id,
            RoleplayTurnIn(content="I combine both retrieval signals."),
            session=session,
            llm=ScriptedLLMClient([LLMResponse(text="Why?")]),
            retriever=retriever,
        )
    elif site == "roleplay_grade":
        roleplay = RoleplaySession(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            status="ended",
            persona_brief={"persona": "Reviewer"},
        )
        session.add(roleplay)
        session.flush()
        session.add(
            RoleplayTurn(
                session_id=roleplay.id,
                role="user",
                content="I combine both retrieval signals.",
            )
        )
        session.commit()
        routes_roleplay.end_roleplay(
            roleplay.id,
            session=session,
            llm=ScriptedLLMClient([_grade_response(), _outcome_response()]),
            retriever=retriever,
        )
    elif site == "paper_start":
        routes_paper_probe.start_paper_probe(
            milestone.program_id,
            milestone.id,
            PaperProbeStartIn(
                pasted_text="The paper combines lexical and semantic retrieval.",
                title="Hybrid Retrieval",
            ),
            session=session,
            llm=ScriptedLLMClient([_paper_questions(concept.id)]),
            retriever=retriever,
        )
    elif site == "paper_answer":
        probe = PaperProbe(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            status="answering",
            questions=[
                {
                    "index": 0,
                    "axis": "method",
                    "prompt": "How are signals combined?",
                    "concept_ids": [concept.id],
                }
            ],
        )
        session.add(probe)
        session.commit()
        routes_paper_probe.post_answer(
            probe.id,
            PaperProbeAnswerIn(
                question_index=0,
                content="The system fuses lexical and semantic rankings.",
            ),
            session=session,
            retriever=retriever,
        )
    elif site == "paper_grade":
        probe = PaperProbe(
            program_id=milestone.program_id,
            milestone_id=milestone.id,
            status="answering",
            questions=[
                {
                    "index": 0,
                    "axis": "method",
                    "prompt": "How are signals combined?",
                    "concept_ids": [concept.id],
                }
            ],
        )
        session.add(probe)
        session.flush()
        session.add(
            PaperProbeAnswer(
                probe_id=probe.id,
                question_index=0,
                content="The system fuses lexical and semantic rankings.",
            )
        )
        session.commit()
        routes_paper_probe.submit_paper_probe(
            probe.id,
            session=session,
            llm=ScriptedLLMClient([_grade_response(), _outcome_response()]),
            retriever=retriever,
        )
    else:  # pragma: no cover - the parameter list is exhaustive
        raise AssertionError(site)

    chunks = session.exec(
        select(Chunk).where(
            Chunk.kind.in_(
                ("learner_output", "tutor_turn", "question", "paper", "source_doc")
            )
        )
    ).all()
    assert chunks
    assert all(chunk.embedding_model == embedder.name for chunk in chunks)


def test_index_text_embeds_changed_chunks_and_removes_orphan_vectors(vec_session):
    session = vec_session
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    source_ref = "test:pieces"

    first = index_text(
        session,
        kind="vault_note",
        text="alpha one\n\nbravo two\n\ncharlie three",
        source_ref=source_ref,
        splitter=_split_small,
        retriever=retriever,
    )
    second = index_text(
        session,
        kind="vault_note",
        text="alpha one",
        source_ref=source_ref,
        splitter=_split_small,
        retriever=retriever,
    )

    chunks = session.exec(select(Chunk).where(Chunk.source_ref == source_ref)).all()
    vector_count = session.execute(text("SELECT count(*) FROM chunk_vec")).scalar_one()
    assert first.indexed == 3
    assert second.removed == 2
    assert len(chunks) == vector_count == 1
    assert chunks[0].embedding_model == retriever.embedder.name


def test_index_text_embedding_failure_is_fail_open(vec_session):
    session = vec_session
    topic = Topic(title="Fail-open embeddings")
    session.add(topic)
    session.flush()

    class FailingEmbedder:
        name = "failing"
        dim = 384

        def embed(self, texts):
            raise RuntimeError("embedding failed")

    retriever = HybridRetriever(FtsRetriever(), FailingEmbedder())

    result = index_text(
        session,
        kind="vault_note",
        text="The chunk remains available to lexical retrieval.",
        source_ref="test:fail-open",
        topic_id=topic.id,
        retriever=retriever,
    )
    session.commit()

    chunk = session.exec(select(Chunk).where(Chunk.source_ref == "test:fail-open")).one()
    event_row = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:error")
    ).one()
    assert result.indexed == 1
    assert chunk.embedding_model is None
    assert event_row.topic_id == topic.id
    assert event_row.detail == "embed: RuntimeError: embedding failed"


def test_chunk_delete_trigger_prevents_stale_vector_on_rowid_reuse(vec_session):
    session = vec_session
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    index_text(
        session,
        kind="vault_note",
        text="obsolete quasar vector",
        source_ref="test:old-row",
        retriever=retriever,
    )
    session.commit()
    old_chunk = session.exec(
        select(Chunk).where(Chunk.source_ref == "test:old-row")
    ).one()
    old_id = old_chunk.id
    assert old_id is not None

    assert remove_source(session, "test:old-row") == 1
    session.commit()
    index_text(
        session,
        kind="learner_output",
        text="replacement content",
        source_ref="test:new-row",
    )
    session.commit()
    new_chunk = session.exec(
        select(Chunk).where(Chunk.source_ref == "test:new-row")
    ).one()

    vector = session.execute(
        text("SELECT chunk_id FROM chunk_vec WHERE chunk_id = :chunk_id"),
        {"chunk_id": old_id},
    ).first()
    hits = retriever.search(
        session,
        "obsolete quasar vector",
        where=ChunkFilter(),
        k=1,
    )
    assert new_chunk.id == old_id
    assert vector is None
    assert hits == []


def test_review_sources_embeds_accepted_source_at_write_time(vec_session):
    session = vec_session
    topic = Topic(title="Accepted source")
    session.add(topic)
    session.flush()
    source = SourceDoc(
        topic_id=topic.id,
        title="Source",
        url="https://example.test/source",
        status="proposed",
    )
    session.add(source)
    session.commit()
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_fetcher] = lambda: lambda _: "Embedded source text."
    app.dependency_overrides[get_retriever] = lambda: retriever

    response = TestClient(app).post(
        f"/api/topics/{topic.id}/sources/review",
        json={"accepted_ids": [source.id], "pruned_ids": []},
    )
    app.dependency_overrides.clear()

    chunk = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{source.id}")).one()
    assert response.status_code == 200
    assert chunk.embedding_model == retriever.embedder.name


def test_assess_route_embeds_scheduled_decay_question(vec_session):
    session = vec_session
    topic = Topic(title="Decay")
    session.add(topic)
    session.flush()
    session.add(
        TopicFoundation(
            topic_id=topic.id,
            overview="Overview",
            key_concepts=["retrieval"],
            prerequisite_map={},
        )
    )
    track = Track(topic_id=topic.id, title="Track")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="retrieval")
    session.add(concept)
    session.flush()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
    session.commit()
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    rubric = json.dumps(
        {
            "criteria": ["clear"],
            "must_include": [],
            "strong_signs": [],
            "weak_signs": [],
            "source_refs": [],
        }
    )
    grade = json.dumps({"score": 0.8, "verdict": "solid", "gaps": [],
                        "missing_required": [], "misconceptions_committed": []})
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=rubric), LLMResponse(text=grade)]
    )
    app.dependency_overrides[get_retriever] = lambda: retriever

    response = TestClient(app).post(
        f"/api/concepts/{concept.id}/assess",
        json={"kind": "self_explanation", "response": "Retrieval selects evidence."},
    )
    app.dependency_overrides.clear()

    chunk = session.exec(
        select(Chunk).where(Chunk.source_ref.startswith("recallprompt:"))
    ).one()
    assert response.status_code == 200
    assert chunk.embedding_model == retriever.embedder.name


def test_vault_ingest_route_embeds_notes_at_write_time(vec_session, tmp_path):
    session = vec_session
    topic = Topic(title="Vault ingest")
    session.add(topic)
    session.commit()
    note = tmp_path / "note.md"
    note.write_text("# Note\n\nEmbedded vault content.", encoding="utf-8")
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_retriever] = lambda: retriever

    response = TestClient(app).post(
        f"/api/topics/{topic.id}/vault/ingest",
        json={"vault_path": str(tmp_path)},
    )
    app.dependency_overrides.clear()

    chunk = session.exec(select(Chunk).where(Chunk.kind == "vault_note")).one()
    assert response.status_code == 200
    assert chunk.embedding_model == retriever.embedder.name


def test_reindex_reembeds_a_chunk_with_a_stale_model(vec_session):
    session = vec_session
    topic = Topic(title="Re-embedding")
    session.add(topic)
    session.flush()
    assert topic.id is not None
    doc = SourceDoc(
        topic_id=topic.id,
        title="Vectors",
        url="https://example.test/vectors",
        status="accepted",
    )
    session.add(doc)
    session.commit()

    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    first = reindex_topic(
        session,
        topic.id,
        vault_path="",
        fetch=lambda _: "semantic vector text",
        kinds=("source_doc",),
        retriever=retriever,
    )
    chunk = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc.id}")).one()
    assert chunk.id is not None
    expected = retriever.embedder.embed([f"{chunk.context}\n{chunk.text}"])[0]
    assert first.indexed == 1
    assert _vector_row(session, chunk.id) == pytest.approx(expected)

    session.execute(
        text("DELETE FROM chunk_vec WHERE chunk_id = :chunk_id"),
        {"chunk_id": chunk.id},
    )
    session.execute(
        text(
            "INSERT INTO chunk_vec(chunk_id, embedding) "
            "VALUES (:chunk_id, :embedding)"
        ),
        {
            "chunk_id": chunk.id,
            "embedding": struct.pack("<384f", *([0.0] * 384)),
        },
    )
    chunk.embedding_model = "obsolete-model"
    session.add(chunk)
    session.commit()

    second = reindex_topic(
        session,
        topic.id,
        vault_path="",
        fetch=lambda _: "semantic vector text",
        kinds=("source_doc",),
        retriever=retriever,
    )
    session.refresh(chunk)

    assert second.indexed == 0
    assert second.skipped == 1
    assert chunk.embedding_model == retriever.embedder.name
    assert _vector_row(session, chunk.id) == pytest.approx(expected)


def test_reindex_reembeds_stale_chunks_outside_selected_kinds(vec_session, tmp_path):
    session = vec_session
    topic = Topic(title="All stale kinds")
    session.add(topic)
    session.flush()
    index_text(
        session,
        kind="learner_output",
        text="Learner output needs a vector.",
        source_ref="test:learner-output",
        topic_id=topic.id,
    )
    session.commit()
    chunk = session.exec(
        select(Chunk).where(Chunk.source_ref == "test:learner-output")
    ).one()
    assert chunk.embedding_model is None
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())

    reindex_topic(
        session,
        topic.id,
        vault_path=str(tmp_path),
        fetch=lambda _: None,
        kinds=("vault_note",),
        retriever=retriever,
    )
    session.refresh(chunk)

    assert chunk.embedding_model == retriever.embedder.name


def test_reindex_batches_stale_embeddings_and_honors_deadline(vec_session):
    session = vec_session
    topic = Topic(title="Embedding deadline")
    session.add(topic)
    session.flush()
    for index in range(130):
        index_text(
            session,
            kind="learner_output",
            text=f"Learner output {index}",
            source_ref=f"test:deadline:{index}",
            topic_id=topic.id,
        )
    session.commit()

    class SlowEmbedder:
        name = "slow-scripted"
        dim = 384

        def __init__(self):
            self.inner = ScriptedEmbedder()
            self.batch_sizes = []

        def embed(self, texts):
            self.batch_sizes.append(len(texts))
            time.sleep(0.02)
            return self.inner.embed(texts)

    embedder = SlowEmbedder()
    retriever = HybridRetriever(FtsRetriever(), embedder)
    result = reindex_topic(
        session,
        topic.id,
        vault_path="",
        fetch=lambda _: None,
        kinds=("source_doc",),
        deadline_s=0.005,
        retriever=retriever,
    )

    chunks = session.exec(
        select(Chunk).where(Chunk.topic_id == topic.id).order_by(Chunk.id)
    ).all()
    embedded = [chunk for chunk in chunks if chunk.embedding_model == embedder.name]
    stale = [chunk for chunk in chunks if chunk.embedding_model is None]
    assert result.truncated is True
    assert embedder.batch_sizes == [64]
    assert embedded
    assert stale


def test_is_near_duplicate_can_match_on_cosine_alone():
    embedder = ScriptedEmbedder()
    original = "cosine"
    candidate = _colliding_token(embedder, original)
    chunk = Chunk(
        id=1,
        kind="question",
        source_ref="question:prior",
        text=original,
        content_hash=content_hash(original),
    )
    hit = Hit(chunk=chunk, score=1.0)

    assert jaccard(candidate, original) == 0.0
    assert is_near_duplicate(candidate, [hit], embedder=embedder) is hit
