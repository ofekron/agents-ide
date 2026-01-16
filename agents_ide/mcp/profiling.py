#!/usr/bin/env python3
"""Profiling tools."""

from ._core import mcp, http_post, format_result


@mcp.tool()
async def profile(filePath: str, functionName: str = None) -> str:
    """
    Profile a Python file or function.

    Args:
        filePath: Absolute path to the Python file
        functionName: Specific function to profile (optional)
    """
    data = {"filePath": filePath}
    if functionName:
        data["functionName"] = functionName
    result = await http_post("profile", data)
    return format_result(result)


@mcp.tool()
async def memory_profile(filePath: str, functionName: str = None) -> str:
    """
    Memory profile a Python file or function.

    Args:
        filePath: Absolute path to the Python file
        functionName: Specific function to profile (optional)
    """
    data = {"filePath": filePath}
    if functionName:
        data["functionName"] = functionName
    result = await http_post("memory_profile", data)
    return format_result(result)
