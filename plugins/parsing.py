"""Text-parsing helpers shared by plugins."""
import calendar
import re
from datetime import datetime
from typing import Optional


def parse_int(text: str) -> Optional[int]:
    """First run of digits in ``text`` (commas/spaces tolerated), or None."""
    if not text:
        return None
    m = re.search(r"\d[\d,\s]*", text)
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(0))
    return int(digits) if digits else None


def extract_latest_date(html: str, today: Optional[datetime] = None) -> Optional[datetime]:
    """Most recent date (not in the future) mentioned anywhere in ``html``.

    Recognises English month names, ISO / dotted / slash numerics, Korean
    년/월/일 forms, and month-only forms (resolved to the last day of that
    month, capped at today). Used to find the last qualifying activity on
    statement pages.
    """
    dates = []
    today = today or datetime.now()

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
