#!/usr/bin/env python3
"""Type checking tools."""

from ._core import mcp, http_post, format_result


@mcp.tool()
async def typecheck(filePath: str) -> str:
    """
    Type check a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("typecheck", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def typecheck_code(code: str) -> str:
    """
    Type check Python code snippet.

    Args:
        code: Python code to type check
    """
    result = await http_post("typecheck_code", {"code": code})
    return format_result(result)
