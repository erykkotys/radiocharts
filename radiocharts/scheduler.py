from __future__ import annotations
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from radiocharts.collector import collect_current
from radiocharts.config import load_config
from radiocharts.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("radiocharts")


def job():
    try:
        for msg in collect_current(): log.info(msg)
    except Exception:
        log.exception("Błąd collectora")


def main():
    init_db()
    cfg = load_config()
    s = cfg.get("schedule", {})
    tz = cfg.get("timezone", "Europe/Warsaw")
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(job, CronTrigger(hour=int(s.get("hour",23)), minute=int(s.get("minute",30)), timezone=tz), max_instances=1, coalesce=True)
    log.info("Scheduler wystartował: codziennie %02d:%02d %s", int(s.get("hour",23)), int(s.get("minute",30)), tz)
    scheduler.start()

if __name__ == "__main__": main()
