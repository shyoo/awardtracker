from typing import Dict, Any, Tuple, Optional
from datetime import datetime
from .base import ProviderPlugin, PluginError, InteractionRequiredError, is_hidden_node
from seleniumbase import SB
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urlparse

class AviancaLifemilesPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Avianca Lifemiles"

    @property
    def plugin_id(self) -> str:
        return "avianca"

    @property
    def default_cpp(self) -> float:
        return 1.2

    @property
    def custom_tip(self) -> str:
        return "Check your email for the <strong>\"Confirm your identity\"</strong> verification code."

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'silver', 'gold', 'diamond', 'red')):
            months = 24
        else:
            months = 12
        from .base import add_months
        return add_months(last_activity_date, months)

    def get_expiration_policy_description(self, status: str = None) -> str:
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'silver', 'gold', 'diamond', 'red')):
            return f"Miles expire after 24 months of inactivity for Elite members (your status: {status or 'Standard'}). Note: Only earning activity resets the clock; redemptions do not."
        return "Miles expire after 12 months of inactivity. Note: Only earning (accrual) activity resets the clock; redemptions do not."

    def _extract_data(self, html: str) -> Tuple[Optional[int], Optional[str]]:
        """
        Parses LifeMiles balance and tier status from page HTML.
        Supports multiple fallback selector-based and regex-based strategies.
        """
        soup = BeautifulSoup(html, "html.parser")
            
        # --- 1. Extract points balance ---
        balance = None
        
        # Strategy A: Check selectors matching data-testid or classes related to miles/puntos/balance
        selectors = [
            "[class*='milesBold']",
            "[class*='miles__']",
            "span[data-testid='user-miles']",
            "div[data-testid='user-miles']",
            "span[data-cy='user-miles']",
            "div[data-cy='user-miles']",
            ".user-miles",
            ".miles-balance",
            ".lifemiles-balance",
            "[class*='miles-balance']",
            "[class*='puntos-balance']",
            "p[class*='miles']",
            "[class*='miles']"
        ]
        
        for selector in selectors:
            try:
                for elem in soup.select(selector):
                    if is_hidden_node(elem):
                        continue
                    text = elem.get_text(strip=True)
                    m = re.search(r'([\d,.]+)', text)
                    if m:
                        num_str = m.group(1).replace(",", "").replace(".", "")
                        if num_str.isdigit():
                            val = int(num_str)
                            # Make sure we don't accidentally parse small menu counts or dates
                            if val > 100 or any(kw in text.lower() for kw in ["mile", "lm", "puntos"]):
                                balance = val
                                break
            except Exception:
                pass
            if balance is not None:
                break

        # Strategy B: Search for label string and find numbers in its siblings or parents
        if balance is None:
            labels = ["lifemiles balance", "my lifemiles", "puntos", "disponible", "saldo", "mis lifemiles"]
            for label_text in labels:
                try:
                    # Find matching string elements
                    for elem in soup.find_all(string=re.compile(rf'\b{label_text}\b', re.I)):
                        if is_hidden_node(elem):
                            continue
                        # If the text node itself is too long, it's probably marketing text
                        if len(elem) > 80:
                            continue
                        parent = elem.parent
                        # Traverse up to 3 levels to find adjacent numeric values
                        for _ in range(3):
                            if parent:
                                text = parent.get_text(strip=True)
                                # Skip very long parent texts (marketing paragraphs)
                                if len(text) > 100:
                                    parent = parent.parent
                                    continue
                                text_without_label = text.lower().replace(label_text, "")
                                m = re.search(r'([\d,.]+)', text_without_label)
                                if m:
                                    num_str = m.group(1).replace(",", "").replace(".", "")
                                    if num_str.isdigit():
                                        balance = int(num_str)
                                        break
                                parent = parent.parent
                            else:
                                break
                        if balance is not None:
                            break
                except Exception:
                    pass
                if balance is not None:
                    break

        # Strategy C: General pattern match inside text nodes
        if balance is None:
            patterns = [
                r'([\d,.]+)\s*(?:lifemiles|miles|lm|puntos|points)\b',
                r'(?:lifemiles|miles|lm|puntos|points)\s*:?\s*([\d,.]+)\b'
            ]
            for pattern in patterns:
                try:
                    for elem in soup.find_all(string=re.compile(pattern, re.I)):
                        if is_hidden_node(elem):
                            continue
                        # Ignore long paragraphs or elements containing copyright symbols
                        if len(elem) > 80:
                            continue
                        if any(kw in elem.lower() for kw in ["copyright", "©", "all rights reserved", "todos los derechos"]):
                            continue
                        m = re.search(pattern, elem, re.I)
                        if m:
                            num_str = m.group(1).replace(",", "").replace(".", "")
                            if num_str.isdigit():
                                balance = int(num_str)
                                break
                except Exception:
                    pass
                if balance is not None:
                    break

        # --- 2. Extract membership status / tier ---
        status = "Clásico"  # Default entry tier for LifeMiles
        
        # Look for specific elite tiers to avoid false-matching generic "Classic" or "Member"
        tiers = ["Diamond", "Gold", "Silver", "Red Plus"]
        for tier in tiers:
            try:
                pattern = rf'\b{tier}\b'
                for elem in soup.find_all(string=re.compile(pattern, re.I)):
                    if is_hidden_node(elem):
                        continue
                    status = tier
                    break
            except Exception:
                pass
            if status != "Clásico":
                break
                
        return balance, status

    def _extract_expiration_date(self, html: str) -> Optional[str]:
        """
        Parses the expiration date from the LifeMiles dashboard page HTML.
        Supports both English and Spanish formats (e.g. "Jun 30, 2026", "30 de junio de 2026").
        Returns the date in ISO format 'YYYY-MM-DD' or None if not found/parseable.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Month name mapping for English and Spanish
            months = {
                "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
                "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
                "ene": "01", "abr": "04", "ago": "08", "dic": "12", "set": "09",
                "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06",
                "julio": "07", "agosto": "08", "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
                "january": "01", "february": "02", "march": "03", "april": "04", "june": "06",
                "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12"
            }
            
            # Look for labels like "expiration date", "fecha de vencimiento", "vencimiento", "vence"
            labels = [
                r'expiration\s*date',
                r'fecha\s*de\s*vencimiento',
                r'vencimiento',
                r'vence'
            ]
            
            for label_pat in labels:
                for elem in soup.find_all(string=re.compile(label_pat, re.I)):
                    if is_hidden_node(elem):
                        continue
                    
                    # 1. Check if the element itself or its parent has a date pattern
                    parent = elem.parent
                    if not parent:
                        continue
                    
                    # Search text in parent or adjacent elements
                    parent_text = parent.get_text(" ", strip=True)
                    
                    # Pattern 1: Month DD, YYYY (e.g. Jun 30, 2026 or June 3, 2026)
                    m1 = re.search(r'\b([A-Za-z]{3,10})\s+(\d{1,2}),?\s+(\d{4})\b', parent_text)
                    if m1:
                        m_str, d_str, y_str = m1.group(1).lower(), m1.group(2), m1.group(3)
                        m_num = months.get(m_str[:3]) or months.get(m_str)
                        if m_num:
                            return f"{y_str}-{m_num}-{int(d_str):02d}"
                            
                    # Pattern 2: DD de Month de YYYY or DD Month YYYY (e.g. 30 de junio de 2026 or 30 jun 2026)
                    m2 = re.search(r'\b(\d{1,2})\s+(?:de\s+)?([A-Za-z]{3,10})\s+(?:de\s+)?(\d{4})\b', parent_text, re.I)
                    if m2:
                        d_str, m_str, y_str = m2.group(1), m2.group(2).lower(), m2.group(3)
                        m_num = months.get(m_str[:3]) or months.get(m_str)
                        if m_num:
                            return f"{y_str}-{m_num}-{int(d_str):02d}"
                    
                    # 2. Check next siblings of parent
                    for sibling in parent.find_next_siblings():
                        sib_text = sibling.get_text(" ", strip=True)
                        if not sib_text:
                            continue
                        
                        m1 = re.search(r'\b([A-Za-z]{3,10})\s+(\d{1,2}),?\s+(\d{4})\b', sib_text)
                        if m1:
                            m_str, d_str, y_str = m1.group(1).lower(), m1.group(2), m1.group(3)
                            m_num = months.get(m_str[:3]) or months.get(m_str)
                            if m_num:
                                return f"{y_str}-{m_num}-{int(d_str):02d}"
                                
                        m2 = re.search(r'\b(\d{1,2})\s+(?:de\s+)?([A-Za-z]{3,10})\s+(?:de\s+)?(\d{4})\b', sib_text, re.I)
                        if m2:
                            d_str, m_str, y_str = m2.group(1), m2.group(2).lower(), m2.group(3)
                            m_num = months.get(m_str[:3]) or months.get(m_str)
                            if m_num:
                                return f"{y_str}-{m_num}-{int(d_str):02d}"
                                
        except Exception as e:
            print("Error extracting expiration date:", e)
    def _fetch_last_accrual_date(self, sb) -> Tuple[Optional[Any], bool]:
        """
        Navigates to the transaction history page, parses the first page of transactions,
        and returns:
        - The latest qualifying accrual (earning) date.
        - A boolean flag `no_accruals_warning` if only redemption (spending) activity was found.
        """
        import datetime as dt
        latest_accrual = None
        has_redemptions = False
        has_accruals = False
        
        # List of potential transaction history URLs
        urls = [
            "https://www.lifemiles.com/profile/transactions",
            "https://www.lifemiles.com/member/transactions",
            "https://www.lifemiles.com/profile/activity",
            "https://www.lifemiles.com/transactions"
        ]
        
        # Try navigating directly
        navigated = False
        for url in urls:
            try:
                sb.open(url)
                sb.sleep(6)
                # Check if we landed on a page with transactions
                if "transaction" in sb.get_current_url().lower() or "actividad" in sb.get_current_url().lower() or "activity" in sb.get_current_url().lower():
                    navigated = True
                    break
            except Exception:
                pass
                
        # If direct navigation didn't work, let's try finding a menu link on the homepage
        if not navigated:
            try:
                sb.open("https://www.lifemiles.com")
                sb.sleep(4)
                # Look for a link/button with transaction text and click it
                selectors = [
                    "a:contains('Transactions')",
                    "a:contains('Transacciones')",
                    "a:contains('Activity')",
                    "a:contains('Actividad')",
                    "a[href*='transactions']",
                    "a[href*='activity']"
                ]
                for sel in selectors:
                    if sb.is_element_visible(sel):
                        sb.click(sel)
                        sb.sleep(6)
                        navigated = True
                        break
            except Exception:
                pass

        # Parse transactions from the current page
        try:
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            rows = []
            for el in soup.find_all(["tr", "div", "li"]):
                text = el.get_text(" ", strip=True)
                if len(text) < 150 and any(kw in text.lower() for kw in ["accrual", "earn", "redemption", "spent", "compra", "canje", "acumulaci", "abono"]):
                    rows.append(text)
            
            text_content = soup.get_text("\n")
            lines = [line.strip() for line in text_content.split("\n") if line.strip()]
            for line in lines:
                if len(line) < 150 and any(kw in line.lower() for kw in ["accrual", "earn", "redemption", "spent", "compra", "canje", "acumulaci", "abono"]):
                    rows.append(line)
                    
            rows = list(set(rows))
            
            months = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                "ene": 1, "abr": 4, "ago": 8, "dic": 12, "set": 9,
                "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
                "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
            }
            
            parsed_activities = []
            for row in rows:
                date_match = re.search(r'\b(\d{1,2})[\s/de]+([A-Za-z]{3,10}|\d{1,2})[\s/de]+(\d{4})\b', row, re.I)
                if not date_match:
                    date_match = re.search(r'\b([A-Za-z]{3,10})\s+(\d{1,2}),?\s+(\d{4})\b', row, re.I)
                    
                if date_match:
                    try:
                        p_date = None
                        g1 = date_match.group(1)
                        if g1.isdigit():
                            d_val = int(g1)
                            g2 = date_match.group(2).lower()
                            y_val = int(date_match.group(3))
                            if g2.isdigit():
                                m_val = int(g2)
                            else:
                                m_val = months.get(g2[:3]) or months.get(g2) or 1
                            p_date = dt.datetime(y_val, m_val, d_val)
                        else:
                            m_val = months.get(g1.lower()[:3]) or months.get(g1.lower()) or 1
                            d_val = int(date_match.group(2))
                            y_val = int(date_match.group(3))
                            p_date = dt.datetime(y_val, m_val, d_val)
                            
                        row_lower = row.lower()
                        is_accrual = any(kw in row_lower for kw in ["accrual", "earn", "acumulaci", "abono", "ingreso", "credit", "credito", "crédito"])
                        is_redemption = any(kw in row_lower for kw in ["redemption", "spent", "debit", "debito", "débito", "canje", "descuento"])
                        
                        if is_accrual and not is_redemption:
                            parsed_activities.append((p_date, "accrual"))
                            has_accruals = True
                        elif is_redemption:
                            parsed_activities.append((p_date, "redemption"))
                            has_redemptions = True
                        else:
                            parsed_activities.append((p_date, "accrual"))
                            has_accruals = True
                    except Exception:
                        pass
                        
            if parsed_activities:
                accruals = [item[0] for item in parsed_activities if item[1] == "accrual"]
                if accruals:
                    latest_accrual = max(accruals)
                    
        except Exception as e:
            print("Error parsing transactions page:", e)
            
        no_accruals_warning = (has_redemptions and not has_accruals) or (has_redemptions and not latest_accrual)
        return latest_accrual, no_accruals_warning

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """
        Interacts with the Keycloak SSO gateway to reveal credential fields and fill them.
        """
        # Wait up to 15 seconds for either the email gateway button or the username field to be visible
        gateway_visible = False
        for _ in range(15):
            if sb.is_element_visible("a[data-testid='emailButton']") or sb.is_element_visible("input#username"):
                gateway_visible = True
                break
            sb.sleep(1)
            
        if not gateway_visible:
            raise InteractionRequiredError("Avianca login page did not load (gateway buttons not visible).")
            
        # If the email gateway button is visible, click it first
        email_btn = "a[data-testid='emailButton']"
        if not sb.is_element_visible("input#username"):
            if sb.is_element_visible(email_btn):
                print("Found 'Email or Lifemiles number' gateway button. Clicking it...")
                sb.click(email_btn)
                sb.sleep(2)
        
        # Wait up to 10 seconds for inputs to load
        try:
            sb.wait_for_element_visible("input#username", timeout=10)
        except Exception:
            raise InteractionRequiredError("Avianca login form (username/password) not visible on SSO page.")
            
        print("SSO credentials inputs visible. Filling credentials...")
        try:
            sb.type("input#username", username)
        except Exception:
            pass
        sb.sleep(0.5)
        
        try:
            sb.type("input#password", password)
        except Exception:
            pass
        sb.sleep(0.5)
        
        # JS Fallback
        try:
            user_el = sb.find_element("input#username")
            pass_el = sb.find_element("input#password")
            
            sb.execute_script("arguments[0].value = arguments[1];", user_el, username)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", user_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", user_el)
            
            sb.execute_script("arguments[0].value = arguments[1];", pass_el, password)
            sb.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", pass_el)
            sb.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", pass_el)
        except Exception:
            pass
        
        if auto_submit:
            print("Auto-submitting credentials...")
            submit_selectors = [
                "button#login-button",
                "button.hub-keycloak-login-ui__buttonLoginWrapper",
                "button#kc-login"
            ]
            submitted = False
            for selector in submit_selectors:
                if sb.is_element_visible(selector):
                    try:
                        sb.click(selector)
                    except Exception:
                        btn = sb.find_element(selector)
                        sb.execute_script("arguments[0].click();", btn)
                    submitted = True
                    break
            if not submitted:
                try:
                    sb.type("input#password", "\n")
                except Exception:
                    pass
            sb.sleep(8)

    def _check_for_mfa(self, sb) -> bool:
        """
        Helper to detect if Avianca is presenting an MFA (Confirm your identity) challenge.
        """
        try:
            current_url = sb.get_current_url().lower()
            # If we are already on a lifemiles.com page, we are not stuck on MFA
            from urllib.parse import urlparse
            parsed = urlparse(current_url)
            if "lifemiles.com" in parsed.netloc:
                return False
        except Exception:
            pass

        mfa_selectors = (
            "input#code, input[name='code'], input[name='otp'], input[name='verificationCode'], "
            "input[id*='code' i], input[name*='code' i], input[placeholder*='code' i], "
            "input[placeholder*='código' i], input[id*='otp' i], input[name*='otp' i]"
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
                "confirm your identity", "confirma tu identidad", "confirmar identidad",
                "verification code", "código de verificación", "enter code", "ingresa el código",
                "security code", "código de seguridad", "one-time passcode", "one-time code", "otp"
            ]
            if any(kw in text_content for kw in mfa_keywords):
                mfa_text_detected = True
        except Exception:
            pass
            
        return mfa_visible or mfa_text_detected

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Clásico",
            "expiration_date": None,
            "certificates": []
        }
        
        try:
            with SB(uc=True, user_data_dir=profile_dir) as sb:
                print("Navigating to Avianca LifeMiles homepage...")
                sb.open("https://www.lifemiles.com")
                sb.sleep(5)
                
                # Check and bypass cookie banner
                cookie_selectors = [
                    "button.CookiesBrowserAlert_acceptButtonNO",
                    "button:contains('Accept')",
                    "button:contains('Aceptar')",
                    ".CookiesBrowserAlert_acceptButtonNO"
                ]
                for sel in cookie_selectors:
                    try:
                        if sb.is_element_visible(sel):
                            print(f"Cookie banner found. Clicking accept ({sel})...")
                            sb.click(sel)
                            sb.sleep(2)
                            break
                    except Exception:
                        pass
                
                # Check if already logged in (no Log in button and page contains points/member info)
                login_button_selectors = [
                    "button:contains('Log in')",
                    "button:contains('Iniciar sesión')",
                    ".hub_menu_ui__menu_button__v6mTdG",
                    ".hub_homepage_ui__dynamibutton__3tJ9FW"
                ]
                logged_in_selectors = [
                    "span[data-testid='user-miles']",
                    "div[data-testid='user-miles']",
                    ".user-miles",
                    "button:contains('Log out')",
                    "button:contains('Cerrar sesión')"
                ]
                
                login_selector = None
                logged_in = False
                
                # Wait up to 15 seconds for either the login button or logged-in indicators to appear
                print("Waiting for page load indicators...")
                for _ in range(15):
                    # Check if login button is visible
                    for sel in login_button_selectors:
                        if sb.is_element_visible(sel):
                            login_selector = sel
                            break
                    if login_selector:
                        break
                        
                    # Check if already logged in
                    for sel in logged_in_selectors:
                        if sb.is_element_visible(sel):
                            logged_in = True
                            break
                    if logged_in:
                        break
                        
                    # Or check if points are already parseable
                    html = sb.get_page_source()
                    balance, _ = self._extract_data(html)
                    if balance is not None:
                        logged_in = True
                        break
                        
                    sb.sleep(1)
                
                if not logged_in:
                    print("Not logged in. Initiating login flow...")
                    # Click the Log in button to navigate to SSO Keycloak portal
                    if login_selector:
                        sb.click(login_selector)
                    else:
                        clicked = False
                        for sel in login_button_selectors:
                            if sb.is_element_visible(sel):
                                sb.click(sel)
                                clicked = True
                                break
                        if not clicked:
                            # Direct check
                            if sb.is_element_visible("button:contains('Log in')"):
                                sb.click("button:contains('Log in')")
                            else:
                                html = sb.get_page_source()
                                with open("avianca_home_error_dump.html", "w", encoding="utf-8") as f:
                                    f.write(html)
                                sb.save_screenshot("avianca_home_error_screenshot.png")
                                print("Saved debug files for homepage button failure.")
                                raise InteractionRequiredError("Could not find or click the 'Log in' button on homepage.")
                            
                    sb.sleep(5)
                    
                    # Fill and submit Keycloak SSO form
                    self._fill_login_form(sb, username, password, auto_submit=True)
                    
                    # Wait up to 15 seconds for the redirect to lifemiles.com to complete
                    print("Waiting for redirect to lifemiles.com after login...")
                    redirected = False
                    for _ in range(15):
                        if self._check_for_mfa(sb):
                            raise InteractionRequiredError(
                                "Avianca LifeMiles requested identity verification (MFA). "
                                "Please run Interactive Login to resolve this."
                            )
                        current_url = sb.get_current_url()
                        parsed = urlparse(current_url)
                        if "lifemiles.com" in parsed.netloc:
                            redirected = True
                            break
                        sb.sleep(1)
                        
                    if not redirected:
                        if self._check_for_mfa(sb):
                            raise InteractionRequiredError(
                                "Avianca LifeMiles requested identity verification (MFA). "
                                "Please run Interactive Login to resolve this."
                            )
                        raise InteractionRequiredError("Did not redirect back to lifemiles.com after login. Manual verification required.")
                
                # Sleep a few more seconds to allow client-side Javascript to load user miles fully
                print("Extracting balance and tier status...")
                for attempt in range(5):
                    html = sb.get_page_source()
                    balance, status = self._extract_data(html)
                    if balance is not None:
                        break
                    sb.sleep(2)
                    
                # Final extraction
                html = sb.get_page_source()
                balance, status = self._extract_data(html)
                
                if balance is None:
                    if self._check_for_mfa(sb):
                        raise InteractionRequiredError(
                            "Avianca LifeMiles requested identity verification (MFA). "
                            "Please run Interactive Login to resolve this."
                        )
                    # Save HTML for debugging
                    with open("avianca_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    raise PluginError("Sync failed: Could not find LifeMiles points balance on dashboard.")
                    
                result["balance"] = balance
                if status:
                    result["status"] = status
                
                # Expiration date extraction
                try:
                    exp_date = self._extract_expiration_date(html)
                    if exp_date:
                        from datetime import datetime
                        result["expiration_date"] = datetime.strptime(exp_date, "%Y-%m-%d")
                        print(f"Extracted expiration date: {result['expiration_date']}")
                except Exception as de:
                    print("Error parsing expiration date:", de)

                # Fetch last accrual date and warning flags
                try:
                    last_act_date, no_accruals_warning = self._fetch_last_accrual_date(sb)
                    if last_act_date:
                        result["last_activity_date"] = last_act_date
                    result["expiration_meta"] = {
                        "no_accruals_warning": no_accruals_warning
                    }
                except Exception as lae:
                    print("Error fetching transaction activities:", lae)

                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Avianca LifeMiles scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Launches a headed browser window, helps pre-fill credentials when the Keycloak
        form is reached, and automatically closes the browser once active session data is parsed.
        """
        with SB(uc=True, user_data_dir=profile_dir) as sb:
            print("Opening Avianca LifeMiles homepage in headed mode...")
            sb.open("https://www.lifemiles.com")
            sb.sleep(5)
            
            # Check and bypass cookie banner
            cookie_selectors = [
                "button.CookiesBrowserAlert_acceptButtonNO",
                "button:contains('Accept')",
                "button:contains('Aceptar')",
                ".CookiesBrowserAlert_acceptButtonNO"
            ]
            for sel in cookie_selectors:
                try:
                    if sb.is_element_visible(sel):
                        print(f"Cookie banner found. Clicking accept ({sel})...")
                        sb.click(sel)
                        sb.sleep(2)
                        break
                except Exception:
                    pass
            
            print("Please perform interactive login. Monitoring dashboard navigation...")
            
            start_time = time.time()
            success = False
            prefilled = False
            
            while time.time() - start_time < 300:  # 5-minute timeout
                try:
                    # If username field is visible and we haven't prefilled yet, prefill it!
                    if (sb.is_element_visible("input#username") or sb.is_element_visible("a[data-testid='emailButton']")) and not prefilled:
                        try:
                            self._fill_login_form(sb, username, password, auto_submit=False)
                            prefilled = True
                            print("SSO form credentials pre-filled successfully!")
                        except Exception as pe:
                            print(f"Autofill failed: {pe}. Retrying when inputs are ready...")
                            
                    current_url = sb.get_current_url()
                    parsed = urlparse(current_url)
                    
                    # Verify if redirected back to lifemiles and points balance is loaded
                    if "lifemiles.com" in parsed.netloc:
                        html = sb.get_page_source()
                        balance, _ = self._extract_data(html)
                        if balance is not None:
                            success = True
                            print(f"Interactive login successful! Found balance: {balance}. Auto-closing browser in 5 seconds...")
                            sb.sleep(5)
                            break
                except Exception:
                    pass
                time.sleep(4)
                
            if not success:
                raise PluginError("Interactive login timed out or failed to reach dashboard.")
