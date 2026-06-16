from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import ItemOut, ItemPatchIn
from adaptive_academy.models import Item

router = APIRouter(prefix="/api/items", tags=["items"])

_VALID_STATUS = {"todo", "doing", "done"}


@router.patch("/{item_id}", response_model=ItemOut)
def patch_item(item_id: int, body: ItemPatchIn, session: Session = Depends(get_session)) -> ItemOut:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if body.status is not None:
        if body.status not in _VALID_STATUS:
            raise HTTPException(422, "invalid status")
        item.status = body.status
    if body.text is not None:
        item.text = body.text
    session.add(item)
    session.commit()
    session.refresh(item)
    return ItemOut(id=item.id, text=item.text, type=item.type, status=item.status,
                   position=item.position)
