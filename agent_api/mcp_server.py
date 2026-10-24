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

from agent_api.tools import TOOLS, ToolError, _call_tool, _int_arg, _str_arg, _tool, call_tool

SERVER_NAME = "awardtracker"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Read-only access to the user's local Award Tracker loyalty portfolio: point and mile "
    "balances, elite status, estimated USD value, expiration dates and reward certificates. "
    "Balances are as of each account's last_updated time; this server cannot start a sync. "
    "Credentials, membership numbers and certificate codes are never returned. "
    "The user must turn on AI assistant access in Award Tracker's Settings first."
)

#: Settings key the user toggles on the Settings page; access is off unless it is "true".
ENABLED_SETTING = "mcp_server_enabled"
DISABLED_MESSAGE = (
    "AI assistant access is turned off in Award Tracker. To allow it, open Award Tracker, "
    "go to Settings > AI Assistant Access (MCP), check \"Allow AI assistants to read my "
    "portfolio\", and save. Then try again."
)

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


def access_enabled() -> bool:
    """Whether the user has allowed assistant access (read at call time, so toggling needs no restart)."""
    from services.settings_store import get_bool_setting
    return get_bool_setting(ENABLED_SETTING, False)


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
                if not access_enabled():
                    raise ToolError(DISABLED_MESSAGE)
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
    try:
        with server.app.app_context():
            if not access_enabled():
                print("AI assistant access is off; tools will refuse until it is enabled in Settings.",
                      file=sys.stderr)
    except Exception:
        pass
    server.serve(sys.stdin, protocol_out)
    return 0
