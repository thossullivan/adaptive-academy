"""Read-only momentum routes — derived wind, the Fleet, and the comeback move."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import ComebackMoveOut, ComebackOut, WindStateOut
from adaptive_academy.engine.momentum import comeback_move, fleet, topic_wind
from adaptive_academy.engine.progress import topic_progress

router = APIRouter(prefix="/api", tags=["momentum"])


def _wind_out(ws, progress: float) -> WindStateOut:
    # Combine the two orthogonal quantities only here, at the view layer: wind (momentum) from the
    # momentum engine, progress (distance) from the progress engine. The engines never touch.
    return WindStateOut(
        topic_id=ws.topic_id, topic_title=ws.topic_title, value=ws.value, state=ws.state,
        last_sailed=ws.last_sailed.isoformat() if ws.last_sailed else None,
        days_since=round(ws.days_since, 2) if ws.days_since is not None else None,
        progress=progress)


@router.get("/fleet", response_model=list[WindStateOut])
def get_fleet(session: Session = Depends(get_session)) -> list[WindStateOut]:
    return [_wind_out(w, topic_progress(session, w.topic_id)) for w in fleet(session)]


@router.get("/topics/{topic_id}/wind", response_model=WindStateOut)
def get_wind(topic_id: int, session: Session = Depends(get_session)) -> WindStateOut:
    return _wind_out(topic_wind(session, topic_id), topic_progress(session, topic_id))


@router.get("/topics/{topic_id}/comeback", response_model=ComebackOut)
def get_comeback(topic_id: int, session: Session = Depends(get_session)) -> ComebackOut:
    m = comeback_move(session, topic_id)
    move = ComebackMoveOut(kind=m.kind, label=m.label, href=m.href, minutes=m.minutes) if m else None
    return ComebackOut(move=move)
