from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import ApiKey, Job
from app.schemas import JobResponse

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("", response_model=list[JobResponse])
def list_jobs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
    limit: int = 50,
):
    return db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return job
