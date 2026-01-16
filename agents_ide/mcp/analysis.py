#!/usr/bin/env python3
"""Analysis tools: complexity, dead_code, dependencies, duplicates."""

from ._core import mcp, http_post, format_result


@mcp.tool()
async def complexity(filePath: str) -> str:
    """
    Analyze cyclomatic complexity and maintainability of a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("complexity", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def dead_code(filePath: str) -> str:
    """
    Find potentially unused code (dead code) in a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("dead_code", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def dependencies(filePath: str) -> str:
    """
    Analyze imports and dependencies of a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("dependencies", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def duplicates(filePath: str, minLines: int = 6) -> str:
    """
    Find duplicate code blocks in a Python file.

    Args:
        filePath: Absolute path to the Python file
        minLines: Minimum lines for a duplicate block (default: 6)
    """
    result = await http_post("duplicates", {"filePath": filePath, "minLines": minLines})
    return format_result(result)


@mcp.tool()
async def loc(filePath: str) -> str:
    """
    Count lines of code in a file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("loc", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def coupling(filePath: str) -> str:
    """
    Analyze coupling metrics for a file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("coupling", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def dependency_graph(filePath: str = None, depth: int = 3) -> str:
    """
    Generate a dependency graph.

    Args:
        filePath: Starting file (default: workspace root)
        depth: Maximum depth to traverse (default: 3)
    """
    data = {"depth": depth}
    if filePath:
        data["filePath"] = filePath
    result = await http_post("dependency_graph", data)
    return format_result(result)
