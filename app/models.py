import enum
from datetime import datetime

from sqlalchemy import (
    String,
    Text,
    DateTime,
    Boolean,
    Integer,
    BigInteger,
    Float,
    Enum as SAEnum,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DeviceType(str, enum.Enum):
    linux = "linux"
    network = "network"


class CiscoPlatform(str, enum.Enum):
    generic_ios = "generic_ios"
    catalyst_2960 = "catalyst_2960"
    catalyst_3560 = "catalyst_3560"
    cisco_2821 = "cisco_2821"
    asa_5512 = "asa_5512"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class JobType(str, enum.Enum):
    connectivity = "connectivity"
    ping = "ping"
    command = "command"
    snmp = "snmp"
    snmp_monitor = "snmp_monitor"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(default=22)
    username: Mapped[str] = mapped_column(String(128))
    password: Mapped[str] = mapped_column(String(512), default="")
    device_type: Mapped[DeviceType] = mapped_column(SAEnum(DeviceType), default=DeviceType.linux)
    network_os: Mapped[str] = mapped_column(String(32), default="ios")
    cisco_platform: Mapped[str] = mapped_column(String(32), default="catalyst_2960")
    groups: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    snmp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    snmp_monitor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    snmp_poll_interval: Mapped[int] = mapped_column(Integer, default=30)
    snmp_version: Mapped[str] = mapped_column(String(8), default="2c")
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    snmp_community: Mapped[str] = mapped_column(String(128), default="public")
    snmp_v3_user: Mapped[str] = mapped_column(String(128), default="")
    snmp_v3_auth_key: Mapped[str] = mapped_column(String(256), default="")
    snmp_v3_priv_key: Mapped[str] = mapped_column(String(256), default="")

    snmp_sys_name: Mapped[str] = mapped_column(String(255), default="")
    snmp_sys_descr: Mapped[str] = mapped_column(Text, default="")
    snmp_sys_location: Mapped[str] = mapped_column(String(512), default="")
    snmp_sys_contact: Mapped[str] = mapped_column(String(512), default="")
    snmp_sys_uptime: Mapped[str] = mapped_column(String(64), default="")
    snmp_last_status: Mapped[str] = mapped_column(String(32), default="")
    snmp_last_polled: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    snmp_last_error: Mapped[str] = mapped_column(Text, default="")

    last_cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_memory_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    jobs: Mapped[list["Job"]] = relationship(back_populates="device")
    ports: Mapped[list["DevicePort"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class DevicePort(Base):
    """장비 인터페이스(포트) 스냅샷 — SNMP IF-MIB 기준"""

    __tablename__ = "device_ports"
    __table_args__ = (UniqueConstraint("device_id", "if_index", name="uq_device_if_index"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    if_index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    alias: Mapped[str] = mapped_column(String(128), default="")
    speed_bps: Mapped[int] = mapped_column(BigInteger, default=0)
    if_type: Mapped[int] = mapped_column(Integer, default=0)
    admin_status: Mapped[int] = mapped_column(Integer, default=0)
    oper_status: Mapped[int] = mapped_column(Integer, default=0)
    is_shutdown: Mapped[bool] = mapped_column(Boolean, default=False)
    last_in_bps: Mapped[float] = mapped_column(Float, default=0.0)
    last_out_bps: Mapped[float] = mapped_column(Float, default=0.0)
    last_in_avg_bps: Mapped[float] = mapped_column(Float, default=0.0)
    last_out_avg_bps: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device: Mapped["Device"] = relationship(back_populates="ports")


class PortTrafficSample(Base):
    __tablename__ = "port_traffic_samples"
    __table_args__ = (
        Index("ix_traffic_device_port_time", "device_id", "if_index", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    if_index: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    in_octets: Mapped[int] = mapped_column(BigInteger, default=0)
    out_octets: Mapped[int] = mapped_column(BigInteger, default=0)
    in_bps: Mapped[float] = mapped_column(Float, default=0.0)
    out_bps: Mapped[float] = mapped_column(Float, default=0.0)
    in_avg_bps: Mapped[float] = mapped_column(Float, default=0.0)
    out_avg_bps: Mapped[float] = mapped_column(Float, default=0.0)


class DeviceMetricSample(Base):
    __tablename__ = "device_metric_samples"
    __table_args__ = (Index("ix_metric_device_time", "device_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_used_kb: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    memory_free_kb: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_type: Mapped[JobType] = mapped_column(SAEnum(JobType))
    status: Mapped[JobStatus] = mapped_column(SAEnum(JobStatus), default=JobStatus.pending)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    target_hosts: Mapped[str] = mapped_column(String(512), default="")
    command: Mapped[str] = mapped_column(Text, default="")
    result_stdout: Mapped[str] = mapped_column(Text, default="")
    result_stderr: Mapped[str] = mapped_column(Text, default="")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device: Mapped["Device | None"] = relationship(back_populates="jobs")
