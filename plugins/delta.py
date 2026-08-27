from typing import Dict, Any, Optional, Tuple
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs
from seleniumbase import SB
from bs4 import BeautifulSoup
import re
import time

class DeltaSkyMilesPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Delta SkyMiles"

    @property
    def plugin_id(self) -> str:
        return "delta"

    @property
    def default_cpp(self) -> float:
        return 1.2

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Miles in this program never expire."

    def _dismiss_cookie_banners(self, sb) -> None:
        try:
            sb.execute_script("""
                ['onetrust-banner-sdk','onetrust-consent-sdk','ot-pc-content'].forEach(id => {
                    const el = document.getElementById(id); if (el) el.remove();
                });
                const ov = document.querySelector('.onetrust-pc-dark-filter');
                if (ov) ov.remove();
            """)
        except Exception:
            pass
        for sel in ["button#onetrust-accept-btn-handler", "button#accept-recommended-btn-handler",
                    "button#accept-all", "button:contains('Accept All')"]:
            try:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.sleep(0.5)
            except Exception:
                pass

    def _extract_balance_status(self, html: str) -> Tuple[Optional[int], str]:
        """Parses SkyMiles balance and tier status from dashboard HTML."""
        soup = BeautifulSoup(html, "html.parser")

        balance = None
        status = "Member"

        # For Delta, the balance is usually under a class or nearby "Miles Available"
        mile_texts = soup.find_all(string=re.compile(r"Miles Available|Available Miles|Total Miles|SkyMiles Balance", re.I))
        for mt in mile_texts:
            parent = mt.parent
            if parent and parent.parent:
                text_content = parent.parent.text.strip()
                # specifically exclude 10-digit account numbers from the match
                matches = re.findall(r"(?:^|\s|AVAILABLE\s*)([\d,]{2,})(?:\s|$)", text_content)
                for m in matches:
                    clean_m = m.replace(",", "")
                    if len(clean_m) != 10: # Account numbers are 10 digits
                        balance = int(clean_m)
                        break
            if balance is not None:
                break

        if balance is None:
            # Try looking for specific classes found in Delta's Angular application
            possible_elements = soup.find_all(class_=re.compile(r"mile.*val|balance.*val|skymiles-balance|skymiles-wrapper__subtitle|content__number", re.I))
            for elem in possible_elements:
                parent_text = elem.parent.text.upper() if elem.parent else ""
                if "LIFETIME" in parent_text:
                    continue # Skip lifetime miles

                text = elem.text.strip()
                matches = re.findall(r"([\d,]+)", text)
                if matches:
                    clean_m = matches[0].replace(",", "")
                    if len(clean_m) != 10:
                        balance = int(clean_m)
                        break

        return balance, status

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir)) as sb:
            try:
                # Delta login page
                sb.open("https://www.delta.com/skymiles/login")
                sb.sleep(3)
                self._dismiss_cookie_banners(sb)
                
                # Check if we are already logged in
                current_url = sb.get_current_url()
                if "myskymiles" not in current_url.lower():
                    # Need to log in
                    if sb.is_element_visible("input#userId-input"):
                        sb.type("input#userId-input", username)
                        sb.type("input#password-input", password)
                        sb.sleep(1)
                        sb.click("button.login-screen__submit-button, button[type='submit']")
                        
                        # Wait for login to complete or profile picker
                        print("Waiting for Delta login...")
                        for _ in range(15):
                            current_url = sb.get_current_url().lower()
                            if "myskymiles/overview" in current_url or sb.is_element_visible("div.dashboard-container"):
                                break
                                
                            # Handle profile picker page if it appears
                            if "profilepicker" in current_url:
                                print("Profile picker page detected. Attempting to select profile.")
                                sb.sleep(3) # Give it a moment to render
                                self._dismiss_cookie_banners(sb)
                                try:
                                    clicked = False
                                    # Find all buttons and click the first visible one that isn't a utility button
                                    buttons = sb.find_elements("button, a")
                                    for b in buttons:
                                        if not b.is_displayed():
                                            continue
                                            
                                        btext = b.text.strip().lower()
                                        if not btext:
                                            continue
                                            
                                        # Skip common utility buttons
                                        if any(skip in btext for skip in ["skip", "close", "cancel", "back", "log in", "login"]):
                                            continue
                                            
                                        # If we find a button with substantial text (like a name), or one that says 'personal', it's likely the right one
                                        print(f"Found potential profile button/link: '{b.text}'")
                                        
                                        # Delta sometimes uses a div/button combo for the card. We'll just click it.
                                        try:
                                            b.click()
                                        except Exception:
                                            try:
                                                sb.execute_script("arguments[0].click();", b)
                                            except Exception as js_e:
                                                print(f"Failed JavaScript click on profile button: {js_e}")
                                        clicked = True
                                        break
                                
                                    sb.sleep(2)
                                    # Often there's a submit/continue button after selection
                                    if sb.is_element_visible('button:contains("Continue")'):
                                        try:
                                            sb.click('button:contains("Continue")')
                                        except Exception:
                                            try:
                                                sb.execute_script("arguments[0].click();", sb.find_element('button:contains("Continue")'))
                                            except Exception:
                                                pass
                                    elif sb.is_element_visible('button[type="submit"]'):
                                        try:
                                            sb.click('button[type="submit"]')
                                        except Exception:
                                            try:
                                                sb.execute_script("arguments[0].click();", sb.find_element('button[type="submit"]'))
                                            except Exception:
                                                pass
                                    
                                    sb.sleep(2)
                                except Exception as inner_e:
                                    print(f"Error handling profile picker: {inner_e}")
                                    
                            sb.sleep(2)
                            
                # If we're not on the dashboard after the wait loop, force navigation
                current_url = sb.get_current_url().lower()
                if "myskymiles" not in current_url and "myprofile" not in current_url:
                    print("Navigating to overview page directly...")
                    sb.open("https://www.delta.com/myskymiles/overview")
                    sb.sleep(5)
                    self._dismiss_cookie_banners(sb)
                
                # Now we should be on the dashboard or similar
                sb.sleep(5)  # Allow data to load
                html = sb.get_page_source()
                with open("delta_dashboard_debug.html", "w", encoding="utf-8") as f:
                    f.write(html)

                balance, status = self._extract_balance_status(html)

                if balance is None:
                    raise PluginError("Could not find SkyMiles balance on the Delta dashboard. Check delta_dashboard_debug.html")

                return {
                    "balance": balance,
                    "status": status,
                    "expiration_date": None
                }
            except Exception as e:
                raise PluginError(f"Delta scraping failed: {e}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> Optional[Dict[str, Any]]:
        with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir)) as sb:
            # Go straight to the real login page and pre-fill credentials, matching
            # fetch_data() -- opening the plain homepage (the previous approach)
            # left the user on a page with no visible login form and nothing
            # pre-filled, with no indication of what to do next.
            sb.open("https://www.delta.com/skymiles/login")
            sb.sleep(3)
            self._dismiss_cookie_banners(sb)

            try:
                if sb.is_element_visible("input#userId-input"):
                    sb.type("input#userId-input", username)
                    sb.type("input#password-input", password)
            except Exception as e:
                print(f"Error pre-filling Delta credentials: {e}")

            # Wait for the user to leave the login page. Requiring a specific
            # post-login URL (the previous approach) doesn't work reliably --
            # reported live: after a real login, Delta redirected back to the
            # plain homepage rather than any profile/dashboard URL, which never
            # matched, so the loop just timed out silently. Leaving the login
            # page at all is a much weaker but more reliable signal; the actual
            # overview page is force-navigated to unconditionally afterward,
            # matching fetch_data()'s own reliable pattern.
            print("Please log in manually. Waiting for login to complete...")
            success = False
            try:
                for _ in range(60):  # Wait up to 5 minutes
                    current_url = sb.get_current_url().lower()
                    if "skymiles/login" not in current_url:
                        print(f"Left login page, now at: {current_url}")
                        sb.sleep(3) # allow page to load
                        success = True
                        break
                    sb.sleep(5)
            except Exception as e:
                print(f"Interactive login wait interrupted: {e}")

            if not success:
                return None

            try:
                # Wherever login redirected to isn't necessarily the scrapeable
                # balance page, so navigate to the overview page directly,
                # matching fetch_data()'s fallback.
                current_url = sb.get_current_url().lower()
                if "myskymiles" not in current_url and "myprofile" not in current_url:
                    print("Navigating to overview page directly...")
                    sb.open("https://www.delta.com/myskymiles/overview")
                    sb.sleep(5)
                    self._dismiss_cookie_banners(sb)

                sb.sleep(5)  # Allow data to load
                html = sb.get_page_source()
                balance, status = self._extract_balance_status(html)
            except PluginError:
                raise
            except Exception as e:
                raise PluginError(f"Logged in successfully, but failed to read SkyMiles balance: {e}")

            if balance is None:
                raise PluginError("Logged in successfully, but could not find SkyMiles balance on the Delta dashboard.")

            return {
                "balance": balance,
                "status": status,
                "expiration_date": None
            }
