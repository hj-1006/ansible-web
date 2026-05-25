"""SNMP 기본 정보 조회 (sys*) — 모니터링은 snmp_collector 사용"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Device, Job, JobStatus, JobType
from app.snmp_client import (
    OID_SYS_CONTACT,
    OID_SYS_DESCR,
    OID_SYS_LOCATION,
    OID_SYS_NAME,
    OID_SYS_UPTIME,
    SnmpClient,
)


@dataclass
class SnmpPollResult:
    reachable: bool
    success: bool
    message: str
    data: dict[str, str]


def poll_device_snmp(device: Device) -> SnmpPollResult:
    if not device.snmp_enabled:
        return SnmpPollResult(False, False, "SNMP가 비활성화된 장비입니다.", {})

    try:
        client = SnmpClient(device)
        data = client.get_multi(
            [OID_SYS_DESCR, OID_SYS_NAME, OID_SYS_UPTIME, OID_SYS_LOCATION, OID_SYS_CONTACT]
        )
        mapped = {
            "sysDescr": data.get(OID_SYS_DESCR, ""),
            "sysName": data.get(OID_SYS_NAME, ""),
            "sysUpTime": data.get(OID_SYS_UPTIME, ""),
            "sysLocation": data.get(OID_SYS_LOCATION, ""),
            "sysContact": data.get(OID_SYS_CONTACT, ""),
        }
        return SnmpPollResult(True, True, "SNMP 조회 성공", mapped)
    except Exception as exc:
        return SnmpPollResult(True, False, str(exc), {})


def apply_snmp_result_to_device(device: Device, result: SnmpPollResult) -> None:
    device.snmp_last_polled = datetime.utcnow()
    device.snmp_last_status = "success" if result.success else "failed"
    device.snmp_last_error = "" if result.success else result.message
    if result.success:
        device.snmp_sys_name = result.data.get("sysName", "")
        device.snmp_sys_descr = result.data.get("sysDescr", "")
        device.snmp_sys_location = result.data.get("sysLocation", "")
        device.snmp_sys_contact = result.data.get("sysContact", "")
        device.snmp_sys_uptime = result.data.get("sysUpTime", "")


def run_snmp_poll(
    db: Session,
    device: Device,
    *,
    connectivity_ok: bool | None = None,
) -> tuple[Job, SnmpPollResult]:
    import json

    if connectivity_ok is False:
        result = SnmpPollResult(False, False, "통신 테스트 실패 후 SNMP를 건너뜁니다.", {})
        job = Job(
            job_type=JobType.snmp,
            status=JobStatus.failed,
            device_id=device.id,
            target_hosts=device.name,
            command="snmp_poll",
            error_message=result.message,
            completed_at=datetime.utcnow(),
        )
        db.add(job)
        apply_snmp_result_to_device(device, result)
        db.commit()
        db.refresh(job)
        return job, result

    job = Job(
        job_type=JobType.snmp,
        status=JobStatus.running,
        device_id=device.id,
        target_hosts=device.name,
        command="snmp_poll",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    result = poll_device_snmp(device)
    apply_snmp_result_to_device(device, result)

    job.status = JobStatus.success if result.success else JobStatus.failed
    job.result_stdout = json.dumps(result.data, ensure_ascii=False, indent=2)
    job.error_message = "" if result.success else result.message
    job.result_json = json.dumps(
        {"reachable": result.reachable, "success": result.success, "message": result.message},
        ensure_ascii=False,
    )
    job.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job, result
