"""HawkSoft MCP — Model Context Protocol server for HawkSoft Insurance AMS."""
from .client import HawkSoftAPIError, HawkSoftAuthError, HawkSoftClient, HawkSoftError
from .log_actions import list_channels, resolve_channel
from .server import main, mcp

__version__ = "0.1.0"
__all__ = [
    "HawkSoftAPIError",
    "HawkSoftAuthError",
    "HawkSoftClient",
    "HawkSoftError",
    "list_channels",
    "main",
    "mcp",
    "resolve_channel",
]