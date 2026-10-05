from datetime import datetime
from plugins.manager import plugin_manager
from plugins.base import add_months

def calculate_expiration(plugin_id: str, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
    """
    Calculates the exact expiration date based on program-specific rules,
    delegating the calculation to the plugin.
    Returns datetime or None (Never Expires).
    """
    # 0. Check for 0 or negative balance (no points/miles to expire)
    if balance <= 0:
        return None

    # 1. Check universal exemption
    if has_exemption:
        return None

    # Retrieve the plugin
    plugin = plugin_manager.get_plugin(plugin_id)
    if plugin:
        return plugin.calculate_expiration(balance, status, last_activity_date, has_exemption)

    return None

def get_program_rule_description(plugin_id: str, status: str = None) -> str:
    """
    Returns a human-readable description of the program's expiration policy.
    Used for UI tooltips.
    """
    plugin = plugin_manager.get_plugin(plugin_id)
    if plugin:
        return plugin.get_expiration_policy_description(status)
    return "Expiration rules vary by loyalty program."

def get_never_expires_reason(plugin_id: str, status: str, has_exemption: bool = False) -> str:
    """
    Returns a short reason to append to the "Never Expires" UI text.
    For example: " (Elite)" or " (Exempt)".
    """
    plugin = plugin_manager.get_plugin(plugin_id)
    if plugin:
        return plugin.get_never_expires_reason(status, has_exemption)
    if has_exemption:
        return " (Exempt)"
    return ""


# --------------------------------------------------------------------------- #
# Classifying an expiration date for the UI
# --------------------------------------------------------------------------- #

def classify_days_left(days_left: int, warning_days: int, advisory_days: int) -> str:
    """Map a day count to the badge state used by the dashboard and detail page."""
    if days_left < 0:
        return 'expired'
    if days_left <= warning_days:
        return 'critical'
    if days_left <= advisory_days:
        return 'warning'
    return 'safe'


def annotate_account_expiration(account, now: datetime, warning_days: int, advisory_days: int) -> None:
    """Set ``account.days_left`` and ``account.expiration_status`` for rendering.

    Korean Air tracks per-batch expiry, so its earliest expiring batch (from
    expiration_meta) takes precedence over the account-level date. Accounts
    with points but no known date are flagged ``at_risk`` when the plugin said
    so, or -- for Hilton accounts synced before the plugin reported it -- when
    there is simply no date.
    """
    account.days_left = None
    account.expiration_status = 'none'
    meta = account.expiration_meta or {}
    plugin_name = account.provider.plugin_name if account.provider else ''

    exp_date = None
    if plugin_name == 'korean' and meta.get('earliest_expiring_date'):
        try:
            exp_date = datetime.strptime(meta['earliest_expiring_date'], '%Y-%m-%d')
        except Exception:
            exp_date = None
    if exp_date is None:
        exp_date = account.expiration_date

    if exp_date:
        account.days_left = (exp_date - now).days
        account.expiration_status = classify_days_left(account.days_left, warning_days, advisory_days)
    elif not account.has_exemption and account.balance > 0 and (
        meta.get('at_risk') or (plugin_name == 'hilton' and not account.expiration_date)
    ):
        account.expiration_status = 'at_risk'


def annotate_certificate_expiration(cert, now: datetime, warning_days: int, advisory_days: int) -> None:
    """Set ``cert.days_left`` and ``cert.expiration_status`` for rendering."""
    if cert.expiration_date:
        cert.days_left = (cert.expiration_date - now).days
        cert.expiration_status = classify_days_left(cert.days_left, warning_days, advisory_days)
    else:
        cert.days_left = None
        cert.expiration_status = 'none'
