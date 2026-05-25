from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Ansible Network Control"
    secret_key: str = "change-me-in-production-use-env"
    # 전체 URL 직접 지정 시 아래 개별 DB 설정보다 우선
    database_url: str = ""
    # MySQL (원격 DB 서버 지원) — .env에서 개별 입력
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_name: str = "ansible_web"
    db_charset: str = "utf8mb4"
    ansible_dir: Path = BASE_DIR / "ansible"
    inventory_dir: Path = BASE_DIR / "ansible" / "inventory"
    playbook_dir: Path = BASE_DIR / "ansible" / "playbooks"
    ansible_timeout: int = 120
    snmp_timeout: int = 10
    snmp_retries: int = 2
    snmp_poll_interval_default: int = 30
    metrics_retention_days: int = 7
    bootstrap_api_key: str = ""

    model_config = {
        "env_file": str(BASE_DIR / ".env"),
        "env_prefix": "ANSIBLE_WEB_",
    }

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.db_user:
            password = quote_plus(self.db_password)
            return (
                f"mysql+pymysql://{self.db_user}:{password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
                f"?charset={self.db_charset}"
            )
        return f"sqlite:///{BASE_DIR / 'data' / 'ansible_web.db'}"

    @property
    def is_mysql(self) -> bool:
        return self.resolved_database_url.startswith("mysql")


settings = Settings()
