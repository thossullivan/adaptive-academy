"""Concept notebooks: a concept's notes and work in one place (engine/notebook.py), and the
learner's own notes on it. Saving a note, like any new attempt or grade, queues the concept's
vault note for a rewrite (engine/notebook_sync.py); that never holds up or fails the save."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import (
    NotebookConceptOut,
    NotebookCountsOut,
    NotebookItemOut,
    NotebookNoteOut,
    NotebookOut,
    NoteIn,
    NoteOut,
    TopicNotebookOut,
)
from adaptive_academy.engine.notebook import NoteTooLong, build_notebook, save_note, topic_notebook
from adaptive_academy.engine.notebook_sync import NOTEBOOK_SYNC, register_vault_path
from adaptive_academy.models import Concept, Topic

router = APIRouter(prefix="/api", tags=["notebook"])


def _concept(session: Session, concept_id: int) -> Concept:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    return concept


@router.get("/concepts/{concept_id}/notebook", response_model=NotebookOut)
def get_notebook(concept_id: int, session: Session = Depends(get_session)) -> NotebookOut:
    nb = build_notebook(session, _concept(session, concept_id))
    note = (NotebookNoteOut(body=nb.note_body, updated_at=nb.note_updated_at)
            if nb.note_updated_at is not None else None)
    return NotebookOut(
        concept_id=nb.concept_id, concept_name=nb.concept_name, topic_id=nb.topic_id,
        note=note,
        counts=NotebookCountsOut(attempts=nb.count("attempt"),
                                 explanations=nb.count("explanation"),
                                 solutions=nb.count("solution")),
        items=[NotebookItemOut(**vars(item)) for item in nb.items],
    )


@router.put("/concepts/{concept_id}/note", response_model=NoteOut)
def put_note(concept_id: int, body: NoteIn, session: Session = Depends(get_session)) -> NoteOut:
    concept = _concept(session, concept_id)
    if body.vault_path.strip():
        try:
            register_vault_path(body.vault_path)
        except ValueError as exc:
            NOTEBOOK_SYNC.record_problem("vault_path", f"Couldn't sync to the vault: {exc}")
    try:
        note = save_note(session, concept.id, body.body)
    except NoteTooLong as exc:
        raise HTTPException(413, str(exc)) from exc
    return NoteOut(concept_id=note.concept_id, body=note.body, updated_at=note.updated_at)


@router.get("/topics/{topic_id}/notebook", response_model=TopicNotebookOut)
def get_topic_notebook(topic_id: int, session: Session = Depends(get_session)) -> TopicNotebookOut:
    if session.get(Topic, topic_id) is None:
        raise HTTPException(404, "topic not found")
    return TopicNotebookOut(
        topic_id=topic_id,
        concepts=[NotebookConceptOut(**vars(row)) for row in topic_notebook(session, topic_id)],
    )
