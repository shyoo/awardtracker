"""Avis Preferred rewards, using the authenticated Rewards dashboard.

Avis fronts its session check with DataDome, which hard-blocks WebDriver
sessions and will not render its slider challenge in one, so sign-in happens
in the user's own Chrome (``interactive_mode = "native"``). Background sync
only reads that saved session; it must never submit credentials or trigger
another code. The sign-in lives partly in session cookies and the Rewards
tab's sessionStorage, which Chrome discards on close, so every Chrome on the
profile is started as a session restore (``restore_browser_session``) and the
sync reads Rewards in the restored tab. Avis's server may still expire the
session between syncs.
"""
import re
from typing import Any, Dict, Optional, Tuple

from bs4 import BeautifulSoup
from seleniumbase import SB

from .base import InteractionRequiredError, PluginError
from .browser_plugin import BrowserPlugin

# DataDome's "Access is temporarily restricted" / security-check overlay.
BOT_BLOCK_SELECTOR = 'iframe[src*="captcha-delivery.com"]'


class AvisPlugin(BrowserPlugin):
    login_url = "https://www.avis.com/en/avis-preferred/dashboard/rewards"
    native_login_url = "https://www.avis.com/en/avis-preferred/login"
    page_settle_seconds = 8

    interactive_mode = "native"
    # DataDome ties its cookie to the browser fingerprint seen at sign-in.
    lock_user_agent = True
    use_cookie_jar = True
    cookie_jar_name = "avis_cookies.json"
    # The sign-in lives in session cookies and the Rewards tab's sessionStorage,
    # both of which Chrome discards on close unless it restores the session.
    restore_browser_session = True
    # Load pages with the driver disconnected so DataDome does not see it.
    uc_reconnect_tries = 4

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
    def show_control_modal(self) -> bool:
        return False

    @property
    def interactive_login_instructions(self) -> dict:
        return {
            "mode": "manual",
            "credential_hint": "your Avis username and password, then the verification code",
            "special_note": (
                'Select "Remember me" on the Avis sign-in page. Once your account details '
                "appear, close Chrome so Award Tracker can check whether the session persists."
            ),
        }

    @property
    def interactive_login_hint(self) -> str:
        return ('Sign in with Interactive Login and select <strong class="text-amber-800">'
                '"Remember me"</strong>. Avis may still require another sign-in after Chrome closes.')

    def native_session_missing_message(self) -> str:
        return (
            "Avis did not keep the signed-in session after Chrome closed. "
            "The Rewards page could not be read; repeating Interactive Login may trigger another security check."
        )

    def sb_kwargs(self, profile_dir: Optional[str], headless: Optional[bool] = None) -> dict:
        # DataDome blocks headless Chrome outright, including the read that
        # follows the native sign-in, so every Avis session is visible.
        return super().sb_kwargs(profile_dir, headless=False)

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
        # A membership that earns an airline or hotel partner's miles instead
        # of Avis points shows the partner program and no gauge.
        partner = soup.select_one('[data-testid="manage-rewards_membership-details-partner-airline"]')
        partner_name = partner.get_text(" ", strip=True) if partner else ""
        if partner_name:
            if partner_name.isupper():
                partner_name = partner_name.title()
            return 0, f"{status} (earns {partner_name})", member_id
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

    @staticmethod
    def is_bot_blocked(html: str) -> bool:
        return BeautifulSoup(html, "html.parser").select_one(BOT_BLOCK_SELECTOR) is not None

    def open_login(self, sb) -> None:
        """Open Rewards; a DataDome block is reported as such, not as a sign-out."""
        super().open_login(sb)
        if self.is_bot_blocked(sb.get_page_source()):
            raise PluginError(
                "Avis's security check blocked this browser (\"Access is temporarily restricted\"). "
                "Wait before syncing again; if it persists, run Interactive Login."
            )

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
