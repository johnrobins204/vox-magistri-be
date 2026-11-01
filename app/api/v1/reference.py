# api/v1/reference.py
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_reference
from app.schemas.v1 import SpeciesListResp

router = APIRouter(prefix="/api/v1/reference", tags=["reference"])


@router.get("/species", response_model=SpeciesListResp)
def list_species(reference=Depends(get_reference)):
    if reference is None:
        raise HTTPException(status_code=503, detail="Reference data unavailable")
    return {"species": reference["species"]}
