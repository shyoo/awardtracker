"""One-time startup work: schema, self-healing migrations, provider registration.

``prepare_database(app)`` runs inside ``create_app`` for every process.
``register_providers()`` and ``heal_zero_balance_expirations()`` run once from
the real entry points (main.py tray launcher, ``python app.py`` dev server).
"""
from sqlalchemy import text

from applog import app_log
from extensions import db
from models import Account, Provider, Settings
from plugins.manager import plugin_manager


def _add_column_if_missing(table, column, ddl, probe_sql):
    """Older databases predate Alembic for some columns; add them in place."""
    try:
        db.session.execute(text(probe_sql))
        return
    except Exception:
        db.session.rollback()
    app_log.info(f"Migration: Adding '{column}' column to '{table}' table...")
    try:
        db.session.execute(text(ddl))
        db.session.commit()
        app_log.info(f"Migration: '{column}' column added successfully.")
    except Exception as migrate_err:
        db.session.rollback()
        app_log.error(f"Migration failed: {migrate_err}")


def _reset_stuck_sync_status():
    """A crash mid sync-all would otherwise leave the UI saying 'running' forever."""
    status = Settings.query.filter_by(key='scheduled_sync_status').first()
    if status and status.value in ('running', 'pending_consent'):
        status.value = 'idle'
        current = Settings.query.filter_by(key='scheduled_sync_current_account').first()
        if current:
            current.value = ''
        else:
            db.session.add(Settings(key='scheduled_sync_current_account', value=''))
        db.session.commit()
        app_log.info("Startup self-healing: Reset stuck scheduled sync status to 'idle'.")


def prepare_database(app):
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            app_log.error(f"Database table creation failed (might be locked by another running instance): {e}")
            raise

        _add_column_if_missing('person', 'color',
                               "ALTER TABLE person ADD COLUMN color VARCHAR(7) DEFAULT '#4f46e5'",
                               "SELECT color FROM person LIMIT 1")
        _add_column_if_missing('account', 'is_manual',
                               "ALTER TABLE account ADD COLUMN is_manual BOOLEAN DEFAULT 0",
                               "SELECT is_manual FROM account LIMIT 1")
        try:
            _reset_stuck_sync_status()
        except Exception as e:
            app_log.error(f"Startup self-healing sync status reset failed: {e}")


def register_providers():
    """Ensure every loaded plugin has a Provider row, renaming if the plugin's name changed."""
    for plugin in plugin_manager.get_all_plugins():
        provider = Provider.query.filter_by(plugin_name=plugin.plugin_id).first()
        if not provider:
            db.session.add(Provider(name=plugin.name, plugin_name=plugin.plugin_id))
        elif provider.name != plugin.name:
            provider.name = plugin.name
    db.session.commit()


def heal_zero_balance_expirations():
    """Points that no longer exist cannot expire."""
    try:
        stale = Account.query.filter(Account.balance <= 0, Account.expiration_date != None).all()  # noqa: E711
        if stale:
            for acc in stale:
                acc.expiration_date = None
            db.session.commit()
            app_log.info(f"Self-healing: Cleared expiration dates for {len(stale)} accounts with 0 balance.")
    except Exception as e:
        app_log.error(f"Self-healing zero-balance cleanup failed: {e}")
