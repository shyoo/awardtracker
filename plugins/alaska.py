from typing import Dict, Any
from datetime import datetime
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs
from seleniumbase import SB
import time

class AlaskaAirlinesPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Alaska Airlines"

    @property
    def plugin_id(self) -> str:
        return "alaska"

    @property
    def default_cpp(self) -> float:
        return 1.4

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        from .base import add_months
        return add_months(last_activity_date, 24)

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Accounts are locked after 24 months of inactivity. Balance is preserved, but account reactivation is required."

    def is_auth_url(self, url: str) -> bool:
        url_lower = url.lower()
        auth_keywords = [
            "login", "auth0", "mfa", "verify", "verification", 
            "otp", "authenticate", "authorize", "challenge", "security"
        ]
        return any(keyword in url_lower for keyword in auth_keywords)

    def is_mfa_challenge(self, sb, url: str) -> bool:
        url_lower = url.lower()
        if "enrollment" in url_lower:
            return False
        if "challenge" in url_lower or "mfa" in url_lower:
            return True
        try:
            if sb.is_element_visible("#mfa-challenge-title") or sb.is_element_visible("h1:contains('Confirm')") or sb.is_element_visible("input[name='code']"):
                return True
        except Exception:
            pass
        return False

    def get_consistent_user_agent(self) -> str:
        import platform
        import subprocess
        import re
        try:
            if platform.system() == "Windows":
                cmd = r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version'
                output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()
                version = re.search(r'version\s+REG_SZ\s+(\S+)', output)
                if version:
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version.group(1)} Safari/537.36"
                cmd2 = r'reg query "HKEY_LOCAL_MACHINE\Software\Google\Chrome\BLBeacon" /v version'
                output2 = subprocess.check_output(cmd2, shell=True, stderr=subprocess.DEVNULL).decode()
                version2 = re.search(r'version\s+REG_SZ\s+(\S+)', output2)
                if version2:
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version2.group(1)} Safari/537.36"
            elif platform.system() == "Darwin":
                cmd = r'defaults read "/Applications/Google Chrome.app/Contents/Info" CFBundleShortVersionString'
                output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode()
                return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{output.strip()} Safari/537.36"
        except Exception:
            pass
        
        # Fallback consistent user agent
        if platform.system() == "Windows":
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        elif platform.system() == "Darwin":
            return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

    def save_cookies_to_json(self, sb, profile_dir: str) -> None:
        if not profile_dir:
            return
        import json
        import os
        try:
            cookies = sb.get_cookies()
            cookies_file = os.path.join(profile_dir, "alaska_cookies.json")
            with open(cookies_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=4)
            print(f"Alaska Airlines cookies saved to JSON: {len(cookies)} cookies.")
        except Exception as e:
            print(f"Error saving Alaska Airlines cookies to JSON: {e}")

    def load_cookies_from_json(self, sb, profile_dir: str) -> None:
        if not profile_dir:
            return
        import json
        import os
        cookies_file = os.path.join(profile_dir, "alaska_cookies.json")
        if not os.path.exists(cookies_file):
            print("No saved cookies JSON file found.")
            return
        try:
            with open(cookies_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            
            print(f"Loading and injecting {len(cookies)} saved cookies...")
            cookies_by_domain = {}
            for cookie in cookies:
                domain = cookie.get('domain', '')
                if not domain:
                    continue
                norm_domain = domain.lstrip('.')
                if norm_domain not in cookies_by_domain:
                    cookies_by_domain[norm_domain] = []
                cookies_by_domain[norm_domain].append(cookie)
                
            for norm_domain, domain_cookies in cookies_by_domain.items():
                current_url = sb.get_current_url().lower()
                if norm_domain not in current_url:
                    if "auth0" in norm_domain:
                        safe_url = f"https://{norm_domain}/robots.txt"
                    else:
                        safe_url = f"https://www.{norm_domain}/"
                    try:
                        print(f"Navigating to {safe_url} to inject cookies for domain {norm_domain}")
                        sb.open(safe_url)
                        sb.sleep(2)
                    except Exception as nav_err:
                        print(f"Failed to navigate to {safe_url}: {nav_err}")
                        continue
                
                injected_count = 0
                for cookie in domain_cookies:
                    try:
                        clean_cookie = {
                            'name': cookie['name'],
                            'value': cookie['value'],
                            'path': cookie.get('path', '/'),
                            'secure': cookie.get('secure', False),
                            'httpOnly': cookie.get('httpOnly', False),
                            'sameSite': cookie.get('sameSite', 'Lax')
                        }
                        if cookie.get('domain'):
                            clean_cookie['domain'] = cookie['domain']
                        if 'expiry' in cookie:
                            clean_cookie['expiry'] = int(cookie['expiry'])
                        sb.add_cookie(clean_cookie)
                        injected_count += 1
                    except Exception:
                        pass
                print(f"Injected {injected_count} cookies for domain {norm_domain}")
            print("Alaska Airlines cookies restore process completed.")
        except Exception as e:
            print(f"Error restoring Alaska Airlines cookies: {e}")

    def configure_session_restore(self, profile_dir: str) -> None:
        if not profile_dir:
            return
        import os
        import json
        import stat
        
        pref_path = os.path.join(profile_dir, 'Default', 'Preferences')
        os.makedirs(os.path.dirname(pref_path), exist_ok=True)
        
        data = {}
        if os.path.exists(pref_path):
            try:
                # Make writable first to make sure we can read/write it
                os.chmod(pref_path, stat.S_IWRITE)
                with open(pref_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
                
        if 'session' not in data or not isinstance(data['session'], dict):
            data['session'] = {}
        data['session']['restore_on_startup'] = 1
        
        if 'profile' not in data or not isinstance(data['profile'], dict):
            data['profile'] = {}
        data['profile']['exit_type'] = "Normal"
        data['profile']['exited_cleanly'] = True
        
        try:
            with open(pref_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            # Keeping the Preferences file writable allows Chrome to cleanly exit and update its exit type.
            print("Chrome session restore and clean exit preference configured successfully.")
        except Exception as e:
            print(f"Error configuring Chrome session restore preference: {e}")



    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        try:
            if profile_dir:
                try:
                    self.configure_session_restore(profile_dir)
                except Exception:
                    pass
            agent = self.get_consistent_user_agent()
            with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir, agent=agent)) as sb:
                # Open homepage first so we can inject cookies into the domain context
                sb.open("https://www.alaskaair.com/")
                sb.sleep(2)
                
                if profile_dir:
                    try:
                        self.load_cookies_from_json(sb, profile_dir)
                    except Exception:
                        pass
                
                # Open Alaska dashboard
                sb.open("https://www.alaskaair.com/atmosrewards/account/overview/")
                sb.sleep(5)
                
                current_url = sb.get_current_url().lower()
                if "login" in current_url or "auth0" in current_url:
                    try:
                        print("Alaska Auth0 login page detected. Attempting auto-login...")
                        sb.wait_for_element_visible("input#username", timeout=15)
                        
                        sb.click("input#username")
                        sb.type("input#username", username)
                        sb.sleep(1)
                        
                        sb.click("input#password")
                        sb.type("input#password", password)
                        sb.sleep(1)
                        
                        submit_btn = None
                        for selector in ["button[type='submit']", "button[name='action']"]:
                            if sb.is_element_visible(selector):
                                submit_btn = selector
                                break
                        
                        if submit_btn:
                            print(f"Clicking submit button: {submit_btn}")
                            sb.click(submit_btn)
                            sb.sleep(7)
                        else:
                            print("Submit button not found. Pressing enter on password field...")
                            sb.press_keys("input#password", "\n")
                            sb.sleep(7)
                            
                        current_url = sb.get_current_url().lower()
                        if self.is_mfa_challenge(sb, current_url):
                            raise InteractionRequiredError("Alaska Airlines session expired or login required. Please use Interactive Login.")
                            
                        # Handle potential MFA Setup/Reminder skip prompt
                        if not self.is_mfa_challenge(sb, current_url):
                            for selector in [
                                "button:contains('Not now')", 
                                "a:contains('Not now')", 
                                "button:contains('Skip')", 
                                "a:contains('Skip')", 
                                "button:contains('Skip for now')", 
                                "a:contains('Skip for now')", 
                                "button:contains('No, thanks')",
                                "a:contains('No, thanks')",
                                "button:contains('Remind me later')",
                                "a:contains('Remind me later')"
                            ]:
                                if sb.is_element_visible(selector):
                                    print(f"MFA prompt detected. Skipping via: {selector}")
                                    sb.click(selector)
                                    sb.sleep(5)
                                    break
                            
                        current_url = sb.get_current_url().lower()
                    except InteractionRequiredError:
                        raise
                    except Exception as login_err:
                        print(f"Auto-login attempt failed: {login_err}")
                        login_err_lower = str(login_err).lower()
                        if any(x in login_err_lower for x in ["no such window", "invalid session id", "disconnected", "chrome was closed", "connection refused", "connection reset", "failed to establish a new connection", "max retries exceeded", "urllib3"]):
                            raise InteractionRequiredError("Browser window was closed or disconnected during sync. Please use Interactive Login.")
                        try:
                            current_url = sb.get_current_url().lower()
                        except Exception:
                            pass
                
                if self.is_auth_url(current_url) or self.is_mfa_challenge(sb, current_url):
                    raise InteractionRequiredError("Alaska Airlines session expired or login required. Please use Interactive Login.")
                
                # Check for dashboard load
                for _ in range(15):
                    try:
                        current_url = sb.get_current_url().lower()
                        if self.is_auth_url(current_url) or self.is_mfa_challenge(sb, current_url):
                            raise InteractionRequiredError("Alaska Airlines session expired or login required. Please use Interactive Login.")
                            
                        if (sb.is_element_visible("div:contains('Available')") or 
                            sb.is_element_visible("div.display-xs") or 
                            sb.is_element_visible(".points-value") or 
                            sb.is_element_visible("div.points-value") or 
                            sb.is_element_visible("div.points-label")):
                            break
                        sb.sleep(2)
                    except InteractionRequiredError:
                        raise
                    except Exception as loop_err:
                        loop_err_lower = str(loop_err).lower()
                        if any(x in loop_err_lower for x in ["no such window", "invalid session id", "disconnected", "chrome was closed", "connection refused", "connection reset", "failed to establish a new connection", "max retries exceeded", "urllib3"]):
                            raise InteractionRequiredError("Browser window was closed or disconnected during sync. Please use Interactive Login.")
                        raise loop_err
                    
                sb.sleep(2)
                html = sb.get_page_source()
                from bs4 import BeautifulSoup
                import re
                soup = BeautifulSoup(html, "html.parser")
                
                balance = None
                status = "Member"
                
                # 1. Search by points-value class (direct and robust on modern dashboard)
                points_val_el = soup.find(class_=re.compile(r"points-value"))
                if points_val_el:
                    text_val = points_val_el.text.strip().replace(",", "")
                    if text_val.isdigit():
                        balance = int(text_val)
                        print(f"Found balance via points-value class: {balance}")
                
                # 2. Look for "Available Points" or "Available Miles" (legacy/alternative layouts)
                if balance is None:
                    avail_texts = soup.find_all(string=re.compile(r"Available Points|Available Miles|Total Miles", re.I))
                    for at in avail_texts:
                        parent = at.parent
                        if not parent:
                            continue
                        
                        # Check sibling elements in parent container
                        parent_container = parent.parent
                        if parent_container:
                            sibling_val = parent_container.find(class_=re.compile(r"points-value|display-sm|display-xs"))
                            if sibling_val:
                                text_val = sibling_val.text.strip().replace(",", "")
                                if text_val.isdigit():
                                    balance = int(text_val)
                                    break
                                    
                        parent_text = parent.text.strip()
                        grandparent_text = parent_container.text.strip() if parent_container else ""
                        
                        matches = re.findall(r"([\d,]+)\s*Available", parent_text, re.I)
                        if not matches:
                            matches = re.findall(r"([\d,]+)\s*Available", grandparent_text, re.I)
                        if not matches:
                            matches = re.findall(r"([\d,]+)", parent_text)
                        if not matches:
                            matches = re.findall(r"([\d,]+)", grandparent_text)
                        
                        for m in matches:
                            clean_m = m.replace(",", "")
                            if clean_m.isdigit():
                                balance = int(clean_m)
                                break
                        if balance is not None:
                            break
                            
                # 3. Look for specific class 'display-xs' as fallback
                if balance is None:
                    spans = soup.find_all(class_="display-xs")
                    for span in spans:
                        text_val = span.text.strip().replace(",", "")
                        if text_val.isdigit() and len(text_val) < 8:
                            balance = int(text_val)
                            break
                            
                # Check tier status
                tier_texts = soup.find_all(string=re.compile(r"MVP|Atmos™ Member|Member|ATMOS REWARDS MEMBER", re.I))
                for t in tier_texts:
                    t_str = t.strip()
                    if len(t_str) < 50:
                        if "100K" in t_str:
                            status = "MVP Gold 100K"
                            break
                        elif "75K" in t_str and status != "MVP Gold 100K":
                            status = "MVP Gold 75K"
                        elif "Gold" in t_str and status not in ["MVP Gold 100K", "MVP Gold 75K"]:
                            status = "MVP Gold"
                        elif "MVP" in t_str and status not in ["MVP Gold 100K", "MVP Gold 75K", "MVP Gold"]:
                            status = "MVP"
                        elif ("Atmos" in t_str or "ATMOS REWARDS MEMBER" in t_str.upper()) and status == "Member":
                            status = "Atmos Member"
                
                if balance is None:
                    raise PluginError("Could not find balance on the Alaska Airlines dashboard.")
                
                if profile_dir:
                    try:
                        self.save_cookies_to_json(sb, profile_dir)
                    except Exception:
                        pass
                
                return {
                    "balance": balance,
                    "status": status,
                    "expiration_date": None
                }
        except InteractionRequiredError:
            raise
        except Exception as e:
            err_lower = str(e).lower()
            if any(x in err_lower for x in ["no such window", "invalid session id", "disconnected", "chrome was closed", "connection refused", "connection reset", "failed to establish a new connection", "max retries exceeded", "urllib3"]):
                raise InteractionRequiredError("Browser window was closed or disconnected during sync. Please use Interactive Login.")
            raise PluginError(f"Alaska Airlines scraping failed: {e}")


    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        try:
            if profile_dir:
                try:
                    self.configure_session_restore(profile_dir)
                except Exception:
                    pass
            agent = self.get_consistent_user_agent()
            with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir, agent=agent)) as sb:
                # Open homepage first to inject any existing cookies
                sb.open("https://www.alaskaair.com/")
                sb.sleep(2)
                
                if profile_dir:
                    try:
                        self.load_cookies_from_json(sb, profile_dir)
                    except Exception:
                        pass
                
                sb.open("https://www.alaskaair.com/atmosrewards/account/overview/")
                sb.sleep(5)
                
                try:
                    sb.wait_for_element_visible("input#username", timeout=15)
                    
                    sb.click("input#username")
                    sb.type("input#username", username)
                    sb.sleep(1)
                    
                    sb.click("input#password")
                    sb.type("input#password", password)
                    sb.sleep(1)
                except Exception as e:
                    print(f"Error pre-filling Alaska Auth0 credentials: {e}")
                    
                print("Please log in manually if needed. Waiting for the dashboard URL...")
                try:
                    for _ in range(60):  # Wait up to 5 minutes
                        current_url = sb.get_current_url()
                        # Help the user by auto-clicking any "Not now" or "Skip" MFA buttons
                        if not self.is_mfa_challenge(sb, current_url):
                            for selector in [
                                "button:contains('Not now')", 
                                "a:contains('Not now')", 
                                "button:contains('Skip')", 
                                "a:contains('Skip')", 
                                "button:contains('Skip for now')", 
                                "a:contains('Skip for now')", 
                                "button:contains('No, thanks')",
                                "a:contains('No, thanks')",
                                "button:contains('Remind me later')",
                                "a:contains('Remind me later')"
                            ]:
                                if sb.is_element_visible(selector):
                                    print(f"Interactive: Auto-skipping MFA prompt: {selector}")
                                    sb.click(selector)
                                    sb.sleep(2)
                                    break
                                
                        current_url = sb.get_current_url()
                        if "myaccount" in current_url.lower() or "mileage-plan" in current_url.lower() or "atmosrewards" in current_url.lower():
                            if not self.is_auth_url(current_url):
                                print(f"Detected dashboard URL: {current_url}")
                                sb.sleep(5) # allow page to load and save cookies
                                if profile_dir:
                                    try:
                                        self.save_cookies_to_json(sb, profile_dir)
                                    except Exception:
                                        pass
                                break
                        sb.sleep(5)
                except Exception as e:
                    print(f"Interactive login wait interrupted: {e}")
        except Exception as e:
            print(f"Interactive login error: {e}")
