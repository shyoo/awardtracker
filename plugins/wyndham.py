from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from bs4 import BeautifulSoup
import time

class WyndhamRewardsPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Wyndham Rewards"

    @property
    def plugin_id(self) -> str:
        return "wyndham"

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str]]:
        """Extracts points balance and tier status from the Wyndham Rewards account DOM."""
        balance, status = None, None

        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")

            balance_selectors = [
                "span.member-points",
                "[class*='member-points']",
                "[class*='points-balance']",
                "[class*='pointsBalance']",
                "[class*='points-total']",
                "[data-testid*='points']",
            ]
            for sel in balance_selectors:
                try:
                    for el in soup.select(sel):
                        text = el.get_text().strip()
                        if not text or len(text) > 40:
                            continue
                        # Skip obvious template placeholders
                        if any(p in text.lower() for p in ("user points", "{{", "}}")):
                            continue
                        # Must actually mention points to avoid grabbing unrelated numbers
                        if "point" not in text.lower():
                            continue
                        clean_points = "".join(filter(str.isdigit, text))
                        if clean_points:
                            balance = int(clean_points)
                            break
                except Exception:
                    pass
                if balance is not None:
                    break

            if balance is None:
                # Fallback: scan all short text nodes for "X,XXX points"
                for el in soup.find_all(["span", "div", "p", "strong", "h1", "h2", "h3"]):
                    text = el.get_text().strip()
                    if "point" in text.lower() and len(text) < 40:
                        clean_points = "".join(filter(str.isdigit, text))
                        if clean_points:
                            balance = int(clean_points)
                            break

            # 2. Extract tier status (Blue, Gold, Platinum, Diamond).
            status = "Blue"
            tiers = ["Diamond", "Platinum", "Gold", "Blue"]
            status_selectors = [
                "span.user-memberlevel",
                "[class*='user-memberlevel']",
                "[class*='member-tier']",
                "[class*='memberTier']",
                "[class*='tier-level']",
            ]
            found_status = False
            for sel in status_selectors:
                try:
                    for elem in soup.select(sel):
                        # Skip the "next level" goal tracker and the static tier ladder
                        cls = " ".join(elem.get("class") or []).lower()
                        if any(bad in cls for bad in ("next-level", "level-container", "tracker")):
                            continue
                        txt = elem.get_text(strip=True).lower()
                        if len(txt) > 60:
                            continue
                        for tier in tiers:
                            if tier.lower() in txt:
                                status = tier
                                found_status = True
                                break
                        if found_status:
                            break
                except Exception:
                    pass
                if found_status:
                    break
        except Exception:
            pass

        return balance, status

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the Wyndham Rewards sign-in form, selects 'Remember Me', and submits."""
        user_selector = "input[name='username']"
        pass_selector = "input[name='password']"

        # Wait for the login form to render; try common fallbacks if needed
        if not sb.is_element_visible(user_selector):
            for cand in ("input#username", "input[type='email']", "input[name='email']", "input[autocomplete='username']"):
                try:
                    if sb.is_element_visible(cand):
                        user_selector = cand
                        break
                except Exception:
                    pass
            try:
                sb.wait_for_element_visible(user_selector, timeout=15)
            except Exception:
                raise InteractionRequiredError("Could not find Wyndham login form, might be blocked by captcha or layout changed.")

        try:
            sb.type(user_selector, username)
        except Exception:
            pass
        sb.sleep(0.5)

        try:
            sb.wait_for_element_visible(pass_selector, timeout=10)
        except Exception:
            for cand in ("input#password", "input[autocomplete='current-password']"):
                try:
                    if sb.is_element_visible(cand):
                        pass_selector = cand
                        break
                except Exception:
                    pass
        try:
            sb.type(pass_selector, password)
        except Exception:
            pass
        sb.sleep(0.5)

        # JS Fallback to ensure framework state (React/Angular) registers the values
        try:
            user_el = sb.find_element(user_selector)
            pass_el = sb.find_element(pass_selector)

            sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)

            sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", pass_el)
        except Exception:
            pass

        # Try to select a "Remember Me" / "Keep me signed in" checkbox so cookies persist longer
        for remember_selector in (
            "input[name='rememberMe']",
            "input[id*='remember']",
            "input[name*='remember']",
            "input[id*='keepSignedIn']",
        ):
            try:
                if sb.is_element_visible(remember_selector) and not sb.is_selected(remember_selector):
                    sb.click(remember_selector)
                    break
            except Exception:
                pass

        if auto_submit:
            submitted = False
            for submit_selector in (
                "button[type='submit']",
                "input[type='submit']",
                "button[id*='signin']",
                "button[id*='login']",
            ):
                try:
                    if sb.is_element_visible(submit_selector):
                        try:
                            sb.click(submit_selector)
                        except Exception:
                            btn = sb.find_element(submit_selector)
                            sb.execute_script("arguments[0].click();", btn)
                        submitted = True
                        break
                except Exception:
                    pass
            if not submitted:
                try:
                    sb.type(pass_selector, "\n")
                except Exception:
                    pass

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }

        SIGNIN_URL = "https://www.wyndhamhotels.com/wyndham-rewards/login"
        ACCOUNT_URL = "https://www.wyndhamhotels.com/wyndham-rewards/account/summary"

        try:
            with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
                # 1. Open the sign-in URL. If cookies are still valid, Wyndham redirects to the account dashboard.
                sb.uc_open_with_reconnect(SIGNIN_URL, 4)
                sb.sleep(10)  # Let dynamic elements render if redirected

                curr_url = sb.get_current_url()
                if "login" not in curr_url and "signin" not in curr_url:
                    balance, status = self._extract_data(sb)
                    if balance is not None:
                        result["balance"] = balance
                        if status:
                            result["status"] = status
                        return result

                # 2. Not logged in -> fill login form
                self._fill_login_form(sb, username, password, auto_submit=True)

                # 3. Wait for redirect to finish
                sb.sleep(10)

                # Force navigate to account summary if not redirected there
                if "account" not in sb.get_current_url():
                    sb.open(ACCOUNT_URL)
                    sb.sleep(10)

                # 4. Extract data
                balance, status = self._extract_data(sb)
                if balance is None:
                    # Fallback refresh in case of slow client-side rendering
                    sb.refresh()
                    sb.sleep(8)
                    balance, status = self._extract_data(sb)

                if balance is None:
                    with open("wyndham_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find points on Wyndham Rewards dashboard after login.")

                result["balance"] = balance
                if status:
                    result["status"] = status
                return result

        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        """
        Opens an interactive browser window for the user to resolve MFA.
        Uses the same user_data_dir so cookies are saved for future headless runs.
        Once the user completes sign-in, automatically navigates to the Wyndham
        Rewards account summary page and closes the window.
        """
        SIGNIN_URL = "https://www.wyndhamhotels.com/wyndham-rewards/login"
        ACCOUNT_URL = "https://www.wyndhamhotels.com/wyndham-rewards/account/summary"

        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.uc_open_with_reconnect(SIGNIN_URL, 4)
            sb.sleep(3)

            # Prefill credentials if the sign-in form is visible
            try:
                self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass

            # Wait up to 5 minutes for the user to complete sign-in / MFA.
            # Success is detected as soon as Wyndham redirects away from the login URL.
            start_time = time.time()
            signed_in = False
            while time.time() - start_time < 300:
                try:
                    curr_url = sb.get_current_url()
                except Exception:
                    time.sleep(2)
                    continue

                if ("login" not in curr_url and "signin" not in curr_url
                        and "wyndhamhotels.com" in curr_url):
                    signed_in = True
                    break

                time.sleep(2)

            if not signed_in:
                raise PluginError("Interactive login timed out after 5 minutes.")

            # Navigate to account summary so fetch_data can work headlessly next time
            if "account" not in sb.get_current_url():
                sb.open(ACCOUNT_URL)
                sb.sleep(8)

            # Confirm we can read the balance (validates the session is live)
            balance, _ = self._extract_data(sb)
            if balance is None:
                sb.refresh()
                sb.sleep(8)
                balance, _ = self._extract_data(sb)

            # Let cookies flush to disk before closing
            sb.sleep(3)

            if balance is None:
                raise PluginError("Interactive login completed but could not read points balance on account summary.")
