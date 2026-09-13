"""Plugin contract and the runner that every sync goes through.

Browser/Chrome infrastructure lives in ``plugins.browser`` and session
persistence in ``plugins.session``; both are re-exported here so plugins and
tests can keep importing from ``plugins.base``.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
import inspect

from .context import RunContext, RunMode, RunTrigger, set_run_context, current_run_context, clear_run_context
from .errors import PluginError, InteractionRequiredError  # noqa: F401
from .browser import (  # noqa: F401
    active_drivers, active_drivers_lock, cancelled_accounts, cancelled_accounts_lock,
    mark_cancelled, is_cancelled, clear_cancelled,
    get_chrome_binary, register_active_driver, unregister_active_driver, cancel_active_driver,
    is_hidden_node, inject_control_modal, wait_for_chrome_exit, _clean_lock_files, configure_session_restore,
)

def get_sb_kwargs(**kwargs) -> dict:
    """
    Returns a kwargs dict suitable for passing to SB(...), with `binary_location`
    pre-populated via get_chrome_binary() when running on macOS or Windows.

    Usage in plugins::

        with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir)) as sb:
            ...

    This ensures the Chrome binary is always found even inside a frozen .app
    bundle or a minimal-PATH environment.
    """
    binary = get_chrome_binary()
    if binary:
        kwargs.setdefault("binary_location", binary)
    return kwargs


def safe_call_plugin_method(method, *args, **kwargs):
    """
    Safely call a plugin method (like fetch_data or interactive_login) by only
    passing the keyword arguments that the method signature actually accepts,
    unless the method signature has a **kwargs parameter.
    """
    # Extract run metadata
    account_id = kwargs.pop('_account_id', None)
    provider_name = kwargs.pop('_provider_name', None)
    current_balance = kwargs.pop('_current_balance', None)
    mode = kwargs.pop('_mode', None)
    trigger = kwargs.pop('_trigger', None)

    # Publish the run context so the guide modal, cache-fallback policy and
    # logging know how this run was started without inspecting the call stack.
    if mode is None:
        mode = RunMode.INTERACTIVE if getattr(method, '__name__', '') == 'interactive_login' else RunMode.FETCH
    set_run_context(RunContext(
        account_id=account_id,
        provider_name=provider_name or '',
        plugin=getattr(method, '__self__', None),
        mode=RunMode(mode),
        trigger=RunTrigger(trigger) if trigger is not None else RunTrigger.MANUAL,
    ))

    # A new run is starting for this account -- clear any stale cancellation
    # flag from a previous run so this one isn't refused before it starts.
    if account_id:
        clear_cancelled(account_id)

    # Initialize debug log context if metadata is provided
    try:
        import debug_logger
        if account_id and provider_name:
            username = args[0] if len(args) > 0 else ""
            password = args[1] if len(args) > 1 else ""
            debug_logger.init_run_context(account_id, provider_name, username, password, current_balance)
            debug_logger.log_action(f"Started sync run for account ID {account_id} ({provider_name})")
    except Exception:
        pass

    # Wait for Chrome to exit if profile_dir is provided to prevent lockouts
    profile_dir = kwargs.get('profile_dir')
    if profile_dir:
        try:
            wait_for_chrome_exit(profile_dir)
        except Exception:
            pass

        # Fix Chrome's exit-type flags to prevent the "didn't shut down correctly" dialog
        try:
            configure_session_restore(profile_dir)
        except Exception:
            pass
        
    try:
        sig = inspect.signature(method)
        # Check if the method accepts arbitrary kwargs (VAR_KEYWORD)
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if has_var_keyword:
            filtered_kwargs = kwargs
        else:
            # Otherwise, filter kwargs to only include parameters that are explicitly defined
            # in the method's signature.
            accepted_params = set(sig.parameters.keys())
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in accepted_params}
    except Exception:
        # Fallback to passing all kwargs if inspect fails
        filtered_kwargs = kwargs

    try:
        try:
            res = method(*args, **filtered_kwargs)
            try:
                import debug_logger
                if isinstance(res, dict) and 'balance' in res:
                    debug_logger.update_balance_in_context(res['balance'])
                    debug_logger.log_action(f"Finished sync run successfully. Balance: {res['balance']}")
            except Exception:
                pass
            return res
        except Exception as e:
            err_msg = str(e)
            if "session not created" in err_msg or "chrome not reachable" in err_msg or "cannot connect to chrome" in err_msg.lower():
                raise PluginError(
                    f"Scraping failed: {err_msg}. If you have another Chrome window open with this profile, "
                    "please close it. Otherwise, there may be an orphaned Chrome process in the background. "
                    "Please terminate any orphaned Chrome processes in your Task Manager/Activity Monitor, or restart your computer."
                )
            try:
                import debug_logger
                debug_logger.log_action(f"Sync run failed with exception: {e}", level="ERROR")
            except Exception:
                pass
            raise e
    finally:
        clear_run_context()
        if account_id:
            unregister_active_driver(account_id)

def add_months(source_date, months):
    """
    Robust month addition helper in pure Python.
    Correctly handles leap years and variable month lengths.
    """
    if source_date is None:
        return None
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31
    ][month - 1])
    return datetime(year, month, day, source_date.hour, source_date.minute, source_date.second)

PROVIDER_CATEGORIES = {
    # Airlines
    'aircanada': 'Airlines',
    'alaska': 'Airlines',
    'american': 'Airlines',
    'ana': 'Airlines',
    'asiana': 'Airlines',
    'avianca': 'Airlines',
    'british': 'Airlines',
    'delta': 'Airlines',
    'eva': 'Airlines',
    'jal': 'Airlines',
    'jetblue': 'Airlines',
    'korean': 'Airlines',
    'southwest': 'Airlines',
    'united': 'Airlines',
    'virgin': 'Airlines',

    # Hotels
    'caesars': 'Hotels',
    'hilton': 'Hotels',
    'hyatt': 'Hotels',
    'ihg': 'Hotels',
    'marriott': 'Hotels',
    'wyndham': 'Hotels',

    # Car Rentals
    'enterprise': 'Car Rentals',
    'hertz': 'Car Rentals',
    'national': 'Car Rentals',

    # Credit Cards
    'chase': 'Credit Cards',
    'amex': 'Credit Cards',
    'citi': 'Credit Cards',
    'capitalone': 'Credit Cards',
    'wellsfargo': 'Credit Cards',
    'bilt': 'Credit Cards',

    # Other
    'manual': 'Other',
}

class ProviderPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g., 'Marriott Bonvoy')"""
        pass

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique ID for the plugin (e.g., 'marriott')"""
        pass

    @property
    @abstractmethod
    def default_cpp(self) -> float:
        """Default cents-per-point (CPP) valuation for this rewards program."""
        pass

    @property
    def category(self) -> str:
        """Category of the loyalty program: 'Airlines', 'Hotels', 'Credit Cards', 'Car Rentals', or 'Other'."""
        return PROVIDER_CATEGORIES.get(self.plugin_id, "Other")

    @property
    def homepage_url(self) -> str:
        """Official homepage or login URL for the loyalty / rewards program."""
        return ""

    @property
    def logo_domain(self) -> str:
        """Domain used to look up the program's logo (e.g. 'hilton.com')."""
        return ""

    @property
    def is_manual(self) -> bool:
        """True for programs tracked by hand: no credentials, no scraping."""
        return False

    def normalize_username(self, username: str) -> str:
        """Clean a login ID the way the provider expects it (override per program)."""
        return username

    @property
    def interactive_login_required(self) -> bool:
        """
        Whether this plugin always requires interactive login on first/new sign-ins.
        """
        return False

    @property
    def show_control_modal(self) -> bool:
        """
        Whether to display the automated sync / interactive login control helper modal in the browser.
        """
        return True

    @property
    def custom_tip(self) -> str:
        """
        A custom instruction tip shown in the helper modal during interactive login.
        """
        return ""

    @property
    def interactive_login_hint(self) -> str:
        """
        Plugin-specific hint shown on the dashboard/detail page when interactive login is required.
        Overrides the default "Don't require verification code again" message.
        """
        return ""

    @property
    def interactive_login_instructions(self) -> Dict[str, Any]:
        """
        Returns structured instructions for the interactive login modal.

        Keys:
          mode: "assisted" (credentials pre-filled, generic 4-step flow) or
                "manual" (native Chrome, fully manual 3-step flow)
          credential_hint: what to enter, e.g. "your email and password"
          special_note: optional HTML callout shown after step 1 (e.g. "Keep me signed in")
          pre_submit_note: optional HTML note shown in assisted mode (e.g. "must click Submit manually")
        """
        return {"mode": "assisted"}

    @abstractmethod
    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        """
        Main entrypoint for the background job to fetch balances and certificates.
        """
        pass

    @abstractmethod
    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Opens a visible browser so the user can manually bypass MFA/Captchas.

        May optionally return a data dict in the same shape as fetch_data()'s
        return value (balance/status/etc.), scraped directly from the
        already-authenticated session before it closes. When a dict is returned,
        the caller persists it immediately instead of launching a separate
        fetch_data() call — avoiding a second browser session that may not
        inherit the login (e.g. on sites that gate every login behind MFA/2FA
        with no way to stay signed in). Plugins that can't scrape data from
        within the login flow (e.g. manual mode using a native, non-automated
        browser) should keep returning None, which falls back to a normal
        fetch_data() call afterward.
        """
        pass

    def extract_membership_id(self, sb) -> Optional[str]:
        """The program's member / account number as shown on the signed-in page, or None.

        Called by the browser flows after a successful scrape (the page the
        scrape finished on is still open). Return the raw identifier, usually
        alphanumeric (e.g. Hilton "378137745"); the caller strips whitespace and
        persists it separately from anything the user typed in.
        """
        return None

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        """
        Calculates the exact expiration date based on program-specific rules.
        Returns datetime or None (Never Expires).
        """
        return None

    def get_expiration_policy_description(self, status: str = None) -> str:
        """
        Returns a human-readable description of the program's expiration policy.
        """
        return "Expiration rules vary by loyalty program."

    def get_never_expires_reason(self, status: str, has_exemption: bool = False) -> str:
        """
        Returns a short reason to append to the "Never Expires" UI text.
        For example: " (Elite)" or " (Exempt)".
        """
        if has_exemption:
            return " (Exempt)"
        return ""
