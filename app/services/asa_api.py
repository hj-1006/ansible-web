"""Cisco ASA REST API 비동기 게이트웨이 서비스 모듈"""

import httpx
from app.models import Device

class AsaApiClient:
    def __init__(self, device: Device):
        self.base_url = f"https://{device.host}/api"
        # ASA REST API는 기본적으로 HTTPS 기본 인증(Basic Auth) 구조를 따릅니다.
        self.auth = (device.username, device.password)
        
    async def get_interfaces(self) -> list[dict]:
        """ASA 방화벽에 설정된 모든 보안 인터페이스 목록 및 설정 파싱"""
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(
                f"{self.base_url}/interfaces", 
                auth=self.auth, 
                timeout=5.0
            )
            if response.status_code == 200:
                return response.json().get("items", [])
            response.raise_for_status()

    async def execute_show_command(self, cmd: str) -> str:
        """Ansible 대신 ASA 내부 REST API CLI 호출 엔진을 사용하여 직접 런타임 명령 수행"""
        payload = {"cmd": cmd}
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                f"{self.base_url}/commands/show",
                auth=self.auth,
                json=payload,
                timeout=10.0
            )
            if response.status_code == 200:
                return response.json().get("response", [])
            return f"Error: {response.status_code}"