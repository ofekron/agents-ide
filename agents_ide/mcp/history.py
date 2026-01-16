#!/usr/bin/env python3
"""History and revert tools."""

from ._core import mcp, http_post, http_get, format_result


@mcp.tool()
async def history(limit: int = 50) -> str:
    """
    Get recent action history entries.

    Args:
        limit: Maximum number of entries to return (default: 50)
    """
    result = await http_get(f"history?limit={limit}")
    return format_result(result)


@mcp.tool()
async def history_stats() -> str:
    """Get statistics about the action history."""
    result = await http_get("history/stats")
    return format_result(result)


@mcp.tool()
async def history_file(filePath: str) -> str:
    """
    Get action history for a specific file.

    Args:
        filePath: Absolute path to the file
    """
    result = await http_post("history/file", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def can_revert(entryId: int) -> str:
    """
    Check if a history entry can be reverted.

    Args:
        entryId: ID of the history entry to check
    """
    result = await http_post("can_revert", {"entryId": entryId})
    return format_result(result)


@mcp.tool()
async def revert(entryId: int, force: bool = False) -> str:
    """
    Revert a specific action from history.

    Args:
        entryId: ID of the history entry to revert
        force: If True, force revert even if there are conflicts
    """
    result = await http_post("revert", {"entryId": entryId, "force": force})
    return format_result(result)


@mcp.tool()
async def revert_to_time(filePath: str, targetTime: float) -> str:
    """
    Revert a file to its state at a specific time.

    Args:
        filePath: Absolute path to the file
        targetTime: Unix timestamp to revert to
    """
    result = await http_post("revert_to_time", {"filePath": filePath, "targetTime": targetTime})
    return format_result(result)
