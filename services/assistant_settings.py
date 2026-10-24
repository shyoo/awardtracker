"""Settings management for the in-app AI assistant ("Ask AI").

Handles provider selection, model configuration, encrypted API key storage,
base URLs for OpenAI-compatible endpoints, and pseudonymization settings.
"""
from typing import Any, Dict, Optional

from core.extensions import db
from core.models import Settings
from core.security import security_manager
from services.settings_store import get_bool_setting, get_setting, set_setting

SETTING_PROVIDER = 'assistant_provider'
SETTING_PSEUDONYMIZE = 'assistant_pseudonymize_names'

PROVIDERS = ('openai', 'anthropic', 'gemini', 'openai_compatible')

DEFAULT_MODELS = {
    'openai': 'gpt-5.5',
    'anthropic': 'claude-sonnet-5-5',
    'gemini': 'gemini-3-flash-preview',
    'openai_compatible': '',
}


def get_public_settings() -> Dict[str, Any]:
    """Return public assistant settings.

    NEVER returns raw or decrypted API keys, only `has_key` booleans.
    """
    current_provider = get_setting(SETTING_PROVIDER, 'openai')
    return {
        'provider': current_provider,
        'model': {
            p: get_setting(f'assistant_model_{p}', DEFAULT_MODELS.get(p, ''))
            for p in PROVIDERS
        },
        'base_url': get_setting('assistant_base_url', ''),
        'has_key': {
            p: bool(get_setting(f'assistant_key_{p}', '').strip())
            for p in PROVIDERS
        },
        'pseudonymize': get_bool_setting(SETTING_PSEUDONYMIZE, True),
    }


def save_settings(form: Dict[str, Any]) -> None:
    """Save assistant settings from JSON payload or form dictionary.

    Blank API key fields retain existing keys; explicit clear flags remove them.
    API keys are encrypted before storage.
    """
    if not form:
        return

    # 1. Provider
    if 'provider' in form and form['provider']:
        set_setting(SETTING_PROVIDER, str(form['provider']).strip(), commit=False)

    # 2. Pseudonymize
    if 'pseudonymize' in form:
        val = form['pseudonymize']
        if isinstance(val, bool):
            p_bool = val
        elif isinstance(val, (int, float)):
            p_bool = bool(val)
        elif isinstance(val, str):
            p_bool = val.lower() in ('true', '1', 'on', 'yes')
        else:
            p_bool = bool(val)
        set_setting(SETTING_PSEUDONYMIZE, 'true' if p_bool else 'false', commit=False)

    # 3. Models
    current_provider = form.get('provider') or get_setting(SETTING_PROVIDER, 'openai')
    if 'model' in form:
        if isinstance(form['model'], dict):
            for p, m in form['model'].items():
                if p in PROVIDERS:
                    set_setting(f'assistant_model_{p}', str(m).strip(), commit=False)
        elif isinstance(form['model'], str):
            if current_provider:
                set_setting(f'assistant_model_{current_provider}', form['model'].strip(), commit=False)

    if 'models' in form and isinstance(form['models'], dict):
        for p, m in form['models'].items():
            if p in PROVIDERS:
                set_setting(f'assistant_model_{p}', str(m).strip(), commit=False)

    for p in PROVIDERS:
        if f'model_{p}' in form:
            set_setting(f'assistant_model_{p}', str(form[f'model_{p}']).strip(), commit=False)
        elif f'assistant_model_{p}' in form:
            set_setting(f'assistant_model_{p}', str(form[f'assistant_model_{p}']).strip(), commit=False)

    # 4. Base URL
    if 'base_url' in form:
        set_setting('assistant_base_url', str(form['base_url']).strip(), commit=False)
    elif 'assistant_base_url' in form:
        set_setting('assistant_base_url', str(form['assistant_base_url']).strip(), commit=False)

    # 5. API Keys and clear flags
    for p in PROVIDERS:
        clear_flag = (
            form.get(f'clear_key_{p}')
            or form.get(f'clear_{p}')
            or (form.get('clear_key') and current_provider == p)
        )
        is_clear = False
        if isinstance(clear_flag, bool):
            is_clear = clear_flag
        elif isinstance(clear_flag, str):
            is_clear = clear_flag.lower() in ('true', '1', 'on', 'yes')
        elif isinstance(clear_flag, (int, float)):
            is_clear = bool(clear_flag)

        if is_clear:
            setting = Settings.query.filter_by(key=f'assistant_key_{p}').first()
            if setting:
                db.session.delete(setting)
        else:
            new_key = None
            if f'assistant_key_{p}' in form:
                new_key = form[f'assistant_key_{p}']
            elif f'api_key_{p}' in form:
                new_key = form[f'api_key_{p}']
            elif f'key_{p}' in form:
                new_key = form[f'key_{p}']
            elif current_provider == p:
                if 'api_key' in form:
                    new_key = form['api_key']
                elif 'key' in form:
                    new_key = form['key']

            if new_key is not None:
                key_str = str(new_key).strip()
                if key_str:
                    encrypted = security_manager.encrypt(key_str)
                    set_setting(f'assistant_key_{p}', encrypted, commit=False)
                # Blank key keeps existing key

    db.session.commit()


def get_provider_config(provider: Optional[str] = None) -> Dict[str, Any]:
    """Return decrypted configuration dict for the specified or active provider."""
    if not provider:
        provider = get_setting(SETTING_PROVIDER, 'openai')

    model = get_setting(f'assistant_model_{provider}', DEFAULT_MODELS.get(provider, ''))
    base_url = get_setting('assistant_base_url', '')
    enc_key = get_setting(f'assistant_key_{provider}', '')
    api_key = ''
    if enc_key:
        try:
            api_key = security_manager.decrypt(enc_key)
        except Exception:
            api_key = ''

    return {
        'provider': provider,
        'model': model,
        'api_key': api_key,
        'base_url': base_url,
    }
