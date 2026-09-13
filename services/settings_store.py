"""Typed access to the key/value ``Settings`` table.

Every caller used to hand-roll ``Settings.query.filter_by(key=...).first()``
plus its own default and int/bool coercion; keep that in one place.
"""
from typing import Any, Dict

from extensions import db
from models import Settings


def get_setting(key: str, default: str = '') -> str:
    setting = Settings.query.filter_by(key=key).first()
    return setting.value if setting else default


def get_int_setting(key: str, default: int) -> int:
    try:
        return int(get_setting(key, str(default)))
    except (TypeError, ValueError):
        return default


def get_bool_setting(key: str, default: bool) -> bool:
    return get_setting(key, 'true' if default else 'false') == 'true'


def set_setting(key: str, value: Any, commit: bool = True) -> None:
    setting = Settings.query.filter_by(key=key).first()
    if setting:
        setting.value = str(value)
    else:
        db.session.add(Settings(key=key, value=str(value)))
    if commit:
        db.session.commit()


def set_settings(values: Dict[str, Any]) -> None:
    """Upsert several keys in one commit."""
    for key, value in values.items():
        set_setting(key, value, commit=False)
    db.session.commit()


def get_settings(defaults: Dict[str, str]) -> Dict[str, str]:
    """Read many keys at once, falling back to the supplied default per key."""
    return {key: get_setting(key, default) for key, default in defaults.items()}


# Thresholds used across the dashboard, account detail and sync notifications.
def get_warning_threshold_days() -> int:
    return get_int_setting('warning_threshold', 30)


def get_advisory_threshold_days() -> int:
    return get_int_setting('advisory_threshold', 90)
