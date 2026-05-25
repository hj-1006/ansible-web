"""Ansible 인벤토리 생성 및 playbook 실행"""

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Device, DeviceType, Job, JobStatus, JobType


def _device_host_vars(device: Device) -> dict[str, Any]:
    vars_: dict[str, Any] = {
        "ansible_host": device.host,
        "ansible_port": device.port,
        "ansible_user": device.username,
        "ansible_connection": "ssh",
        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
    }
    if device.password:
        vars_["ansible_password"] = device.password
        vars_["ansible_ssh_pass"] = device.password

    if device.device_type == DeviceType.network:
        vars_["ansible_connection"] = "ansible.netcommon.network_cli"
        vars_["ansible_network_os"] = _map_network_os(device.network_os)
        if device.password:
            vars_["ansible_password"] = device.password

    return vars_


def _map_network_os(network_os: str) -> str:
    mapping = {
        "ios": "cisco.ios.ios",
        "junos": "junipernetworks.junos.junos",
        "eos": "arista.eos.eos",
        "nxos": "cisco.nxos.nxos",
        "vyos": "vyos.vyos.vyos",
        "generic": "ansible.netcommon.network_cli",
    }
    return mapping.get(network_os.lower(), "ansible.netcommon.network_cli")


def build_inventory(devices: list[Device]) -> Path:
    """동적 인벤토리 YAML 파일 생성"""
    settings.inventory_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = settings.inventory_dir / "dynamic_inventory.yml"

    hosts: dict[str, dict] = {}
    linux_group: list[str] = []
    network_group: list[str] = []

    for device in devices:
        if not device.enabled:
            continue
        hosts[device.name] = _device_host_vars(device)
        if device.device_type == DeviceType.network:
            network_group.append(device.name)
        else:
            linux_group.append(device.name)

    inv: dict = {"all": {"hosts": hosts}}
    if linux_group or network_group:
        inv["all"]["children"] = {}
        if linux_group:
            inv["all"]["children"]["linux_hosts"] = {"hosts": {h: None for h in linux_group}}
        if network_group:
            inv["all"]["children"]["network_hosts"] = {"hosts": {h: None for h in network_group}}

    with open(inventory_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(inv, f, default_flow_style=False, allow_unicode=True)

    return inventory_path


def _run_ansible_playbook(
    playbook: str,
    limit: str | None = None,
    extra_vars: dict | None = None,
) -> tuple[int, str, str]:
    inventory = settings.inventory_dir / "dynamic_inventory.yml"
    if not inventory.exists():
        return 1, "", "인벤토리 파일이 없습니다. 장비를 먼저 등록하세요."

    cmd = [
        "ansible-playbook",
        str(settings.playbook_dir / playbook),
        "-i",
        str(inventory),
    ]
    if limit:
        cmd.extend(["--limit", limit])
    if extra_vars:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            json.dump(extra_vars, tf)
            extra_file = tf.name
        cmd.extend(["-e", f"@{extra_file}"])

    env = {"ANSIBLE_HOST_KEY_CHECKING": "False", "ANSIBLE_STDOUT_CALLBACK": "json"}
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.ansible_timeout,
            cwd=str(settings.ansible_dir),
            env={**subprocess.os.environ.copy(), **env},
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"Ansible 실행 시간 초과 ({settings.ansible_timeout}초)"
    except FileNotFoundError:
        return 1, "", "ansible-playbook 명령을 찾을 수 없습니다. ansible-core를 설치하세요."


def _run_ansible_adhoc(
    module: str,
    args: str,
    limit: str,
) -> tuple[int, str, str]:
    inventory = settings.inventory_dir / "dynamic_inventory.yml"
    cmd = [
        "ansible",
        limit,
        "-i",
        str(inventory),
        "-m",
        module,
        "-a",
        args,
    ]
    env = {"ANSIBLE_HOST_KEY_CHECKING": "False"}
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.ansible_timeout,
            cwd=str(settings.ansible_dir),
            env={**subprocess.os.environ.copy(), **env},
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Ansible ad-hoc 시간 초과"
    except FileNotFoundError:
        return 1, "", "ansible 명령을 찾을 수 없습니다."


def sync_inventory(db: Session) -> Path:
    devices = db.query(Device).filter(Device.enabled.is_(True)).all()
    return build_inventory(devices)


def run_connectivity_test(
    db: Session,
    device: Device,
    ping_target: str | None = None,
) -> Job:
    sync_inventory(db)
    job = Job(
        job_type=JobType.connectivity,
        status=JobStatus.running,
        device_id=device.id,
        target_hosts=device.name,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    extra = {"ping_target": ping_target or "8.8.8.8"}
    if device.device_type == DeviceType.network:
        playbook = "network_connectivity.yml"
    else:
        playbook = "linux_connectivity.yml"

    code, stdout, stderr = _run_ansible_playbook(playbook, limit=device.name, extra_vars=extra)

    job.status = JobStatus.success if code == 0 else JobStatus.failed
    job.result_stdout = stdout
    job.result_stderr = stderr
    job.error_message = stderr if code != 0 else ""
    job.completed_at = datetime.utcnow()
    job.result_json = json.dumps(
        {"return_code": code, "ping_target": extra["ping_target"]},
        ensure_ascii=False,
    )
    db.commit()
    db.refresh(job)

    if device.snmp_enabled and job.status == JobStatus.success:
        try:
            from app import snmp_service
            from app.snmp_collector import collect_device_metrics, discover_ports

            snmp_service.run_snmp_poll(db, device, connectivity_ok=True)
            if device.snmp_monitor_enabled:
                discover_ports(db, device)
                collect_device_metrics(db, device)
        except Exception:
            pass

    return job


def run_command(db: Session, device: Device, command: str, become: bool = False) -> Job:
    sync_inventory(db)
    job = Job(
        job_type=JobType.command,
        status=JobStatus.running,
        device_id=device.id,
        target_hosts=device.name,
        command=command,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if device.device_type == DeviceType.network:
        code, stdout, stderr = _run_ansible_playbook(
            "network_command.yml",
            limit=device.name,
            extra_vars={"cli_command": command},
        )
    else:
        args = command.replace('"', '\\"')
        if become:
            code, stdout, stderr = _run_ansible_adhoc(
                "shell", f'"{args}"', device.name
            )
            # become은 playbook 사용 권장
            if code != 0:
                code, stdout, stderr = _run_ansible_playbook(
                    "linux_command.yml",
                    limit=device.name,
                    extra_vars={"run_command": command, "use_become": become},
                )
        else:
            code, stdout, stderr = _run_ansible_playbook(
                "linux_command.yml",
                limit=device.name,
                extra_vars={"run_command": command, "use_become": become},
            )

    job.status = JobStatus.success if code == 0 else JobStatus.failed
    job.result_stdout = stdout
    job.result_stderr = stderr
    job.error_message = stderr if code != 0 else ""
    job.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    return job
