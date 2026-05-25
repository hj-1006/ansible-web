from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import generate_api_key, require_api_key
from app.database import get_db
from app.models import ApiKey
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyResponse

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyResponse])
def list_keys(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    return db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()


@router.post("", response_model=ApiKeyCreated, status_code=201)
def create_key(
    body: ApiKeyCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    full_key, prefix, key_hash = generate_api_key()
    record = ApiKey(name=body.name, key_prefix=prefix, key_hash=key_hash)
    db.add(record)
    db.commit()
    db.refresh(record)
    return ApiKeyCreated(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        is_active=record.is_active,
        created_at=record.created_at,
        api_key=full_key,
    )


@router.delete("/{key_id}", status_code=204)
def revoke_key(
    key_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    record = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="API 키를 찾을 수 없습니다.")
    record.is_active = False
    db.commit()
