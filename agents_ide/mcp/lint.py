#!/usr/bin/env python3
"""Lint and format tools."""

from ._core import mcp, http_post, format_result


@mcp.tool()
async def lint(filePath: str) -> str:
    """
    Run linter (ruff) on a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("lint", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def autofix(filePath: str) -> str:
    """
    Auto-fix linting issues in a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("autofix", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def format_code(filePath: str) -> str:
    """
    Format a Python file using the LSP formatter.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("formatting", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def sort_imports(filePath: str) -> str:
    """
    Sort imports in a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("sort_imports", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def pydoc(moduleName: str) -> str:
    """
    Get Python documentation for a module/class/function.

    Args:
        moduleName: Fully qualified module name (e.g., "os.path", "json.dumps")
    """
    result = await http_post("pydoc", {"moduleName": moduleName})
    return format_result(result)
