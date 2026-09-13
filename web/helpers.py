"""Small helpers shared by several route modules and the templates."""
import json
import os
import shutil

from config import basedir, write_dir
from plugins.manager import plugin_manager

CATEGORY_ORDER = ['Airlines', 'Hotels', 'Credit Cards', 'Car Rentals', 'Other']

CATEGORY_ICONS = {
    'Airlines': '✈️',
    'Hotels': '🏨',
    'Credit Cards': '💳',
    'Car Rentals': '🚗',
    'Other': '✨',
}


def get_category_icon(category_name):
    return CATEGORY_ICONS.get(category_name, '✨')


def manual_plugin_ids():
    """Plugin IDs whose accounts are tracked by hand (no credentials, no scraping)."""
    return {p.plugin_id for p in plugin_manager.get_all_plugins() if p.is_manual}


# --------------------------------------------------------------------------- #
# settings.json / valuations.json (user-writable copies of the bundled defaults)
# --------------------------------------------------------------------------- #

def _load_user_json(filename, default_filename):
    path = os.path.join(write_dir, filename)
    if not os.path.exists(path):
        default_path = os.path.join(basedir, default_filename)
        if os.path.exists(default_path):
            try:
                shutil.copy2(default_path, path)
            except Exception:
                pass
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def load_settings():
    return _load_user_json('settings.json', 'settings.default.json')


def load_valuations():
    return _load_user_json('valuations.json', 'valuations.default.json')


def save_valuations(valuations):
    try:
        with open(os.path.join(write_dir, 'valuations.json'), 'w') as f:
            json.dump(valuations, f, indent=2)
        return True
    except Exception:
        return False


DEFAULT_STANDARD_VALUATIONS = {
    plugin.plugin_id: {'name': plugin.name, 'cpp': plugin.default_cpp}
    for plugin in plugin_manager.get_all_plugins()
}


def get_account_cpp_and_value(account, valuations):
    """
    Computes and returns the CPP (cents per point) and equivalent USD value
    for an account, taking into account custom overrides for manual entries.
    """
    if account.is_manual and account.provider.plugin_name == 'manual':
        prog_name = account.program_name or ""
        val = valuations.get(prog_name.lower())
        if val is None:
            val = valuations.get('manual', {})
        cpp = val.get('cpp', DEFAULT_STANDARD_VALUATIONS.get('manual', {}).get('cpp', 1.0))
    else:
        plugin_name = account.provider.plugin_name
        val = valuations.get(plugin_name, {})
        default_val = DEFAULT_STANDARD_VALUATIONS.get(plugin_name, {})
        cpp = val.get('cpp', default_val.get('cpp', 0.0))

    value_usd = (account.balance * cpp) / 100.0
    return cpp, value_usd


def format_time_remaining(days):
    if days is None:
        return ""
    if days < 0:
        return "Expired"

    # Use calendar-accurate relativedelta rather than 365/30-day integer arithmetic
    # so that e.g. 366 days shows "1 yr, 1 day" instead of "1 yr" and
    # 700 days shows "1 yr, 11 mos" instead of rounding to "2 yrs".
    try:
        from dateutil.relativedelta import relativedelta
        from datetime import date as _date
        today = _date.today()
        future = today + relativedelta(days=days)
        delta = relativedelta(future, today)
        parts = []
        if delta.years > 0:
            parts.append(f"{delta.years} yr{'s' if delta.years != 1 else ''}")
        if delta.months > 0:
            parts.append(f"{delta.months} mo{'s' if delta.months != 1 else ''}")
        if delta.days > 0 or not parts:
            parts.append(f"{delta.days} day{'s' if delta.days != 1 else ''}")
        return ", ".join(parts) + " remaining"
    except ImportError:
        years = days // 365
        rem = days % 365
        months = rem // 30
        rem_days = rem % 30
        parts = []
        if years > 0:
            parts.append(f"{years} yr{'s' if years != 1 else ''}")
        if months > 0:
            parts.append(f"{months} mo{'s' if months != 1 else ''}")
        if rem_days > 0 or not parts:
            parts.append(f"{rem_days} day{'s' if rem_days != 1 else ''}")
        return ", ".join(parts) + " remaining"


def parse_date_field(value, fmt='%Y-%m-%d'):
    """Parse a form date field; blank or malformed input yields None."""
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.strptime(value, fmt)
    except (ValueError, TypeError):
        return None


def parse_int_field(value, default=0):
    """Parse a numeric form field that may carry thousands separators."""
    try:
        return int(float(str(value).replace(',', '')))
    except (ValueError, TypeError):
        return default
