"""Per-thread description of the plugin run currently in progress.

Set by ``safe_call_plugin_method`` before a plugin's ``fetch_data`` /
``interactive_login`` is entered and cleared afterwards. Anything that needs to
know *how* it is being run (the in-browser guide modal, cache-fallback policy,
the debug logger) reads it from here instead of walking ``inspect.stack()``.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class RunMode(str, Enum):
    FETCH = "fetch"              # plugin.fetch_data -- unattended scrape
    INTERACTIVE = "interactive"  # plugin.interactive_login -- user is at the keyboard


class RunTrigger(str, Enum):
    MANUAL = "manual"        # user clicked Sync Now / Interactive Login
    SCHEDULED = "scheduled"  # background sync-all (scheduler or tray)


@dataclass
class RunContext:
    account_id: Any
    provider_name: str
    plugin: Any                 # the ProviderPlugin instance, or None
    mode: RunMode
    trigger: RunTrigger

    @property
    def is_interactive(self) -> bool:
        return self.mode is RunMode.INTERACTIVE

    @property
    def is_manual(self) -> bool:
        return self.trigger is RunTrigger.MANUAL


_local = threading.local()


def set_run_context(ctx: Optional[RunContext]) -> None:
    _local.ctx = ctx


def current_run_context() -> Optional[RunContext]:
    return getattr(_local, 'ctx', None)


def clear_run_context() -> None:
    _local.ctx = None
