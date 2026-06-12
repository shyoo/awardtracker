import os
import re
import logging
from datetime import datetime
import threading
from config import write_dir

_log_context = threading.local()

def get_setting(key, default=''):
    try:
        from flask import has_app_context
        if has_app_context():
            from models import Settings
            setting = Settings.query.filter_by(key=key).first()
            return setting.value if setting else default
    except Exception:
        pass
    return default

def is_debug_mode() -> bool:
    return get_setting('debug_mode', 'false') == 'true'

def is_privacy_masked() -> bool:
    return get_setting('debug_mask_privacy', 'true') == 'true'

def init_run_context(account_id, provider_name, username, password, current_balance=None):
    _log_context.account_id = account_id
    _log_context.provider_name = provider_name
    _log_context.timestamp = datetime.now()
    _log_context.date_str = _log_context.timestamp.strftime('%Y-%m-%d')
    _log_context.timestamp_str = _log_context.timestamp.strftime('%Y%m%d_%H%M%S')
    _log_context.step_counter = 0
    _log_context.in_logger = False
    _log_context.in_patched_call = False
    
    # Store sensitive data to mask
    _log_context.sensitive_data = {
        'username': username,
        'password': password,
        'balance': str(current_balance) if current_balance is not None else None
    }
    
    if is_debug_mode():
        # Create run directory (replace spaces/special chars in provider name to be path-friendly)
        safe_provider = re.sub(r'[^a-zA-Z0-9_]', '_', provider_name)
        _log_context.run_dir = os.path.join(
            write_dir, 'logs', _log_context.date_str,
            f"{_log_context.timestamp_str}-{account_id}-{safe_provider}"
        )
        os.makedirs(_log_context.run_dir, exist_ok=True)
    else:
        _log_context.run_dir = None

def update_balance_in_context(balance):
    if hasattr(_log_context, 'sensitive_data'):
        _log_context.sensitive_data['balance'] = str(balance)

def clear_run_context():
    if hasattr(_log_context, 'account_id'):
        del _log_context.account_id
    if hasattr(_log_context, 'provider_name'):
        del _log_context.provider_name
    if hasattr(_log_context, 'timestamp'):
        del _log_context.timestamp
    if hasattr(_log_context, 'date_str'):
        del _log_context.date_str
    if hasattr(_log_context, 'timestamp_str'):
        del _log_context.timestamp_str
    if hasattr(_log_context, 'step_counter'):
        del _log_context.step_counter
    if hasattr(_log_context, 'sensitive_data'):
        del _log_context.sensitive_data
    if hasattr(_log_context, 'run_dir'):
        del _log_context.run_dir
    if hasattr(_log_context, 'in_logger'):
        del _log_context.in_logger
    if hasattr(_log_context, 'in_patched_call'):
        del _log_context.in_patched_call

def mask_sensitive(text: str) -> str:
    if not text or not is_privacy_masked():
        return text
    
    sensitive = getattr(_log_context, 'sensitive_data', None)
    if not sensitive:
        return text
        
    masked = text
    p = sensitive.get('password')
    if p and len(p) > 2:
        masked = masked.replace(p, '***')
        
    u = sensitive.get('username')
    if u and len(u) > 2:
        masked = masked.replace(u, '***')
        
    b = sensitive.get('balance')
    if b and str(b) != '0':
        masked = masked.replace(str(b), '***')
        try:
            formatted_b = f"{int(b):,}"
            if formatted_b != '0':
                masked = masked.replace(formatted_b, '***')
        except Exception:
            pass
            
    return masked

def log_action(message, level="INFO"):
    masked_message = mask_sensitive(message)
    
    # Write to app log
    app_log = logging.getLogger('awardtracker')
    if level == "INFO":
        app_log.info(masked_message)
    elif level == "WARNING":
        app_log.warning(masked_message)
    elif level == "ERROR":
        app_log.error(masked_message)
    else:
        app_log.debug(masked_message)
        
    # If debug mode is enabled, write to run-specific run.log
    run_dir = getattr(_log_context, 'run_dir', None)
    if run_dir:
        log_file_path = os.path.join(run_dir, 'run.log')
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
            with open(log_file_path, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp} {level} {masked_message}\n")
        except Exception:
            pass

def save_snapshot(sb, action_name):
    run_dir = getattr(_log_context, 'run_dir', None)
    if not run_dir or not is_debug_mode():
        return
        
    # Prevent infinite recursion if snapshot functions trigger selenium wrappers
    if getattr(_log_context, 'in_logger', False):
        return
        
    _log_context.in_logger = True
    try:
        # Log the current browser URL
        try:
            current_url = sb.get_current_url()
            _log_context.in_logger = False
            log_action(f"Current browser URL: {current_url}")
            _log_context.in_logger = True
        except Exception:
            pass

        _log_context.step_counter += 1
        step = _log_context.step_counter
        safe_action = re.sub(r'[^a-zA-Z0-9_]', '_', action_name)
        
        # Save screenshot
        screenshot_name = f"{step:03d}_{safe_action}.png"
        try:
            sb.save_screenshot(screenshot_name, folder=run_dir)
        except Exception as e:
            # We don't call save_snapshot recursively on errors, just log it
            _log_context.in_logger = False # temporarily drop flag for logging
            log_action(f"Failed to save screenshot {screenshot_name}: {e}", level="WARNING")
            _log_context.in_logger = True
            
        # Save HTML
        html_name = f"{step:03d}_{safe_action}.html"
        html_path = os.path.join(run_dir, html_name)
        try:
            html_content = sb.get_page_source()
            masked_html = mask_sensitive(html_content)
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(masked_html)
        except Exception as e:
            _log_context.in_logger = False
            log_action(f"Failed to save HTML source {html_name}: {e}", level="WARNING")
            _log_context.in_logger = True
            
    finally:
        _log_context.in_logger = False

class SensitiveMaskingFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()
            record.msg = mask_sensitive(message)
            record.args = ()
        except Exception:
            pass
        return True

_app_log = logging.getLogger('awardtracker')
if not any(isinstance(f, SensitiveMaskingFilter) for f in _app_log.filters):
    _app_log.addFilter(SensitiveMaskingFilter())
