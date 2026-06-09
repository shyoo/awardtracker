from datetime import datetime

def add_months(source_date, months):
    """
    Robust month addition helper in pure Python.
    Correctly handles leap years and variable month lengths.
    """
    if source_date is None:
        return None
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31
    ][month - 1])
    return datetime(year, month, day, source_date.hour, source_date.minute, source_date.second)

def calculate_expiration(plugin_id: str, balance: int, status: str, last_activity_date: datetime, has_exemption: bool = False) -> datetime:
    """
    Calculates the exact expiration date based on program-specific rules.
    Returns datetime or None (Never Expires).
    """
    # 0. Check for 0 or negative balance (no points/miles to expire)
    if balance <= 0:
        return None

    # 1. Check universal exemption
    if has_exemption:
        return None

    pid = plugin_id.lower().strip()

    # 2. Permanent/Lifetime programs
    if pid in ('delta', 'southwest', 'united', 'virgin'):
        return None

    # 3. Programs requiring last activity date
    if last_activity_date is None:
        return None

    # 4. Inactivity-based calculation
    if pid in ('american', 'alaska', 'marriott', 'hilton', 'hyatt'):
        return add_months(last_activity_date, 24)

    elif pid == 'wyndham':
        # Wyndham Rewards points expire after 18 months of account inactivity,
        # regardless of elite tier. Any earning or redemption transaction extends them.
        return add_months(last_activity_date, 18)

    elif pid == 'aircanada':
        # Aeroplan Elite status holders never expire
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'altitude', 'super elite', '25k', '35k', '50k', '75k', '100k')):
            return None
        return add_months(last_activity_date, 18)

    elif pid == 'ihg':
        # IHG Elite status holders (Silver, Gold, Platinum, Diamond) never expire
        st = (status or "").lower()
        if any(tier in st for tier in ('silver', 'gold', 'platinum', 'diamond')):
            return None
        return add_months(last_activity_date, 12)

    elif pid == 'avianca':
        # Avianca LifeMiles standard is 12 months, Elite/status is 24 months
        st = (status or "").lower()
        # "elite" or "silver" / "gold" / "diamond" / "red"
        if any(tier in st for tier in ('elite', 'silver', 'gold', 'diamond', 'red')):
            return add_months(last_activity_date, 24)
        return add_months(last_activity_date, 12)

    elif pid in ('korean', 'asiana', 'jal', 'ana'):
        # Korean Air Skypass, Asiana Club, JAL Mileage Bank, and ANA Mileage Club use a fixed-date system, calculated during scraping.
        # This function acts as a pass-through if we already fetched the exact date.
        return last_activity_date

    return None

def get_program_rule_description(plugin_id: str, status: str = None) -> str:
    """
    Returns a human-readable description of the program's expiration policy.
    Used for UI tooltips.
    """
    pid = plugin_id.lower().strip()
    if pid in ('delta', 'southwest', 'united', 'virgin'):
        return "Miles in this program never expire."
    
    if pid == 'american':
        return "Miles expire after 24 months of inactivity. Any earning or redemption transaction extends them."
    
    if pid == 'alaska':
        return "Accounts are locked after 24 months of inactivity. Balance is preserved, but account reactivation is required."
    
    if pid == 'marriott':
        return "Points expire after 24 months of inactivity. Any earning or redemption transaction extends them."
    
    if pid == 'hilton':
        return "Points expire after 24 months of inactivity. Any earning or redemption transaction extends them."
    
    if pid == 'hyatt':
        return "Points expire after 24 months of inactivity. Any earning or redemption transaction extends them."

    if pid == 'wyndham':
        return "Points expire after 18 months of inactivity, regardless of elite tier. Any earning or redemption transaction extends them."

    if pid == 'aircanada':
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'altitude', 'super elite', '25k', '35k', '50k', '75k', '100k')):
            return f"Points never expire for Elite members (your status: {status or 'Standard'})."
        return "Points expire after 18 months of inactivity. Primary credit card holders or Elite status prevents expiration."

    if pid == 'ihg':
        st = (status or "").lower()
        if any(tier in st for tier in ('silver', 'gold', 'platinum', 'diamond')):
            return f"Points never expire for Elite members (your status: {status or 'Club'})."
        return "Points expire after 12 months of inactivity. Elite status prevents expiration."
    
    if pid == 'avianca':
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'silver', 'gold', 'diamond', 'red')):
            return f"Miles expire after 24 months of inactivity for Elite members (your status: {status or 'Standard'}). Note: Only earning activity resets the clock; redemptions do not."
        return "Miles expire after 12 months of inactivity. Note: Only earning (accrual) activity resets the clock; redemptions do not."
    
    if pid == 'korean':
        return "Miles earned on or after July 1, 2008 expire strictly on December 31 of the 10th year following the earn date. Activity does not extend them."
        
    if pid == 'asiana':
        return "Asiana Club miles earned are valid strictly for 10 years (Silver/Gold) or 12 years (Diamond and above) from the date of accrual. Activity does not extend them."

    if pid == 'jal':
        return "JAL Mileage Bank miles are valid for 36 months from the month they were earned. Activity does not extend them."

    if pid == 'ana':
        return "ANA Mileage Club miles are valid for 36 months from the month they were earned. Activity does not extend them."
        
    return "Expiration rules vary by loyalty program."

def get_never_expires_reason(plugin_id: str, status: str, has_exemption: bool = False) -> str:
    """
    Returns a short reason to append to the "Never Expires" UI text.
    For example: " (Elite)" or " (Exempt)".
    """
    if has_exemption:
        return " (Exempt)"
        
    pid = plugin_id.lower().strip()
    if pid == 'ihg':
        st = (status or "").lower()
        if any(tier in st for tier in ('silver', 'gold', 'platinum', 'diamond')):
            return " (Elite)"
    elif pid == 'aircanada':
        st = (status or "").lower()
        if any(tier in st for tier in ('elite', 'altitude', 'super elite', '25k', '35k', '50k', '75k', '100k')):
            return " (Elite)"
    return ""
