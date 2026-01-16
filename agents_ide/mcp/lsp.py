#!/usr/bin/env python3
"""Additional LSP navigation and formatting tools."""

from ._core import mcp, http_post, format_result


@mcp.tool()
async def format_check(filePath: str) -> str:
    """
    Check formatting without applying changes.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("format_check", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def parse_traceback(traceback: str) -> str:
    """
    Parse a Python traceback into structured data.

    Args:
        traceback: The traceback text to parse
    """
    result = await http_post("parse_traceback", {"traceback": traceback})
    return format_result(result)


@mcp.tool()
async def find_exception_handlers(filePath: str, exceptionType: str = None) -> str:
    """
    Find exception handlers in a file.

    Args:
        filePath: Absolute path to the Python file
        exceptionType: Filter by exception type (optional)
    """
    data = {"filePath": filePath}
    if exceptionType:
        data["exceptionType"] = exceptionType
    result = await http_post("find_exception_handlers", data)
    return format_result(result)


@mcp.tool()
async def declaration(filePath: str, line: int, column: int) -> str:
    """
    Get the declaration location of a symbol.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("declaration", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def type_definition(filePath: str, line: int, column: int) -> str:
    """
    Get the type definition location of a symbol.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("type_definition", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def implementation(filePath: str, line: int, column: int) -> str:
    """
    Get implementation locations of an interface/abstract method.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("implementation", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def signature_help(filePath: str, line: int, column: int) -> str:
    """
    Get signature help for a function call.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("signature_help", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def document_highlight(filePath: str, line: int, column: int) -> str:
    """
    Get document highlights for a symbol (all occurrences in file).

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("document_highlight", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def folding_ranges(filePath: str) -> str:
    """
    Get folding ranges for a file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("folding_ranges", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def selection_ranges(filePath: str, line: int, column: int) -> str:
    """
    Get smart selection ranges at a position.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("selection_ranges", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def call_hierarchy(filePath: str, line: int, column: int, direction: str = "incoming") -> str:
    """
    Get call hierarchy for a function.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
        direction: "incoming" (who calls this) or "outgoing" (what this calls)
    """
    result = await http_post("call_hierarchy", {
        "filePath": filePath,
        "line": line,
        "column": column,
        "direction": direction
    })
    return format_result(result)


@mcp.tool()
async def completion(filePath: str, line: int, column: int) -> str:
    """
    Get code completion suggestions at a position.

    Args:
        filePath: Absolute path to the Python file
        line: Line number (1-indexed)
        column: Column number (1-indexed)
    """
    result = await http_post("completion", {
        "filePath": filePath,
        "line": line,
        "column": column
    })
    return format_result(result)


@mcp.tool()
async def code_actions(filePath: str, startLine: int, startCol: int, endLine: int, endCol: int) -> str:
    """
    Get available code actions for a range.

    Args:
        filePath: Absolute path to the Python file
        startLine: Start line (1-indexed)
        startCol: Start column (1-indexed)
        endLine: End line (1-indexed)
        endCol: End column (1-indexed)
    """
    result = await http_post("code_actions", {
        "filePath": filePath,
        "startLine": startLine,
        "startCol": startCol,
        "endLine": endLine,
        "endCol": endCol
    })
    return format_result(result)


@mcp.tool()
async def code_lens(filePath: str) -> str:
    """
    Get code lenses for a file.

    Args:
        filePath: Absolute path to the Python file
    """
    result = await http_post("code_lens", {"filePath": filePath})
    return format_result(result)


@mcp.tool()
async def range_formatting(
    filePath: str,
    startLine: int,
    startCol: int,
    endLine: int,
    endCol: int
) -> str:
    """
    Format a specific range in a file.

    Args:
        filePath: Absolute path to the Python file
        startLine: Start line (1-indexed)
        startCol: Start column (1-indexed)
        endLine: End line (1-indexed)
        endCol: End column (1-indexed)
    """
    result = await http_post("range_formatting", {
        "filePath": filePath,
        "startLine": startLine,
        "startCol": startCol,
        "endLine": endLine,
        "endCol": endCol
    })
    return format_result(result)


@mcp.tool()
async def index_files(paths: list[str] = None) -> str:
    """
    Index files for LSP analysis.

    Args:
        paths: List of file paths to index (default: all Python files)
    """
    result = await http_post("index_files", {"paths": paths or []})
    return format_result(result)
