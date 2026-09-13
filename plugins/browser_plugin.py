"""Template for SeleniumBase-driven provider plugins.

A plugin describes its site -- where to log in, how to tell a signed-in page
from the login form, how to fill the form, what an MFA challenge looks like,
and how to read the balance page -- and this base runs the two flows that
every plugin used to re-implement side by side:

* ``fetch_data``: open, sign in unattended if needed, scrape.
* ``interactive_login``: open, pre-fill, wait for the user to finish
  (MFA, captcha, ...), then scrape from the same authenticated session.

Both end in the same ``scrape()`` so the interactive path can never drift
behind the automated one (certificates, membership ID, activity dates).

Three site archetypes are covered by attributes rather than subclasses:

* assisted (default): SeleniumBase pre-fills the form and the user submits.
* ``interactive_mode = "native"``: the user's own Chrome is launched on the
  profile for the login (no automation flags), then a headless SeleniumBase
  session reads the balance and saves cookies.
* ``cache_max_age_seconds``: the last good result is served when the site is
  unreachable during an unattended (scheduled) sync.
"""
from __future__ import annotations

import time
from abc import abstractmethod
from typing import Any, Dict, Optional

from seleniumbase import SB  # noqa: F401  (single patch seam for tests: plugins.browser_plugin.SB)

from .base import InteractionRequiredError, PluginError, ProviderPlugin, get_sb_kwargs, wait_for_chrome_exit
from .context import current_run_context
from .session import (ResultCache, clear_profile_session, get_consistent_user_agent, launch_native_chrome,
                      load_cookies_from_json, raise_if_window_closed, save_cookies_to_json)


def log(message: str, level: str = "INFO") -> None:
    """Route plugin progress messages through the run-aware debug logger."""
    try:
        import debug_logger
        debug_logger.log_action(message, level=level)
    except Exception:
        pass


class BrowserPlugin(ProviderPlugin):
    # ------------------------------------------------------------------ #
    # Site description -- override in subclasses
    # ------------------------------------------------------------------ #
    login_url: str = ""
    username_selector: str = ""
    password_selector: str = ""

    #: Seconds to let the page settle after opening ``login_url``.
    page_settle_seconds: float = 5.0
    #: Seconds to wait after submitting credentials before checking the result.
    post_login_settle_seconds: float = 10.0
    #: Seconds to let the session flush before scraping after an interactive login.
    post_interactive_settle_seconds: float = 3.0
    #: How long the user gets to finish an interactive login.
    interactive_timeout_seconds: int = 300
    interactive_poll_seconds: float = 2.0

    #: ``uc_open_with_reconnect(url, N)`` instead of ``open(url)`` for the first page.
    uc_reconnect_tries: Optional[int] = None
    headless: bool = False
    #: Pin the User-Agent to the installed Chrome version (Auth0-style bot checks).
    lock_user_agent: bool = False
    #: Persist / restore session cookies in ``profile_dir/<cookie_jar_name>``.
    use_cookie_jar: bool = False
    cookie_jar_name: str = "cookies.json"
    #: Domains injected via /robots.txt rather than the www. homepage.
    cookie_jar_robots_domains: tuple = ("auth0",)
    #: Serve the last good result when the live scrape fails. None disables.
    cache_max_age_seconds: Optional[int] = None
    cache_name: str = "result_cache.json"
    #: Whether a user-initiated Sync Now may also fall back to the cache.
    cache_fallback_on_manual: bool = False
    #: "assisted" (SeleniumBase pre-fills the form) or "native" (user's own Chrome).
    interactive_mode: str = "assisted"
    #: URL opened in native mode; defaults to ``login_url``.
    native_login_url: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Hooks -- override as needed
    # ------------------------------------------------------------------ #

    def sb_kwargs(self, profile_dir: Optional[str], headless: Optional[bool] = None) -> dict:
        kwargs = dict(uc=True, user_data_dir=profile_dir, headless=self.headless if headless is None else headless)
        if self.lock_user_agent:
            kwargs["agent"] = get_consistent_user_agent()
        return get_sb_kwargs(**kwargs)

    def open_url(self, sb, url: str, settle: Optional[float] = None) -> None:
        if self.uc_reconnect_tries:
            sb.uc_open_with_reconnect(url, self.uc_reconnect_tries)
        else:
            sb.open(url)
        sb.sleep(self.page_settle_seconds if settle is None else settle)

    def open_login(self, sb) -> None:
        """Land on the page where the login form (or the signed-in dashboard) lives."""
        self.open_url(sb, self.login_url)

    def login_form_visible(self, sb) -> bool:
        try:
            return bool(self.username_selector) and sb.is_element_visible(self.username_selector)
        except Exception:
            return False

    def is_logged_in(self, sb) -> bool:
        """Strong signed-in check, also used to detect completion of an interactive login.

        The default is only "no login form and no MFA prompt"; plugins should
        check for something on the authenticated page (a balance, a greeting).
        """
        return not self.login_form_visible(sb) and not self.is_mfa(sb)

    def fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Type credentials; submit only when ``auto_submit`` (never during interactive login)."""
        raise InteractionRequiredError(f"{self.name} requires Interactive Login.")

    def is_mfa(self, sb) -> bool:
        return False

    def mfa_message(self) -> str:
        return f"{self.name} requested additional verification (MFA). Please run Interactive Login."

    def login_failed_message(self) -> str:
        return f"{self.name} login did not complete. Please run Interactive Login."

    @abstractmethod
    def scrape(self, sb) -> Dict[str, Any]:
        """Read everything from the authenticated session and return the result dict."""

    def before_native_login(self, profile_dir: Optional[str]) -> None:
        """Runs before the user's Chrome is launched (e.g. clear stale cookies)."""
        clear_profile_session(profile_dir, self.cookie_jar_name if self.use_cookie_jar else None)

    # ------------------------------------------------------------------ #
    # Shared machinery
    # ------------------------------------------------------------------ #

    def cache(self, profile_dir: Optional[str]) -> ResultCache:
        return ResultCache(profile_dir, self.cache_name)

    def restore_session(self, sb, profile_dir: Optional[str]) -> None:
        if self.use_cookie_jar and profile_dir:
            n = load_cookies_from_json(sb, profile_dir, self.cookie_jar_name, self.cookie_jar_robots_domains)
            if n:
                log(f"Restored {n} saved cookies for {self.name}.")

    def finish(self, sb, profile_dir: Optional[str], result: Dict[str, Any]) -> Dict[str, Any]:
        """Post-scrape bookkeeping common to both flows."""
        if 'membership_id' not in result:
            try:
                membership_id = self.extract_membership_id(sb)
                if membership_id:
                    result['membership_id'] = str(membership_id).strip()
            except Exception:
                pass
        if profile_dir:
            if self.use_cookie_jar:
                save_cookies_to_json(sb, profile_dir, self.cookie_jar_name)
            if self.cache_max_age_seconds:
                self.cache(profile_dir).save(result)
        return result

    def _cached_fallback(self, profile_dir: Optional[str]) -> Optional[Dict[str, Any]]:
        if not self.cache_max_age_seconds or not profile_dir:
            return None
        ctx = current_run_context()
        is_manual = ctx.is_manual if ctx else True
        if is_manual and not self.cache_fallback_on_manual:
            return None
        cached = self.cache(profile_dir).load(self.cache_max_age_seconds)
        if cached:
            log(f"{self.name}: live scrape failed; returning cached result.", level="WARNING")
        return cached

    def sign_in(self, sb, username: str, password: str) -> None:
        """Unattended sign-in when the page shows the login form."""
        self.fill_login_form(sb, username, password, auto_submit=True)
        sb.sleep(self.post_login_settle_seconds)
        if self.is_mfa(sb):
            raise InteractionRequiredError(self.mfa_message())
        if not self.is_logged_in(sb):
            if self.is_mfa(sb):
                raise InteractionRequiredError(self.mfa_message())
            raise InteractionRequiredError(self.login_failed_message())

    def wait_for_user_login(self, sb) -> None:
        """Poll until the plugin's signed-in check passes or the interactive window expires."""
        deadline = time.time() + self.interactive_timeout_seconds
        while time.time() < deadline:
            if self.is_logged_in(sb):
                return
            time.sleep(self.interactive_poll_seconds)
        raise PluginError(
            f"Interactive login timed out after {self.interactive_timeout_seconds // 60} minutes "
            f"or the {self.name} account page did not load."
        )

    # ------------------------------------------------------------------ #
    # Flows
    # ------------------------------------------------------------------ #

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        username = self.normalize_username(username)
        try:
            with SB(**self.sb_kwargs(profile_dir)) as sb:
                self.restore_session(sb, profile_dir)
                self.open_login(sb)
                if not self.is_logged_in(sb):
                    if not self.login_form_visible(sb):
                        # Some sites need a second navigation to show the form.
                        self.open_login(sb)
                    self.sign_in(sb, username, password)
                result = self.scrape(sb)
                return self.finish(sb, profile_dir, result)
        except InteractionRequiredError:
            cached = self._cached_fallback(profile_dir)
            if cached:
                return cached
            raise
        except PluginError:
            cached = self._cached_fallback(profile_dir)
            if cached:
                return cached
            raise
        except Exception as e:
            raise_if_window_closed(e)
            cached = self._cached_fallback(profile_dir)
            if cached:
                return cached
            raise PluginError(f"{self.name} scraping failed: {e}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Optional[Dict[str, Any]]:
        username = self.normalize_username(username)
        if self.interactive_mode == "native":
            return self._native_interactive_login(profile_dir)
        try:
            with SB(**self.sb_kwargs(profile_dir, headless=False)) as sb:
                self.restore_session(sb, profile_dir)
                self.open_login(sb)
                if not self.is_logged_in(sb):
                    try:
                        self.fill_login_form(sb, username, password, auto_submit=False)
                    except Exception as e:
                        log(f"Could not pre-fill {self.name} login form: {e}", level="WARNING")
                    self.wait_for_user_login(sb)
                sb.sleep(self.post_interactive_settle_seconds)
                result = self.scrape(sb)
                return self.finish(sb, profile_dir, result)
        except (PluginError, InteractionRequiredError):
            raise
        except Exception as e:
            raise_if_window_closed(e)
            raise PluginError(f"Interactive login failed: {e}")

    def _native_interactive_login(self, profile_dir: Optional[str]) -> Optional[Dict[str, Any]]:
        if not profile_dir:
            raise PluginError("A browser profile directory is required for interactive login.")
        try:
            wait_for_chrome_exit(profile_dir)
            self.before_native_login(profile_dir)
            log(f"Launching native Chrome for {self.name} login...")
            launch_native_chrome(profile_dir, self.native_login_url or self.login_url)
            wait_for_chrome_exit(profile_dir)

            log("Chrome closed by user. Reading the account page in the background...")
            with SB(**self.sb_kwargs(profile_dir, headless=True)) as sb:
                self.open_login(sb)
                if not self.is_logged_in(sb):
                    raise PluginError(
                        f"Chrome was closed, but {self.name} does not show a signed-in account page. "
                        "Please try Interactive Login again and finish signing in before closing the window."
                    )
                result = self.scrape(sb)
                return self.finish(sb, profile_dir, result)
        except (PluginError, InteractionRequiredError):
            raise
        except Exception as e:
            raise_if_window_closed(e)
            raise PluginError(f"Interactive login error: {e}")
