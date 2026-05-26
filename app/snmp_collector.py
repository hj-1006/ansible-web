"""Cisco 장비 SNMP 모니터링 — 포트 트래픽·CPU·RAM 시계열 수집"""

from __future__ import annotations

import logging
import re  # 텍스트 형태의 SNMP 응답(e.g. up(1))에서 숫자만 정밀하게 추출하기 위해 추가
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Device, DeviceMetricSample, DevicePort, PortTrafficSample
from app.snmp_client import (
    OID_ASA_CPU,
    OID_CISCO_CPU_5MIN,
    OID_CISCO_MEM_FREE,
    OID_CISCO_MEM_USED,
    OID_IF_ADMIN,
    OID_IF_ALIAS,
    OID_IF_DESCR,
    OID_IF_HC_IN,
    OID_IF_HC_OUT,
    OID_IF_IN,
    OID_IF_OPER,
    OID_IF_OUT,
    OID_IF_SPEED,
    OID_IF_TYPE,
    OID_SYS_CONTACT,
    OID_SYS_DESCR,
    OID_SYS_LOCATION,
    OID_SYS_NAME,
    OID_SYS_UPTIME,
    SnmpClient,
)

logger = logging.getLogger(__name__)

# 물리 포트 위주 (루프백/터널 등 제외 옵션)
SKIP_IF_TYPES = {24, 131, 53}  # loopback, tunnel, propVirtual
SKIP_NAME_PREFIXES = ("Null", "Vlan", "NVI", "unrouted")


def _admin_shutdown(admin: int, oper: int) -> bool:
    # ifAdminStatus: 2=down → 관리자 셧다운
    return admin == 2


def _status_label(admin: int, oper: int) -> str:
    if admin == 2:
        return "shutdown"
    if oper == 1:
        return "up"
    return "down"


def _should_include_port(name: str, if_type: int, include_virtual: bool = False) -> bool:
    if not include_virtual:
        if if_type in SKIP_IF_TYPES:
            return False
        for p in SKIP_NAME_PREFIXES:
            if name.startswith(p):
                return False
    return True


def _rows_to_map(rows) -> dict[int, str]:
    return {r.index: r.value for r in rows}


def _rows_to_int_map(rows) -> dict[int, int]:
    """텍스트가 혼합된 SNMP 반환값(예: up(1), ethernetCsmacd(6))에서 순수 정수만 파싱"""
    out: dict[int, int] = {}
    for r in rows:
        cleaned = r.value.strip()
        # 1. 괄호 안에 숫자가 매칭되는 형태 처리 (예: up(1) -> 1)
        match = re.search(r"\((\d+)\)", cleaned)
        if match:
            out[r.index] = int(match.group(1))
        else:
            try:
                out[r.index] = int(cleaned)
            except ValueError:
                # 2. 괄호는 없으나 문자열 내부에 숫자가 포함되어 있는 경우 숫자만 필터링 시도
                digits = re.search(r"\d+", cleaned)
                if digits:
                    out[r.index] = int(digits.group())
    return out


def _counter_delta(prev: int, curr: int) -> int:
    if curr >= prev:
        return curr - prev
    # 32/64-bit wrap
    return (2**64 - prev + curr) if curr < prev else 0


def discover_ports(db: Session, device: Device, include_virtual: bool = False) -> int:
    client = SnmpClient(device)
    descr = _rows_to_map(client.walk(OID_IF_DESCR))
    if_types = _rows_to_int_map(client.walk(OID_IF_TYPE))
    speeds = _rows_to_int_map(client.walk(OID_IF_SPEED))
    admin = _rows_to_int_map(client.walk(OID_IF_ADMIN))
    oper = _rows_to_int_map(client.walk(OID_IF_OPER))
    try:
        aliases = _rows_to_map(client.walk(OID_IF_ALIAS))
    except Exception:
        aliases = {}

    existing = {
        (p.device_id, p.if_index): p
        for p in db.query(DevicePort).filter(DevicePort.device_id == device.id).all()
    }
    count = 0
    now = datetime.utcnow()
    for idx, name in descr.items():
        if not _should_include_port(name, if_types.get(idx, 0), include_virtual):
            continue
        a = admin.get(idx, 0)
        o = oper.get(idx, 0)
        port = existing.get((device.id, idx))
        if not port:
            port = DevicePort(device_id=device.id, if_index=idx, name=name)
            db.add(port)
        port.name = name
        port.alias = aliases.get(idx, "")
        port.speed_bps = speeds.get(idx, 0)
        port.if_type = if_types.get(idx, 0)
        port.admin_status = a
        port.oper_status = o
        port.is_shutdown = _admin_shutdown(a, o)
        port.updated_at = now
        count += 1
    db.commit()
    return count


def _fetch_cpu_memory(client: SnmpClient, platform: str) -> tuple[float | None, float | None, int | None, int | None]:
    cpu_percent: float | None = None
    mem_percent: float | None = None
    mem_used: int | None = None
    mem_free: int | None = None

    cpu_oid = OID_ASA_CPU if platform == "asa_5512" else OID_CISCO_CPU_5MIN
    try:
        cpu_rows = client.walk(cpu_oid)
        vals = []
        for r in cpu_rows:
            try:
                vals.append(float(r.value))
            except ValueError:
                pass
        if vals:
            cpu_percent = max(vals)
    except Exception as exc:
        logger.debug("CPU SNMP %s: %s", client.host, exc)

    try:
        used_rows = client.walk(OID_CISCO_MEM_USED)
        free_rows = client.walk(OID_CISCO_MEM_FREE)
        used_map = _rows_to_int_map(used_rows)
        free_map = _rows_to_int_map(free_rows)
        if used_map and free_map:
            best_idx = max(used_map.keys(), key=lambda k: used_map.get(k, 0))
            mem_used = used_map.get(best_idx)
            mem_free = free_map.get(best_idx, 0)
            if mem_used is not None and mem_free is not None:
                total = mem_used + mem_free
                if total > 0:
                    mem_percent = round(mem_used / total * 100, 2)
    except Exception as exc:
        logger.debug("Memory SNMP %s: %s", client.host, exc)

    return cpu_percent, mem_percent, mem_used, mem_free


def _get_octet_maps(client: SnmpClient) -> tuple[dict[int, int], dict[int, int]]:
    try:
        in_map = _rows_to_int_map(client.walk(OID_IF_HC_IN))
        out_map = _rows_to_int_map(client.walk(OID_IF_HC_OUT))
        if in_map and out_map:
            return in_map, out_map
    except Exception:
        pass
    return _rows_to_int_map(client.walk(OID_IF_IN)), _rows_to_int_map(client.walk(OID_IF_OUT))


def collect_device_metrics(db: Session, device: Device) -> None:
    if not device.snmp_enabled:
        return

    client = SnmpClient(device)
    now = datetime.utcnow()

    try:
        sys_data = client.get_multi(
            [OID_SYS_DESCR, OID_SYS_NAME, OID_SYS_UPTIME, OID_SYS_LOCATION, OID_SYS_CONTACT]
        )
        device.snmp_sys_descr = sys_data.get(OID_SYS_DESCR, device.snmp_sys_descr)
        device.snmp_sys_name = sys_data.get(OID_SYS_NAME, device.snmp_sys_name)
        device.snmp_sys_uptime = sys_data.get(OID_SYS_UPTIME, device.snmp_sys_uptime)
        device.snmp_sys_location = sys_data.get(OID_SYS_LOCATION, device.snmp_sys_location)
        device.snmp_sys_contact = sys_data.get(OID_SYS_CONTACT, device.snmp_sys_contact)
    except Exception as exc:
        logger.warning("sysInfo %s: %s", device.name, exc)

    cpu, mem_pct, mem_used, mem_free = _fetch_cpu_memory(client, device.cisco_platform or "generic_ios")
    if cpu is not None:
        device.last_cpu_percent = cpu
    if mem_pct is not None:
        device.last_memory_percent = mem_pct
    db.add(
        DeviceMetricSample(
            device_id=device.id,
            recorded_at=now,
            cpu_percent=cpu,
            memory_percent=mem_pct,
            memory_used_kb=mem_used,
            memory_free_kb=mem_free,
        )
    )

    admin = _rows_to_int_map(client.walk(OID_IF_ADMIN))
    oper = _rows_to_int_map(client.walk(OID_IF_OPER))
    in_octets, out_octets = _get_octet_maps(client)

    ports = db.query(DevicePort).filter(DevicePort.device_id == device.id).all()
    if not ports:
        discover_ports(db, device)
        ports = db.query(DevicePort).filter(DevicePort.device_id == device.id).all()

    prev_samples: dict[int, PortTrafficSample] = {}
    cutoff = now - timedelta(seconds=max(device.snmp_poll_interval * 3, 120))
    for s in (
        db.query(PortTrafficSample)
        .filter(
            PortTrafficSample.device_id == device.id,
            PortTrafficSample.recorded_at >= cutoff,
        )
        .order_by(PortTrafficSample.recorded_at.desc())
        .all()
    ):
        if s.if_index not in prev_samples:
            prev_samples[s.if_index] = s

    history: dict[int, list[PortTrafficSample]] = defaultdict(list)
    for s in (
        db.query(PortTrafficSample)
        .filter(PortTrafficSample.device_id == device.id)
        .order_by(PortTrafficSample.recorded_at.desc())
        .limit(500)
        .all()
    ):
        if len(history[s.if_index]) < 5:
            history[s.if_index].append(s)

    for port in ports:
        idx = port.if_index
        a = admin.get(idx, port.admin_status)
        o = oper.get(idx, port.oper_status)
        port.admin_status = a
        port.oper_status = o
        port.is_shutdown = _admin_shutdown(a, o)
        port.updated_at = now

        curr_in = in_octets.get(idx)
        curr_out = out_octets.get(idx)
        if curr_in is None or curr_out is None:
            continue

        prev = prev_samples.get(idx)
        in_bps = out_bps = 0.0
        if prev:
            dt = (now - prev.recorded_at).total_seconds()
            if dt > 0:
                in_bps = _counter_delta(prev.in_octets, curr_in) * 8 / dt
                out_bps = _counter_delta(prev.out_octets, curr_out) * 8 / dt

        hist = history.get(idx, [])
        in_avg = sum(h.in_bps for h in hist) / len(hist) if hist else in_bps
        out_avg = sum(h.out_bps for h in hist) / len(hist) if hist else out_bps

        port.last_in_bps = in_bps
        port.last_out_bps = out_bps
        port.last_in_avg_bps = in_avg
        port.last_out_avg_bps = out_avg

        db.add(
            PortTrafficSample(
                device_id=device.id,
                if_index=idx,
                recorded_at=now,
                in_octets=curr_in,
                out_octets=curr_out,
                in_bps=in_bps,
                out_bps=out_bps,
                in_avg_bps=in_avg,
                out_avg_bps=out_avg,
            )
        )

    device.snmp_last_polled = now
    device.snmp_last_status = "success"
    device.snmp_last_error = ""
    db.commit()


def prune_old_samples(db: Session) -> None:
    days = settings.metrics_retention_days
    cutoff = datetime.utcnow() - timedelta(days=days)
    db.execute(delete(PortTrafficSample).where(PortTrafficSample.recorded_at < cutoff))
    db.execute(delete(DeviceMetricSample).where(DeviceMetricSample.recorded_at < cutoff))
    db.commit()


def poll_all_monitored_devices(db: Session) -> int:
    devices = (
        db.query(Device)
        .filter(
            Device.enabled.is_(True),
            Device.snmp_enabled.is_(True),
            Device.snmp_monitor_enabled.is_(True),
        )
        .all()
    )
    n = 0
    for device in devices:
        try:
            collect_device_metrics(db, device)
            n += 1
        except Exception as exc:
            logger.exception("SNMP collect failed %s: %s", device.name, exc)
            device.snmp_last_status = "failed"
            device.snmp_last_error = str(exc)[:1000]
            device.snmp_last_polled = datetime.utcnow()
            db.commit()
    if n:
        prune_old_samples(db)
    return n