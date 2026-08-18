from __future__ import annotations
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from radiocharts.collector import collect_current
from radiocharts.config import load_config
from radiocharts.db import init_db
from radiocharts.airplay import collect_airplay_recent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("radiocharts")


def job():
    try:
        for msg in collect_current(attempts_per_source=3, retry_delay=6.0):
            log.info(msg)
    except Exception:
        log.exception("Błąd collectora")


def airplay_job():
    try:
        result = collect_airplay_recent(request_delay=0.20)
        log.info("Emisje odSluchane: ok=%s failed=%s new=%s", result["ok"], result["failed"], result["inserted"])
    except Exception:
        log.exception("Błąd collectora Emisji")


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
    # odSluchane exposes a rolling playlist. Poll every two hours with a
    # deliberately overlapping 3-hour window; DB uniqueness removes duplicates.
    scheduler.add_job(
        airplay_job,
        CronTrigger(hour="1,3,5,7,9,11,13,15,17,19,21,23", minute=20, timezone=tz),
        max_instances=1,
        coalesce=True,
    )
    log.info("Scheduler wystartował: listy %s:%02d; Emisje co 2h o :20; %s", ",".join(f"{h:02d}" for h in hours), minute, tz)
    scheduler.start()


if __name__ == "__main__":
    main()
