"""
Manual tracking plugins for credit card and other rewards programs.
These accounts do not use any browser automation — balances are entered
manually by the user.  No credentials are ever required or stored.
"""
from abc import abstractmethod
from .base import ProviderPlugin, PluginError


class _ManualBase(ProviderPlugin):
    """Abstract base shared by all manually-tracked providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        pass

    def fetch_data(self, username: str, password: str, profile_dir: str = None, **kwargs):
        raise PluginError(
            f"{self.name} is a manually-tracked account. "
            "Please use the 'Update Balance' button to record your current balance."
        )

    def interactive_login(self, username: str, password: str, profile_dir: str = None, **kwargs) -> None:
        raise PluginError(
            f"{self.name} is a manually-tracked account and does not require login."
        )


# ---------------------------------------------------------------------------
# Pre-defined popular credit card reward programs
# ---------------------------------------------------------------------------

class ChaseUltimateRewardsPlugin(_ManualBase):
    @property
    def name(self) -> str:
        return "Chase Ultimate Rewards"

    @property
    def plugin_id(self) -> str:
        return "chase"


class AmexMembershipRewardsPlugin(_ManualBase):
    @property
    def name(self) -> str:
        return "Amex Membership Rewards"

    @property
    def plugin_id(self) -> str:
        return "amex"


class CitiThankYouPlugin(_ManualBase):
    @property
    def name(self) -> str:
        return "Citi ThankYou Rewards"

    @property
    def plugin_id(self) -> str:
        return "citi"


class CapitalOneMilesPlugin(_ManualBase):
    @property
    def name(self) -> str:
        return "Capital One Miles"

    @property
    def plugin_id(self) -> str:
        return "capitalone"


class WellsFargoRewardsPlugin(_ManualBase):
    @property
    def name(self) -> str:
        return "Wells Fargo Rewards"

    @property
    def plugin_id(self) -> str:
        return "wellsfargo"


# ---------------------------------------------------------------------------
# Generic manual entry provider (user-defined programs)
# ---------------------------------------------------------------------------

class ManualEntryPlugin(_ManualBase):
    @property
    def name(self) -> str:
        return "Manual Entry"

    @property
    def plugin_id(self) -> str:
        return "manual"
