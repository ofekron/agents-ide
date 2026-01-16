#!/usr/bin/env python3
"""Refactoring tools: rename, move, change_signature, toggle_comment, find_and_replace."""

import re
from ._core import mcp, http_post, format_result, resolve_path, in_range


@mcp.tool()
async def find_and_replace(operations: list[tuple], phase: str = "apply", file_map: dict[str, str] | None = None) -> str:
    """
    Find and replace text in files or directories.

    Args:
        operations: List of tuples (paths, find, replace, is_regex). paths: list of filePath or (dirPath, recursive).
        phase: "preview" | "changes" | "apply"
        file_map: Optional dict mapping short names to full paths
    """
    import os

    file_data = {}

    def collect_files(p):
        p = resolve_path(p, file_map) if isinstance(p, str) else p
        result = []
        if isinstance(p, (tuple, list)) and len(p) == 2 and isinstance(p[1], bool):
            dir_path, recursive = resolve_path(p[0], file_map), p[1]
            if recursive:
                for root, _, files in os.walk(dir_path):
                    for f in files:
                        if f.endswith(".py"):
                            result.append(os.path.join(root, f))
            else:
                for f in os.listdir(dir_path):
                    if f.endswith(".py"):
                        result.append(os.path.join(dir_path, f))
        else:
            result.append(p)
        return result

    for op in operations:
        paths, find, replace = op[0], op[1], op[2]
        is_regex = op[3] if len(op) > 3 else False
        paths = [paths] if isinstance(paths, str) or isinstance(paths, tuple) else paths

        file_paths = []
        for p in paths:
            file_paths.extend(collect_files(p))

        # Apply to files
        for fp in file_paths:
            if fp not in file_data:
                with open(fp, "r") as f:
                    content = f.read()
                file_data[fp] = {"original": content, "new": content, "count": 0}

            entry = file_data[fp]
            if is_regex:
                entry["new"], count = re.subn(find, replace, entry["new"])
            else:
                count = entry["new"].count(find)
                entry["new"] = entry["new"].replace(find, replace)
            entry["count"] += count

    # Filter to files with changes
    file_data = {k: v for k, v in file_data.items() if v["count"] > 0}

    if phase == "preview":
        total = sum(e["count"] for e in file_data.values())
        return format_result({"phase": "preview", "total": total, "files": {f: e["count"] for f, e in file_data.items()}})

    if phase == "changes":
        changes = {}
        for fp, entry in file_data.items():
            orig_lines = entry["original"].splitlines()
            new_lines = entry["new"].splitlines()
            diff = []
            for i, (o, n) in enumerate(zip(orig_lines, new_lines)):
                if o != n:
                    diff.append({i + 1: [o, n]})
            changes[fp] = diff[:10]
        return format_result({"phase": "changes", "files": changes})

    if phase == "apply":
        for fp, entry in file_data.items():
            with open(fp, "w") as f:
                f.write(entry["new"])
        total = sum(e["count"] for e in file_data.values())
        return format_result({"phase": "apply", "total": total, "files": len(file_data)})

    return format_result({"error": "Invalid phase"})


@mcp.tool()
async def toggle_comment(operations: list[tuple], file_map: dict[str, str] | None = None) -> str:
    """
    Toggle comment on lines in batch.

    Args:
        operations: List of tuples (filePath, startLine, endLine). endLine=None means end of file.
        file_map: Optional dict mapping short names to full paths
    """
    files = {}
    results = []

    for filePath, startLine, endLine in operations:
        filePath = resolve_path(filePath, file_map)
        if filePath not in files:
            with open(filePath, "r") as f:
                files[filePath] = f.readlines()

        lines = files[filePath]
        if endLine is None:
            endLine = len(lines)
        target_lines = lines[startLine - 1:endLine]
        commented = sum(1 for l in target_lines if l.lstrip().startswith("#"))
        should_uncomment = commented > len(target_lines) / 2

        for i in range(startLine - 1, endLine):
            line = lines[i]
            stripped = line.lstrip()
            indent = line[:len(line) - len(stripped)]

            if should_uncomment:
                if stripped.startswith("# "):
                    lines[i] = indent + stripped[2:]
                elif stripped.startswith("#"):
                    lines[i] = indent + stripped[1:]
            else:
                lines[i] = indent + "# " + stripped

        results.append({"file": filePath, "lines": [startLine, endLine], "uncommented": should_uncomment})

    for filePath, lines in files.items():
        with open(filePath, "w") as f:
            f.writelines(lines)

    return format_result({"modified": len(files), "operations": results})


@mcp.tool()
async def rename(operations: list[tuple], phase: str = "apply", file_map: dict[str, str] | None = None) -> str:
    """
    Rename symbols across files in batch.

    Args:
        operations: List of tuples (filePath, line, column, newName, filters?)
            filters: optional dict {include_files, exclude_files, include_lines, exclude_lines}
            - include_files/exclude_files: glob patterns
            - include_lines/exclude_lines: list of (start, end) ranges. end=None means no upper bound.
        phase: "preview" | "changes" | "apply"
        file_map: Optional dict mapping short names to full paths
    """
    import fnmatch
    results = []
    for op in operations:
        filePath, line, column, newName = op[0], op[1], op[2], op[3]
        filePath = resolve_path(filePath, file_map)
        filters = op[4] if len(op) > 4 else {}

        result = await http_post("rename_local", {
            "filePath": filePath,
            "line": line,
            "column": column,
            "newName": newName,
            "phase": phase
        })

        # Apply filters to edits if present
        if "edits" in result and filters:
            filtered_edits = []
            for edit in result.get("edits", []):
                edit_file = edit.get("file", "")
                edit_line = edit.get("line", 0)

                # File filters
                if "include_files" in filters:
                    if not any(fnmatch.fnmatch(edit_file, p) for p in filters["include_files"]):
                        continue
                if "exclude_files" in filters:
                    if any(fnmatch.fnmatch(edit_file, p) for p in filters["exclude_files"]):
                        continue

                # Line filters
                if "include_lines" in filters:
                    if not any(in_range(edit_line, s, e) for s, e in filters["include_lines"]):
                        continue
                if "exclude_lines" in filters:
                    if any(in_range(edit_line, s, e) for s, e in filters["exclude_lines"]):
                        continue

                filtered_edits.append(edit)
            result["edits"] = filtered_edits

        results.append(result)

    return format_result({"operations": results})


@mcp.tool()
async def rename_local(operations: list[tuple], phase: str = "apply", file_map: dict[str, str] | None = None) -> str:
    """
    Rename local variables in batch.

    Args:
        operations: List of tuples (filePath, line, column, newName, filters?)
            filters: optional dict {include_lines, exclude_lines}
            - include_lines/exclude_lines: list of (start, end) ranges. end=None means no upper bound.
        phase: "preview" | "changes" | "apply"
        file_map: Optional dict mapping short names to full paths
    """
    results = []
    for op in operations:
        filePath, line, column, newName = op[0], op[1], op[2], op[3]
        filePath = resolve_path(filePath, file_map)
        filters = op[4] if len(op) > 4 else {}

        result = await http_post("rename_local", {
            "filePath": filePath,
            "line": line,
            "column": column,
            "newName": newName,
            "phase": phase
        })

        # Apply line filters if present
        if "edits" in result and filters:
            filtered_edits = []
            for edit in result.get("edits", []):
                edit_line = edit.get("line", 0)

                if "include_lines" in filters:
                    if not any(in_range(edit_line, s, e) for s, e in filters["include_lines"]):
                        continue
                if "exclude_lines" in filters:
                    if any(in_range(edit_line, s, e) for s, e in filters["exclude_lines"]):
                        continue

                filtered_edits.append(edit)
            result["edits"] = filtered_edits

        results.append(result)

    return format_result({"operations": results})


@mcp.tool()
async def move(filePath: str, name: str, destPath: str, phase: str = "apply") -> str:
    """
    Move class or function to another file.

    Args:
        filePath: Source file path
        name: Name of class/function to move
        destPath: Destination file path
        phase: "preview" | "changes" | "apply"
    """
    result = await http_post("move", {
        "filePath": filePath,
        "name": name,
        "destPath": destPath,
        "phase": phase
    })
    return format_result(result)


@mcp.tool()
async def change_signature(filePath: str, functionName: str, newParams: list[str], phase: str = "apply") -> str:
    """
    Change function signature (parameters).

    Args:
        filePath: Python file path
        functionName: Name of function
        newParams: New params (e.g., ["x: int", "y: str = 'default'"])
        phase: "preview" | "changes" | "apply"
    """
    result = await http_post("change_signature", {
        "filePath": filePath,
        "functionName": functionName,
        "newParams": newParams,
        "phase": phase
    })
    return format_result(result)
