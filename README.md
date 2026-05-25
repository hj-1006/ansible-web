# Ansible Web - 네트워크 장비 제어 플랫폼

Python(FastAPI) + SNMP 모니터링으로 Cisco 레거시 장비(2960, 3560, 2821, ASA5512 등)의 **포트 트래픽·CPU·RAM**을 수집하고 실시간 그래프로 확인합니다.

## 요구 사항

- Python 3.10+
- `ansible-core`
- SNMP: `snmpwalk` / `snmpget` (net-snmp, 권장) 또는 `pysnmp-lextudio`
- MySQL (권장, 원격 DB 서버 가능) 또는 SQLite

```bash
# Ubuntu/Debian
sudo apt install snmp snmp-mibs-downloader
pip install -r requirements.txt
ansible-galaxy collection install cisco.ios ansible.netcommon
```

## 설정 (.env)

```bash
cp .env.example .env
# MySQL 계정은 반드시 .env에 입력 (원격 DB 호스트는 ANSIBLE_WEB_DB_HOST)
```

| 변수 | 설명 |
|------|------|
| `ANSIBLE_WEB_DB_HOST` | DB 서버 IP/호스트 (앱과 분리 가능) |
| `ANSIBLE_WEB_DB_USER` / `PASSWORD` / `NAME` | MySQL 계정 |
| `ANSIBLE_WEB_SNMP_POLL_INTERVAL_DEFAULT` | 백그라운드 수집 주기(초) |

`ANSIBLE_WEB_DB_USER`가 비어 있으면 SQLite를 사용합니다.

## 실행

```bash
python run.py
# http://localhost:8080
```

## Cisco 장비 SNMP

장비 등록 시:

1. **SNMP 사용** · **실시간 트래픽 수집** 체크
2. **Community** (예: `public` 또는 운영 community)
3. **Cisco 모델** 선택 (CPU MIB 경로)

장비 목록 → **모니터** 클릭:

- 포트별 Up/Down/**Shutdown** 상태
- In/Out bps 및 **평균 트래픽**
- 포트 클릭 → 실시간 트래픽 차트 (10초 갱신)
- CPU / Memory 그래프 (지원 시)

### 지원 모델

| 모델 | `cisco_platform` |
|------|------------------|
| Catalyst 2960 | `catalyst_2960` |
| Catalyst 3560 | `catalyst_3560` |
| Cisco 2821 | `cisco_2821` |
| ASA 5512 | `asa_5512` |

구형 IOS는 IF-MIB(32bit 카운터)로 트래픽을 계산합니다. Gigabit 이상 포트는 HC-MIB가 있으면 자동 사용합니다.

## API (모니터링)

| 메서드 | 경로 |
|--------|------|
| GET | `/api/v1/devices/{id}/monitor/overview` |
| GET | `/api/v1/devices/{id}/monitor/ports/{if_index}/traffic?minutes=60` |
| POST | `/api/v1/devices/{id}/monitor/discover` |
| POST | `/api/v1/devices/{id}/monitor/poll` |

모든 API는 `X-API-Key` 헤더 필요.

## 프로젝트 구조

```
ansible-web/
├── app/
│   ├── snmp_client.py      # SNMP GET/WALK
│   ├── snmp_collector.py   # 트래픽·CPU·RAM 수집
│   └── routers/monitoring.py
├── static/js/monitor.js    # 실시간 차트 GUI
└── data/                   # SQLite 시
```
