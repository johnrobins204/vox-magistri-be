# app/api/v1/world.py
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.deps import get_world_store, require_local_token
from app.schemas.world import (
    WorldEntityCreateReq,
    WorldEntityListResp,
    WorldEntityPatchReq,
    WorldEntityResp,
)
from app.type_defs import EntityKind, EntityStatus, WorldStore

router = APIRouter(
    prefix="/api/v1/world", tags=["world"], dependencies=[Depends(require_local_token)]
)


def _world_store(store: Annotated[WorldStore | None, Depends(get_world_store)]) -> WorldStore:
    if store is None:
        raise HTTPException(status_code=503, detail="World store unavailable")
    return store


Store = Annotated[WorldStore, Depends(_world_store)]


@router.get("/entities", response_model=WorldEntityListResp)
async def list_entities(
    store: Store,
    session_id: str | None = None,
    status: EntityStatus | None = None,
    kind: EntityKind | None = None,
):
    return WorldEntityListResp(entities=store.list_entities(session_id, status=status, kind=kind))


@router.post("/entities", response_model=WorldEntityResp, status_code=status.HTTP_201_CREATED)
async def create_entity(req: WorldEntityCreateReq, store: Store):
    try:
        return store.create_entity(
            name=req.name,
            kind=req.kind,
            aliases=req.aliases,
            notes=req.notes,
            status=req.status,
            session_id=req.session_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found") from None


@router.get("/entities/{entity_id}", response_model=WorldEntityResp)
async def get_entity(entity_id: str, store: Store):
    try:
        return store.get_entity(entity_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Entity not found") from None


@router.patch("/entities/{entity_id}", response_model=WorldEntityResp)
async def patch_entity(entity_id: str, req: WorldEntityPatchReq, store: Store):
    changes = req.model_dump(exclude_unset=True)
    try:
        if not changes:
            return store.get_entity(entity_id)
        return store.update_entity(entity_id, changes)
    except KeyError:
        raise HTTPException(status_code=404, detail="Entity not found") from None


@router.delete("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(entity_id: str, store: Store):
    try:
        store.delete_entity(entity_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Entity not found") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
