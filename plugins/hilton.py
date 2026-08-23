from typing import Dict, Any, Tuple, Optional
from datetime import datetime
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs
from seleniumbase import SB
from bs4 import BeautifulSoup
import time

class HiltonHonorsPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Hilton Honors"

    @property
    def plugin_id(self) -> str:
        return "hilton"

    @property
    def default_cpp(self) -> float:
        return 0.6

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        from .base import add_months
        return add_months(last_activity_date, 24)

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Points expire after 24 months of inactivity. Any earning or redemption transaction extends them."

    def _extract_last_activity_date(self, html: str) -> Optional[datetime]:
        """Extracts the latest qualifying activity date found in the HTML source."""
        import re
        from datetime import datetime
        import calendar

        dates = []
        today = datetime.now()

        # 1. Full dates: Month DD, YYYY (e.g. Mar 15, 2025, March 15, 2025)
        pattern_month_day = r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(20\d{2})\b'
        for m in re.finditer(pattern_month_day, html, re.IGNORECASE):
            try:
                m_str, d_str, y_str = m.group(1), m.group(2), m.group(3)
                for fmt in ('%b %d %Y', '%B %d %Y'):
                    try:
                        dt = datetime.strptime(f"{m_str} {d_str} {y_str}", fmt)
                        if dt <= today:
                            dates.append(dt)
                        break
                    except ValueError:
                        pass
            except Exception:
                pass

        # 2. Full dates: DD Month YYYY (e.g. 15 Mar 2025, 15 March 2025)
        pattern_day_month = r'\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?),?\s+(20\d{2})\b'
        for m in re.finditer(pattern_day_month, html, re.IGNORECASE):
            try:
                d_str, m_str, y_str = m.group(1), m.group(2), m.group(3)
                for fmt in ('%d %b %Y', '%d %B %Y'):
                    try:
                        dt = datetime.strptime(f"{d_str} {m_str} {y_str}", fmt)
                        if dt <= today:
                            dates.append(dt)
                        break
                    except ValueError:
                        pass
            except Exception:
                pass

        # 3. ISO / Dash dates: YYYY-MM-DD (e.g. 2025-03-15)
        for m in re.findall(r'\b(20\d{2}-\d{2}-\d{2})\b', html):
            try:
                dt = datetime.strptime(m, "%Y-%m-%d")
                if dt <= today:
                    dates.append(dt)
            except Exception:
                pass

        # 4. Dot dates: YYYY.MM.DD (e.g. 2025.03.15 or 2025. 03. 15)
        for m in re.findall(r'\b20\d{2}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\b', html):
            try:
                clean = re.sub(r'\s+', '', m)
                parts = clean.split('.')
                dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                if dt <= today:
                    dates.append(dt)
            except Exception:
                pass

        # 5. Slash dates: MM/DD/YYYY or M/D/YYYY (e.g. 03/15/2025, 3/15/2025)
        for m in re.findall(r'\b(\d{1,2}/\d{1,2}/20\d{2})\b', html):
            try:
                dt = datetime.strptime(m, "%m/%d/%Y")
                if dt <= today:
                    dates.append(dt)
            except Exception:
                pass

        # 6. Korean full dates: YYYY년 MM월 DD일
        for m in re.findall(r'20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일', html):
            try:
                nums = re.findall(r'\d+', m)
                if len(nums) == 3:
                    dt = datetime(int(nums[0]), int(nums[1]), int(nums[2]))
                    if dt <= today:
                        dates.append(dt)
            except Exception:
                pass

        # 7. Month-Year only: Month YYYY (e.g. Mar 2025, March 2025)
        pattern_month_year = r'(?<!\d\s)(?<!\d)(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(20\d{2})(?!\s*\d)'
        for m in re.finditer(pattern_month_year, html, re.IGNORECASE):
            try:
                m_str = m.group(0).split()[0]
                y_str = m.group(1)
                for fmt in ('%b %Y', '%B %Y'):
                    try:
                        parsed = datetime.strptime(f"{m_str} {y_str}", fmt)
                        _, last_day = calendar.monthrange(parsed.year, parsed.month)
                        dt = datetime(parsed.year, parsed.month, last_day)
                        if dt > today:
                            dt = datetime(parsed.year, parsed.month, min(today.day, last_day))
                        if dt <= today:
                            dates.append(dt)
                        break
                    except ValueError:
                        pass
            except Exception:
                pass

        # 8. ISO Month-Year: YYYY-MM (e.g. 2025-03)
        for m in re.finditer(r'(?<!\d)(20\d{2})-(\d{2})(?!-\d)', html):
            try:
                y, mon = int(m.group(1)), int(m.group(2))
                if 1 <= mon <= 12:
                    _, last_day = calendar.monthrange(y, mon)
                    dt = datetime(y, mon, last_day)
                    if dt > today:
                        dt = datetime(y, mon, min(today.day, last_day))
                    if dt <= today:
                        dates.append(dt)
            except Exception:
                pass

        # 9. Korean Month-Year: YYYY년 MM월
        for m in re.finditer(r'(20\d{2})\s*년\s*(\d{1,2})\s*월(?!\s*\d{1,2}\s*일)', html):
            try:
                y, mon = int(m.group(1)), int(m.group(2))
                if 1 <= mon <= 12:
                    _, last_day = calendar.monthrange(y, mon)
                    dt = datetime(y, mon, last_day)
                    if dt > today:
                        dt = datetime(y, mon, min(today.day, last_day))
                    if dt <= today:
                        dates.append(dt)
            except Exception:
                pass

        if dates:
            return max(dates)
        return None

    def _extract_data(self, sb) -> Tuple[Optional[int], Optional[str], Optional[datetime]]:
        """Extracts points balance, status, and last activity date from the Hilton DOM."""
        balance, status, last_activity_date = None, None, None
        
        try:
            import re
            html = sb.get_page_source()
            soup = BeautifulSoup(html, "html.parser")
            
            # 1. Extract Points using specific regex patterns
            patterns_points = [
                r'([\d,]+)\s*points\s*total',
                r'total\s*points[:\s]+([\d,]+)',
                r'([\d,]+)\s*hilton\s*honors\s*points',
                r'([\d,]+)\s*total\s*honors\s*points',
            ]
            for pat in patterns_points:
                m = re.search(pat, html, re.IGNORECASE)
                if m:
                    clean = m.group(1).replace(",", "").strip()
                    if clean.isdigit():
                        balance = int(clean)
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
            patterns_status = [
                r'\b(Diamond|Gold|Silver|Member)\s+Status\b',
                r'\b(Diamond|Gold|Silver|Member)\s+Tier\b',
            ]
            for pat in patterns_status:
                m = re.search(pat, html, re.IGNORECASE)
                if m:
                    status = m.group(1).capitalize()
                    break

            if not status:
                for tier in ["Diamond", "Gold", "Silver", "Member"]:
                    for el in soup.find_all(["p", "span", "h1", "h2", "h3"]):
                        if not el.find_all(True):
                            t = el.get_text(strip=True)
                            if t.lower() == tier.lower() or t.lower() == f"{tier.lower()} member" or t.lower() == f"{tier.lower()} status":
                                status = tier
                                break
                    if status:
                        break

            # 3. Extract Last Activity Date
            last_activity_date = self._extract_last_activity_date(html)
                
        except Exception:
            pass
            
        return balance, status, last_activity_date

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        """Fills the Hilton login form and submits."""
        user_selector = "input[name='username']"
        pass_selector = "input[name='password']"
        submit_selector = "button[type='submit']"
        
        if not sb.is_element_visible(user_selector):
            sb.sleep(3)
            
        if not sb.is_element_visible(user_selector):
            raise InteractionRequiredError("Could not find Hilton login form, might be blocked by captcha or layout changed.")

        sb.wait_for_element_visible(user_selector, timeout=10)
        try:
            sb.type(user_selector, username)
        except Exception:
            pass
        sb.sleep(0.5)
        
        sb.wait_for_element_visible(pass_selector, timeout=10)
        try:
            sb.type(pass_selector, password)
        except Exception:
            pass
        sb.sleep(0.5)
        
        if auto_submit:
            if sb.is_element_visible(submit_selector):
                try:
                    sb.click(submit_selector)
                except Exception:
                    sb.type(pass_selector, "\n")
            else:
                sb.type(pass_selector, "\n")
        elif not auto_submit and sb.is_element_visible(submit_selector):
            sb.click(submit_selector)

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        result = {
            "balance": 0,
            "status": "Unknown",
            "expiration_date": None,
            "certificates": []
        }
        
        try:
            with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir)) as sb:
                # 1. Open Hilton sign-in URL first
                sb.uc_open_with_reconnect("https://www.hilton.com/en/hilton-honors/login/", 4)
                sb.sleep(8)
                
                # Check if login form is presented
                user_selector = "input[name='username']"
                if sb.is_element_visible(user_selector):
                    self._fill_login_form(sb, username, password, auto_submit=True)
                    sb.sleep(10)

                # 2. Always navigate to the activity page to extract transactions/stays & last activity date
                curr_url = sb.get_current_url()
                if "activity" not in curr_url:
                    sb.open("https://www.hilton.com/en/hilton-honors/guest/activity/")
                    sb.sleep(8)

                # 3. Extract data from activity page
                balance, status, last_activity = self._extract_data(sb)
                if balance is None:
                    # Fallback refresh in case of slow API response rendering
                    sb.refresh()
                    sb.sleep(8)
                    balance, status, last_activity = self._extract_data(sb)

                # 4. If balance was not found on activity page, fallback to overview / dashboard
                if balance is None:
                    sb.open("https://www.hilton.com/en/hilton-honors/guest/overview/")
                    sb.sleep(8)
                    overview_balance, overview_status, _ = self._extract_data(sb)
                    if overview_balance is not None:
                        balance = overview_balance
                        if not status:
                            status = overview_status
                    
                if balance is None:
                    # Dump the HTML for debug
                    with open("hilton_error_dump.html", "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
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
                
                return result
                
        except InteractionRequiredError:
            raise
        except Exception as e:
            raise PluginError(f"Scraping failed: {str(e)}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        """
        Opens an interactive browser window for the user to resolve MFA.
        Uses the same user_data_dir so cookies are saved for future headless runs.
        """
        with SB(**get_sb_kwargs(uc=True, headless=False, user_data_dir=profile_dir)) as sb:
            sb.uc_open_with_reconnect("https://www.hilton.com/en/hilton-honors/login/", 4)
            sb.sleep(3)
            
            # Prefill credentials if visible
            try:
                self._fill_login_form(sb, username, password, auto_submit=False)
            except Exception:
                pass
            
            # Wait up to 5 minutes for the user to resolve MFA and reach the dashboard
            try:
                start_time = time.time()
                success = False
                while time.time() - start_time < 300:
                    balance, _, _ = self._extract_data(sb)
                    if balance is not None:
                        success = True
                        break
                    time.sleep(2)
                
                if not success:
                    raise PluginError("Interactive login timed out after 5 minutes or points were not found.")
                
                # Let it settle so cookies save
                sb.sleep(5)
            except Exception:
                raise PluginError("Interactive login timed out after 5 minutes or activity page failed to load.")
