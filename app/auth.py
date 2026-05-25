import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiKey

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """(full_key, prefix, hash) 반환"""
    raw = secrets.token_urlsafe(32)
    full_key = f"aw_{raw}"
    prefix = full_key[:12]
    return full_key, prefix, hash_api_key(full_key)


def verify_api_key(db: Session, key: str) -> ApiKey | None:
    if not key:
        return None
    key_hash = hash_api_key(key)
    prefix = key[:12] if len(key) >= 12 else key
    record = (
        db.query(ApiKey)
        .filter(ApiKey.key_prefix == prefix, ApiKey.is_active.is_(True))
        .first()
    )
    if record and secrets.compare_digest(record.key_hash, key_hash):
        return record
    return None


async def require_api_key(
    api_key: Annotated[str | None, Security(API_KEY_HEADER)],
    db: Annotated[Session, Depends(get_db)],
) -> ApiKey:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API 키가 필요합니다. 헤더 X-API-Key 를 설정하세요.",
        )
    record = verify_api_key(db, api_key)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="유효하지 않거나 비활성화된 API 키입니다.",
        )
    return record
