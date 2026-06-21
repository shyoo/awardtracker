from typing import Dict, Any, Tuple, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from bs4 import BeautifulSoup
import time
import re

class AmericanAirlinesPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "American Airlines"

    @property
    def plugin_id(self) -> str:
        return "american"

    @property
    def default_cpp(self) -> float:
        return 1.5

    @property
    def custom_tip(self) -> str:
        return "Check your email or phone for the <strong>\"Verification Code\"</strong>."

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        from .base import add_months
        return add_months(last_activity_date, 24)

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Miles expire after 24 months of inactivity. Any earning or redemption transaction extends them. Primary credit cardmembers' miles do not expire."

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Optional[Any], Optional[Any]]:
        """Extracts AAdvantage miles balance, status tier, expiration_date, and last_activity_date from AA profile summary."""
        balance, status = None, None
        expiration_date, last_activity_date = None, None
        
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            text_content = soup.get_text()
            
            # 1. Search for miles balance in the DOM
            # Look for spans, divs, strong tags containing the word "miles"
            candidates = []
            for el in soup.find_all(["span", "div", "p", "strong", "h1", "h2", "h3", "a"]):
                text = el.get_text().strip()
                if "miles" in text.lower() and len(text) < 45:
                    # Clean points digits
                    clean_points = "".join(filter(str.isdigit, text))
                    if clean_points:
                        candidates.append((int(clean_points), text))
            
            if candidates:
                # Prioritize first or largest number
                balance = candidates[0][0]
                
            # 2. Extract elite status tier (avoiding promotional/marketing texts on the page)
            status = "Member"
            anchors = []
            for el in soup.find_all(["span", "div", "p", "strong", "h1", "h2", "h3", "a"]):
                text = el.get_text().strip().lower()
                if not text:
                    continue
                if (
                    ("aadvantage" in text and "#" in text)
                    or "aadvantage number" in text
                    or "aadv #" in text
                    or "loyalty points" in text
                ):
                    anchors.append(el)

            found_tier = None
            for anchor in anchors:
                curr = anchor
                for _ in range(3):
                    if not curr.parent:
                        break
                    curr = curr.parent
                    if curr.name in ["body", "html"]:
                        break
                    container_text = curr.get_text().strip()
                    if len(container_text) < 1500:
                        container_text_lower = container_text.lower()
                        # Skip containers describing status goals or progress to next tier
                        skip_keywords = ["goal", "next", "progress", "reach", "earn", "needed", "to go", "miles to"]
                        if any(kw in container_text_lower for kw in skip_keywords):
                            continue

                        for tier in ["ConciergeKey", "Executive Platinum", "Platinum Pro", "Platinum", "Gold"]:
                            tier_lower = tier.lower()
                            if tier_lower in container_text_lower:
                                found_tier = tier
                                break
                    if found_tier:
                        break
                if found_tier:
                    break

            if found_tier:
                status = found_tier

            # 3. Extract explicit expiration text or exemption
            import datetime as dt
            has_no_expiration = False
            no_expiration_keywords = [
                "no miles expiration",
                "no expiration",
                "miles do not expire",
                "miles never expire",
                "never expire"
            ]
            for kw in no_expiration_keywords:
                if kw in text_content.lower():
                    has_no_expiration = True
                    break

            if has_no_expiration:
                expiration_date = None
                last_activity_date = None
            else:
                expire_matches = re.findall(r'(?:expire[s]?|expir\w*)\s+(?:on|by)?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{2}/\d{2}/\d{4})', text_content, re.IGNORECASE)
                if expire_matches:
                    date_str = expire_matches[0]
                    try:
                        expiration_date = dt.datetime.strptime(date_str, "%B %d, %Y")
                    except ValueError:
                        try:
                            expiration_date = dt.datetime.strptime(date_str, "%b %d, %Y")
                        except ValueError:
                            try:
                                expiration_date = dt.datetime.strptime(date_str, "%m/%d/%Y")
                            except ValueError:
                                pass

                # 4. Extract latest transaction / activity date (only if not already resolved)
                if expiration_date:
                    last_activity_date = None
                else:
                    parsed_dates = []
                    date_patterns = [
                        r'\b([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})\b', # e.g. Jan 15, 2026
                        r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b'            # e.g. 01/15/2026
                    ]
                    
                    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                    for pattern in date_patterns:
                        for match in re.finditer(pattern, text_content):
                            d_str = match.group(0)
                            try:
                                p_date = None
                                if "," in d_str:
                                    p_date = dt.datetime.strptime(d_str, "%b %d, %Y")
                                else:
                                    p_date = dt.datetime.strptime(d_str, "%m/%d/%Y")
                                
                                if p_date and p_date <= now and p_date.year >= 2020:
                                    parsed_dates.append(p_date)
                            except ValueError:
                                try:
                                    p_date = dt.datetime.strptime(d_str, "%B %d, %Y")
                                    if p_date and p_date <= now and p_date.year >= 2020:
                                        parsed_dates.append(p_date)
                                except ValueError:
                                    pass
                    
                    if parsed_dates:
                        # Latest past date
                        last_activity_date = max(parsed_dates)
                
        except Exception:
            pass
            
        return balance, status, expiration_date, last_activity_date

    def _type_in_shadow(self, sb, host_selector: str, value: str) -> None:
        """Types into a custom Aileron Design System (adc-text-input) web component shadow DOM."""
        sb.execute_script(f"""
            let host = document.querySelector('{host_selector}');
            if (host && host.shadowRoot) {{
                let inp = host.shadowRoot.querySelector('input');
                if (inp) {{
                    inp.value = '{value}';
                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }}
        """)

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills AA login form containing custom Aileron Web Components."""
        user_selector = "adc-text-input#username"
        pass_selector = "adc-text-input#password"
        
        sb.wait_for_element_visible(user_selector, timeout=20)
        
        # Type username into web component shadow input
        self._type_in_shadow(sb, user_selector, username)
        sb.sleep(0.5)
        
        # Type password into web component shadow input
        self._type_in_shadow(sb, pass_selector, password)
        sb.sleep(0.5)
        
        if auto_submit:
            # Click the primary submit button in the shadow host or regular host
            try:
                # First try direct click on Aileron button
                if sb.is_element_visible("adc-button"):
                    sb.click("adc-button")
                else:
                    sb.execute_script("document.querySelector('adc-button').shadowRoot.querySelector('button').click()")
            except Exception:
                try:
                    sb.click("adc-button")
                except Exception:
                    pass
            sb.sleep(2)

    def _check_for_mfa(self, sb) -> bool:
        """Helper to detect if American Airlines is presenting an MFA passcode/OTP challenge."""
        try:
            curr_url = sb.get_current_url().lower()
            if "account-summary" in curr_url and not sb.is_element_visible("adc-text-input#username"):
                # Successfully logged in, definitely not stuck on MFA
                return False
        except Exception:
            pass

        mfa_selectors = (
            "input#code, input[name='code'], input[name='otp'], input[name='verificationCode'], "
            "input[id*='code' i], input[name*='code' i], input[placeholder*='code' i], "
            "adc-text-input#verification-code, adc-text-input[id*='code' i]"
        )
        mfa_visible = False
        try:
            mfa_visible = sb.is_element_visible(mfa_selectors)
        except Exception:
            pass
            
        mfa_text_detected = False
        try:
            text_content = sb.get_page_source().lower()
            mfa_keywords = [
                "verification code", "verify your identity", "one-time passcode", "security code",
                "enter code", "six-digit", "6-digit", "temporary code", "one-time code"
            ]
            if any(kw in text_content for kw in mfa_keywords):
                mfa_text_detected = True
        except Exception:
            pass
            
        return mfa_visible or mfa_text_detected

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Member",
            "expiration_date": None,
            "certificates": []
        }
        
        try:
            with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
                # 1. Open American Airlines summary page directly
                sb.open("https://www.aa.com/aadvantage-program/profile/account-summary")
                sb.sleep(12)
                
                # Check cookie banner and accept to clear overlay click interception
                cookie_btn = "#accept-recommended-btn-handler"
                try:
                    if sb.is_element_visible(cookie_btn):
                        sb.click(cookie_btn)
                        sb.sleep(1)
                except Exception:
                    pass

                # Check if we are already logged in
                curr_url = sb.get_current_url()
                if "account-summary" in curr_url and not sb.is_element_visible("adc-text-input#username"):
                    balance, status, exp_date, last_act = self._extract_data(sb)
                    if balance is not None:
                        result["balance"] = balance
                        if status:
                            result["status"] = status
                        result["expiration_date"] = exp_date
                        result["last_activity_date"] = last_act
                        return result
                
                # 2. Not logged in -> We must be on the sign-in page
                if not sb.is_element_visible("adc-text-input#username"):
                    sb.open("https://www.aa.com/aadvantage-program/profile/account-summary")
                    sb.sleep(8)
                
                # Prefill and submit the login form
                self._fill_login_form(sb, username, password, auto_submit=True)
                
                if self._check_for_mfa(sb):
                    raise InteractionRequiredError("American Airlines requested a verification code (MFA). Please run Interactive Login to resolve this.")
                
                # 3. Wait for redirect and dynamic render to settle
                sb.sleep(12)
                
                if self._check_for_mfa(sb):
                    raise InteractionRequiredError("American Airlines requested a verification code (MFA). Please run Interactive Login to resolve this.")
                
                # Extract data
                balance, status, exp_date, last_act = self._extract_data(sb)
                if balance is None:
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("American Airlines requested a verification code (MFA). Please run Interactive Login to resolve this.")
                    # Retry refreshing in case of a slow dashboard render
                    sb.refresh()
                    sb.sleep(8)
                    balance, status, exp_date, last_act = self._extract_data(sb)
                    
                if balance is None:
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError("American Airlines requested a verification code (MFA). Please run Interactive Login to resolve this.")
                    # Take an error dump for debug purposes
                    with open("american_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                    raise PluginError("Could not find AAdvantage balance on summary dashboard after login.")
                
                result["balance"] = balance
                if status:
                    result["status"] = status
                result["expiration_date"] = exp_date
                result["last_activity_date"] = last_act
                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Interactive login to allow the user to resolve captchas and log in to American Airlines.
        """
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            sb.open("https://www.aa.com/aadvantage-program/profile/account-summary")
            sb.sleep(12)
            
            # Click cookie banner and accept to clear overlay
            cookie_btn = "#accept-recommended-btn-handler"
            try:
                if sb.is_element_visible(cookie_btn):
                    sb.click(cookie_btn)
                    sb.sleep(1)
            except Exception:
                pass

            # Prefill credentials if form is visible
            try:
                if sb.is_element_present("adc-text-input#username"):
                    self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass
            
            # Monitor URL and close window automatically when logged in
            try:
                start_time = time.time()
                success = False
                while time.time() - start_time < 300:
                    curr_url = sb.get_current_url()
                    if "account-summary" in curr_url and not sb.is_element_present("adc-text-input#username") and not self._check_for_mfa(sb):
                        # Settle and verify points can be extracted
                        sb.sleep(5)
                        if self._check_for_mfa(sb) or sb.is_element_present("adc-text-input#username"):
                            continue
                        balance, _, _, _ = self._extract_data(sb)
                        if balance is not None:
                            success = True
                            break
                    time.sleep(2)
                
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
                
                sb.sleep(3) # Let session write completely
            except Exception:
                raise PluginError("Interactive login timed out after 5 minutes or dashboard failed to load.")
