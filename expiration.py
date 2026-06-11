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
