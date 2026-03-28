"""
Samuraizer – Database backup service.
"""

import os
import time
import shutil
import threading

import backend.config as cfg
from backend.logging_setup import logger


def _ensure_backup_dir():
    os.makedirs(cfg.BACKUP_DIR, exist_ok=True)


def make_db_backup(reason: str = "manual", keep: int = 10):
    """Copy the current DB to a timestamped backup file, pruning old backups."""
    try:
        _ensure_backup_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(cfg.BACKUP_DIR, f"samuraizer_{ts}.db")
        shutil.copy2(cfg.DB_PATH, dest)
        logger.info("DB backup saved to %s (%s)", dest, reason)
        backups = sorted(
            [f for f in os.listdir(cfg.BACKUP_DIR) if f.startswith("samuraizer_") and f.endswith(".db")]
        )
        for old in backups[:-keep]:
            try:
                os.remove(os.path.join(cfg.BACKUP_DIR, old))
                logger.info("DB backup pruned: %s", old)
            except Exception as prune_exc:
                logger.warning("Could not prune old backup %s: %s", old, prune_exc)
    except Exception as exc:
        logger.error("DB backup failed (%s): %s", reason, exc)


def start_backup_scheduler(interval_hours: int = 12):
    def loop():
        while True:
            time.sleep(interval_hours * 3600)
            make_db_backup("interval")

    t = threading.Thread(target=loop, daemon=True)
    t.start()
