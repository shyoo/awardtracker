"""British Airways Executive Club.

BA fronts its login with hCaptcha and Akamai bot detection that reject
WebDriver sessions outright, so sign-in happens in the user's own Chrome
(``interactive_mode = "native"``); the automated sync only ever reuses the
resulting session, restored from the JSON cookie jar.
"""
import re
from datetime import datetime
from typing import Any, Dict, Optional

from bs4 import BeautifulSoup

from .base import InteractionRequiredError, add_months
from .browser_plugin import BrowserPlugin, log
from .session import raise_if_window_closed


class BritishAirwaysPlugin(BrowserPlugin):
    home_url = "https://www.britishairways.com/travel/home/public/en_us/"
    dashboard_url = "https://www.britishairways.com/nx/b/customerhub/en/us/your-account/"
    login_url = dashboard_url
    native_login_url = "https://www.britishairways.com/en-gb/executive-club/login"

    interactive_mode = "native"
    lock_user_agent = True
    use_cookie_jar = True
    cookie_jar_name = "british_cookies.json"
    cookie_jar_robots_domains = ("auth0", "britishairways")
    cache_max_age_seconds = 900
    cache_name = "british_cache.json"
    uc_reconnect_tries = 4
    page_settle_seconds = 5

    @property
    def name(self) -> str:
        return "British Airways"

    @property
    def plugin_id(self) -> str:
        return "british"

    @property
    def homepage_url(self) -> str:
        return "https://www.britishairways.com/executive-club"

    @property
    def logo_domain(self) -> str:
        return "britishairways.com"

    @property
    def default_cpp(self) -> float:
        return 1.5

    @property
    def interactive_login_required(self) -> bool:
        return True

    @property
    def show_control_modal(self) -> bool:
        return False

    @property
    def interactive_login_instructions(self):
        return {
            "mode": "manual",
            "credential_hint": "your Executive Club number, PIN/password",
        }

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> Optional[datetime]:
        if balance == 0:
            return None
        return add_months(last_activity_date, 36)

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Avios expire after 36 months of inactivity. Any collection or redemption activity will extend the validity of all remaining Avios."

    # ------------------------------------------------------------------ #
    # Site hooks
    # ------------------------------------------------------------------ #

    def open_login(self, sb) -> None:
        log("Opening British Airways homepage to initialize domain...")
        self.open_url(sb, self.home_url, settle=2)
        self._dismiss_cookie_consent(sb)
        log("Navigating to British Airways dashboard...")
        self.open_url(sb, self.dashboard_url)

    def is_logged_in(self, sb) -> bool:
        return self._check_logged_in(sb)

    def fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        raise InteractionRequiredError(
            "British Airways session expired. Please run Interactive Login to complete CAPTCHA/MFA."
        )

    def scrape(self, sb) -> Dict[str, Any]:
        result = self._parse_account_html(sb.get_page_source())
        if not result:
            raise InteractionRequiredError(
                "Successfully reached British Airways, but could not read the Avios balance from the dashboard. "
                "Try running Interactive Login."
            )
        log(f"Captured British Airways Avios balance: {result['balance']}")
        return result

    def extract_membership_id(self, sb) -> Optional[str]:
        soup = BeautifulSoup(sb.get_page_source(), "html.parser")
        el = soup.find(attrs={"data-testid": "membership-number"})
        if not el:
            return None
        digits = re.sub(r"\D", "", el.get_text(" ", strip=True))
        return digits or None

    # ------------------------------------------------------------------ #
    # Page helpers
    # ------------------------------------------------------------------ #

    def _check_logged_in(self, sb) -> bool:
        try:
            current_url = sb.get_current_url().lower()
            if "login" in current_url or "pre-login" in current_url or "accounts.britishairways.com" in current_url:
                return False
            for selector in ("[data-testid='membership-number']",
                             "[data-testid='avios-card-value']",
                             "[data-testid='execAccountGreetingLabel']"):
                if sb.is_element_visible(selector):
                    return True
        except Exception as e:
            raise_if_window_closed(e)
        return False

    def _dismiss_cookie_consent(self, sb) -> None:
        for selector in ("#onetrust-reject-all-handler", "#ensCloseBanner", ".ot-pc-refuse-all-handler",
                         "button:contains('Reject All')", "#ensCancel"):
            try:
                if not sb.is_element_present(selector):
                    continue
                try:
                    if sb.is_element_visible(selector):
                        sb.click(selector)
                    else:
                        sb.js_click(selector)
                except Exception:
                    sb.js_click(selector)
                sb.sleep(1)
            except Exception as e:
                log(f"Cookie consent dismissal for {selector} failed: {e}", level="WARNING")

    def _parse_account_html(self, html: str) -> Optional[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")

        balance = None
        avios_card_val = soup.find(attrs={"data-testid": "avios-card-value"})
        if avios_card_val:
            val_text = "".join(filter(str.isdigit, avios_card_val.get_text(strip=True)))
            if val_text:
                balance = int(val_text)
        if balance is None:
            avios_match = re.search(r'(\d{1,3}(?:,\d{3})*)\s+Your Avios', soup.get_text(), re.I)
            if avios_match:
                balance = int(avios_match.group(1).replace(',', ''))
        if balance is None:
            return None

        status = "Blue"
        badge_el = soup.find(attrs={"data-testid": "membership-badge"})
        if badge_el:
            status = badge_el.get_text(strip=True).replace(" member", "").replace(" Member", "").strip()
        else:
            page_text = soup.get_text().lower()
            for tier in ("gold", "silver", "bronze"):
                if f"{tier} member" in page_text:
                    status = tier.capitalize()
                    break

        # BA does not show the inactivity clock; assume the full 36 months from now.
        expiration_date = add_months(datetime.now(), 36).strftime("%Y-%m-%dT00:00:00Z")

        return {
            "balance": balance,
            "status": status,
            "expiration_date": expiration_date,
        }
