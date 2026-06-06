from typing import Dict, Any
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
import time

class AlaskaAirlinesPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Alaska Airlines"

    @property
    def plugin_id(self) -> str:
        return "alaska"

    def is_auth_url(self, url: str) -> bool:
        url_lower = url.lower()
        auth_keywords = [
            "login", "auth0", "mfa", "verify", "verification", 
            "otp", "authenticate", "authorize", "challenge", "security"
        ]
        return any(keyword in url_lower for keyword in auth_keywords)

    def is_mfa_challenge(self, sb, url: str) -> bool:
        url_lower = url.lower()
        if "challenge" in url_lower:
            return True
        try:
            if sb.is_element_visible("#mfa-challenge-title") or sb.is_element_visible("h1:contains('Confirm')"):
                return True
        except Exception:
            pass
        return False

    def persist_session_cookies(self, profile_dir: str) -> None:
        if not profile_dir:
            return
        import os
        import sqlite3
        import datetime
        db_path = os.path.join(profile_dir, 'Default', 'Network', 'Cookies')
        if not os.path.exists(db_path):
            return
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            now = datetime.datetime.utcnow()
            expires_date = now + datetime.timedelta(days=7)
            chrome_epoch = datetime.datetime(1601, 1, 1)
            delta = expires_date - chrome_epoch
            expires_utc = int(delta.total_seconds() * 1000000)
            cursor.execute(
                "UPDATE cookies SET expires_utc = ? WHERE host_key LIKE '%alaskaair.com%' AND expires_utc = 0",
                (expires_utc,)
            )
            conn.commit()
            conn.close()
            print("Alaska Airlines session cookies persisted successfully.")
        except Exception as e:
            print(f"Error persisting Alaska Airlines session cookies: {e}")

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        try:
            with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
                try:
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
                        except Exception as login_err:
                            print(f"Auto-login attempt failed: {login_err}")
                    
                    if self.is_auth_url(current_url):
                        raise InteractionRequiredError("Alaska Airlines session expired or login required. Please use Interactive Login.")
                    
                    # Check for dashboard load
                    for _ in range(10):
                        if (sb.is_element_visible("div:contains('Available')") or 
                            sb.is_element_visible("div.display-xs") or 
                            sb.is_element_visible(".points-value") or 
                            sb.is_element_visible("div.points-value") or 
                            sb.is_element_visible("div.points-label")):
                            break
                        sb.sleep(2)
                        
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
                        
                    return {
                        "balance": balance,
                        "status": status,
                        "expiration_date": None
                    }
                except InteractionRequiredError:
                    raise
                except Exception as e:
                    raise PluginError(f"Alaska Airlines scraping failed: {e}")
        finally:
            if profile_dir:
                try:
                    self.persist_session_cookies(profile_dir)
                except Exception:
                    pass

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        try:
            with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
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
                                break
                        sb.sleep(5)
                except Exception as e:
                    print(f"Interactive login wait interrupted: {e}")
        finally:
            if profile_dir:
                try:
                    self.persist_session_cookies(profile_dir)
                except Exception:
                    pass
