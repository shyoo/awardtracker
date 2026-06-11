from apscheduler.schedulers.background import BackgroundScheduler
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from datetime import datetime

# Setup rotating log
from config import write_dir

log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(funcName)s(%(lineno)d) %(message)s')
log_file = os.path.join(write_dir, 'scraper_debug.log')
log_handler = RotatingFileHandler(log_file, mode='a', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8', delay=0)
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)

app_log = logging.getLogger('awardtracker')
app_log.setLevel(logging.INFO)
app_log.addHandler(log_handler)

def get_setting(key, default=''):
    from models import Settings
    setting = Settings.query.filter_by(key=key).first()
    return setting.value if setting else default

def set_setting(db, key, value):
    from models import Settings
    setting = Settings.query.filter_by(key=key).first()
    if setting:
        setting.value = str(value)
    else:
        setting = Settings(key=key, value=str(value))
        db.session.add(setting)
    db.session.commit()

scheduler = BackgroundScheduler()

def sync_all_accounts():
    """
    This function will be called sequentially to sync all accounts.
    It runs outside the request context, so we need to setup an app context.
    Tracks progress dynamically and checks for cancel requests from user.
    """
    app_log.info("Starting sync for all accounts...")
    
    # We must import app here to avoid circular imports
    from app import create_app
    from extensions import db
    from models import Account, AccountHistory, Certificate
    from security import security_manager
    from plugins.manager import plugin_manager
    from plugins.base import safe_call_plugin_method
    
    app = create_app()
    with app.app_context():
        # Set status to running
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
            # Check for cancellation before processing each account
            status = get_setting('scheduled_sync_status', 'idle')
            if status != 'running':
                app_log.info("Scheduled sync canceled or stopped by user.")
                break
                
            set_setting(db, 'scheduled_sync_current_index', str(idx + 1))
            set_setting(db, 'scheduled_sync_current_account', account.display_name)
            
            if account.interactive_login_required:
                app_log.info(f"Skipping account {idx+1}/{total_count}: {account.display_name} because it requires Interactive Login.")
                continue

            app_log.info(f"Syncing account {idx+1}/{total_count}: {account.display_name}")
            
            provider = account.provider
            plugin = plugin_manager.get_plugin(provider.plugin_name)
            
            if not plugin:
                app_log.error(f"Plugin {provider.plugin_name} not found.")
                continue

            try:
                password = security_manager.decrypt(account.password_encrypted)
                profile_dir = os.path.join(write_dir, 'browser_profiles', str(account.id))
                data = safe_call_plugin_method(plugin.fetch_data, account.username, password, profile_dir=profile_dir, **account.extra_metadata)
                
                # Update account
                account.balance = data.get('balance', account.balance)
                account.status = data.get('status', account.status)
                
                # Dynamic expiration calculation
                from expiration import calculate_expiration
                last_activity = data.get('last_activity_date')
                scraped_exp = data.get('expiration_date')
                
                if last_activity:
                    computed_expiration = calculate_expiration(
                        provider.plugin_name,
                        account.balance,
                        account.status,
                        last_activity,
                        account.has_exemption
                    )
                else:
                    computed_expiration = calculate_expiration(
                        provider.plugin_name,
                        account.balance,
                        account.status,
                        scraped_exp if provider.plugin_name == 'korean' else None,
                        account.has_exemption
                    )
                    if provider.plugin_name != 'korean' and scraped_exp:
                        computed_expiration = scraped_exp
                
                if account.has_exemption:
                    computed_expiration = None
                    
                account.expiration_date = computed_expiration
                account.expiration_meta = data.get('expiration_meta', {})
                
                # Spam-filtered warning notifications
                from models import Settings
                warning_threshold_setting = Settings.query.filter_by(key='warning_threshold').first()
                warning_threshold_days = int(warning_threshold_setting.value) if warning_threshold_setting else 30
                
                if computed_expiration:
                    days_left = (computed_expiration - datetime.utcnow()).days
                    if days_left <= warning_threshold_days:
                        if (account.last_notified_expiration is None or 
                                computed_expiration < account.last_notified_expiration):
                            from notifier import send_desktop_notification
                            title = f"Points Expiring Soon: {account.provider.name}"
                            message = f"Your balance of {account.balance:,} points is set to expire on {computed_expiration.strftime('%Y-%m-%d')} ({days_left} days left)!"
                            send_desktop_notification(title, message)
                            account.last_notified_expiration = computed_expiration
                    else:
                        if account.last_notified_expiration and computed_expiration > account.last_notified_expiration:
                            account.last_notified_expiration = None
                else:
                    account.last_notified_expiration = None
                
                account.last_fetch_status = 'SUCCESS'
                account.last_error = None
                account.last_updated = datetime.utcnow()
                
                # Add history
                history = AccountHistory(account_id=account.id, balance=account.balance)
                db.session.add(history)
                
                # Sync certificates/coupons if present in parsed data
                if 'certificates' in data:
                    Certificate.query.filter_by(account_id=account.id).delete()
                    for cert_data in data.get('certificates', []):
                        exp_date_str = cert_data.get('expiration_date')
                        exp_date = None
                        if exp_date_str:
                            try:
                                exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d")
                            except Exception:
                                pass
                        cert = Certificate(
                            account_id=account.id,
                            name=cert_data.get('name'),
                            expiration_date=exp_date,
                            details=cert_data.get('details', {})
                        )
                        db.session.add(cert)
                
                db.session.commit()
                app_log.info(f"Successfully synced {account.display_name}")
            except Exception as e:
                account.last_fetch_status = 'FAILED'
                account.last_error = str(e)
                account.last_updated = datetime.utcnow()
                db.session.commit()
                app_log.error(f"Sync failed for {account.display_name}: {str(e)}")
        
        # Reset state on finish or cancel
        status = get_setting('scheduled_sync_status', 'idle')
        if status == 'running':
            set_setting(db, 'scheduled_sync_status', 'idle')
            set_setting(db, 'scheduled_sync_last_run', datetime.utcnow().isoformat())
            set_setting(db, 'scheduled_sync_snooze_until', '')
            set_setting(db, 'scheduled_sync_current_account', 'Completed')
            from notifier import send_desktop_notification
            send_desktop_notification("Scheduled Sync Completed", "Automated background synchronization finished successfully!")
        elif status == 'idle':
            # This was canceled
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
    from datetime import timedelta

    db_file = os.path.join(write_dir, 'awardtracker.db')
    backup_dir = os.path.join(write_dir, 'backups')
    today_str = datetime.now().strftime('%Y%m%d')
    backup_file = os.path.join(backup_dir, f'awardtracker_backup_{today_str}.db')

    try:
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        # Skip if today's backup already exists
        if os.path.exists(backup_file):
            app_log.info(f"Today's backup already exists at {backup_file}. Skipping.")
            return

        if not os.path.exists(db_file):
            app_log.warning("SQLite database file awardtracker.db not found. Skip backup.")
            return

        shutil.copy2(db_file, backup_file)
        app_log.info(f"Database backed up successfully to {backup_file}")

        # Prune backups older than retention window
        cutoff = datetime.now() - timedelta(days=retention_days)
        for fname in os.listdir(backup_dir):
            if not fname.startswith('awardtracker_backup_') or not fname.endswith('.db'):
                continue
            fpath = os.path.join(backup_dir, fname)
            try:
                fmtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if fmtime < cutoff:
                    os.remove(fpath)
                    app_log.info(f"Pruned old backup file: {fpath}")
            except Exception as prune_err:
                app_log.warning(f"Could not prune {fpath}: {prune_err}")
    except Exception as e:
        app_log.error(f"Automated database backup failed: {str(e)}")

def check_startup_backup():
    """
    Called once at application startup. If yesterday's backup is missing, runs
    backup_database() to ensure we never lose more than one day of data even if
    the 3AM cron was missed (e.g., machine was off).
    """
    from datetime import timedelta
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    backup_dir = os.path.join(write_dir, 'backups')
    yesterday_file = os.path.join(backup_dir, f'awardtracker_backup_{yesterday_str}.db')
    if not os.path.exists(yesterday_file):
        app_log.info("Startup backup check: yesterday's backup not found. Running backup now.")
        backup_database()
    else:
        app_log.info("Startup backup check: yesterday's backup already present. No action needed.")



def check_scheduled_sync():
    """
    Periodic job that runs every 15 minutes to check if a scheduled sync is due
    based on user settings, frequency, and snooze state.
    """
    from app import create_app
    from extensions import db
    import threading
    
    app = create_app()
    with app.app_context():
        # 1. Check if enabled
        enabled = get_setting('scheduled_sync_enabled', 'false')
        frequency = get_setting('scheduled_sync_frequency', 'never')
        if enabled != 'true' or frequency == 'never':
            return
            
        # 2. Check current status (only trigger if idle)
        status = get_setting('scheduled_sync_status', 'idle')
        if status != 'idle':
            return
            
        # 3. Check snooze
        snooze_until_str = get_setting('scheduled_sync_snooze_until', '')
        if snooze_until_str:
            try:
                snooze_until = datetime.fromisoformat(snooze_until_str)
                if datetime.utcnow() < snooze_until:
                    # Still snoozed, skip
                    return
            except Exception:
                pass
                
        # 4. Check frequency & elapsed time since last run
        frequency = get_setting('scheduled_sync_frequency', 'daily')
        last_run_str = get_setting('scheduled_sync_last_run', '')
        
        due = True
        if last_run_str:
            try:
                from datetime import timedelta
                last_run = datetime.fromisoformat(last_run_str)
                elapsed = datetime.utcnow() - last_run
                
                if frequency == 'hourly' and elapsed < timedelta(hours=1):
                    due = False
                elif frequency == 'daily' and elapsed < timedelta(days=1):
                    due = False
                elif frequency == 'every_3_days' and elapsed < timedelta(days=3):
                    due = False
                elif frequency == 'weekly' and elapsed < timedelta(days=7):
                    due = False
                elif frequency == 'monthly' and elapsed < timedelta(days=30):
                    due = False
            except Exception:
                pass
                
        if not due:
            return
            
        # 5. Trigger
        consent_required = get_setting('scheduled_sync_consent_required', 'true')
        if consent_required == 'true':
            set_setting(db, 'scheduled_sync_status', 'pending_consent')
            app_log.info("Scheduled sync conditions met. Status set to 'pending_consent' (waiting for user approval).")
        else:
            app_log.info("Scheduled sync conditions met. Spawning automatic background sync thread...")
            # Automatically spawn sync all in background thread
            t = threading.Thread(target=run_sync_all_in_background, daemon=True)
            t.start()

def run_sync_all_in_background():
    """Wrapper to update last run and execute the sync all sequentially in a daemon thread."""
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
