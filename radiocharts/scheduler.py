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
        for msg in collect_current():
            log.info(msg)
    except Exception:
        log.exception("Błąd collectora")


def main():
    init_db()
    cfg = load_config()
    s = cfg.get("schedule", {})
    tz = cfg.get("timezone", "Europe/Warsaw")
    hours = s.get("hours")
    if not hours:
        hours = [int(s.get("hour", 23))]
    hours = sorted({int(h) for h in hours})
    minute = int(s.get("minute", 30))
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(
        job,
        CronTrigger(hour=",".join(str(h) for h in hours), minute=minute, timezone=tz),
        max_instances=1,
        coalesce=True,
    )
    log.info("Scheduler wystartował: codziennie %s:%02d %s", ",".join(f"{h:02d}" for h in hours), minute, tz)
    scheduler.start()


if __name__ == "__main__":
    main()
