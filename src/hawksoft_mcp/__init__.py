"""HawkSoft MCP — public surface.

NOTE: ``__version__`` is defined BEFORE any subpackage import. ``client.py``
imports ``from . import __version__`` (for the User-Agent header) so the
version must be resolvable at the moment ``client`` is loaded.
"""
__version__ = "0.2.0"

from .client import HawkSoftClient
from .exceptions import (
    HawkSoftAPIError,
    HawkSoftAuthError,
    HawkSoftConnectionError,
    HawkSoftError,
    HawkSoftNotFoundError,
    HawkSoftRateLimitError,
)
from .server import main, mcp

__all__ = [
    "HawkSoftAPIError",
    "HawkSoftAuthError",
    "HawkSoftClient",
    "HawkSoftConnectionError",
    "HawkSoftError",
    "HawkSoftNotFoundError",
    "HawkSoftRateLimitError",
    "main",
    "mcp",
]
