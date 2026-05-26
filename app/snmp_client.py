"""SNMP GET/WALK — net-snmp(snmpwalk) 우선, 없으면 pysnmp"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from dataclasses import dataclass

from app.config import settings
from app.models import Device

OID_IF_DESCR = "1.3.6.1.2.1.1.2.1.2.1.2"
OID_IF_TYPE = "1.3.6.1.2.1.2.1.3.1.2"
OID_IF_SPEED = "1.3.6.1.2.1.2.1.5.1.2"
OID_IF_ADMIN = "1.3.6.1.2.1.2.1.7.1.2"
OID_IF_OPER = "1.3.6.1.2.1.2.1.8.1.2"
OID_IF_IN = "1.3.6.1.2.1.2.1.10.1.2"
OID_IF_OUT = "1.3.6.1.2.1.2.1.16.1.2"
OID_IF_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"
OID_IF_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"
OID_IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
OID_SYS_CONTACT = "1.3.6.1.2.1.1.4.0"

# Cisco IOS / Catalyst / ISR (구형 포함)
OID_CISCO_CPU_5MIN = "1.3.6.1.4.1.9.9.109.1.1.1.1.5"
OID_CISCO_MEM_USED = "1.3.6.1.4.1.9.9.48.1.1.1.5"
OID_CISCO_MEM_FREE = "1.3.6.1.4.1.9.9.48.1.1.1.6"
# ASA 등
OID_ASA_CPU = "1.3.6.1.4.1.9.9.109.1.1.1.1.5"


@dataclass
class SnmpWalkRow:
    index: int
    value: str


def _parse_index_from_oid(oid: str) -> int:
    m = re.search(r"\.(\d+)\s*$", oid.strip())
    if m:
        return int(m.group(1))
    parts = oid.rstrip(".").split(".")
    return int(parts[-1])


def _parse_walk_line(line: str) -> SnmpWalkRow | None:
    line = line.strip()
    if not line or "Timeout" in line or "No Such" in line:
        return None
    if "=" not in line:
        return None
    left, _, right = line.partition("=")
    oid_part = left.strip()
    val = right.strip()
    for prefix in ("STRING:", "INTEGER:", "Counter32:", "Counter64:", "Gauge32:", "Hex-STRING:"):
        if val.startswith(prefix):
            val = val[len(prefix) :].strip().strip('"')
            break
    val = val.strip('"')
    try:
        idx = _parse_index_from_oid(oid_part)
    except (ValueError, IndexError):
        return None
    return SnmpWalkRow(index=idx, value=val)


class SnmpClient:
    def __init__(self, device: Device):
        self.device = device
        self.host = device.host
        self.port = device.snmp_port
        self.community = device.snmp_community or "public"
        self.version = (device.snmp_version or "2c").lower().replace("v", "")
        self.timeout = settings.snmp_timeout

    def _has_snmp_tools(self) -> bool:
        return shutil.which("snmpwalk") is not None

    def _snmp_base_cmd(self, tool: str) -> list[str]:
        v = "2c" if self.version in ("2c", "2") else self.version
        cmd = [tool, f"-v{v}", "-c", self.community, "-t", str(self.timeout), "-r", str(settings.snmp_retries)]
        if self.port != 161:
            cmd.extend(["-p", str(self.port)])
        return cmd

    def walk(self, oid: str) -> list[SnmpWalkRow]:
        if self._has_snmp_tools():
            return self._walk_subprocess(oid)
        return self._walk_pysnmp(oid)

    def get_multi(self, oids: list[str]) -> dict[str, str]:
        if self._has_snmp_tools():
            return self._get_subprocess(oids)
        return self._get_pysnmp(oids)

    def _walk_subprocess(self, oid: str) -> list[SnmpWalkRow]:
        target = f"{self.host}:{self.port}" if self.port != 161 else self.host
        cmd = self._snmp_base_cmd("snmpwalk") + [target, oid]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 30)
        rows: list[SnmpWalkRow] = []
        for line in (proc.stdout or "").splitlines():
            row = _parse_walk_line(line)
            if row:
                rows.append(row)
        if proc.returncode != 0 and not rows:
            err = (proc.stderr or proc.stdout or "snmpwalk 실패").strip()
            raise RuntimeError(err[:500])
        return rows

    def _get_subprocess(self, oids: list[str]) -> dict[str, str]:
        target = f"{self.host}:{self.port}" if self.port != 161 else self.host
        result: dict[str, str] = {}
        for oid in oids:
            cmd = self._snmp_base_cmd("snmpget") + [target, oid]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 5)
            for line in (proc.stdout or "").splitlines():
                row = _parse_walk_line(line.replace(" = ", " = ", 1) if "=" in line else line)
                if row:
                    result[oid] = row.value
                    break
            if oid not in result and proc.stdout:
                parts = proc.stdout.split("=", 1)
                if len(parts) == 2:
                    result[oid] = parts[1].strip().split(":", 1)[-1].strip().strip('"')
        return result

    def _walk_pysnmp(self, oid: str) -> list[SnmpWalkRow]:
        return asyncio.run(self._walk_pysnmp_async(oid))

    def _get_pysnmp(self, oids: list[str]) -> dict[str, str]:
        return asyncio.run(self._get_pysnmp_async(oids))

    async def _walk_pysnmp_async(self, oid: str) -> list[SnmpWalkRow]:
        from pysnmp.hlapi.v3arch.asyncio import (
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            next_cmd,
        )

        mp = 0 if self.version == "1" else 1
        auth = CommunityData(self.community, mpModel=mp)
        transport = await UdpTransportTarget.create(
            (self.host, self.port),
            timeout=self.timeout,
            retries=settings.snmp_retries,
        )
        engine = SnmpEngine()
        rows: list[SnmpWalkRow] = []
        var = ObjectType(ObjectIdentity(oid))
        while True:
            err, status, _, binds = await next_cmd(
                engine, auth, transport, ContextData(), var
            )
            if err or status:
                break
            if not binds:
                break
            for b in binds:
                oid_str = str(b[0])
                val = str(b[1])
                idx = _parse_index_from_oid(oid_str)
                rows.append(SnmpWalkRow(index=idx, value=val))
                var = ObjectType(ObjectIdentity(oid_str))
        return rows

    async def _get_pysnmp_async(self, oids: list[str]) -> dict[str, str]:
        from pysnmp.hlapi.v3arch.asyncio import (
            CommunityData,
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            get_cmd,
        )

        mp = 0 if self.version == "1" else 1
        auth = CommunityData(self.community, mpModel=mp)
        transport = await UdpTransportTarget.create(
            (self.host, self.port),
            timeout=self.timeout,
            retries=settings.snmp_retries,
        )
        engine = SnmpEngine()
        obj_types = [ObjectType(ObjectIdentity(o)) for o in oids]
        err, status, _, binds = await get_cmd(
            engine, auth, transport, ContextData(), *obj_types
        )
        if err:
            raise RuntimeError(str(err))
        if status:
            raise RuntimeError(str(status))
        out: dict[str, str] = {}
        for oid, bind in zip(oids, binds):
            out[oid] = str(bind[1])
        return out