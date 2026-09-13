"""Exceptions raised by provider plugins."""


class PluginError(Exception):
    pass


class InteractionRequiredError(PluginError):
    """Raised when the plugin hits a captcha or MFA and needs manual intervention."""
    pass
