#!/usr/bin/env python3
"""Copy paste tool: copy text ranges between files."""

from ._core import mcp, resolve_path


def extract_range(lines: list[str], start_line: int, start_col: int, end_line: int, end_col: int) -> str:
    """Extract text from lines given 1-indexed line/col positions."""
    if start_line < 1 or end_line > len(lines):
        raise ValueError(f"Line range {start_line}-{end_line} out of bounds (file has {len(lines)} lines)")

    if start_line == end_line:
        line = lines[start_line - 1]
        return line[start_col - 1:end_col - 1]

    result = []
    result.append(lines[start_line - 1][start_col - 1:])
    for i in range(start_line, end_line - 1):
        result.append(lines[i])
    result.append(lines[end_line - 1][:end_col - 1])
    return "\n".join(result)


def insert_at(lines: list[str], line: int, col: int, text: str) -> list[str]:
    """Insert text at 1-indexed line/col position."""
    if line < 1 or line > len(lines) + 1:
        raise ValueError(f"Line {line} out of bounds")

    if line > len(lines):
        lines.append("")

    target_line = lines[line - 1]
    new_line = target_line[:col - 1] + text + target_line[col - 1:]

    new_lines = new_line.split("\n")
    return lines[:line - 1] + new_lines + lines[line:]


@mcp.tool()
async def copy_paste(operations: list[tuple], file_map: dict[str, str] | None = None) -> str:
    """
    Copy text ranges between files in batch.

    Args:
        operations: List of tuples: (from_file, start_line, start_col, end_line, end_col, to_file, to_line, to_col)
            - end_line=None means end of file
            - end_col=None means end of line
        file_map: Optional dict mapping short names to full paths, e.g. {"a": "/path/to/file_a.py"}
    """
    results = []
    files_modified = {}

    for i, op in enumerate(operations):
        try:
            from_file, start_line, start_col, end_line, end_col, to_file, to_line, to_col = op
            from_file = resolve_path(from_file, file_map)
            to_file = resolve_path(to_file, file_map)

            with open(from_file, "r") as f:
                source_lines = f.read().split("\n")

            if end_line is None:
                end_line = len(source_lines)
            if end_col is None:
                end_col = len(source_lines[end_line - 1]) + 1

            text = extract_range(source_lines, start_line, start_col, end_line, end_col)

            if to_file in files_modified:
                dest_lines = files_modified[to_file]
            else:
                with open(to_file, "r") as f:
                    dest_lines = f.read().split("\n")

            dest_lines = insert_at(dest_lines, to_line, to_col, text)
            files_modified[to_file] = dest_lines

            results.append(f"op {i+1}: copied {len(text)} chars")
        except Exception as e:
            results.append(f"op {i+1}: error - {e}")

    for file_path, lines in files_modified.items():
        with open(file_path, "w") as f:
            f.write("\n".join(lines))

    return f"Completed {len(operations)} operations. Modified {len(files_modified)} files. " + "; ".join(results)
