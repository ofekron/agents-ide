#!/usr/bin/env python3
"""Search tools: grep, find_files, ast, ast_search, source, imports."""

from ._core import mcp, http_post, http_get, format_result


@mcp.tool()
async def grep(pattern: str, path: str = None, filePattern: str = None, maxResults: int = 100) -> str:
    """
    Search for a pattern in files using grep.

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search in (default: workspace root)
        filePattern: Glob pattern to filter files (e.g., "*.py")
        maxResults: Maximum number of results (default: 100)
    """
    data = {"pattern": pattern, "maxResults": maxResults}
    if path:
        data["path"] = path
    if filePattern:
        data["filePattern"] = filePattern
    result = await http_post("grep", data)
    return format_result(result)


@mcp.tool()
async def find_files(pattern: str, path: str = None, maxResults: int = 100) -> str:
    """
    Find files matching a pattern.

    Args:
        pattern: Glob pattern to match (e.g., "*.py", "**/*test*.py")
        path: Directory to search in (default: workspace root)
        maxResults: Maximum number of results (default: 100)
    """
    data = {"pattern": pattern, "maxResults": maxResults}
    if path:
        data["path"] = path
    result = await http_post("find_files", data)
    return format_result(result)


@mcp.tool()
async def ast(filePath: str, nodeType: str = None) -> str:
    """
    Get AST (Abstract Syntax Tree) of a Python file.

    Args:
        filePath: Absolute path to the Python file
        nodeType: Filter for specific node types (e.g., "FunctionDef", "ClassDef")
    """
    data = {"filePath": filePath}
    if nodeType:
        data["nodeType"] = nodeType
    result = await http_post("ast", data)
    return format_result(result)


@mcp.tool()
async def ast_search(filePath: str, pattern: str) -> str:
    """
    Search for AST patterns in a Python file.

    Supports common pattern searches:
    - "raise" - find all raise statements
    - "if __name__" or "main" - find if __name__ == '__main__' blocks
    - "try" - find all try/except blocks
    - "assert" - find all assert statements
    - "global" - find all global statements
    - "yield" - find all yield statements
    - "await" - find all await expressions
    - "lambda" - find all lambda expressions
    - "comprehension" - find all list/dict/set comprehensions
    - "decorator" - find all decorated functions/classes
    - "docstring" - find all docstrings
    - "string:<text>" - find string literals containing text
    - "call:<name>" - find function calls matching name

    Args:
        filePath: Absolute path to the Python file
        pattern: Search pattern (see above for supported patterns)
    """
    result = await http_post("ast_search", {"filePath": filePath, "pattern": pattern})
    return format_result(result)


@mcp.tool()
async def source(filePath: str, startLine: int = None, endLine: int = None) -> str:
    """
    Get source code from a file.

    Args:
        filePath: Absolute path to the Python file
        startLine: Start line (1-indexed, optional)
        endLine: End line (1-indexed, optional)
    """
    data = {"filePath": filePath}
    if startLine:
        data["startLine"] = startLine
    if endLine:
        data["endLine"] = endLine
    result = await http_post("source", data)
    return format_result(result)


@mcp.tool()
async def imports(filePath: str) -> str:
    """
    Get all imports in a Python file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("imports", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def installed_packages() -> str:
    """Get list of installed Python packages."""
    result = await http_get("installed_packages")
    return format_result(result)
