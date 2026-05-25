from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.database import get_db
from app.models import ApiKey, Device, DeviceMetricSample, DevicePort, PortTrafficSample
from app.schemas import (
    DeviceMonitorOverview,
    DevicePortResponse,
    DeviceResponse,
    MetricSamplePoint,
    PortTrafficHistoryResponse,
    TrafficSamplePoint,
)
from app.snmp_collector import collect_device_metrics, discover_ports, _status_label

router = APIRouter(prefix="/api/v1/devices", tags=["monitoring"])


def _port_response(port: DevicePort) -> DevicePortResponse:
    return DevicePortResponse(
        id=port.id,
        if_index=port.if_index,
        name=port.name,
        alias=port.alias,
        speed_bps=port.speed_bps,
        admin_status=port.admin_status,
        oper_status=port.oper_status,
        is_shutdown=port.is_shutdown,
        status=_status_label(port.admin_status, port.oper_status),
        last_in_bps=port.last_in_bps,
        last_out_bps=port.last_out_bps,
        last_in_avg_bps=port.last_in_avg_bps,
        last_out_avg_bps=port.last_out_avg_bps,
        updated_at=port.updated_at,
    )


def _get_device(db: Session, device_id: int) -> Device:
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="장비를 찾을 수 없습니다.")
    return device


@router.get("/{device_id}/monitor/overview", response_model=DeviceMonitorOverview)
def monitor_overview(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    device = _get_device(db, device_id)
    ports = (
        db.query(DevicePort)
        .filter(DevicePort.device_id == device_id)
        .order_by(DevicePort.name)
        .all()
    )
    since = datetime.utcnow() - timedelta(hours=1)
    metrics = (
        db.query(DeviceMetricSample)
        .filter(
            DeviceMetricSample.device_id == device_id,
            DeviceMetricSample.recorded_at >= since,
        )
        .order_by(DeviceMetricSample.recorded_at.asc())
        .limit(120)
        .all()
    )
    return DeviceMonitorOverview(
        device=DeviceResponse.model_validate(device),
        ports=[_port_response(p) for p in ports],
        recent_metrics=[
            MetricSamplePoint(
                recorded_at=m.recorded_at,
                cpu_percent=m.cpu_percent,
                memory_percent=m.memory_percent,
            )
            for m in metrics
        ],
    )


@router.get("/{device_id}/monitor/ports", response_model=list[DevicePortResponse])
def list_ports(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    _get_device(db, device_id)
    ports = (
        db.query(DevicePort)
        .filter(DevicePort.device_id == device_id)
        .order_by(DevicePort.name)
        .all()
    )
    return [_port_response(p) for p in ports]


@router.get("/{device_id}/monitor/ports/{if_index}/traffic", response_model=PortTrafficHistoryResponse)
def port_traffic_history(
    device_id: int,
    if_index: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
    minutes: int = Query(60, ge=5, le=1440),
    limit: int = Query(500, ge=10, le=2000),
):
    device = _get_device(db, device_id)
    port = (
        db.query(DevicePort)
        .filter(DevicePort.device_id == device_id, DevicePort.if_index == if_index)
        .first()
    )
    if not port:
        raise HTTPException(status_code=404, detail="포트를 찾을 수 없습니다.")

    since = datetime.utcnow() - timedelta(minutes=minutes)
    samples = (
        db.query(PortTrafficSample)
        .filter(
            PortTrafficSample.device_id == device_id,
            PortTrafficSample.if_index == if_index,
            PortTrafficSample.recorded_at >= since,
        )
        .order_by(PortTrafficSample.recorded_at.asc())
        .limit(limit)
        .all()
    )
    return PortTrafficHistoryResponse(
        device_id=device_id,
        if_index=if_index,
        port_name=port.name,
        samples=[
            TrafficSamplePoint(
                recorded_at=s.recorded_at,
                in_bps=s.in_bps,
                out_bps=s.out_bps,
                in_avg_bps=s.in_avg_bps,
                out_avg_bps=s.out_avg_bps,
            )
            for s in samples
        ],
    )


@router.get("/{device_id}/monitor/metrics", response_model=list[MetricSamplePoint])
def device_metrics_history(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
    minutes: int = Query(60, ge=5, le=1440),
):
    _get_device(db, device_id)
    since = datetime.utcnow() - timedelta(minutes=minutes)
    rows = (
        db.query(DeviceMetricSample)
        .filter(
            DeviceMetricSample.device_id == device_id,
            DeviceMetricSample.recorded_at >= since,
        )
        .order_by(DeviceMetricSample.recorded_at.asc())
        .all()
    )
    return [
        MetricSamplePoint(
            recorded_at=r.recorded_at,
            cpu_percent=r.cpu_percent,
            memory_percent=r.memory_percent,
        )
        for r in rows
    ]


@router.post("/{device_id}/monitor/discover")
def discover_device_ports(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    device = _get_device(db, device_id)
    if not device.snmp_enabled:
        raise HTTPException(status_code=400, detail="SNMP를 먼저 활성화하세요.")
    try:
        count = discover_ports(db, device)
        return {"ok": True, "ports_discovered": count}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc


@router.post("/{device_id}/monitor/poll")
def poll_device_now(
    device_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[ApiKey, Depends(require_api_key)],
):
    device = _get_device(db, device_id)
    if not device.snmp_enabled:
        raise HTTPException(status_code=400, detail="SNMP를 먼저 활성화하세요.")
    try:
        collect_device_metrics(db, device)
        return {"ok": True, "polled_at": device.snmp_last_polled}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc
