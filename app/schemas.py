from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models import DeviceType, JobStatus, JobType


class DeviceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    host: str
    port: int = 22
    username: str
    password: str = ""
    device_type: DeviceType = DeviceType.network
    network_os: str = "ios"
    cisco_platform: str = "catalyst_2960"
    groups: str = ""
    description: str = ""
    enabled: bool = True
    snmp_enabled: bool = False
    snmp_monitor_enabled: bool = False
    snmp_poll_interval: int = Field(default=30, ge=10, le=300)
    snmp_version: str = "2c"
    snmp_port: int = 161
    snmp_community: str = "public"
    snmp_v3_user: str = ""
    snmp_v3_auth_key: str = ""
    snmp_v3_priv_key: str = ""


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    device_type: Optional[DeviceType] = None
    network_os: Optional[str] = None
    cisco_platform: Optional[str] = None
    groups: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    snmp_enabled: Optional[bool] = None
    snmp_monitor_enabled: Optional[bool] = None
    snmp_poll_interval: Optional[int] = Field(default=None, ge=10, le=300)
    snmp_version: Optional[str] = None
    snmp_port: Optional[int] = None
    snmp_community: Optional[str] = None
    snmp_v3_user: Optional[str] = None
    snmp_v3_auth_key: Optional[str] = None
    snmp_v3_priv_key: Optional[str] = None


class DeviceResponse(BaseModel):
    id: int
    name: str
    host: str
    port: int
    username: str
    device_type: DeviceType
    network_os: str
    cisco_platform: str
    groups: str
    description: str
    enabled: bool
    snmp_enabled: bool
    snmp_monitor_enabled: bool
    snmp_poll_interval: int
    snmp_version: str
    snmp_port: int
    snmp_sys_name: str
    snmp_sys_descr: str
    snmp_sys_location: str
    snmp_last_status: str
    snmp_last_polled: Optional[datetime]
    last_cpu_percent: Optional[float]
    last_memory_percent: Optional[float]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DevicePortResponse(BaseModel):
    id: int
    if_index: int
    name: str
    alias: str
    speed_bps: int
    admin_status: int
    oper_status: int
    is_shutdown: bool
    status: str = ""
    last_in_bps: float
    last_out_bps: float
    last_in_avg_bps: float
    last_out_avg_bps: float
    updated_at: datetime

    model_config = {"from_attributes": True}


class TrafficSamplePoint(BaseModel):
    recorded_at: datetime
    in_bps: float
    out_bps: float
    in_avg_bps: float
    out_avg_bps: float


class PortTrafficHistoryResponse(BaseModel):
    device_id: int
    if_index: int
    port_name: str
    samples: list[TrafficSamplePoint]


class MetricSamplePoint(BaseModel):
    recorded_at: datetime
    cpu_percent: Optional[float]
    memory_percent: Optional[float]


class DeviceMonitorOverview(BaseModel):
    device: DeviceResponse
    ports: list[DevicePortResponse]
    recent_metrics: list[MetricSamplePoint]


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1)
    become: bool = False


class ConnectivityTestRequest(BaseModel):
    device_ids: Optional[list[int]] = None
    ping_target: Optional[str] = None
    fetch_snmp: bool = True


class JobResponse(BaseModel):
    id: int
    job_type: JobType
    status: JobStatus
    device_id: Optional[int]
    target_hosts: str
    command: str
    result_stdout: str
    result_stderr: str
    error_message: str
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class ApiKeyResponse(BaseModel):
    id: int
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyResponse):
    api_key: str
