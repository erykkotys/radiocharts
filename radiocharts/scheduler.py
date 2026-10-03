from __future__ import annotations
import logging
from datetime import date, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from radiocharts.collector import collect_current
from radiocharts.airplay import collect_latest_window
from radiocharts.config import load_config
from radiocharts.db import init_db
from radiocharts.local_station import sync_zetta2go_live, sync_zetta2go_schedule_horizon
from radiocharts.zetta2go import settings as zetta2go_settings

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




def zetta_live_job(service_date: date | None = None):
    try:
        cfg = zetta2go_settings()
        if not cfg.configured or not cfg.live_enabled:
            return
        result = sync_zetta2go_live(service_date)
        log.info(
            "Zetta2GO live %s: rows=%s played=%s not_played=%s upcoming=%s%s",
            result.get("date_from", service_date or date.today()), result.get("rows", 0),
            result.get("played_rows", 0), result.get("nonplayed_rows", 0), result.get("upcoming_rows", 0),
            " unchanged" if result.get("unchanged") else "",
        )
    except Exception:
        log.exception("Błąd Zetta2GO live")


def zetta_finalize_previous_day_job():
    # 00:03 catches events that finished in the last minute before midnight.
    zetta_live_job(date.today() - timedelta(days=1))


def zetta_schedule_job(mark_cutoff: bool = True):
    try:
        cfg = zetta2go_settings()
        if not cfg.configured or not cfg.schedule_enabled:
            return
        result = sync_zetta2go_schedule_horizon(
            horizon_days=cfg.schedule_horizon_days, mark_cutoff=mark_cutoff
        )
        changed = sum(1 for x in result.get("days", []) if not x.get("duplicate"))
        log.info(
            "Zetta2GO scheduled: %s dni, cutoff=%s, zmienione=%s",
            len(result.get("days", [])), result.get("cutoff_date") or "forecast", changed,
        )
    except Exception:
        log.exception("Błąd Zetta2GO scheduled")


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

    # Always register Zetta2GO jobs.  Each execution reads the latest settings
    # from the shared DB and exits cheaply when disabled/unconfigured.  This is
    # important now that credentials can be entered from the web Settings page:
    # the worker starts using them on the next minute without a container restart.
    zcfg = zetta2go_settings()
    scheduler.add_job(
        zetta_live_job,
        CronTrigger(minute="*", second=5, timezone=tz),
        max_instances=1, coalesce=True, misfire_grace_time=45,
    )
    scheduler.add_job(
        zetta_finalize_previous_day_job,
        CronTrigger(hour=0, minute=3, second=20, timezone=tz),
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        zetta_schedule_job,
        CronTrigger(hour=23, minute=59, second=20, timezone=tz),
        max_instances=1, coalesce=True,
    )

    log.info("Scheduler wystartował: codziennie %s:%02d %s", ",".join(f"{h:02d}" for h in hours), minute, tz)
    log.info("Scheduler emisji: co 2h o :12 uzupełnia brakujące zakończone bloki 2h z ostatnich 24h")
    if zcfg.configured:
        log.info(
            "Zetta2GO: live=%s co 1 min; scheduled=%s codziennie 23:59; horyzont=%s dni",
            zcfg.live_enabled, zcfg.schedule_enabled, zcfg.schedule_horizon_days,
        )
        # Prime data immediately after deploy/restart. Today's Scheduled is never
        # touched; only live Played + future schedules are refreshed.
        if zcfg.live_enabled:
            zetta_live_job()
        if zcfg.schedule_enabled:
            zetta_schedule_job(mark_cutoff=False)
    else:
        log.info("Zetta2GO: brak konfiguracji login/hasło — synchronizacja wyłączona")
    scheduler.start()


if __name__ == "__main__":
    main()
