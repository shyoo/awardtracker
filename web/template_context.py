"""Jinja context processor: helpers every template can call."""
import os
from datetime import datetime

from expiration import get_program_rule_description, get_never_expires_reason
from plugins.manager import plugin_manager
from services.settings_store import get_setting
from web.helpers import format_time_remaining, get_category_icon, load_settings

RELEASES_URL = 'https://github.com/shyoo/awardtracker/releases'


def get_logo_url(plugin_name):
    plugin = plugin_manager.get_plugin((plugin_name or '').lower())
    domain = plugin.logo_domain if plugin else ''
    if not domain:
        return ""
    token = load_settings().get('LOGO_DEV_TOKEN') or os.environ.get('LOGO_DEV_TOKEN', 'pk_YOUR_TOKEN_HERE')
    return f"https://img.logo.dev/{domain}?token={token}&size=256"


def get_provider_homepage_url(plugin_name, custom_url=None):
    if custom_url:
        return custom_url
    if not plugin_name:
        return ""
    plugin = plugin_manager.get_plugin(plugin_name.lower())
    if not plugin:
        return ""
    if plugin.homepage_url:
        return plugin.homepage_url
    if plugin.logo_domain:
        return f"https://www.{plugin.logo_domain}"
    return ""


def get_interactive_login_hint(plugin_name):
    plugin = plugin_manager.get_plugin(plugin_name)
    return plugin.interactive_login_hint if plugin else ""


def get_interactive_login_instructions(plugin_name):
    plugin = plugin_manager.get_plugin(plugin_name)
    return plugin.interactive_login_instructions if plugin else {"mode": "assisted"}


def time_ago(dt):
    if not dt:
        return "never"
    seconds = (datetime.utcnow() - dt).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hr ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days > 1 else ''} ago"


def _available_update(current_version, respect_dismissed):
    """Newer-release info for the update banner, or None."""
    if get_setting('check_for_updates', 'true') == 'false':
        return None
    latest = get_setting('latest_version_available', '')
    if not latest:
        return None
    if respect_dismissed and get_setting('update_dismissed_version', '') == latest:
        return None
    from updater import parse_version
    if parse_version(latest) > parse_version(current_version):
        return {'version': latest, 'url': get_setting('latest_release_url', '') or RELEASES_URL}
    return None


def register(app):
    @app.context_processor
    def inject_helpers():
        current_version = app.config.get('APP_VERSION', '1.2.2')
        return dict(
            get_program_rule_description=get_program_rule_description,
            get_never_expires_reason=get_never_expires_reason,
            format_time_remaining=format_time_remaining,
            get_logo_url=get_logo_url,
            get_provider_homepage_url=get_provider_homepage_url,
            get_interactive_login_hint=get_interactive_login_hint,
            get_interactive_login_instructions=get_interactive_login_instructions,
            get_category_icon=get_category_icon,
            time_ago=time_ago,
            app_version=current_version,
            # Dashboard banner respects "dismiss"; the Settings page always shows the truth.
            update_info=_available_update(current_version, respect_dismissed=True),
            update_info_raw=_available_update(current_version, respect_dismissed=False),
        )
