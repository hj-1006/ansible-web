"""최초 API 키 부트스트랩"""

import logging

from sqlalchemy.orm import Session

from app.auth import generate_api_key
from app.config import settings
from app.models import ApiKey

logger = logging.getLogger(__name__)


def ensure_api_key(db: Session) -> str | None:
    if db.query(ApiKey).filter(ApiKey.is_active.is_(True)).first():
        return None

    if settings.bootstrap_api_key:
        from app.auth import hash_api_key

        key = settings.bootstrap_api_key
        record = ApiKey(
            name="bootstrap",
            key_prefix=key[:12],
            key_hash=hash_api_key(key),
        )
        db.add(record)
        db.commit()
        logger.warning("부트스트랩 API 키가 .env 에서 등록되었습니다.")
        return key

    full_key, prefix, key_hash = generate_api_key()
    record = ApiKey(name="auto-generated", key_prefix=prefix, key_hash=key_hash)
    db.add(record)
    db.commit()
    logger.warning("=" * 60)
    logger.warning("최초 API 키가 생성되었습니다. 반드시 저장하세요:")
    logger.warning("  %s", full_key)
    logger.warning("=" * 60)
    return full_key
