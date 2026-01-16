#!/usr/bin/env python3
"""
Agents IDE MCP Tools Package

Bridges the Agents IDE daemon to MCP protocol, allowing AI agents to use
IDE tools via MCP instead of direct HTTP calls.

The HTTP daemon is a SINGLETON - one instance serves all MCP clients.
This bridge auto-ensures the daemon is running on startup.
"""

import asyncio
import sys

# Import core components first
from ._core import (
    mcp,
    http_post,
    http_get,
    format_result,
    ensure_daemon_running,
    HTTP_BASE_URL,
    SCRIPT_DIR,
    cleanup,
)

# Import all tool modules to register their @mcp.tool() decorators
# from . import navigation
from . import structure
from . import copy_paste
from . import analysis
from . import refactoring
# from . import patterns
# from . import generation
# from . import lint
# from . import history
# from . import search
# from . import typecheck
# from . import profiling
# from . import lsp
# from . import feedback

__all__ = [
    "mcp",
    "http_post",
    "http_get",
    "format_result",
    "ensure_daemon_running",
    "main",
]


def main():
    """Run the MCP server."""
    print(f"Starting LSP MCP Bridge Server", file=sys.stderr)
    print(f"  HTTP Backend: {HTTP_BASE_URL}", file=sys.stderr)

    # Auto-ensure the singleton daemon is running
    print(f"  Ensuring HTTP daemon is running...", file=sys.stderr)
    if ensure_daemon_running():
        print(f"  HTTP daemon is ready", file=sys.stderr)
    else:
        print(f"  Warning: Could not verify daemon status", file=sys.stderr)

    try:
        mcp.run()
    finally:
        # Cleanup HTTP session (daemon keeps running for other clients)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(cleanup())
        loop.close()


if __name__ == "__main__":
    main()
