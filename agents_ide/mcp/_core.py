#!/usr/bin/env python3
"""
Core utilities shared across all Agents IDE MCP tools.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import aiohttp
from mcp.server.fastmcp import FastMCP
from toon import encode as toon_encode

# Configuration
DEFAULT_HTTP_PORT = 7902
HTTP_BASE_URL = os.environ.get("LSP_HTTP_URL", f"http://localhost:{DEFAULT_HTTP_PORT}")
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=60)
SCRIPT_DIR = Path(__file__).parent.parent

# Shared MCP instance
mcp = FastMCP("agents-ide")

# Shared HTTP session
_http_session: Optional[aiohttp.ClientSession] = None


def ensure_daemon_running():
    """Ensure the singleton HTTP daemon is running."""
    manager_script = SCRIPT_DIR / "manager.py"
    if manager_script.exists():
        result = subprocess.run(
            [sys.executable, str(manager_script), "ensure"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"Warning: Failed to ensure daemon: {result.stderr}", file=sys.stderr)
            return False
        return True
    else:
        print(f"Warning: Daemon manager not found at {manager_script}", file=sys.stderr)
        return False


async def get_session() -> aiohttp.ClientSession:
    """Get or create HTTP session."""
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession(timeout=HTTP_TIMEOUT)
    return _http_session


async def http_post(endpoint: str, data: dict) -> dict:
    """Make POST request to HTTP daemon."""
    session = await get_session()
    url = f"{HTTP_BASE_URL}/{endpoint}"
    try:
        async with session.post(url, json=data) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                return {"error": f"HTTP {resp.status}: {text}"}
    except aiohttp.ClientError as e:
        return {"error": f"Connection error: {e}. Is the LSP HTTP daemon running on {HTTP_BASE_URL}?"}


async def http_get(endpoint: str) -> dict:
    """Make GET request to HTTP daemon."""
    session = await get_session()
    url = f"{HTTP_BASE_URL}/{endpoint}"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                return {"error": f"HTTP {resp.status}: {text}"}
    except aiohttp.ClientError as e:
        return {"error": f"Connection error: {e}. Is the LSP HTTP daemon running on {HTTP_BASE_URL}?"}


def format_result(result: dict) -> str:
    """Format result dict as TOON for token efficiency."""
    if "error" in result:
        return f"Error: {result['error']}"
    return toon_encode(result)


def resolve_path(path: str, file_map: dict[str, str] | None) -> str:
    """Resolve path using file_map if provided."""
    if file_map is None:
        return path
    return file_map.get(path, path)


def in_range(value: int, start: int, end: int | None) -> bool:
    """Check if value is in range [start, end]. end=None means no upper bound."""
    if end is None:
        return value >= start
    return start <= value <= end


async def cleanup():
    """Cleanup HTTP session on shutdown."""
    global _http_session
    if _http_session and not _http_session.closed:
        await _http_session.close()
