"""Run a provider plugin against an account and persist whatever it returns.

This is the single implementation behind every way a sync can start -- the
"Sync Now" button (HTML form and JSON API), the Interactive Login button, the
background scheduler and the tray menu -- so expiration, notifications,
membership ID and certificate handling are computed identically on each path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from applog import app_log
from config import write_dir
from extensions import db
from models import Account, AccountHistory, Certificate
from plugins import base as plugin_base
from plugins.context import RunMode, RunTrigger
from plugins.manager import plugin_manager
from security import security_manager
from services.settings_store import get_warning_threshold_days


class SyncError(Exception):
    """A sync could not even be attempted (no plugin, manual account, ...)."""


@dataclass
class SyncOutcome:
    ok: bool
    message: str
    cancelled: bool = False
    expiration: Optional[datetime] = None


@dataclass
class InteractiveOutcome:
    login_ok: bool
    synced: bool
    message: str
    cancelled: bool = False


# --------------------------------------------------------------------------- #
# Running plugins
# --------------------------------------------------------------------------- #

def profile_dir_for(account: Account) -> str:
    """Chrome user-data directory dedicated to this account's sessions."""
    return os.path.join(write_dir, 'browser_profiles', str(account.id))


def get_plugin_for(account: Account):
    plugin = plugin_manager.get_plugin(account.provider.plugin_name)
    if not plugin:
        raise SyncError(f"Plugin {account.provider.plugin_name} not found.")
    return plugin


def run_plugin(account: Account, mode: RunMode, trigger: RunTrigger) -> Any:
    """Decrypt credentials and invoke the plugin's fetch_data / interactive_login.

    Goes through ``plugins.base.safe_call_plugin_method`` (looked up on the
    module so tests can patch it in one place) which filters kwargs to the
    plugin's signature, sets up the run context and debug logging, and waits
    for any previous Chrome process on this profile to exit.
    """
    plugin = get_plugin_for(account)
    method = plugin.interactive_login if mode is RunMode.INTERACTIVE else plugin.fetch_data
    password = security_manager.decrypt(account.password_encrypted)
    return plugin_base.safe_call_plugin_method(
        method,
        account.username,
        password,
        profile_dir=profile_dir_for(account),
        _account_id=account.id,
        _provider_name=account.provider.name,
        _current_balance=account.balance,
        _mode=mode,
        _trigger=trigger,
        **account.extra_metadata,
    )


# --------------------------------------------------------------------------- #
# Persisting results
# --------------------------------------------------------------------------- #

def _compute_expiration(account: Account, data: Dict[str, Any]) -> Optional[datetime]:
    from expiration import calculate_expiration

    plugin_name = account.provider.plugin_name
    last_activity = data.get('last_activity_date')
    scraped_exp = data.get('expiration_date')

    if last_activity:
        computed = calculate_expiration(plugin_name, account.balance, account.status, last_activity, account.has_exemption)
    else:
        # Korean Air's plugin hands back the earliest-expiring batch date as
        # expiration_date and its calculate_expiration() expects it; every other
        # plugin's scraped expiration_date is the answer itself.
        computed = calculate_expiration(
            plugin_name, account.balance, account.status,
            scraped_exp if plugin_name == 'korean' else None, account.has_exemption
        )
        if plugin_name != 'korean' and scraped_exp:
            computed = scraped_exp

    if account.has_exemption:
        computed = None

    if isinstance(computed, str):
        try:
            computed = datetime.fromisoformat(computed.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            computed = None
    return computed


def _notify_if_expiring(account: Account, computed_expiration: Optional[datetime]) -> None:
    """Spam-filtered "points expiring soon" desktop notification."""
    if not computed_expiration:
        account.last_notified_expiration = None
        return

    days_left = (computed_expiration - datetime.utcnow()).days
    if days_left <= get_warning_threshold_days():
        if account.last_notified_expiration is None or computed_expiration < account.last_notified_expiration:
            _notify(
                f"Points Expiring Soon: {account.provider.name}",
                f"Your balance of {account.balance:,} points is set to expire on "
                f"{computed_expiration.strftime('%Y-%m-%d')} ({days_left} days left)!",
            )
            account.last_notified_expiration = computed_expiration
    elif account.last_notified_expiration and computed_expiration > account.last_notified_expiration:
        account.last_notified_expiration = None


def _replace_scraped_certificates(account: Account, certificates: list) -> None:
    """Scraped certificates are fully re-derived on each sync; user-added ones are kept."""
    for cert in Certificate.query.filter_by(account_id=account.id).all():
        if not cert.details.get('is_custom'):
            db.session.delete(cert)
    for cert_data in certificates:
        exp_date = None
        exp_date_str = cert_data.get('expiration_date')
        if exp_date_str:
            try:
                exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d")
            except Exception:
                pass
        db.session.add(Certificate(
            account_id=account.id,
            name=cert_data.get('name'),
            expiration_date=exp_date,
            details=cert_data.get('details', {}),
        ))


def persist_result(account: Account, data: Dict[str, Any]) -> Optional[datetime]:
    """Apply a plugin result dict to the account and commit.

    Returns the expiration date that was stored. Raises on failure with the
    session left dirty -- callers are expected to call ``mark_failed``, which
    rolls back first.
    """
    account.balance = data.get('balance', account.balance)
    account.status = data.get('status', account.status)

    computed_expiration = _compute_expiration(account, data)
    account.expiration_date = computed_expiration
    account.expiration_meta = data.get('expiration_meta', {})

    member_number = data.get('member_number') or data.get('account_number')
    if member_number:
        meta = account.extra_metadata
        meta['membership_number'] = str(member_number)
        account.extra_metadata = meta

    _notify_if_expiring(account, computed_expiration)

    account.last_fetch_status = 'SUCCESS'
    account.last_error = None
    account.last_updated = datetime.utcnow()
    db.session.add(AccountHistory(account_id=account.id, balance=account.balance))

    if 'certificates' in data:
        _replace_scraped_certificates(account, data.get('certificates') or [])

    db.session.commit()
    return computed_expiration


def mark_failed(account: Account, error: str) -> None:
    """Discard any half-applied result and record the failure."""
    db.session.rollback()
    account.last_fetch_status = 'FAILED'
    account.last_error = error
    account.last_updated = datetime.utcnow()
    db.session.commit()


# --------------------------------------------------------------------------- #
# End-to-end flows
# --------------------------------------------------------------------------- #

def _notify(title: str, message: str) -> None:
    from notifier import send_desktop_notification
    send_desktop_notification(title, message)


def _clear_debug_context() -> None:
    try:
        import debug_logger
        debug_logger.clear_run_context()
    except Exception:
        pass


def sync_account(account: Account, trigger: RunTrigger = RunTrigger.MANUAL, notify: bool = True) -> SyncOutcome:
    """Full unattended sync: run fetch_data and persist, or record the failure."""
    name = account.display_name
    if account.is_manual:
        return SyncOutcome(False, f'{name} is a manually-tracked account. Use "Update Balance" instead.')
    try:
        get_plugin_for(account)
    except SyncError as e:
        app_log.warning(f"{e} (account {name})")
        return SyncOutcome(False, str(e))

    try:
        app_log.info(f"Starting {trigger.value} sync for account {name}...")
        if notify:
            _notify("Sync Started", f"Synchronizing account: {name}")
        data = run_plugin(account, RunMode.FETCH, trigger)
        expiration = persist_result(account, data)
        app_log.info(f"Sync successful for {name}. Balance: {account.balance}, Expiration: {expiration}")
        if notify:
            _notify("Sync Successful", f"{name} balance updated successfully to {account.balance:,} points.")
        return SyncOutcome(True, f'{name} synced successfully.', expiration=expiration)
    except Exception as e:
        mark_failed(account, str(e))
        app_log.error(f"Sync failed for {name}: {e}", exc_info=True)
        if notify:
            _notify("Sync Failed", f"Synchronization failed for {name}: {e}")
        return SyncOutcome(False, f'Sync failed for {name}: {e}', cancelled=plugin_base.is_cancelled(account.id))
    finally:
        _clear_debug_context()


def interactive_login(account: Account) -> InteractiveOutcome:
    """Interactive (headed) login, then persist data from the same session.

    If the plugin scraped data from the still-open authenticated session it is
    used directly; plugins that cannot (native-Chrome manual mode) return None
    and a normal fetch_data() call follows. A failed or cancelled login leaves
    the account untouched.
    """
    name = account.display_name
    try:
        get_plugin_for(account)
    except SyncError as e:
        return InteractiveOutcome(False, False, str(e))

    try:
        app_log.info(f"Starting interactive login for account {name}...")
        login_result = run_plugin(account, RunMode.INTERACTIVE, RunTrigger.MANUAL)
        app_log.info(f"Interactive login completed for {name}.")
    except Exception as e:
        app_log.error(f"Interactive login failed for {name}: {e}", exc_info=True)
        _clear_debug_context()
        if plugin_base.is_cancelled(account.id):
            return InteractiveOutcome(False, False, f'Interactive login for {name} was cancelled.', cancelled=True)
        return InteractiveOutcome(False, False, f'Interactive login failed for {name}: {e}')

    # Some plugins' broad except blocks swallow the cancellation error and
    # return None, which would otherwise look like "please fall back to
    # fetch_data()" and launch a brand-new browser the user just cancelled.
    if plugin_base.is_cancelled(account.id):
        app_log.info(f"Interactive login cancelled by user for {name}.")
        _clear_debug_context()
        return InteractiveOutcome(False, False, f'Interactive login for {name} was cancelled.', cancelled=True)

    try:
        if isinstance(login_result, dict):
            data = login_result
        else:
            app_log.info(f"Fetching balance immediately after login for {name}...")
            data = run_plugin(account, RunMode.FETCH, RunTrigger.MANUAL)
        persist_result(account, data)
        app_log.info(f"Post-login sync successful for {name}. Balance: {account.balance}")
        _notify("Sync Successful", f"{name} balance updated successfully to {account.balance:,} points.")
        return InteractiveOutcome(True, True, f'{name} logged in and synced successfully.')
    except Exception as e:
        mark_failed(account, str(e))
        app_log.error(f"Post-login sync failed for {name}: {e}", exc_info=True)
        return InteractiveOutcome(
            True, False,
            f'Interactive login succeeded for {name}, but the immediate sync failed: {e}. Try "Sync Now".',
        )
    finally:
        _clear_debug_context()
