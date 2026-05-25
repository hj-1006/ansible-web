from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import ApiKey, Device, Job
from app.schemas import (
    CommandRequest,
    ConnectivityTestRequest,
    DeviceCreate,
    DeviceResponse,
    DeviceUpdate,
    JobResponse,
)
from app import ansible_service
from app.snmp_collector import collect_device_metrics, discover_ports

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.get("", response_model=list[DeviceResponse])
def list_devices(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    return db.query(Device).order_by(Device.name).all()


@router.post("", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED)
def create_device(
    body: DeviceCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    if db.query(Device).filter(Device.name == body.name).first():
        raise HTTPException(status_code=400, detail="이미 존재하는 장비 이름입니다.")
    device = Device(**body.model_dump())
    db.add(device)
    db.commit()
    db.refresh(device)
    ansible_service.sync_inventory(db)
    return device


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")
    return device


@router.patch("/{device_id}", response_model=DeviceResponse)
def update_device(
    device_id: int,
    body: DeviceUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(device, key, value)
    db.commit()
    db.refresh(device)
    ansible_service.sync_inventory(db)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")
    db.delete(device)
    db.commit()
    ansible_service.sync_inventory(db)


@router.post("/{device_id}/test", response_model=JobResponse)
def test_device(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
    ping_target: str | None = None,
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")
    return ansible_service.run_connectivity_test(db, device, ping_target)


@router.post("/{device_id}/snmp/poll")
def snmp_poll_device(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")
    if not device.snmp_enabled:
        raise HTTPException(status_code=400, detail="SNMP를 활성화하세요.")
    from app.snmp_service import run_snmp_poll

    job, _ = run_snmp_poll(db, device)
    if device.snmp_monitor_enabled:
        discover_ports(db, device)
        collect_device_metrics(db, device)
    return job


@router.post("/{device_id}/command", response_model=JobResponse)
def run_command(
    device_id: int,
    body: CommandRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")
    return ansible_service.run_command(db, device, body.command, body.become)


@router.post("/test/bulk", response_model=list[JobResponse])
def test_bulk(
    body: ConnectivityTestRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    q = db.query(Device).filter(Device.enabled.is_(True))
    if body.device_ids:
        q = q.filter(Device.id.in_(body.device_ids))
    devices = q.all()
    if not devices:
        raise HTTPException(status_code=400, detail="테스트할 장비가 없습니다.")
    jobs = []
    for device in devices:
        job = ansible_service.run_connectivity_test(db, device, body.ping_target)
        jobs.append(job)
    return jobs
