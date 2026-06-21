from typing import Dict, Any, Optional
from .base import ProviderPlugin, PluginError, InteractionRequiredError
from seleniumbase import SB
from bs4 import BeautifulSoup
import re
from datetime import datetime
import logging

logger = logging.getLogger('awardtracker')

def print(*args, **kwargs):
    message = " ".join(str(arg) for arg in args)
    logger.info(f"[JAL] {message}")


class JAPANAirlinesPlugin(ProviderPlugin):
    @property
    def name(self) -> str:
        return "JAL Mileage Bank"

    @property
    def plugin_id(self) -> str:
        return "jal"

    @property
    def default_cpp(self) -> float:
        return 1.4

    def calculate_expiration(self, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
        return last_activity_date

    def get_expiration_policy_description(self, status: str = None) -> str:
        return "JAL Mileage Bank miles are valid for 36 months from the month they were earned. Activity does not extend them."

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def is_auth_url(self, url: str) -> bool:
        main_url = url.lower().split('?')[0]
        return any(k in main_url for k in ["jallogin", "login", "auth", "sso"])

    def _start_url(self, region: str) -> str:
        urls = {
            "AR": "https://www121.jal.co.jp/JmbWeb/AR/JMBmemberTop_en.do",
            "ER": "https://www121.jal.co.jp/JmbWeb/ER/JMBmemberTop_en.do",
            "SR": "https://www121.jal.co.jp/JmbWeb/SR/JMBmemberTop_en.do",
        }
        return urls.get(region, "https://www121.jal.co.jp/JmbWeb/JR/JmbTop_en.do")

    def _regional_homepage(self, region: str) -> str:
        urls = {"AR": "https://www.jal.co.jp/ar/en/", "ER": "https://www.jal.co.jp/er/en/",
                "SR": "https://www.jal.co.jp/sr/en/"}
        return urls.get(region, "https://www.jal.co.jp/jp/en/")

    def _dismiss_cookie_banners(self, sb) -> None:
        try:
            sb.execute_script("""
                ['onetrust-banner-sdk','onetrust-consent-sdk'].forEach(id => {
                    const el = document.getElementById(id); if (el) el.remove();
                });
                const ov = document.querySelector('.onetrust-pc-dark-filter');
                if (ov) ov.remove();
            """)
        except Exception:
            pass
        for sel in ["button#onetrust-accept-btn-handler", "button#accept-recommended-btn-handler",
                    "button#accept-all"]:
            try:
                if sb.is_element_visible(sel):
                    sb.click(sel)
                    sb.sleep(0.5)
            except Exception:
                pass

    def _normalize_status(self, raw: str) -> str:
        t = raw.strip().upper()
        if "CRYSTAL" in t:   return "JMB Crystal"
        if "SAPPHIRE" in t:  return "JMB Sapphire"
        if "PREMIER" in t:   return "JGC Premier"
        if "DIAMOND" in t:   return "JMB Diamond"
        if "MILEAGE BANK" in t or not t: return "Member"
        return t.title()

    # -------------------------------------------------------------------------
    # Region mismatch detection
    # -------------------------------------------------------------------------

    def _detect_region_mismatch(self, sb) -> Optional[str]:
        try:
            if sb.is_element_present("span#JS_121_mileBalance"):
                return None
            current_url = sb.get_current_url().lower()
            if "jal.com/index" in current_url or "worldwide" in sb.get_title().lower():
                return None
            page_text = sb.get_text("body").lower()
            mismatch_phrases = [
                "not registered", "region mismatch", "different region",
                "registered in another region", "another region", "other region",
                "登録されていません", "地区", "居住地", "異なる地区",
                "services on this website are not available to you",
                "go to the jal website of your membership region",
            ]
            if not any(p in page_text for p in mismatch_phrases):
                return None

            print("Region mismatch detected. Determining correct region...")
            html = sb.get_page_source().lower()
            soup = BeautifulSoup(html, "html.parser")
            error_unit = soup.find(class_=re.compile(r"error-unit|error-box|warning-unit|alert"))
            links = error_unit.find_all("a") if error_unit else soup.find_all("a")

            for a in links:
                href = a.get("href", "").lower()
                if "jal.co.jp" in href or "jal.com" in href or "jmbweb" in href:
                    if "/ar/" in href:   return "AR"
                    if "/er/" in href or "/uk/en/" in href: return "ER"
                    if "/sr/" in href or "/sg/en/" in href or "/au/en/" in href: return "SR"
                    if "/jr/" in href or "/jp/en/" in href:
                        if error_unit: return "JR"

            main_text = error_unit.text.lower() if error_unit else page_text
            if "america" in main_text or "usa" in main_text or "canada" in main_text: return "AR"
            if "europe" in main_text or "uk" in main_text or "london" in main_text:  return "ER"
            if "asia" in main_text or "oceania" in main_text or "singapore" in main_text: return "SR"
            if ("japan" in main_text or "tokyo" in main_text) and error_unit: return "JR"
        except Exception as e:
            print(f"Region mismatch detection error: {e}")
        return None

    # -------------------------------------------------------------------------
    # Worldwide Sites selector handling
    # -------------------------------------------------------------------------

    def _handle_worldwide_sites(self, sb, region: str = "JR") -> bool:
        current_url = sb.get_current_url().lower()
        try:
            title = sb.get_title().lower()
        except Exception:
            title = ""

        is_ww = (
            "worldwide sites" in title
            or "jal.com/index" in current_url
            or ("jal.com" in current_url and sb.is_element_visible("a[href='https://www.jal.co.jp/en/']"))
        )
        if not is_ww:
            return False

        print(f"Worldwide Sites page detected. Selecting region {region}...")
        selectors = {
            "AR": ["a[href*='/ar/en/']", "a[href*='jal.co.jp/ar/']"],
            "ER": ["a[href*='/er/en/']", "a[href*='jal.co.jp/er/']", "a[href*='/uk/en/']"],
            "SR": ["a[href*='/sr/en/']", "a[href*='jal.co.jp/sr/']", "a[href*='/sg/en/']", "a[href*='/au/en/']"],
            "JR": ["a[href='https://www.jal.co.jp/en/']", "a[href*='jal.co.jp/en/']", "a[href*='/ar/en/']"],
        }.get(region, ["a[href*='jal.co.jp/en/']"])

        clicked = False
        for sel in selectors:
            if sb.is_element_present(sel):
                try:
                    sb.execute_script(f'const el = document.querySelector("{sel}"); if (el) el.click();')
                    clicked = True
                    break
                except Exception:
                    pass

        if not clicked:
            for sel in selectors:
                if sb.is_element_visible(sel):
                    try:
                        sb.click(sel)
                        clicked = True
                        break
                    except Exception:
                        pass

        if not clicked:
            # Fallback: use dropdown form
            city = {"AR": "SFO", "ER": "LON", "SR": "SIN"}.get(region, "TYO")
            try:
                sb.select_option_by_value("select#JS_countryList", city)
                sb.execute_script(
                    'const el = document.querySelector("select#JS_countryList");'
                    'if (el) el.dispatchEvent(new Event("change", {bubbles:true}));'
                )
                sb.sleep(1)
                lang_sel = next((s for s in ["span#en", "li[lang='en'] a"]
                                 if sb.is_element_visible(s)), None)
                if lang_sel:
                    sb.click(lang_sel)
                else:
                    sb.execute_script(
                        'const el = document.querySelector("span#en") || '
                        'document.querySelector(\'li[lang="en"] a\'); if (el) el.click();'
                    )
                sb.sleep(1)
                sb.click("a#JS_btnLocation")
                clicked = True
            except Exception as e:
                print(f"Worldwide Sites dropdown fallback failed: {e}")

        if clicked:
            for _ in range(15):
                sb.sleep(1)
                if "jal.com/index" not in sb.get_current_url().lower():
                    break
        sb.sleep(3)
        return True

    # -------------------------------------------------------------------------
    # Login helpers
    # -------------------------------------------------------------------------

    def _fill_login_form(self, sb, username: str, password: str, auto_submit: bool = True) -> None:
        self._dismiss_cookie_banners(sb)

        input_selector = "input#LA_input-number-01, input[name='id'], input.JS_jmbNo"
        sb.wait_for_element_visible(input_selector, timeout=15)

        jmb_el = next((s for s in ["input#LA_input-number-01", "input[name='id']", "input.JS_jmbNo"]
                       if sb.is_element_visible(s)), "input#LA_input-number-01")
        pass_el = next((s for s in ["input#LA_input-password", "input[name='password']", "input.JS_jmbPass"]
                        if sb.is_element_visible(s)), "input#LA_input-password")

        for sel, val in [(jmb_el, username), (pass_el, password)]:
            try:
                sb.click(sel); sb.sleep(0.2); sb.clear(sel); sb.type(sel, val)
            except Exception:
                pass

        # React virtual DOM binding bypass
        try:
            for sel, val in [(jmb_el, username), (pass_el, password)]:
                web_el = sb.find_element(sel)
                sb.execute_script("""
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    setter.call(arguments[0], arguments[1]);
                    ['input','change','blur'].forEach(e =>
                        arguments[0].dispatchEvent(new Event(e, {bubbles:true})));
                    arguments[0].classList.remove('is-blank');
                """, web_el, val)
        except Exception:
            pass

        if auto_submit:
            submitted = False
            for sel in ["button.btn", "button.btn-next"]:
                if sb.is_element_visible(sel):
                    try:
                        sb.click(sel)
                        submitted = True
                        break
                    except Exception:
                        pass
            if not submitted:
                try:
                    sb.execute_script("const b = document.querySelector('button.btn'); if (b) b.click();")
                except Exception:
                    pass
            sb.sleep(10)

    def _navigate_to_login(self, sb, region: str) -> None:
        url = self._regional_homepage(region)
        print(f"Navigating to regional homepage: {url}")
        sb.open(url)
        sb.sleep(5)
        self._dismiss_cookie_banners(sb)

        # Click header login button
        login_selectors = ["a.login-Judg", "a.JS_hdrMemLogin", "a.JS_SpHeaderloginBtn", ".login-btn a"]
        clicked = False
        for sel in login_selectors:
            for el in sb.find_elements(sel):
                if el.is_displayed():
                    try:
                        el.click()
                        clicked = True
                        break
                    except Exception:
                        pass
            if clicked:
                break
        if not clicked:
            try:
                sb.execute_script(
                    "const sel = 'a.login-Judg, a.JS_hdrMemLogin, a.JS_SpHeaderloginBtn, .login-btn a';"
                    "const el = Array.from(document.querySelectorAll(sel))"
                    ".find(e => e.offsetWidth > 0 || e.offsetHeight > 0);"
                    "if (el) el.click();"
                )
            except Exception:
                pass
        sb.sleep(5)

    # -------------------------------------------------------------------------
    # Parsing
    # -------------------------------------------------------------------------

    def extract_expiration_date(self, soup: BeautifulSoup) -> Optional[str]:
        table = soup.find("table", class_="termmile")
        if not table:
            return None
        tbody = table.find("tbody")
        if not tbody:
            return None
        rows = tbody.find_all("tr")
        if len(rows) < 2:
            return None

        dates = [c.text.strip() for c in rows[0].find_all(["td", "th"])[1:]]
        miles = [c.text.strip() for c in rows[1].find_all(["td", "th"])[1:]]

        earliest = None
        for date_str, mile_str in zip(dates, miles):
            if re.sub(r"\D", "", mile_str) and int(re.sub(r"\D", "", mile_str)) > 0:
                m = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", date_str)
                if m:
                    try:
                        d = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%Y/%m/%d")
                        if earliest is None or d < earliest:
                            earliest = d
                    except Exception:
                        pass
        return earliest.strftime("%Y-%m-%d") if earliest else None

    def _parse_jmb_page(self, soup: BeautifulSoup):
        """Parse balance and status from jal.co.jp/en/jmb/ page."""
        balance = 0
        status = "Member"

        for sel in ["#JS_121_mileBalance", "[class*='mileBalance']", "[class*='MileBalance']",
                    "[class*='totalMile']", "[class*='total-mile']", ".c-balance__num", ".p-mileTotal"]:
            el = soup.select_one(sel)
            if el:
                txt = re.sub(r"\D", "", el.text.strip())
                if txt:
                    balance = int(txt)
                    break

        if balance == 0:
            candidates = re.findall(
                r"([\d,]+)\s*(?:mile|マイル)|(?:mile|マイル)[^\d]*([\d,]+)",
                soup.get_text(" ", strip=True), re.IGNORECASE
            )
            nums = [int(re.sub(r"\D", "", g)) for m in candidates for g in m if re.sub(r"\D", "", g)]
            if nums:
                balance = max(nums)

        for sel in ["#JS_jmbStatusNameText", "[class*='statusName']", "[class*='status-name']",
                    "[class*='memberStatus']", ".c-status__name", ".p-statusName"]:
            el = soup.select_one(sel)
            if el and el.text.strip():
                status = self._normalize_status(el.text)
                break

        print(f"JMB page parsed: balance={balance}, status={status}")
        return balance, status

    # -------------------------------------------------------------------------
    # Core: fetch_data
    # -------------------------------------------------------------------------

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs) -> Dict[str, Any]:
        region = (kwargs.get("region") or "JR").upper()
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            try:
                for attempt in range(2):
                    print(f"Sync attempt {attempt + 1}, region: {region}")
                    sb.open(self._start_url(region))

                    input_sel = "input#LA_input-number-01, input[name='id'], input.JS_jmbNo"
                    logged_in_sel = "span#JS_121_mileBalance"
                    detected_mismatch = False
                    correct_region = None

                    # Wait for page to settle into a known state
                    for _ in range(15):
                        if sb.is_element_visible(logged_in_sel): break
                        if sb.is_element_visible(input_sel):     break
                        if self._handle_worldwide_sites(sb, region): break
                        correct_region = self._detect_region_mismatch(sb)
                        if correct_region and correct_region != region:
                            detected_mismatch = True
                            break
                        sb.sleep(1)

                    if detected_mismatch:
                        print(f"Region mismatch on load. Switching to {correct_region}...")
                        sb.delete_all_cookies()
                        region = correct_region
                        continue

                    current_url = sb.get_current_url().lower()
                    if sb.is_element_visible(logged_in_sel) and not self.is_auth_url(current_url):
                        print("Session active. Skipping login.")
                    else:
                        if not sb.is_element_visible(input_sel) and not self.is_auth_url(current_url):
                            self._navigate_to_login(sb, region)
                        self._fill_login_form(sb, username, password, auto_submit=True)

                        # Wait for login to complete
                        for _ in range(20):
                            current_url = sb.get_current_url().lower()
                            if sb.is_element_visible(logged_in_sel) and not self.is_auth_url(current_url):
                                break
                            if self._handle_worldwide_sites(sb, region):
                                # Authenticated on jal.co.jp — go directly to JMB page
                                sb.sleep(2)
                                sb.open("https://www.jal.co.jp/en/jmb/?m=header_menu")
                                sb.sleep(5)
                                break
                            correct_region = self._detect_region_mismatch(sb)
                            if correct_region and correct_region != region:
                                detected_mismatch = True
                                break
                            sb.sleep(1)

                    if detected_mismatch:
                        print(f"Region mismatch after login. Switching to {correct_region}...")
                        sb.delete_all_cookies()
                        region = correct_region
                        continue
                    break

                current_url = sb.get_current_url().lower()
                on_jmb_page = "jal.co.jp/en/jmb" in current_url
                on_www121   = sb.is_element_visible("span#JS_121_mileBalance")

                if self.is_auth_url(current_url) or (not on_jmb_page and not on_www121):
                    raise InteractionRequiredError("JAL login required. Please use Interactive Login.")

                soup = BeautifulSoup(sb.get_page_source(), "html.parser")

                if on_jmb_page:
                    balance, status = self._parse_jmb_page(soup)
                    expiration_date = None
                    try:
                        clicked = sb.execute_script("""
                            const a = Array.from(document.querySelectorAll('a')).find(el => {
                                const href = (el.getAttribute('href') || '').toLowerCase();
                                const text = (el.textContent || '').toLowerCase();
                                return href.includes('mile') || text.includes('expir') || text.includes('detail');
                            });
                            if (a) { a.click(); return true; }
                            return false;
                        """)
                        if clicked:
                            sb.sleep(5)
                            expiration_date = self.extract_expiration_date(
                                BeautifulSoup(sb.get_page_source(), "html.parser"))
                    except Exception:
                        pass
                else:
                    sb.wait_for_element_visible("span#JS_121_mileBalance", timeout=20)
                    sb.sleep(3)
                    soup = BeautifulSoup(sb.get_page_source(), "html.parser")

                    balance_el = soup.find(id="JS_121_mileBalance")
                    if not balance_el:
                        raise PluginError("Could not retrieve mileage balance from JAL.")
                    balance = int(re.sub(r"\D", "", balance_el.text.strip()) or 0)

                    status_el = soup.find(id="JS_jmbStatusNameText")
                    status = self._normalize_status(status_el.text if status_el else "")

                    # Navigate to mileage detail page for expiration
                    try:
                        if not sb.execute_script(
                            'const f = document.querySelector(\'form[name="mileDetailFrm"]\');'
                            'if (f) { f.submit(); return true; } return false;'
                        ):
                            sb.execute_script("""
                                let el = Array.from(document.querySelectorAll('a')).find(a => {
                                    const t = (a.textContent || '').toLowerCase();
                                    const h = a.getAttribute('href') || '';
                                    return t.includes('mile') && (h.includes('javascript') || h.includes('CnfMlg'));
                                });
                                if (!el) {
                                    const sp = document.querySelector('span#JS_121_mileBalance');
                                    if (sp) el = sp.closest('a');
                                }
                                if (el) el.click();
                            """)
                    except Exception:
                        pass

                    try:
                        sb.wait_for_element_visible("table.termmile", timeout=20)
                    except Exception:
                        sb.sleep(5)

                    expiration_date = self.extract_expiration_date(
                        BeautifulSoup(sb.get_page_source(), "html.parser"))

                return {"balance": balance, "status": status, "expiration_date": expiration_date}

            except InteractionRequiredError:
                raise
            except Exception as e:
                raise PluginError(f"JAL scraping failed: {e}")

    # -------------------------------------------------------------------------
    # Core: interactive_login
    # -------------------------------------------------------------------------

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        region = (kwargs.get("region") or "JR").upper()
        with SB(uc=True, headless=False, user_data_dir=profile_dir) as sb:
            try:
                for attempt in range(2):
                    print(f"Interactive login attempt {attempt + 1}, region: {region}")
                    sb.open(self._start_url(region))
                    sb.sleep(3)

                    input_sel = "input#LA_input-number-01, input[name='id'], input.JS_jmbNo"
                    logged_in_sel = "span#JS_121_mileBalance"
                    detected_mismatch = False
                    correct_region = None

                    for _ in range(15):
                        if sb.is_element_visible(logged_in_sel): break
                        if sb.is_element_visible(input_sel):     break
                        if self._handle_worldwide_sites(sb, region): break
                        correct_region = self._detect_region_mismatch(sb)
                        if correct_region and correct_region != region:
                            detected_mismatch = True
                            break
                        sb.sleep(1)

                    if detected_mismatch:
                        sb.delete_all_cookies()
                        region = correct_region
                        continue

                    current_url = sb.get_current_url().lower()
                    if not (sb.is_element_visible(logged_in_sel) and not self.is_auth_url(current_url)):
                        if not sb.is_element_visible(input_sel) and not self.is_auth_url(current_url):
                            self._navigate_to_login(sb, region)
                        try:
                            self._fill_login_form(sb, username, password, auto_submit=False)
                        except Exception as e:
                            print(f"Pre-fill error: {e}")

                    print("Please complete login manually. Waiting up to 5 minutes...")
                    for _ in range(60):
                        current_url = sb.get_current_url().lower()
                        if sb.is_element_visible(logged_in_sel) and not self.is_auth_url(current_url):
                            print("Login complete.")
                            sb.sleep(5)
                            break
                        if self._handle_worldwide_sites(sb, region):
                            sb.sleep(3)
                            sb.open(self._start_url(region))
                            sb.sleep(5)
                            continue
                        correct_region = self._detect_region_mismatch(sb)
                        if correct_region and correct_region != region:
                            detected_mismatch = True
                            break
                        sb.sleep(5)

                    if detected_mismatch:
                        sb.delete_all_cookies()
                        region = correct_region
                        continue
                    break

            except Exception as e:
                print(f"Interactive login interrupted: {e}")
