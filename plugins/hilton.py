import re
from typing import Dict, Any, Tuple, Optional
from datetime import datetime
from bs4 import BeautifulSoup

from .base import PluginError, InteractionRequiredError, add_months
from .browser_plugin import BrowserPlugin
from .parsing import extract_latest_date


class HiltonHonorsPlugin(BrowserPlugin):
    login_url = "https://www.hilton.com/en/hilton-honors/login/"
    activity_url = "https://www.hilton.com/en/hilton-honors/guest/activity/"
    overview_url = "https://www.hilton.com/en/hilton-honors/guest/overview/"
    account_url = "https://www.hilton.com/en/hilton-honors/guest/my-account/"
    username_selector = "input[name='username']"
    password_selector = "input[name='password']"
    submit_selector = "button[type='submit']"
    uc_reconnect_tries = 4
    page_settle_seconds = 8
    post_login_settle_seconds = 10
    post_interactive_settle_seconds = 5

    @property
    def name(self) -> str:
        return "Hilton Honors"

    @property
    def plugin_id(self) -> str:
        return "hilton"

    @property
    def homepage_url(self) -> str:
        return "https://www.hilton.com/en/hilton-honors/"

    @property
    def logo_domain(self) -> str:
        return "hilton.com"

    @property
    def default_cpp(self) -> float:
        return 0.6

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        return add_months(last_activity_date, 24)

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Points expire after 24 months of inactivity. Any earning or redemption transaction extends them."

    def _extract_last_activity_date(self, html: str) -> Optional[datetime]:
        return extract_latest_date(html)

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Optional[datetime]]:
        """Extracts points balance, status, and last activity date from the Hilton DOM."""
        balance, status, last_activity_date = None, None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Extract Points using specific regex patterns
            patterns_points = [
                r'([\d,]+)\s*points\s*total',
                r'total\s*points[:\s]+([\d,]+)',
                r'([\d,]+)\s*hilton\s*honors\s*points',
                r'([\d,]+)\s*total\s*honors\s*points',
            ]
            # Try the raw source first, then the visible text with tags collapsed to spaces so a
            # label and value split across elements (<p>Total Points</p><p>123,809</p>) still match.
            for haystack in (html, soup.get_text(" ", strip=True)):
                for pat in patterns_points:
                    m = re.search(pat, haystack, re.IGNORECASE)
                    if m:
                        clean = m.group(1).replace(",", "").strip()
                        if clean.isdigit():
                            balance = int(clean)
                            break
                if balance is not None:
                    break

            # Fallback to leaf DOM elements if regex didn't match
            if balance is None:
                for el in soup.find_all(["p", "span", "h1", "h2", "h3", "div"]):
                    if not el.find_all(True):  # Leaf node
                        text = el.get_text(strip=True)
                        if "points total" in text.lower() and len(text) < 30:
                            m = re.search(r'[\d,]+', text)
                            if m:
                                clean = m.group(0).replace(",", "").strip()
                                if clean.isdigit():
                                    balance = int(clean)
                                    break
                        
            # 2. Extract Status
            status = self._extract_status(soup)

            # 3. Extract Last Activity Date
            last_activity_date = self._extract_last_activity_date(html)
                
        except Exception:
            pass
            
        return balance, status, last_activity_date

    # Ordered highest-to-lowest so multi-word tiers are matched before their prefix ("Diamond Reserve" before "Diamond").
    STATUS_TIERS = ["Diamond Reserve", "Diamond", "Gold", "Silver", "Member"]

    def _extract_status(self, soup) -> Optional[str]:
        """Extracts the member's elite tier from the rendered Hilton DOM.

        Only visible text is considered: the raw page source embeds marketing copy and analytics
        JSON (e.g. "give the gift of Gold status to a family member") that previously caused a
        Diamond member to be reported as Gold (Issue #135). Known layouts:
          * overview hero:      <h1>Diamond</h1>
          * nav drawer:         <p class="capitalize"><span>Silver</span> Status</p>
          * activity header:    <div class="heading--sm">Silver member</div>
        """

        visible = BeautifulSoup(str(soup), "html.parser")
        for tag in visible.find_all(["script", "style", "noscript", "template"]):
            tag.decompose()

        def _match_exact(text: str) -> Optional[str]:
            t = re.sub(r'\s+', ' ', text).strip().lower()
            for tier in self.STATUS_TIERS:
                tl = tier.lower()
                if t in (tl, f"{tl} status", f"{tl} member", f"{tl} tier"):
                    return tier
            return None

        # Pass A: an element whose entire text is the tier label (hero heading, nav drawer, activity header).
        for el in visible.find_all(["h1", "h2", "h3", "h4", "p", "span", "div"]):
            found = _match_exact(el.get_text(" ", strip=True))
            if found:
                return found

        # Pass B: "<Tier> Status" / "<Tier> Tier" phrase anywhere in the visible text.
        text = visible.get_text(" ", strip=True)
        tiers_alt = "|".join(re.escape(t) for t in self.STATUS_TIERS)
        m = re.search(r'\b(' + tiers_alt + r')\s+(?:Status|Tier)\b', text, re.IGNORECASE)
        if m:
            return m.group(1).title()
        return None

    def _extract_member_number(self, html: str) -> Optional[str]:
        """Extracts Hilton Honors membership number from the account page HTML."""
        m = re.search(r'Hilton\s+Honors\s*#?\s*(\d{7,12})', html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r'(?:Honors|Account)\s*#\s*(\d{7,12})', html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def _parse_free_night_awards(self, html: str) -> list:
        """Extracts unredeemed Free Night Certificates from the Rewards section of the my-account page."""

        soup = BeautifulSoup(html, "html.parser")
        certificates = []

        # Only the "Current rewards" tab (Ready to use / Reserved for upcoming stay) holds
        # certificates still available to use; the "Used rewards" tab is intentionally skipped.
        current_tab = soup.find(id="tab-panel-currentRewards")
        if not current_tab:
            return certificates

        for card in current_tab.find_all("div", attrs={"data-testid": "award-card-FNC"}):
            name_el = card.find("h4")
            name = name_el.get_text(strip=True) if name_el else "Hilton Free Night Certificate"

            card_text = card.get_text(" ", strip=True)

            details = {}
            cert_match = re.search(r'Certificate\s*#\s*([•\d\s]+\d)', card_text)
            if cert_match:
                details["Certificate #"] = re.sub(r'\s+', ' ', cert_match.group(1)).strip()

            expiration_date = None
            valid_match = re.search(r'Valid until\s+(\d{1,2}/\d{1,2}/\d{4})', card_text)
            if valid_match:
                try:
                    dt = datetime.strptime(valid_match.group(1), "%m/%d/%Y")
                    expiration_date = dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass

            certificates.append({
                "name": name,
                "expiration_date": expiration_date,
                "details": details
            })

        return certificates

    def extract_membership_id(self, sb) -> Optional[str]:
        return self._extract_member_number(sb.get_page_source())

    def is_logged_in(self, sb) -> bool:
        """Hilton redirects a signed-in visitor straight to an account page that shows the balance."""
        balance, _, _ = self._extract_data(sb)
        return balance is not None

    def fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        if not sb.is_element_visible(self.username_selector):
            sb.sleep(3)
        if not sb.is_element_visible(self.username_selector):
            raise InteractionRequiredError("Could not find Hilton login form, might be blocked by captcha or layout changed.")

        sb.wait_for_element_visible(self.username_selector, timeout=10)
        try:
            sb.type(self.username_selector, username)
        except Exception:
            pass
        sb.sleep(0.5)

        sb.wait_for_element_visible(self.password_selector, timeout=10)
        try:
            sb.type(self.password_selector, password)
        except Exception:
            pass
        sb.sleep(0.5)

        if auto_submit:
            if sb.is_element_visible(self.submit_selector):
                try:
                    sb.click(self.submit_selector)
                except Exception:
                    sb.type(self.password_selector, "\n")
            else:
                sb.type(self.password_selector, "\n")

    def scrape(self, sb) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }

        # Free Night Certificates live on the account page, which login often lands on;
        # grab them now to save a round-trip later.
        certificates_captured = False
        if "my-account" in sb.get_current_url():
            try:
                result["certificates"] = self._parse_free_night_awards(sb.get_page_source())
                certificates_captured = True
            except Exception:
                pass

        # The activity page carries the balance, tier and the transactions that
        # decide the last-activity date.
        if "activity" not in sb.get_current_url():
            self.open_url(sb, self.activity_url, settle=8)

        balance, status, last_activity = self._extract_data(sb)
        if balance is None:
            sb.refresh()
            sb.sleep(8)
            balance, status, last_activity = self._extract_data(sb)

        if balance is None:
            self.open_url(sb, self.overview_url, settle=8)
            overview_balance, overview_status, _ = self._extract_data(sb)
            if overview_balance is not None:
                balance = overview_balance
                status = status or overview_status

        if balance is None:
            raise PluginError("Could not find points on Hilton activity page after login.")

        result["balance"] = balance
        if status:
            result["status"] = status
        if last_activity:
            result["last_activity_date"] = last_activity
        elif balance > 0:
            result["expiration_meta"] = {
                "at_risk": True,
                "reason": "No activity recorded in the last 12 months"
            }

        member_num = self._extract_member_number(sb.get_page_source())
        if member_num:
            result["membership_id"] = member_num

        if not certificates_captured:
            try:
                self.open_url(sb, self.account_url, settle=8)
                result["certificates"] = self._parse_free_night_awards(sb.get_page_source())
            except Exception:
                pass

        return result
