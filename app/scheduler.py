import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.snmp_collector import poll_all_monitored_devices

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _tick():
    db = SessionLocal()
    try:
        count = poll_all_monitored_devices(db)
        if count:
            logger.info("SNMP 모니터링 %d대 수집 완료", count)
    except Exception:
        logger.exception("SNMP 스케줄러 오류")
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _tick,
        "interval",
        seconds=settings.snmp_poll_interval_default,
        id="snmp_monitor",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("SNMP 모니터 스케줄러 시작 (간격 %ds)", settings.snmp_poll_interval_default)


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
