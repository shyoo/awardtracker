from apscheduler.schedulers.background import BackgroundScheduler
import os
from datetime import datetime, timedelta

from applog import app_log
from config import write_dir, get_active_db_path
from services.settings_store import get_setting, set_setting as _set_setting


def set_setting(db, key, value):
    """Kept for callers that still pass the db handle; the store commits itself."""
    _set_setting(key, value)


scheduler = BackgroundScheduler()


def sync_all_accounts(is_scheduled=True):
    """
    Sync every automated account sequentially.
    Runs outside the request context, so we set up an app context ourselves.
    Progress is written to Settings so the UI can poll it and the user can cancel.
    """
    app_log.info("Starting sync for all accounts...")

    # Imported here to avoid a circular import at module load.
    from app import create_app
    from extensions import db
    from models import Account
    from security import security_manager
    from plugins.context import RunTrigger
    from services import sync_service

    app = create_app()
    with app.app_context():
        set_setting(db, 'scheduled_sync_status', 'running')

        if not security_manager.is_initialized():
            app_log.warning("Security manager not initialized (app locked). Cannot run scheduled sync.")
            set_setting(db, 'scheduled_sync_status', 'idle')
            return

        accounts = Account.query.filter_by(is_manual=False).all()
        total_count = len(accounts)
        set_setting(db, 'scheduled_sync_total_count', str(total_count))
        set_setting(db, 'scheduled_sync_current_index', '0')
        set_setting(db, 'scheduled_sync_current_account', '')

        for idx, account in enumerate(accounts):
            if get_setting('scheduled_sync_status', 'idle') != 'running':
                app_log.info("Scheduled sync canceled or stopped by user.")
                break

            set_setting(db, 'scheduled_sync_current_index', str(idx + 1))
            set_setting(db, 'scheduled_sync_current_account', account.display_name)

            if account.interactive_login_required:
                app_log.info(f"Skipping account {idx+1}/{total_count}: {account.display_name} because it requires Interactive Login.")
                continue

            app_log.info(f"Syncing account {idx+1}/{total_count}: {account.display_name}")
            outcome = sync_service.sync_account(account, trigger=RunTrigger.SCHEDULED, notify=False)
            if outcome.ok:
                app_log.info(f"Successfully synced {account.display_name}")

        # Reset state on finish or cancel
        status = get_setting('scheduled_sync_status', 'idle')
        if status == 'running':
            set_setting(db, 'scheduled_sync_status', 'idle')
            set_setting(db, 'scheduled_sync_last_run', datetime.utcnow().isoformat())
            set_setting(db, 'scheduled_sync_snooze_until', '')
            set_setting(db, 'scheduled_sync_current_account', 'Completed')

            enabled = get_setting('scheduled_sync_enabled', 'false')
            frequency = get_setting('scheduled_sync_frequency', 'never')
            if is_scheduled and enabled == 'true' and frequency != 'never':
                from notifier import send_desktop_notification
                send_desktop_notification("Scheduled Sync Completed", "Automated background synchronization finished successfully!")
        elif status == 'idle':
            set_setting(db, 'scheduled_sync_current_account', 'Canceled')


def backup_database():
    """
    Automated daily database backup. Retention window is configurable via
    the 'db_backup_frequency' setting (never / 3 / 7 / 30 days).
    Backup filename format: awardtracker_backup_YYYYMMDD.db
    """
    from app import create_app
    app = create_app()
    with app.app_context():
        retention_days_str = get_setting('db_backup_frequency', '7')
        if retention_days_str == 'never':
            app_log.info("Database backup skipped (backup disabled in settings).")
            return
        try:
            retention_days = int(retention_days_str)
        except ValueError:
            retention_days = 7

    app_log.info(f"Starting automated daily database backup (retention: {retention_days} days)...")
    import shutil

    db_file = get_active_db_path()
    backup_dir = os.path.join(write_dir, 'backups')
    today_str = datetime.now().strftime('%Y%m%d')
    backup_file = os.path.join(backup_dir, f'awardtracker_backup_{today_str}.db')

    try:
        os.makedirs(backup_dir, exist_ok=True)

        if os.path.exists(backup_file):
            app_log.info(f"Today's backup already exists at {backup_file}. Skipping.")
            return

        if not os.path.exists(db_file):
            app_log.warning("SQLite database file awardtracker.db not found. Skip backup.")
            return

        shutil.copy2(db_file, backup_file)
        app_log.info(f"Database backed up successfully to {backup_file}")

        cutoff = datetime.now() - timedelta(days=retention_days)
        for fname in os.listdir(backup_dir):
            if not fname.startswith('awardtracker_backup_') or not fname.endswith('.db'):
                continue
            fpath = os.path.join(backup_dir, fname)
            try:
                if datetime.fromtimestamp(os.path.getmtime(fpath)) < cutoff:
                    os.remove(fpath)
                    app_log.info(f"Pruned old backup file: {fpath}")
            except Exception as prune_err:
                app_log.warning(f"Could not prune {fpath}: {prune_err}")
    except Exception as e:
        app_log.error(f"Automated database backup failed: {str(e)}")


def check_startup_backup():
    """
    Called once at application startup. If yesterday's backup is missing, runs
    backup_database() so we never lose more than one day of data even if the
    3AM job was missed (e.g. machine was off).
    """
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    yesterday_file = os.path.join(write_dir, 'backups', f'awardtracker_backup_{yesterday_str}.db')
    if not os.path.exists(yesterday_file):
        app_log.info("Startup backup check: yesterday's backup not found. Running backup now.")
        backup_database()
    else:
        app_log.info("Startup backup check: yesterday's backup already present. No action needed.")


_FREQUENCY_INTERVALS = {
    'hourly': timedelta(hours=1),
    'daily': timedelta(days=1),
    'every_3_days': timedelta(days=3),
    'weekly': timedelta(days=7),
    'monthly': timedelta(days=30),
}


def check_scheduled_sync():
    """
    Periodic job (every 15 minutes) that decides whether a scheduled sync is due
    based on user settings, frequency and snooze state.
    """
    from app import create_app
    from extensions import db
    import threading

    app = create_app()
    with app.app_context():
        enabled = get_setting('scheduled_sync_enabled', 'false')
        frequency = get_setting('scheduled_sync_frequency', 'never')
        if enabled != 'true' or frequency == 'never':
            return

        if get_setting('scheduled_sync_status', 'idle') != 'idle':
            return

        snooze_until_str = get_setting('scheduled_sync_snooze_until', '')
        if snooze_until_str:
            try:
                if datetime.utcnow() < datetime.fromisoformat(snooze_until_str):
                    return
            except Exception:
                pass

        last_run_str = get_setting('scheduled_sync_last_run', '')
        if last_run_str:
            try:
                elapsed = datetime.utcnow() - datetime.fromisoformat(last_run_str)
                interval = _FREQUENCY_INTERVALS.get(frequency)
                if interval and elapsed < interval:
                    return
            except Exception:
                pass

        if get_setting('scheduled_sync_consent_required', 'true') == 'true':
            set_setting(db, 'scheduled_sync_status', 'pending_consent')
            app_log.info("Scheduled sync conditions met. Status set to 'pending_consent' (waiting for user approval).")
        else:
            app_log.info("Scheduled sync conditions met. Spawning automatic background sync thread...")
            threading.Thread(target=run_sync_all_in_background, daemon=True).start()


def run_sync_all_in_background():
    """Record the run time, notify, and execute sync-all in the calling (daemon) thread."""
    from app import create_app
    from extensions import db
    from notifier import send_desktop_notification

    app = create_app()
    with app.app_context():
        set_setting(db, 'scheduled_sync_last_run', datetime.utcnow().isoformat())
        send_desktop_notification("Scheduled Sync Started", "Starting automated background synchronization for all accounts...")
        sync_all_accounts()


# Run check dispatcher every 15 minutes
scheduler.add_job(func=check_scheduled_sync, trigger="interval", minutes=15)
# Run database backup every day at 3:00 AM
scheduler.add_job(func=backup_database, trigger="cron", hour=3, minute=0)
