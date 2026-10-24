"""Minimal Model Context Protocol server over stdio.

Exposes the read-only portfolio views in ``services.portfolio`` as MCP tools,
so desktop AI assistants (Claude Desktop, Claude Code, ...) can answer
questions such as "which miles expire this quarter?".

Only the small subset of MCP a tools-only server needs is implemented here:
newline-delimited JSON-RPC 2.0 with ``initialize``, ``ping``, ``tools/list``
and ``tools/call``. Keeping it dependency-free avoids pinning the app to a
fast-moving SDK and keeps it out of the PyInstaller bundle.

The database is opened read-only, independently of a running Award Tracker;
nothing here decrypts credentials or starts a browser.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Dict, Optional, TextIO

SERVER_NAME = "awardtracker"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Read-only access to the user's local Award Tracker loyalty portfolio: point and mile "
    "balances, elite status, estimated USD value, expiration dates and reward certificates. "
    "Balances are as of each account's last_updated time; this server cannot start a sync. "
    "Credentials, membership numbers and certificate codes are never returned."
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def _tool(name: str, description: str, properties: Optional[dict] = None, required: tuple = ()) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties or {}, "required": list(required),
                        "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


TOOLS = [
    _tool("get_portfolio_summary",
          "Totals across every loyalty account: points, estimated USD value, breakdowns by person "
          "and category, and counts of items expiring soon, failed syncs and accounts needing "
          "Interactive Login."),
    _tool("list_accounts",
          "List loyalty accounts with balance, status, estimated value, expiration and last sync. "
          "Filters are optional, exact and case-insensitive.",
          {
              "person": {"type": "string", "description": "Owner name, e.g. as shown on the dashboard."},
              "category": {"type": "string", "description": "Airlines, Hotels, Credit Cards, Car Rentals or Other."},
              "program": {"type": "string", "description": "Program name, e.g. 'United Airlines'."},
          }),
    _tool("get_account",
          "One account in detail: its summary plus reward certificates (name and expiry only), "
          "the program's expiration rule and recent balance history.",
          {
              "account_id": {"type": "integer", "description": "The id from list_accounts."},
              "history_limit": {"type": "integer", "minimum": 0, "maximum": 500, "default": 20,
                                "description": "How many recent balance history entries to include."},
          },
          required=("account_id",)),
    _tool("list_expiring",
          "Accounts and certificates that expire within the given number of days, soonest first "
          "(already-expired items have negative days_left).",
          {"days": {"type": "integer", "minimum": 0, "default": 90, "description": "Look-ahead window in days."}}),
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


def _call_tool(name: str, args: dict) -> Any:
    from services import portfolio
    if name == "get_portfolio_summary":
        return portfolio.summary()
    if name == "list_accounts":
        return {"accounts": portfolio.list_accounts(_str_arg(args, "person"), _str_arg(args, "category"),
                                                    _str_arg(args, "program"))}
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


class McpServer:
    def __init__(self, app, version: str = "dev"):
        self.app = app
        self.version = version

    # -------------------------------------------------------------- #
    # JSON-RPC dispatch
    # -------------------------------------------------------------- #

    def handle(self, message: Any) -> Optional[dict]:
        """Answer one decoded JSON-RPC message; None for notifications."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "Invalid request")
        is_notification = "id" not in message
        handler: Optional[Callable[[dict], Any]] = {
            "initialize": self._initialize,
            "ping": lambda params: {},
            "tools/list": lambda params: {"tools": TOOLS},
            "tools/call": self._tools_call,
        }.get(message["method"])
        if is_notification:
            return None  # notifications/initialized, notifications/cancelled, ...
        if handler is None:
            return _error(message["id"], METHOD_NOT_FOUND, f"Method not found: {message['method']}")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(message["id"], INVALID_PARAMS, "params must be an object")
        try:
            return {"jsonrpc": "2.0", "id": message["id"], "result": handler(params)}
        except _InvalidParams as e:
            return _error(message["id"], INVALID_PARAMS, str(e))

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "Award Tracker", "version": self.version},
            "instructions": INSTRUCTIONS,
        }

    def _tools_call(self, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise _InvalidParams("arguments must be an object")
        if name not in {t["name"] for t in TOOLS}:
            raise _InvalidParams(f"Unknown tool: {name}")
        try:
            with self.app.app_context():
                data = _call_tool(name, args)
        except ToolError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:  # report, don't crash the session
            return {"content": [{"type": "text", "text": f"{name} failed: {type(e).__name__}"}], "isError": True}
        text = json.dumps(data, ensure_ascii=False, default=str)
        return {"content": [{"type": "text", "text": text}], "structuredContent": data, "isError": False}

    # -------------------------------------------------------------- #
    # stdio loop
    # -------------------------------------------------------------- #

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                response = _error(None, PARSE_ERROR, "Parse error")
            else:
                response = self.handle(message)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
                stdout.flush()


class _InvalidParams(Exception):
    pass


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def create_readonly_app(db_path: str):
    """A bare Flask app bound read-only to ``db_path``: no routes, migrations or scheduler."""
    from flask import Flask
    from core.extensions import db

    app = Flask(__name__)
    uri_path = os.path.abspath(db_path).replace("\\", "/")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///file:{uri_path}?mode=ro&uri=true",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    return app


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m agent_api",
                                     description="Award Tracker MCP server (stdio, read-only).")
    parser.add_argument("--db", help="Path to awardtracker.db (default: the database the app is using).")
    args = parser.parse_args(argv)

    # stdout carries the protocol; anything else printed (imports, plugins) goes to stderr.
    protocol_out = sys.stdout
    sys.stdout = sys.stderr
    # MCP messages are UTF-8 and newline-delimited; Windows would otherwise use
    # the console code page and write \r\n.
    for stream in (protocol_out, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n" if stream is protocol_out else None)
        except (AttributeError, ValueError):
            pass

    from core.config import APP_VERSION, get_active_db_path
    db_path = args.db or get_active_db_path()
    if not os.path.isfile(db_path):
        print(f"Award Tracker database not found: {db_path}", file=sys.stderr)
        return 1
    server = McpServer(create_readonly_app(db_path), version=APP_VERSION)
    print(f"Award Tracker MCP server ready (read-only): {db_path}", file=sys.stderr)
    server.serve(sys.stdin, protocol_out)
    return 0
