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

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        with SB(uc=True, user_data_dir=profile_dir) as sb:
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
                
                if "login" in current_url or "auth0" in current_url:
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

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        with SB(uc=True, user_data_dir=profile_dir) as sb:
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
                    # Help the user by auto-clicking any "Not now" or "Skip" MFA buttons
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
                        if "login" not in current_url.lower() and "auth0" not in current_url.lower():
                            print(f"Detected dashboard URL: {current_url}")
                            sb.sleep(5) # allow page to load and save cookies
                            break
                    sb.sleep(5)
            except Exception as e:
                print(f"Interactive login wait interrupted: {e}")
