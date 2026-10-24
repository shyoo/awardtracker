"""In-app AI assistant backend services.

Manages tool execution loops, prompt building, free-tier URL generation,
and Zero-Knowledge pseudonymization of user/person names.
"""
from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional
import urllib.parse

from agent_api.tools import TOOLS, ToolError, call_tool
from services import llm_providers
from services.llm_providers import LLMError, ToolCall

MAX_TOOL_ROUNDS = 8
MAX_PREFILL_URL_CHARS = 8000
PREFILL_SAFE_CHARS = "/,:;()$'!*~"
FREE_SITES = ('chatgpt', 'claude', 'gemini')


# --------------------------------------------------------------------------- #
# Pseudonymization
# --------------------------------------------------------------------------- #

def _index_to_letter(index: int) -> str:
    """Map 0 -> 'A', 25 -> 'Z', 26 -> 'AA', 27 -> 'AB', etc."""
    result = []
    while True:
        result.append(chr(ord('A') + (index % 26)))
        index = index // 26 - 1
        if index < 0:
            break
    return "".join(reversed(result))


class Pseudonymizer:
    """Masks real person names with 'Person A', 'Person B', etc., and unmasks on return."""

    def __init__(self, real_to_pseudo: Optional[Dict[str, str]] = None, disabled: bool = False):
        self._disabled = disabled
        self._real_to_pseudo = dict(real_to_pseudo or {})
        self._pseudo_to_real = {pseudo: real for real, pseudo in self._real_to_pseudo.items()}

    @classmethod
    def from_people(cls, names: List[str]) -> Pseudonymizer:
        """Create a Pseudonymizer mapping names ordered by Person.id to Person A, Person B, ..."""
        real_to_pseudo: Dict[str, str] = {}
        seen_lower = set()
        idx = 0

        for raw_name in names:
            if not raw_name:
                continue
            name = raw_name.strip()
            if not name or name.lower() == 'unassigned':
                continue
            if name.lower() in seen_lower:
                continue
            seen_lower.add(name.lower())
            real_to_pseudo[name] = f"Person {_index_to_letter(idx)}"
            idx += 1

        return cls(real_to_pseudo=real_to_pseudo, disabled=False)

    @classmethod
    def disabled(cls) -> Pseudonymizer:
        """Create a pass-through Pseudonymizer."""
        return cls(disabled=True)

    def mask(self, text: str) -> str:
        """Replace real names with pseudonyms: whole-word, case-insensitive, longest name first."""
        if self._disabled or not text or not self._real_to_pseudo:
            return text

        # Longest real name first to prevent partial replacements of compound names
        sorted_items = sorted(self._real_to_pseudo.items(), key=lambda kv: len(kv[0]), reverse=True)
        for real_name, pseudo in sorted_items:
            left_b = r'\b' if re.match(r'^\w', real_name) else ''
            right_b = r'\b' if re.search(r'\w$', real_name) else ''
            pattern = re.compile(rf'{left_b}{re.escape(real_name)}{right_b}', re.IGNORECASE)
            text = pattern.sub(lambda _m, p=pseudo: p, text)
        return text

    def unmask(self, text: str) -> str:
        """Replace pseudonyms with real names: whole-word, longest pseudonym first."""
        if self._disabled or not text or not self._pseudo_to_real:
            return text

        sorted_items = sorted(self._pseudo_to_real.items(), key=lambda kv: len(kv[0]), reverse=True)
        for pseudo, real_name in sorted_items:
            left_b = r'\b' if re.match(r'^\w', pseudo) else ''
            right_b = r'\b' if re.search(r'\w$', pseudo) else ''
            # Case-sensitive: plain English such as "per person a year" must not unmask.
            pattern = re.compile(rf'{left_b}{re.escape(pseudo)}{right_b}')
            text = pattern.sub(lambda _m, r=real_name: r, text)
        return text

    def mask_data(self, obj: Any) -> Any:
        """Recursively mask strings within dict, list, tuple or str."""
        if self._disabled:
            return obj
        if isinstance(obj, str):
            return self.mask(obj)
        if isinstance(obj, dict):
            return {self.mask_data(k): self.mask_data(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.mask_data(item) for item in obj]
        if isinstance(obj, tuple):
            return tuple(self.mask_data(item) for item in obj)
        return obj

    def unmask_data(self, obj: Any) -> Any:
        """Recursively unmask strings within dict, list, tuple or str."""
        if self._disabled:
            return obj
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, dict):
            return {self.unmask_data(k): self.unmask_data(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.unmask_data(item) for item in obj]
        if isinstance(obj, tuple):
            return tuple(self.unmask_data(item) for item in obj)
        return obj

    def legend(self) -> Dict[str, str]:
        """Return a mapping of pseudonym -> real name for local UI display only."""
        if self._disabled:
            return {}
        return dict(self._pseudo_to_real)


def build_pseudonymizer() -> Pseudonymizer:
    """Build a Pseudonymizer from the database Person table and application settings."""
    from services.settings_store import get_bool_setting

    if not get_bool_setting('assistant_pseudonymize_names', True):
        return Pseudonymizer.disabled()

    from core.models import Person
    people = Person.query.order_by(Person.id).all()
    names = [p.name for p in people if p.name and p.name.strip()]
    return Pseudonymizer.from_people(names)


# --------------------------------------------------------------------------- #
# System prompt & turn execution
# --------------------------------------------------------------------------- #

def system_prompt() -> str:
    """Build the assistant's system instructions."""
    from datetime import datetime
    today = datetime.utcnow().strftime('%Y-%m-%d')
    return (
        f"You are the Award Tracker AI assistant. Today is {today}. "
        "You help the user understand, monitor, and optimize their loyalty rewards portfolio, "
        "including airline miles, hotel points, credit card currencies, status tiers, "
        "expiration rules, and reward certificates.\n\n"
        "Core Rules:\n"
        "1. You have read-only access to portfolio tools (get_portfolio_summary, list_accounts, "
        "get_account, list_expiring). You cannot make bookings, transfer points, modify accounts, "
        "or initiate account syncs.\n"
        "2. Account details and balances reflect each account's last sync time.\n"
        "3. Answer questions accurately based on tool results. Call appropriate tools when specific "
        "details are needed to answer the question.\n"
        "4. Privacy: All data is local and sanitized. Sensitive identifiers (passwords, login credentials, "
        "account numbers, certificate redemption codes) are never exposed.\n"
        "5. Trip planning: when the user asks where to go, which flights or hotels to book, or when to "
        "search, start from their actual balances, certificates and statuses (and those of the people "
        "they mention), then use your general knowledge of award charts, airline alliances and partners, "
        "transferable currencies, hotel categories and seasonal demand. Give concrete options with "
        "approximate point costs and say which accounts would cover them. You cannot see live award "
        "availability or prices, so say so and tell the user what to search for and where."
    )


def run_turn(config: dict, history: list[dict], user_text: str) -> dict:
    """Execute a single user chat turn against an LLM provider, running tool loops as needed.

    Args:
        config: LLM provider configuration dict.
        history: Prior conversation turns [{'role': 'user'|'assistant', 'content': str}] with real names.
        user_text: The latest user prompt with real names.

    Returns:
        {'text': str (unmasked final answer), 'tools_used': list[str]}
    """
    pseudonymizer = build_pseudonymizer()

    # Mask system prompt, history, and user input before sending to LLM
    masked_system = pseudonymizer.mask(system_prompt())
    messages: List[Dict[str, Any]] = []

    for msg in history:
        role = msg.get('role', 'user')
        content = pseudonymizer.mask(msg.get('content', ''))
        messages.append({'role': role, 'content': content})

    masked_user_text = pseudonymizer.mask(user_text)
    messages.append({'role': 'user', 'content': masked_user_text})

    tools_used: List[str] = []
    last_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        reply = llm_providers.chat(config, masked_system, messages, TOOLS)
        last_text = reply.text

        if not reply.tool_calls:
            # Model returned a terminal text reply
            unmasked_reply = pseudonymizer.unmask(reply.text)
            return {'text': unmasked_reply, 'tools_used': tools_used}

        # Assistant turn with tool calls
        messages.append({
            'role': 'assistant',
            'content': reply.text,
            'tool_calls': reply.tool_calls,
        })

        for tc in reply.tool_calls:
            tools_used.append(tc.name)
            # Unmask tool arguments before execution against local database
            unmasked_args = pseudonymizer.unmask_data(tc.arguments)

            try:
                result_data = call_tool(tc.name, unmasked_args)
                masked_result = pseudonymizer.mask_data(result_data)
                content_str = json.dumps(masked_result, ensure_ascii=False, default=str)
            except ToolError as e:
                masked_err = pseudonymizer.mask(str(e))
                content_str = json.dumps({"error": masked_err})
            except Exception as e:
                masked_err = pseudonymizer.mask(f"{tc.name} failed: {type(e).__name__}")
                content_str = json.dumps({"error": masked_err})

            messages.append({
                'role': 'tool',
                'tool_call_id': tc.id,
                'name': tc.name,
                'content': content_str,
            })

    # Hit MAX_TOOL_ROUNDS cap
    unmasked_last = pseudonymizer.unmask(last_text)
    note = " (Reached maximum tool rounds limit.)"
    final_text = (unmasked_last + f"\n\n{note}") if unmasked_last else note.strip()
    return {'text': final_text, 'tools_used': tools_used}


# --------------------------------------------------------------------------- #
# Free Mode
# --------------------------------------------------------------------------- #

def free_prompt(question: str) -> dict:
    """Build a self-contained, privacy-safe prompt embedding portfolio summary and accounts."""
    from services import portfolio

    pseudonymizer = build_pseudonymizer()

    # One short line per account rather than JSON: the prompt has to fit in a
    # ChatGPT/Claude address (MAX_PREFILL_URL_CHARS) to be pre-filled.
    lines = [FREE_INSTRUCTIONS.format(today=datetime.now().strftime('%Y-%m-%d')), '']

    summary = portfolio.summary()
    lines.append(f"Totals: {summary['account_count']} accounts, "
                 f"{summary['total_points']:,} points/miles, about ${summary['total_value_usd']:,.0f}.")
    people = [f"{name} ${entry['value_usd']:,.0f}" for name, entry in summary['by_person'].items()]
    if people:
        lines.append('By person: ' + ', '.join(people) + '.')

    lines += ['', 'Accounts (program; person; balance; status; ~USD value; expires):']
    omitted = 0
    for a in portfolio.list_accounts():
        if not a.get('balance') and not a.get('status') and not a.get('certificate_count'):
            omitted += 1
            continue
        lines.append('- ' + '; '.join(_account_fields(a)))
    if omitted:
        lines.append(f"({omitted} accounts with no balance, status or certificates omitted.)")

    certificates = portfolio.expiring_within(90)['certificates']
    if certificates:
        lines += ['', 'Certificates expiring within 90 days:']
        for c in certificates:
            lines.append(f"- {c['program']}; {c['person']}; {c['name']}; expires {c['expiration_date']}")

    lines += ['', f"My question: {question}"]
    prompt = pseudonymizer.mask('\n'.join(lines))

    return {
        'prompt': prompt,
        'legend': pseudonymizer.legend(),
    }


FREE_INSTRUCTIONS = (
    "Help me use my loyalty points and miles. Today is {today}. Below is a snapshot of my accounts "
    "from my Award Tracker app (people are named Person A, B... for privacy; balances are as of "
    "the last sync). Combine it with your knowledge of award charts, alliances, transfer partners, "
    "hotel categories and seasonal demand. Give concrete options with approximate point costs and "
    "say which accounts cover them. You cannot see live award availability or prices, so tell me "
    "what to search for and where."
)


def _account_fields(a: dict) -> List[str]:
    """Compact, privacy-safe fields of one ``portfolio.list_accounts()`` entry."""
    fields = [a.get('program') or '?', a.get('person') or 'Unassigned', f"{a.get('balance') or 0:,}"]
    fields.append(a.get('status') or '-')
    fields.append(f"${a['value_usd']:,.0f}" if a.get('value_usd') else '-')
    if a.get('expiration_date'):
        fields.append(f"{a['expiration_date']} ({a.get('days_left')}d)")
    else:
        fields.append('-')
    if a.get('certificate_count'):
        fields.append(f"{a['certificate_count']} certificates")
    return fields


def free_site_url(site: str, prompt: str) -> dict:
    """Generate pre-filled or clipboard-fallback URL for free-tier web LLM sites.

    An empty ``site`` means "Copy prompt": clipboard only, nothing to open.
    """
    if not site:
        return {'url': '', 'copy_to_clipboard': True}
    if site not in FREE_SITES:
        raise ValueError(f"Unknown free site: '{site}'. Must be one of {FREE_SITES}")

    if site == 'gemini':
        return {'url': 'https://gemini.google.com/app', 'copy_to_clipboard': True}

    # Leave characters that are legal in a query string unescaped: escaping
    # triples them and the address has to stay under MAX_PREFILL_URL_CHARS.
    # '&', '=', '+', '#' and '?' stay escaped so the value parses back intact.
    quoted = urllib.parse.quote(prompt, safe=PREFILL_SAFE_CHARS)

    if site == 'chatgpt':
        url = f"https://chatgpt.com/?q={quoted}"
        if len(url) <= MAX_PREFILL_URL_CHARS:
            return {'url': url, 'copy_to_clipboard': False}
        return {'url': 'https://chatgpt.com/', 'copy_to_clipboard': True}

    if site == 'claude':
        url = f"https://claude.ai/new?q={quoted}"
        if len(url) <= MAX_PREFILL_URL_CHARS:
            return {'url': url, 'copy_to_clipboard': False}
        return {'url': 'https://claude.ai/new', 'copy_to_clipboard': True}

    return {'url': '', 'copy_to_clipboard': True}
