from __future__ import annotations
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from radiocharts.collector import collect_current
from radiocharts.airplay import collect_latest_window
from radiocharts.config import load_config
from radiocharts.db import init_db

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
        result = collect_latest_window()
        log.info(
            "Emisje odSluchane 24h catch-up: pobrano %s brakujących okien, pominięto %s, błędy %s, zapisano %s emisji",
            result.get("ok", 0), result.get("skipped", 0), result.get("errors", 0), result.get("plays", 0),
        )
    except Exception:
        log.exception("Błąd collectora emisji")


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
    scheduler.add_job(
        airplay_job,
        CronTrigger(hour="0,2,4,6,8,10,12,14,16,18,20,22", minute=12, timezone=tz),
        max_instances=1,
        coalesce=True,
    )
    log.info("Scheduler wystartował: codziennie %s:%02d %s", ",".join(f"{h:02d}" for h in hours), minute, tz)
    log.info("Scheduler emisji: co 2h o :12 uzupełnia brakujące zakończone bloki 2h z ostatnich 24h")
    scheduler.start()


if __name__ == "__main__":
    main()
