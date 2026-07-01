from typing import Dict, Any, Optional, Tuple
from .base import ProviderPlugin, PluginError, InteractionRequiredError, get_sb_kwargs
from seleniumbase import SB
from bs4 import BeautifulSoup
import re
import json
import os
from datetime import datetime

class KoreanAirPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "Korean Air"

    @property
    def plugin_id(self) -> str:
        return "korean"

    @property
    def default_cpp(self) -> float:
        return 1.8

    @property
    def custom_tip(self) -> str:
        return "After a successful sign-in, please wait a few seconds for the application to automatically redirect to your mileage overview page, or navigate to <strong>My Mileage > Overview</strong> manually if needed."

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        return last_activity_date

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "Miles earned on or after July 1, 2008 expire strictly on December 31 of the 10th year following the earn date. Activity does not extend them."

    def _cache_path(self, profile_dir: str) -> str:
        """Path to the cached mileage data JSON file for this profile."""
        return os.path.join(profile_dir, "korean_cache.json")

    def _parse_mileage_html(self, html: str) -> Optional[Dict[str, Any]]:
        """Parse mileage data from Korean Air dashboard HTML.
        Returns dict with balance/status/expiration_date, or None if parsing fails."""
        soup = BeautifulSoup(html, "html.parser")

        balance = None
        for box in soup.find_all("div", class_="mileage-my__innerbox"):
            box_text = box.get_text(" ", strip=True)
            if re.search(r"available mileage", box_text, re.I):
                pt_span = box.find("span", class_="mileage-my__point")
                if pt_span:
                    raw = pt_span.text.strip().replace(",", "")
                    if raw.isdigit():
                        balance = int(raw)
                        break

        if balance is None:
            # Fallback balance parsing
            candidates = []
            for el in soup.find_all(["span", "div", "p", "strong", "h1", "h2", "h3", "a"]):
                text = el.get_text().strip()
                if any(kw in text.lower() for kw in ["available mileage", "available mile", "잔여 마일리지", "마일리지"]) and len(text) < 60:
                    clean_points = "".join(filter(str.isdigit, text))
                    if clean_points:
                        candidates.append(int(clean_points))
            if candidates:
                balance = candidates[0]

        if balance is None:
            return None

        # Look for status
        status = "SKYPASS Member"
        status_keywords = ["morning calm", "million miler", "premium", "club", "elite"]
        text_content = soup.get_text().lower()
        for kw in status_keywords:
            if kw in text_content:
                if kw == "morning calm":
                    status = "Morning Calm"
                elif kw == "million miler":
                    status = "Million Miler"
                else:
                    status = kw.title()
                break

        return {
            "balance": balance,
            "status": status,
            "expiration_date": None,
        }

    def _fetch_korean_expiration_data(self, sb, prefix: str = "") -> Tuple[Optional[datetime], Optional[Dict[str, Any]]]:
        """
        Navigates to the Korean Air Mileage Validity page and extracts the earliest expiring mileage batch.
        Returns:
        - expiration_date (datetime of the earliest batch)
        - expiration_meta (dict containing earliest_expiring_amount, earliest_expiring_date, and full list of batches if found)
        """
        import datetime as dt
        
        navigated = False
        
        # 1. Prioritize clicking the "Mileage per valid period" / "유효기간별 마일리지" link on the current dashboard page
        try:
            click_selectors = [
                "a:contains('Mileage per valid period')",
                "a:contains('유효기간별 마일리지')",
                "a:contains('유효기간별')",
                "a:contains('Mileage validity')",
                "a:contains('Validity')",
                "a:contains('유효기간')",
                "a[href*='validity']",
                "a[href*='validity-period']",
                "a[href*='valid']",
                "button:contains('Mileage per valid period')",
                "button:contains('유효기간별 마일리지')",
                "span:contains('Mileage per valid period')",
                "span:contains('유효기간별 마일리지')",
            ]
            for sel in click_selectors:
                if sb.is_element_visible(sel):
                    # Click the link to navigate via SPA transition/Angular Router
                    sb.click(sel)
                    sb.sleep(6)
                    
                    # Validate that we successfully landed on a valid validity/expiration page
                    curr_url = sb.get_current_url().lower()
                    page_title = sb.get_title().lower()
                    page_source = sb.get_page_source().lower()
                    is_404 = (
                        "404" in page_title or 
                        "error" in page_title or 
                        "not found" in page_title or
                        "error" in curr_url or
                        "page cannot be found" in page_source or
                        "존재하지 않는" in page_source or
                        "페이지를 찾을 수" in page_source
                    )
                    if not is_404 and ("validity" in curr_url or "expiration" in curr_url or "mileage" in curr_url or "valid" in curr_url):
                        navigated = True
                        break
        except Exception as click_err:
            print(f"Error clicking validity link on overview page: {click_err}")
            
        # 2. Fall back to direct URL navigation if clicking the dashboard link failed or did not resolve
        if not navigated:
            raw_urls = [
                f"https://www.koreanair.com/{prefix}my-mileage/validity",
                "https://www.koreanair.com/us/en/my-mileage/validity",
                "https://www.koreanair.com/ko/ko/my-mileage/validity",
            ]
            
            # Deduplicate while preserving order
            urls = []
            for u in raw_urls:
                if u not in urls:
                    urls.append(u)
            
            for url in urls:
                try:
                    sb.open(url)
                    sb.sleep(6)
                    curr_url = sb.get_current_url().lower()
                    
                    # Check if page is an error/404 page even if HTTP status is 200
                    page_title = sb.get_title().lower()
                    page_source = sb.get_page_source().lower()
                    is_404 = (
                        "404" in page_title or 
                        "error" in page_title or 
                        "not found" in page_title or
                        "error" in curr_url or
                        "page cannot be found" in page_source or
                        "존재하지 않는" in page_source or
                        "페이지를 찾을 수" in page_source
                    )
                    
                    if not is_404 and ("validity" in curr_url or "expiration" in curr_url or "mileage" in curr_url or "valid" in curr_url):
                        navigated = True
                        break
                except Exception:
                    pass
                
        earliest_exp_date = None
        earliest_exp_amount = None
        batches = []
        
        try:
            html = sb.get_page_source()

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()

            # 1. Target table rows that have both th and td (highly structured table format)
            for tr in soup.find_all("tr"):
                th = tr.find("th")
                td = tr.find("td")
                if not th or not td:
                    # Fallback to checking two td elements in a row if they change th to td
                    tds = tr.find_all("td")
                    if len(tds) >= 2:
                        th, td = tds[0], tds[1]
                    else:
                        continue
                    
                th_text = th.get_text(" ", strip=True)
                td_text = td.get_text(" ", strip=True)
                
                # Search for a year in the range 2024-2038 inside the th/header
                year_match = re.search(r'\b(202\d|203\d)\b', th_text)
                if not year_match:
                    continue
                year = int(year_match.group(1))
                
                # Extract mileage value from the td/details
                numbers = re.findall(r'\b([\d,]+)\b', td_text)
                mileage = None
                for num_str in numbers:
                    clean_num = num_str.replace(",", "")
                    if clean_num.isdigit():
                        val = int(clean_num)
                        if val > 0:
                            mileage = val
                            break
                            
                if mileage is not None:
                    batches.append({
                        "date": dt.datetime(year, 12, 31),
                        "amount": mileage
                    })

            # 2. General fallback: if no table rows matched, search general elements but be extremely strict
            if not batches:
                all_elements = soup.find_all(["tr", "div", "li", "p"])
                for el in all_elements:
                    text = el.get_text(" ", strip=True)
                    if len(text) > 150:
                        continue
                        
                    year_match = re.search(r'\b(202\d|203\d)\b', text)
                    if not year_match:
                        continue
                    year = int(year_match.group(1))
                    
                    # Mileage must be explicitly followed by "miles", "mile", "마일", or "마일리지"
                    # E.g. "Dec 2034 8,599 Miles"
                    miles_matches = re.finditer(r'\b([\d,]+)\s*(?:miles|mile|마일|마일리지)\b', text, re.I)
                    for match in miles_matches:
                        clean_m = match.group(1).replace(",", "")
                        if clean_m.isdigit():
                            val = int(clean_m)
                            if val != year and val > 0:
                                batches.append({
                                    "date": dt.datetime(year, 12, 31),
                                    "amount": val
                                })

            # 3. Page-wide search using date patterns (backup fallback)
            if not batches:
                text_content = soup.get_text(" ", strip=True)
                date_matches = re.finditer(r'\b(202\d|203\d)[.-/년\s]+(12|[01]?\d)[.-/월\s]+(31|[0-3]?\d)일?\b', text_content)
                for dm in date_matches:
                    year_val = int(dm.group(1))
                    start_pos = max(0, dm.start() - 60)
                    end_pos = min(len(text_content), dm.end() + 60)
                    window_text = text_content[start_pos:end_pos]
                    miles_in_window = re.findall(r'\b([\d,]+)\s*(?:miles|mile|마일|마일리지)?\b', window_text, re.I)
                    for m_str in miles_in_window:
                        clean_m = m_str.replace(",", "")
                        if clean_m.isdigit():
                            m_val = int(clean_m)
                            if m_val != year_val and 0 < m_val < 10000000 and m_val != 12 and m_val != 31:
                                batches.append({
                                    "date": dt.datetime(year_val, 12, 31),
                                    "amount": m_val
                                })

            if batches:
                unique_batches = {}
                for b in batches:
                    d_key = b["date"].strftime("%Y-%m-%d")
                    unique_batches[d_key] = max(unique_batches.get(d_key, 0), b["amount"])
                    
                sorted_batches = sorted([{"date": dt.datetime.strptime(k, "%Y-%m-%d"), "amount": v} for k, v in unique_batches.items()], key=lambda x: x["date"])
                
                if sorted_batches:
                    earliest = sorted_batches[0]
                    earliest_exp_date = earliest["date"]
                    earliest_exp_amount = earliest["amount"]
                    
                    return earliest_exp_date, {
                        "earliest_expiring_amount": earliest_exp_amount,
                        "earliest_expiring_date": earliest_exp_date.strftime("%Y-%m-%d"),
                        "batches": [{"date": b["date"].strftime("%Y-%m-%d"), "amount": b["amount"]} for b in sorted_batches]
                    }
        except Exception as e:
            print(f"Error parsing Korean Air validity page: {e}")
            
        return earliest_exp_date, None

    def _save_cache(self, profile_dir: str, data: Dict[str, Any]) -> None:
        """Save parsed mileage data to a JSON cache file."""
        import copy
        data_copy = copy.deepcopy(data)
        if "expiration_date" in data_copy and isinstance(data_copy["expiration_date"], datetime):
            data_copy["expiration_date"] = data_copy["expiration_date"].strftime("%Y-%m-%d")
            
        cache = {
            "fetched_at": datetime.utcnow().isoformat(),
            "data": data_copy,
        }
        os.makedirs(profile_dir, exist_ok=True)
        with open(self._cache_path(profile_dir), "w") as f:
            json.dump(cache, f)

    def _load_cache(self, profile_dir: str, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Load cached mileage data. Returns the data dict or None."""
        path = self._cache_path(profile_dir)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                cache = json.load(f)
            
            # Check max age if specified
            if max_age_seconds is not None:
                fetched_at_str = cache.get("fetched_at")
                if not fetched_at_str:
                    return None
                fetched_at = datetime.fromisoformat(fetched_at_str)
                age = (datetime.utcnow() - fetched_at).total_seconds()
                if age > max_age_seconds:
                    return None

            data = cache.get("data")
            if data and "expiration_date" in data and data["expiration_date"]:
                if isinstance(data["expiration_date"], str):
                    data["expiration_date"] = datetime.strptime(data["expiration_date"], "%Y-%m-%d")
            return data
        except Exception:
            return None

    def _try_auto_login(self, sb, username: str, password: str) -> bool:
        """Attempt to fill in credentials and log in on the Korean Air login page.
        Returns True if login appears successful (navigated away from login page)."""
        try:
            # Wait for login form to render
            sb.sleep(4)

            # Check username format: 12-digit is SKYPASS number, otherwise it is User ID
            is_skypass = bool(re.match(r'^\d{12}$', username.strip()))
            
            if is_skypass:
                # tab_1 is Skypass number
                tab_selectors = [
                    "button[id*='tab_1']",
                    "[id*='tab_1']",
                    "#tab_1",
                    "button:contains('SKYPASS')",
                    "button:contains('스카이패스')",
                    "a:contains('SKYPASS')",
                    "li:contains('SKYPASS')"
                ]
            else:
                # tab_0 is User ID
                tab_selectors = [
                    "button[id*='tab_0']",
                    "[id*='tab_0']",
                    "#tab_0",
                    "button:contains('User ID')",
                    "button:contains('아이디')",
                    "a:contains('User ID')",
                    "li:contains('User ID')"
                ]

            for tab_sel in tab_selectors:
                try:
                    if sb.is_element_visible(tab_sel):
                        sb.click(tab_sel)
                        sb.sleep(1.5)
                        break
                except Exception:
                    pass

            # Type username/SKYPASS number
            username_selectors = [
                "input[id*='id']",
                "input[id*='username']",
                "input[placeholder*='SKYPASS']",
                "input[placeholder*='skypass']",
                "input[type='text']",
            ]
            username_filled = False
            for sel in username_selectors:
                if sb.is_element_visible(sel):
                    sb.type(sel, username)
                    username_filled = True
                    sb.sleep(1)
                    break
            
            if not username_filled:
                return False

            # Type password
            password_selectors = [
                "input[type='password']",
                "input[id*='password']",
            ]
            password_filled = False
            for sel in password_selectors:
                if sb.is_element_visible(sel):
                    sb.type(sel, password)
                    password_filled = True
                    sb.sleep(1)
                    break

            if not password_filled:
                return False

            # Click login button
            submit_selectors = [
                "button.login__submit-act",
                "button:contains('Log In')",
                "button:contains('로그인')",
                "button[type='submit']",
            ]
            submit_clicked = False
            for sel in submit_selectors:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    submit_clicked = True
                    break

            if not submit_clicked:
                return False

            # Wait for navigation away from login page, detecting and bypassing any password change notification dialog
            bypass_selectors = [
                "button.confirm.-ghost",
                "button:contains('Remind me again in 90 days')",
                "button:contains('다음에 변경')",
                "button:contains('90일')",
            ]

            for _ in range(15):
                sb.sleep(2)
                current_url = sb.get_current_url().lower()
                
                # Check for password change reminder popup and dismiss it
                for bp_sel in bypass_selectors:
                    try:
                        if sb.is_element_visible(bp_sel):
                            print(f"Detected password change reminder. Clicking to bypass: {bp_sel}")
                            sb.click(bp_sel)
                            sb.sleep(4)
                            current_url = sb.get_current_url().lower()
                            break
                    except Exception:
                        pass

                if "set-password" in current_url or "password/verify" in current_url:
                    print("Detected password reset redirection.")
                    raise InteractionRequiredError(
                        "Your Korean Air account requires a password reset. "
                        "Please run Interactive Login to complete the password reset flow directly."
                    )

                if "login" not in current_url and "signin" not in current_url:
                    return True

            return False
        except InteractionRequiredError:
            raise
        except Exception:
            return False

    def _fetch_korean_coupon_data(self, sb, prefix: str = "") -> list:
        """
        Navigates to the Korean Air Coupons/Wallet page and extracts all available discount and lounge coupons.
        """
        navigated = False
        
        # 1. Try to click Coupon / Wallet links from the overview page
        try:
            click_selectors = [
                "a:contains('Coupon')",
                "a:contains('쿠폰')",
                "a[href*='coupon']",
                "a[href*='wallet']",
                "button:contains('Coupon')",
                "button:contains('쿠폰')",
                "span:contains('Coupon')",
                "span:contains('쿠폰')",
            ]
            for sel in click_selectors:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.sleep(6)
                    
                    curr_url = sb.get_current_url().lower()
                    if "coupon" in curr_url or "wallet" in curr_url:
                        navigated = True
                        break
        except Exception as click_err:
            print(f"Error clicking coupon link: {click_err}")
            
        # 2. Direct URL navigation fallback
        if not navigated:
            urls = [
                f"https://www.koreanair.com/{prefix}my-wallet/coupon",
                "https://www.koreanair.com/my-wallet/coupon",
                f"https://www.koreanair.com/{prefix}my-mileage/wallet/coupon",
                f"https://www.koreanair.com/{prefix}my-mileage/coupon",
                "https://www.koreanair.com/us/en/my-mileage/wallet/coupon",
                "https://www.koreanair.com/ko/ko/my-mileage/wallet/coupon",
            ]
            for url in urls:
                try:
                    sb.open(url)
                    sb.sleep(6)
                    curr_url = sb.get_current_url().lower()
                    if "coupon" in curr_url or "wallet" in curr_url:
                        navigated = True
                        break
                except Exception:
                    pass
                    
        # 3. Parse the page source using our multi-strategy parser
        certificates = []
        try:
            html = sb.get_page_source()
                
            from bs4 import BeautifulSoup
            import re
            import datetime as dt
            
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
                
            # Strategy 1: Card-based layouts
            all_candidates = soup.find_all(class_=re.compile(r"\b(?:coupon-item|coupon-card|coupon-box|benefit-item|card-item|button-card__list|button-card__link)\b", re.I))
            cards = []
            for el in all_candidates:
                if any(ancestor in cards for ancestor in el.parents):
                    continue
                cards.append(el)
                
            for card in cards:
                text = card.get_text(" ", strip=True)
                if not any(k in text.lower() for k in ["coupon", "voucher", "lounge", "discount", "쿠폰", "할인", "라운지", "우대권"]):
                    continue
                    
                title_el = card.find(class_=re.compile(r"title|name|subject", re.I))
                if not title_el:
                    title_el = card.find(class_=re.compile(r"header|label", re.I))
                
                title = "SKYPASS Benefit"
                if title_el:
                    status_el = title_el.find(class_=re.compile(r"status|state", re.I))
                    if status_el:
                        status_el.decompose()
                    title = title_el.text.strip()
                    
                num_el = card.find(class_=re.compile(r"number|code|no", re.I))
                number = None
                if num_el:
                    number = num_el.text.strip().replace("Coupon No :", "").replace("쿠폰번호 :", "").replace(":", "").strip()
                else:
                    num_match = re.search(r'(?:no|number|번호|코드)\s*[:：]?\s*([A-Za-z0-9-]+)', text, re.I)
                    if num_match:
                        number = num_match.group(1).strip()
                        
                expiry = None
                date_matches = list(re.finditer(r'\b(202\d|203\d)[.\-/년\s]+(12|[01]?\d)[.\-/월\s]+(31|[0-3]?\d)일?\b', text))
                if date_matches:
                    last_match = date_matches[-1]
                    expiry = dt.datetime(int(last_match.group(1)), int(last_match.group(2)), int(last_match.group(3)))
                else:
                    eng_matches = list(re.finditer(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\s*,?\s*(202\d|203\d)\b', text, re.I))
                    if eng_matches:
                        last_match = eng_matches[-1]
                        months = {"jan":1, "feb":2, "mar":3, "apr":4, "may":5, "jun":6, "jul":7, "aug":8, "sep":9, "oct":10, "nov":11, "dec":12}
                        m_str = last_match.group(1).lower()[:3]
                        expiry = dt.datetime(int(last_match.group(3)), months.get(m_str, 12), int(last_match.group(2)))
                        
                details = {}
                if number:
                    details["Coupon Number"] = number
                    
                badge_el = card.find(class_=re.compile(r"badge", re.I))
                if badge_el:
                    details["Type"] = badge_el.text.strip()
                    
                desc_el = card.find(class_=re.compile(r"desc|detail|terms|info", re.I))
                if desc_el:
                    details["Description"] = desc_el.text.strip()
                    
                certificates.append({
                    "name": title,
                    "expiration_date": expiry.strftime("%Y-%m-%d") if expiry else None,
                    "details": details
                })
                card.decompose()

            # Strategy 2: Table-based layouts
            rows = soup.find_all("tr")
            for tr in rows:
                tds = tr.find_all(["td", "th"])
                if len(tds) < 2:
                    continue
                    
                row_text = tr.get_text(" ", strip=True)
                if not any(k in row_text.lower() for k in ["coupon", "voucher", "lounge", "discount", "쿠폰", "할인", "라운지", "우대권"]) or "coupon name" in row_text.lower():
                    continue
                    
                title = tds[0].text.strip()
                number = None
                if len(tds) >= 3:
                    number = tds[1].text.strip()
                    
                expiry = None
                date_matches = list(re.finditer(r'\b(202\d|203\d)[.\-/년\s]+(12|[01]?\d)[.\-/월\s]+(31|[0-3]?\d)일?\b', row_text))
                if date_matches:
                    last_match = date_matches[-1]
                    expiry = dt.datetime(int(last_match.group(1)), int(last_match.group(2)), int(last_match.group(3)))
                    
                details = {}
                if number:
                    details["Coupon Number"] = number
                    
                certificates.append({
                    "name": title,
                    "expiration_date": expiry.strftime("%Y-%m-%d") if expiry else None,
                    "details": details
                })
        except Exception as e:
            print(f"Error parsing Korean Air coupons page: {e}")
            
        return certificates

    def _get_localized_prefix(self, sb) -> str:
        """
        Extracts the region/language prefix path segment (e.g., 'us/en/' or 'ko/ko/') from the current browser URL.
        Returns empty string '' if no prefix is found.
        """
        curr_url = sb.get_current_url().lower()
        match = re.search(r'koreanair\.com/([a-z]{2})/([a-z]{2})/', curr_url)
        if match:
            return f"{match.group(1)}/{match.group(2)}/"
        return ""

    def fetch_data(self, username: str, password: str, profile_dir: str = None) -> Dict[str, Any]:
        if username:
            username = username.replace(' ', '')
        result = None

        try:
            with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir)) as sb:
                # 1. First open login page to check session validity
                sb.open("https://www.koreanair.com/login")
                sb.sleep(5)

                current_url = sb.get_current_url().lower()
                if "set-password" in current_url or "password/verify" in current_url:
                    raise InteractionRequiredError(
                        "Your Korean Air account requires a password reset. "
                        "Please run Interactive Login to complete the password reset flow directly."
                    )
                prefix = self._get_localized_prefix(sb)

                # If redirected or stuck on login page, attempt login
                if "login" in current_url or "signin" in current_url:
                    logged_in = self._try_auto_login(sb, username, password)
                    if not logged_in:
                        raise InteractionRequiredError("auto_login_failed")
                    current_url = sb.get_current_url().lower()
                    if "set-password" in current_url or "password/verify" in current_url:
                        raise InteractionRequiredError(
                            "Your Korean Air account requires a password reset. "
                            "Please run Interactive Login to complete the password reset flow directly."
                        )
                    prefix = self._get_localized_prefix(sb)

                # 2. Open localized overview page
                target_url = f"https://www.koreanair.com/{prefix}my-mileage/overview"
                sb.open(target_url)
                sb.sleep(5)

                current_url = sb.get_current_url().lower()
                if "set-password" in current_url or "password/verify" in current_url:
                    raise InteractionRequiredError(
                        "Your Korean Air account requires a password reset. "
                        "Please run Interactive Login to complete the password reset flow directly."
                    )
                # Post-navigation session-loss fallback check
                if "login" in current_url or "signin" in current_url:
                    logged_in = self._try_auto_login(sb, username, password)
                    if logged_in:
                        current_url = sb.get_current_url().lower()
                        if "set-password" in current_url or "password/verify" in current_url:
                            raise InteractionRequiredError(
                                "Your Korean Air account requires a password reset. "
                                "Please run Interactive Login to complete the password reset flow directly."
                            )
                        prefix = self._get_localized_prefix(sb)
                        sb.open(f"https://www.koreanair.com/{prefix}my-mileage/overview")
                        sb.sleep(5)
                    else:
                        raise InteractionRequiredError("auto_login_failed")

                # Wait for Angular app to render mileage data (up to 60s)
                for _ in range(30):
                    src = sb.get_page_source()
                    soup = BeautifulSoup(src, "html.parser")
                    pt_span = soup.find("span", class_="mileage-my__point") or soup.find(class_="mileage-my__point")
                    if pt_span and pt_span.text.strip():
                        break
                    sb.sleep(2)
                else:
                    raise InteractionRequiredError("page_not_loaded")

                sb.sleep(2)
                html = sb.get_page_source()

                result = self._parse_mileage_html(html)
                if result:
                    # Fetch expiration batches
                    try:
                        exp_date, exp_meta = self._fetch_korean_expiration_data(sb, prefix=prefix)
                        if exp_date:
                            result["expiration_date"] = exp_date
                        if exp_meta:
                            result["expiration_meta"] = exp_meta
                    except Exception as ex_err:
                        print(f"Failed to fetch Korean Air expiration data: {ex_err}")

                    # Fetch coupons
                    try:
                        certs = self._fetch_korean_coupon_data(sb, prefix=prefix)
                        result["certificates"] = certs
                    except Exception as cert_err:
                        print(f"Failed to fetch Korean Air coupon data: {cert_err}")

            if result:
                if profile_dir:
                    self._save_cache(profile_dir, result)
                return result
            else:
                # Parse failed on live page — try cache if fresh
                raise InteractionRequiredError("parse_failed")

        except InteractionRequiredError:
            # Live session failed — only fall back to cache if it is fresh (within 15 minutes)
            if profile_dir:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    return cached

            raise InteractionRequiredError(
                "Korean Air session expired and auto-login failed. "
                "Please run Interactive Login — your mileage will be captured during the login session."
            )
        except PluginError:
            raise
        except Exception as e:
            # On any unexpected error, also try cache only if it is fresh (within 15 minutes)
            if profile_dir:
                cached = self._load_cache(profile_dir, max_age_seconds=900)
                if cached:
                    return cached
            raise PluginError(f"Korean Air scraping failed: {e}")

    def interactive_login(self, username: str, password: str, profile_dir: str = None) -> None:
        if username:
            username = username.replace(' ', '')
        with SB(**get_sb_kwargs(uc=True, user_data_dir=profile_dir, headed=True)) as sb:
            sb.open("https://www.koreanair.com/login")
            sb.sleep(3)

            print("Please log in manually on the Korean Air login page.")
            print("After logging in, navigate to My Mileage > Overview.")
            print("Your mileage will be captured automatically once the page loads.")
            try:
                for _ in range(60):  # Wait up to 5 minutes
                    current_url = sb.get_current_url().lower()
                    
                    # If logged in successfully and landed on homepage/any non-login page, redirect to mileage overview
                    if "login" not in current_url and "signin" not in current_url and "my-mileage" not in current_url and "skypass" not in current_url:
                        match = re.search(r'koreanair\.com/([a-z]{2})/([a-z]{2})', current_url)
                        prefix = f"{match.group(1)}/{match.group(2)}/" if match else ""
                        target = f"https://www.koreanair.com/{prefix}my-mileage/overview"
                        print(f"Logged in detected! Redirecting automatically to mileage overview: {target}")
                        sb.open(target)
                        sb.sleep(5)
                        current_url = sb.get_current_url().lower()

                    if "my-mileage" in current_url or "skypass" in current_url:
                        print(f"Detected dashboard URL: {current_url}")

                        match = re.search(r'koreanair\.com/([a-z]{2})/([a-z]{2})/', current_url.lower())
                        prefix = f"{match.group(1)}/{match.group(2)}/" if match else ""

                        print("Waiting for Angular SPA to finish loading...")
                        for _ in range(30):
                            src = sb.get_page_source()
                            soup = BeautifulSoup(src, "html.parser")
                            pt_span = soup.find("span", class_="mileage-my__point") or soup.find(class_="mileage-my__point")
                            if pt_span and pt_span.text.strip():
                                break
                            sb.sleep(2)

                        sb.sleep(3)  # allow page to fully render

                        html = sb.get_page_source()

                        # Parse and cache the mileage data while session is alive
                        result = self._parse_mileage_html(html)
                        if result:
                            try:
                                exp_date, exp_meta = self._fetch_korean_expiration_data(sb, prefix=prefix)
                                if exp_date:
                                    result["expiration_date"] = exp_date.strftime("%Y-%m-%d")
                                if exp_meta:
                                    result["expiration_meta"] = exp_meta
                            except Exception as ex_err:
                                print(f"Failed to fetch Korean Air expiration data in interactive mode: {ex_err}")

                            # Fetch coupons
                            try:
                                certs = self._fetch_korean_coupon_data(sb, prefix=prefix)
                                result["certificates"] = certs
                            except Exception as cert_err:
                                print(f"Failed to fetch Korean Air coupon data in interactive mode: {cert_err}")

                            if profile_dir:
                                self._save_cache(profile_dir, result)
                                print(f"Captured mileage: {result['balance']} miles (cached for sync)")
                        else:
                            print("Warning: could not parse mileage from the page.")

                        # Also save raw HTML for debugging
                        with open("korean_dashboard_debug.html", "w", encoding="utf-8") as f:
                            f.write(html)

                        break
                    sb.sleep(5)
            except Exception as e:
                print(f"Interactive login wait interrupted: {e}")
