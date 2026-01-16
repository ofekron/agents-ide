#!/usr/bin/env python3
"""Structure tools: structure, symbol_search, code_search."""

import fnmatch
import os
import re

from ._core import mcp, http_post, format_result

SKIP_DIRS = {'__pycache__', '.git', '.tox', '.mypy_cache', '.pytest_cache',
             'node_modules', '.venv', 'venv', '.eggs', 'dist', 'build'}


def _skip_dir(name: str) -> bool:
    return name.startswith('.') or name in SKIP_DIRS or name.endswith('.egg-info')


def _make_filter(include: list | str | None, exclude: list | str | None):
    include_patterns = [include] if isinstance(include, str) else (include or [])
    exclude_patterns = [exclude] if isinstance(exclude, str) else (exclude or [])

    def matches(name: str) -> bool:
        if exclude_patterns and any(fnmatch.fnmatch(name, p) for p in exclude_patterns):
            return False
        if include_patterns and not any(fnmatch.fnmatch(name, p) for p in include_patterns):
            return False
        return True
    return matches


def _symbol_to_line(sym: dict) -> str:
    """Convert symbol dict to compact Python-like format."""
    kind = sym.get("kind", "?")
    parts = []

    if sym.get("decorators"):
        parts.append(" ".join(f"@{d}" for d in sym["decorators"]))

    if kind.startswith("async_"):
        parts.append("async")
        kind = kind[6:]

    if kind in ("function", "method"):
        args = sym.get("args", [])
        args_str = ", ".join(args) if isinstance(args, list) else str(args)
        sig = f"def({args_str})"
        if sym.get("returns"):
            sig += f" -> {sym['returns']}"
        parts.append(sig)
    elif kind == "class":
        bases = sym.get("bases", [])
        parts.append(f"class({', '.join(bases)})" if bases else "class")
    else:
        parts.append(kind)

    line, end = sym.get("line"), sym.get("endLine")
    if line:
        parts.append(f"L{line}-{end}" if end else f"L{line}")

    if sym.get("visibility") and sym["visibility"] != "public":
        parts.append(sym["visibility"])

    return " ".join(parts)


def _format_symbols(symbols: list, allowed_types: set | None = None, indent: int = 0) -> str:
    """Format symbols as indented text lines."""
    lines = []
    prefix = "  " * indent
    for sym in symbols:
        if allowed_types and sym.get("kind") not in allowed_types:
            continue
        name = sym.pop("name")
        children = sym.pop("children", None)
        line = _symbol_to_line(sym)
        lines.append(f"{prefix}{name}: {line}")
        if children:
            lines.append(_format_symbols(children, allowed_types, indent + 1))
    return "\n".join(lines)


async def _handle_lambda_search(dir_path: str) -> str:
    """Search for lambdas in a directory."""
    files = {}
    for f in sorted(os.listdir(dir_path)):
        if not f.endswith(".py"):
            continue
        fp = os.path.join(dir_path, f)
        r = await http_post("ast_search", {"filePath": fp, "pattern": "lambda"})
        if "error" not in r and r.get("matches"):
            files[f] = r["matches"]
    return format_result(files)


async def _list_dir_entries(dir_path: str, matches_filter) -> str:
    """List directory entries at depth=0."""
    entries = []
    for f in sorted(os.listdir(dir_path)):
        if not matches_filter(f):
            continue
        fp = os.path.join(dir_path, f)
        if f.endswith(".py"):
            entries.append(f)
        elif os.path.isdir(fp) and not _skip_dir(f):
            entries.append(f"{f}/")
    return "\n".join(entries)


async def _process_directory(dir_path: str, depth: int | None, reset_depth_per_dir: bool,
                             symbol: str | None, symbolTypes, visibility,
                             allowed_types: set | None, matches_filter,
                             include, exclude) -> str:
    """Process directory with depth > 0."""
    child_depth = depth - 1 if depth is not None else None
    lines = []

    for f in sorted(os.listdir(dir_path)):
        if not matches_filter(f):
            continue
        fp = os.path.join(dir_path, f)

        if f.endswith(".py"):
            r = await http_post("file_structure", {
                "filePath": fp, "depth": child_depth, "symbol": symbol,
                "visibility": visibility, "symbolTypes": list(allowed_types),
            })
            if "error" not in r and r.get("symbols"):
                lines.append(f"{f}:")
                lines.append(_format_symbols(r["symbols"], allowed_types, indent=1))

        elif os.path.isdir(fp) and not _skip_dir(f):
            sub_depth = depth if reset_depth_per_dir else child_depth
            sub_result = await structure(
                fp, depth=sub_depth, reset_depth_per_dir=reset_depth_per_dir,
                symbol=symbol, symbolTypes=symbolTypes, visibility=visibility,
                include=include, exclude=exclude
            )
            if sub_result:
                lines.append(f"{f}/:")
                lines.append("\n".join("  " + line for line in sub_result.split("\n")))

    return "\n".join(lines)


async def _process_file(file_path: str, depth: int | None, symbol: str | None,
                        visibility, allowed_types: set) -> str:
    """Process a single file."""
    result = await http_post("file_structure", {
        "filePath": file_path,
        "depth": depth,
        "symbol": symbol,
        "visibility": visibility,
        "symbolTypes": list(allowed_types),
    })
    if "error" in result:
        return f"Error: {result['error']}"
    if "symbols" in result:
        return _format_symbols(result["symbols"], allowed_types)
    return ""


@mcp.tool()
async def structure(
    filePath: str,
    depth: int | None = None,
    reset_depth_per_dir: bool = False,
    symbol: str | None = None,
    symbolTypes: list | str | None = None,
    visibility: list | str | None = None,
    include: list | str | None = None,
    exclude: list | str | None = None,
) -> str:
    """
    Get structure of a file, package, symbol, or nested symbol.

    Args:
        filePath: Python file or package
        depth: 0=top-level, 1=children, None=unlimited
        reset_depth_per_dir: If True, depth resets for each directory
        symbol: Target symbol, supports dot notation (e.g., "MyClass.method")
        symbolTypes: class, function, method, async_function, async_method, property, lambda, file, variable, constant
            Default: class, function, method, async_function, async_method, property
        visibility: public, protected, private, dunder
        include: glob patterns to include (e.g., "test_*" or ["api/*", "core/*"])
        exclude: glob patterns to exclude (e.g., "*.bak" or ["temp/*", "old_*"])

    Output format: <name>: [@decorator] [async] <kind>(<args>) [-> ret] L<start>-<end> [visibility]
    Kinds: def (function/method), class, constant, variable
    Example: process: @mcp.tool async def(data: str) -> dict L45-80 protected
    Example: MAX_SIZE: constant L5
    """
    DEFAULT_TYPES = {"class", "function", "method", "async_function", "async_method", "property"}
    if symbolTypes:
        allowed_types = {symbolTypes} if isinstance(symbolTypes, str) else set(symbolTypes)
    else:
        allowed_types = DEFAULT_TYPES
    matches_filter = _make_filter(include, exclude)

    # Lambda special case
    if allowed_types and "lambda" in allowed_types:
        if os.path.isdir(filePath):
            return await _handle_lambda_search(filePath)
        result = await http_post("ast_search", {"filePath": filePath, "pattern": "lambda"})
        return format_result(result.get("matches", []))

    # File list special case
    if allowed_types and "file" in allowed_types and os.path.isdir(filePath):
        files = [f for f in sorted(os.listdir(filePath)) if f.endswith(".py")]
        return "\n".join(files)

    # Directory handling
    if os.path.isdir(filePath):
        if depth == 0:
            return await _list_dir_entries(filePath, matches_filter)
        return await _process_directory(
            filePath, depth, reset_depth_per_dir, symbol, symbolTypes,
            visibility, allowed_types, matches_filter, include, exclude
        )

    # Single file
    return await _process_file(filePath, depth, symbol, visibility, allowed_types)


@mcp.tool()
async def symbol_search(query: str) -> str:
    """
    Search for symbols by name across the workspace.

    Args:
        query: Symbol name to search for (supports fuzzy matching)

    Output format: <kind> <name> in <container> (<path>:<line>)
    Example: method process in MyClass (/src/api.py:45)
    """
    result = await http_post("symbol_search", {"query": query})
    return format_result(result)


@mcp.tool()
async def code_search(
    pattern: str,
    symbolTypes: list | str | None = None,
    visibility: list | str | None = None,
    symbolName: str | None = None,
    argName: str | None = None,
    filePattern: str = "*.py",
    maxResults: int = 50,
    path: str | None = None
) -> str:
    """
    Code search: grep + structure for structured results.

    Args:
        pattern: Search pattern (regex)
        symbolTypes: Filter by type (class, function, method, async_function, etc.)
        visibility: Filter by visibility (public, protected, private, dunder)
        symbolName: Filter by symbol name pattern (regex)
        argName: Filter functions/methods that have an argument matching this pattern
        filePattern: Glob for files (default: "*.py")
        maxResults: Limit results (default: 50)
        path: Directory to search (default: workspace root)

    Output format: files: {"<path>": {"<match>": "<start>-<end>"}, ...}, count: N
    Example: files: {"/src/api.py": {"def process(self):": "45-80"}}, count: 1
    """
    result = await http_post("code_search", {
        "pattern": pattern,
        "symbolTypes": symbolTypes,
        "visibility": visibility,
        "filePattern": filePattern,
        "maxResults": maxResults,
        "path": path,
    })
    if "error" in result or "results" not in result:
        return format_result(result)

    grouped = {}
    for r in result["results"]:
        sym = r.get("symbol", {})
        if symbolName and not re.search(symbolName, sym.get("name", "")):
            continue
        if argName:
            args = sym.get("args", [])
            if not any(re.search(argName, a) for a in args):
                continue
        f = r.pop("file")
        match = r.pop("match")
        grouped.setdefault(f, {})[match] = f"{sym.get('line', r.get('matchLine'))}-{sym.get('endLine', '')}"

    return format_result({"files": grouped, "count": len([m for f in grouped.values() for m in f])})
