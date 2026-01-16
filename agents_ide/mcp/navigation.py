#!/usr/bin/env python3
"""Navigation tools: definition, references, hover, diagnostics."""

from ._core import mcp, http_post, format_result


@mcp.tool()
async def definition(filePath: str, line: int, column: int) -> str:
    """
    Get the definition location of a symbol at a specific position.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("definition", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def references(filePath: str, line: int, column: int) -> str:
    """
    Find all references to a symbol at a specific position.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("references", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def hover(filePath: str, line: int, column: int) -> str:
    """
    Get type information and documentation for a symbol at a position.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("hover", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def diagnostics(filePath: str) -> str:
    """
    Get diagnostics (errors, warnings) for a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("diagnostics", {"filePath": filePath})
    return format_result(result)
