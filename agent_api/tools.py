"""Shared tool definitions and dispatcher for AI assistants (MCP server and in-app assistant).

Exposes read-only views of the portfolio via services.portfolio.
Must be called within an application context.
"""
from __future__ import annotations

from typing import Any, Optional


def _tool(name: str, description: str, properties: Optional[dict] = None, required: tuple = ()) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": list(required),
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


TOOLS = [
    _tool(
        "get_portfolio_summary",
        "Totals across every loyalty account: points, estimated USD value, breakdowns by person "
        "and category, and counts of items expiring soon, failed syncs and accounts needing "
        "Interactive Login.",
    ),
    _tool(
        "list_accounts",
        "List loyalty accounts with balance, status, estimated value, expiration and last sync. "
        "Filters are optional, exact and case-insensitive.",
        {
            "person": {"type": "string", "description": "Owner name, e.g. as shown on the dashboard."},
            "category": {"type": "string", "description": "Airlines, Hotels, Credit Cards, Car Rentals or Other."},
            "program": {"type": "string", "description": "Program name, e.g. 'United Airlines'."},
        },
    ),
    _tool(
        "get_account",
        "One account in detail: its summary plus reward certificates (name and expiry only), "
        "the program's expiration rule and recent balance history.",
        {
            "account_id": {"type": "integer", "description": "The id from list_accounts."},
            "history_limit": {
                "type": "integer",
                "minimum": 0,
                "maximum": 500,
                "default": 20,
                "description": "How many recent balance history entries to include.",
            },
        },
        required=("account_id",),
    ),
    _tool(
        "list_expiring",
        "Accounts and certificates that expire within the given number of days, soonest first "
        "(already-expired items have negative days_left).",
        {"days": {"type": "integer", "minimum": 0, "default": 90, "description": "Look-ahead window in days."}},
    ),
]


class ToolError(Exception):
    """A tool ran but the request could not be answered (reported with isError)."""


def _int_arg(args: dict, name: str, default: int, minimum: int = 0, maximum: Optional[int] = None) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"'{name}' must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        raise ToolError(f"'{name}' is out of range.")
    return value


def _str_arg(args: dict, name: str) -> Optional[str]:
    value = args.get(name)
    if value is not None and not isinstance(value, str):
        raise ToolError(f"'{name}' must be a string.")
    return value or None


def call_tool(name: str, args: dict) -> Any:
    """Execute a tool by name with arguments dict. Must be run within an app context."""
    from services import portfolio

    if name == "get_portfolio_summary":
        return portfolio.summary()
    if name == "list_accounts":
        return {
            "accounts": portfolio.list_accounts(
                _str_arg(args, "person"),
                _str_arg(args, "category"),
                _str_arg(args, "program"),
            )
        }
    if name == "get_account":
        if "account_id" not in args:
            raise ToolError("'account_id' is required.")
        account_id = _int_arg(args, "account_id", 0, minimum=1)
        data = portfolio.get_account(account_id, _int_arg(args, "history_limit", 20, maximum=500))
        if data is None:
            raise ToolError(f"No account with id {account_id}.")
        return data
    if name == "list_expiring":
        return portfolio.expiring_within(_int_arg(args, "days", 90))
    raise KeyError(name)


_call_tool = call_tool
