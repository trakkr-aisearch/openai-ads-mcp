"""OpenAI Ads MCP Server, typed tools for the OpenAI Advertiser API."""

from .client import __version__
from ._core import mcp
from .tools_account import *
from .tools_campaigns import *
from .tools_adgroups import *
from .tools_ads import *
from .tools_insights import *
from .tools_audiences import *
from .tools_conversions import *
from .helpers import *


def main() -> None:
    """Entry point for the openai-ads-mcp command."""
    mcp.run()


__all__ = [
    "main",
    "mcp",
    "__version__",
]
