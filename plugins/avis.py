"""Avis Preferred rewards, using the authenticated Rewards dashboard.

Avis may require a one-time code during sign-in. Background sync only reads an
existing session; it must never submit credentials or trigger another code.
"""
import re
from typing import Any, Dict, Optional, Tuple

from bs4 import BeautifulSoup
from seleniumbase import SB

from .base import InteractionRequiredError, PluginError
from .browser_plugin import BrowserPlugin


class AvisPlugin(BrowserPlugin):
    login_url = "https://www.avis.com/en/avis-preferred/dashboard/rewards"
    username_selector = "input[placeholder*='Username'], input[name='username'], input[type='email']"
    password_selector = "input[type='password']"
    page_settle_seconds = 5
    use_cookie_jar = True
    cookie_jar_name = "avis_cookies.json"

    @property
    def name(self) -> str:
        return "Avis Preferred"

    @property
    def plugin_id(self) -> str:
        return "avis"

    @property
    def homepage_url(self) -> str:
        return "https://www.avis.com/en/loyalty-profile/avis-preferred"

    @property
    def logo_domain(self) -> str:
        return "avis.com"

    @property
    def default_cpp(self) -> float:
        return 1.0

    @property
    def interactive_login_required(self) -> bool:
        return True

    @property
    def interactive_login_instructions(self) -> dict:
        return {
            "mode": "assisted",
            "credential_hint": "your Avis username and password",
            "pre_submit_note": (
                "Avis may show separate username, password, and verification pages. "
                "Complete each page yourself, enter any code only once, then open "
                "Rewards to finish syncing."
            ),
        }

    @property
    def interactive_login_hint(self) -> str:
        return "Avis may request a verification code. Use Interactive Login and open Rewards after signing in."

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Avis Preferred points expiration is not calculated automatically. Check your Avis account for current terms."

    @staticmethod
    def parse_rewards(html: str) -> Optional[Tuple[int, str, str]]:
        """Read the points view or Avis's newly enrolled Rewards view."""
        soup = BeautifulSoup(html, "html.parser")
        member = soup.select_one('[data-testid="avis-preferred-member-label"]')
        points = soup.select_one('[data-testid="gauge-points-value"]')
        if member is not None:
            label = member.get_text(" ", strip=True)
            match = re.fullmatch(r"Avis\s+(.+?)\s+Member\s*:\s*#?\s*([A-Za-z0-9]+)", label, re.I)
            if not match:
                return None
            status = re.sub(r"\s+", " ", match.group(1)).strip()
            member_id = match.group(2)
        else:
            # The current account layout uses a card above the Rewards section.
            if soup.select_one('[data-testid="manage-rewards_page"]') is None:
                return None
            tier = soup.select_one('[data-testid="loyalty-tier-label"]')
            wizard = soup.select_one('[data-testid="wizard-number"]')
            if tier is None or wizard is None:
                return None
            status = tier.get_text(" ", strip=True)
            member_id = wizard.get_text(" ", strip=True)
            if status.isupper():
                status = status.title()
        if not status or not re.fullmatch(r"[A-Za-z0-9]+", member_id):
            return None

        if points is not None:
            balance_text = points.get_text("", strip=True)
            if not re.fullmatch(r"[\d,]+", balance_text):
                return None
            return int(balance_text.replace(",", "")), status, member_id

        # A newly enrolled account shows a membership card and welcome alert,
        # but no gauge. That explicit state represents no earned Avis points.
        welcome = soup.select_one('[data-testid="rewards-loyalty-tier-welcome-alert-description"]')
        if welcome and "successfully enrolled in Avis Preferred" in welcome.get_text(" ", strip=True):
            return 0, status, member_id
        return None

    def is_logged_in(self, sb) -> bool:
        html = sb.get_page_source()
        if self.parse_rewards(html) is not None:
            return True
        soup = BeautifulSoup(html, "html.parser")
        return all(soup.select_one(selector) is not None for selector in (
            '[data-testid="manage-rewards_page"]',
            '[data-testid="loyalty-tier-label"]',
            '[data-testid="wizard-number"]',
        ))

    def fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        if auto_submit:
            raise InteractionRequiredError(self.mfa_message())
        # Avis can present username and password on separate pages. Fill only
        # fields currently shown; the user advances each step and handles MFA.
        for selector, value in ((self.username_selector, username), (self.password_selector, password)):
            if sb.is_element_visible(selector):
                sb.type(selector, value)

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        """Read a saved session once. Never initiate a login in a scheduled run."""
        try:
            with SB(**self.sb_kwargs(profile_dir)) as sb:
                self.restore_session(sb, profile_dir)
                self.open_login(sb)
                if not self.is_logged_in(sb):
                    raise InteractionRequiredError(self.login_failed_message())
                return self.finish(sb, profile_dir, self.scrape(sb))
        except (InteractionRequiredError, PluginError):
            raise
        except Exception as exc:
            raise PluginError(f"Avis Preferred sync failed: {exc}") from exc

    def scrape(self, sb) -> Dict[str, Any]:
        html = sb.get_page_source()
        parsed = self.parse_rewards(html)
        if parsed is None:
            if self.is_logged_in(sb):
                raise PluginError("Avis Rewards is signed in but does not show an available points balance.")
            raise InteractionRequiredError(self.mfa_message())
        balance, status, member_id = parsed
        return {
            "balance": balance,
            "status": status,
            "membership_id": member_id,
            "expiration_date": None,
            "certificates": [],
        }
