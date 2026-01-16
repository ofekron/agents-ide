#!/usr/bin/env python3
"""
Agents IDE - LSP Client

Shared LSP client and utilities for the Agents IDE daemon.
Manages persistent pyright-langserver connection.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


# LSP JSON-RPC client
class LSPClient:
    def __init__(self, workspace: str):
        self.workspace = workspace
        self.process: asyncio.subprocess.Process | None = None
        self.request_id = 0
        self.pending_requests: dict[int, asyncio.Future] = {}
        self._read_task: asyncio.Task | None = None
        self._initialized = False
        self._buffer = b""
        self._diagnostics: dict[str, list] = {}  # uri -> diagnostics

    async def start(self):
        """Start pyright-langserver and initialize LSP session."""
        self.process = await asyncio.create_subprocess_exec(
            "pyright-langserver", "--stdio",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Start reading responses
        self._read_task = asyncio.create_task(self._read_loop())

        # Send initialize request
        init_result = await self.request("initialize", {
            "processId": os.getpid(),
            "capabilities": {
                "textDocument": {
                    "definition": {"dynamicRegistration": False},
                    "references": {"dynamicRegistration": False},
                    "hover": {"dynamicRegistration": False},
                    "rename": {"dynamicRegistration": False},
                    "publishDiagnostics": {"relatedInformation": True},
                }
            },
            "rootUri": f"file://{self.workspace}",
            "workspaceFolders": [
                {"uri": f"file://{self.workspace}", "name": "workspace"}
            ],
        })

        # Send initialized notification
        await self.notify("initialized", {})
        self._initialized = True
        return init_result

    async def stop(self):
        """Stop the LSP server."""
        if self._read_task:
            self._read_task.cancel()
        if self.process:
            self.process.terminate()
            await self.process.wait()

    async def _read_loop(self):
        """Read and dispatch LSP responses."""
        while True:
            try:
                # Read header
                header = b""
                while b"\r\n\r\n" not in header:
                    chunk = await self.process.stdout.read(1)
                    if not chunk:
                        return
                    header += chunk

                # Parse content length
                content_length = 0
                for line in header.decode().split("\r\n"):
                    if line.startswith("Content-Length:"):
                        content_length = int(line.split(":")[1].strip())

                # Read content
                content = await self.process.stdout.readexactly(content_length)
                message = json.loads(content.decode())

                # Dispatch response or handle notification
                if "id" in message and message["id"] in self.pending_requests:
                    future = self.pending_requests.pop(message["id"])
                    if "error" in message:
                        future.set_exception(Exception(message["error"].get("message", "LSP error")))
                    else:
                        future.set_result(message.get("result"))
                elif message.get("method") == "textDocument/publishDiagnostics":
                    # Store diagnostics pushed by server
                    params = message.get("params", {})
                    uri = params.get("uri", "")
                    self._diagnostics[uri] = params.get("diagnostics", [])

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"LSP read error: {e}", file=sys.stderr)

    def _send(self, message: dict):
        """Send a JSON-RPC message to the LSP server."""
        content = json.dumps(message)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        self.process.stdin.write(header.encode() + content.encode())
        asyncio.create_task(self.process.stdin.drain())

    async def request(self, method: str, params: dict) -> Any:
        """Send a request and wait for response."""
        self.request_id += 1
        request_id = self.request_id

        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future

        self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        })

        return await asyncio.wait_for(future, timeout=30.0)

    async def notify(self, method: str, params: dict):
        """Send a notification (no response expected)."""
        self._send({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })

    # High-level LSP operations

    async def open_file(self, path: str) -> str:
        """Open a file in the LSP (required before operations)."""
        uri = f"file://{path}"
        try:
            content = Path(path).read_text()
        except Exception as e:
            return f"Error reading file: {e}"

        await self.notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": "python",
                "version": 1,
                "text": content,
            }
        })
        return content

    async def get_definition(self, path: str, line: int, column: int) -> dict:
        """Get definition at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result

    async def get_references(self, path: str, line: int, column: int) -> list:
        """Get all references to symbol at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
            "context": {"includeDeclaration": True},
        })
        return result or []

    async def get_hover(self, path: str, line: int, column: int) -> dict:
        """Get hover info (type, docs) at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result

    async def rename_symbol(self, path: str, line: int, column: int, new_name: str) -> dict:
        """Rename symbol at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/rename", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
            "newName": new_name,
        })
        return result

    async def get_diagnostics(self, path: str) -> list:
        """Get diagnostics for a file. Opens file and waits for diagnostics."""
        await self.open_file(path)
        uri = f"file://{path}"
        # Give LSP server time to analyze and push diagnostics
        await asyncio.sleep(0.5)
        return self._diagnostics.get(uri, [])

    async def get_document_symbols(self, path: str) -> list:
        """Get document symbols (outline) for a file."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri},
        })
        return result or []

    async def get_workspace_symbols(self, query: str) -> list:
        """Search for symbols across the workspace."""
        result = await self.request("workspace/symbol", {
            "query": query,
        })
        return result or []

    async def get_declaration(self, path: str, line: int, column: int) -> dict:
        """Get declaration location at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/declaration", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result

    async def get_type_definition(self, path: str, line: int, column: int) -> dict:
        """Get type definition location at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/typeDefinition", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result

    async def get_implementation(self, path: str, line: int, column: int) -> list:
        """Get implementation locations at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/implementation", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result or []

    async def get_signature_help(self, path: str, line: int, column: int) -> dict:
        """Get signature help at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/signatureHelp", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result

    async def get_document_highlight(self, path: str, line: int, column: int) -> list:
        """Get document highlights (all occurrences) at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/documentHighlight", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result or []

    async def get_folding_ranges(self, path: str) -> list:
        """Get folding ranges for a file."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/foldingRange", {
            "textDocument": {"uri": uri},
        })
        return result or []

    async def prepare_call_hierarchy(self, path: str, line: int, column: int) -> list:
        """Prepare call hierarchy at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/prepareCallHierarchy", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result or []

    async def get_incoming_calls(self, item: dict) -> list:
        """Get incoming calls for a call hierarchy item."""
        result = await self.request("callHierarchy/incomingCalls", {
            "item": item,
        })
        return result or []

    async def get_outgoing_calls(self, item: dict) -> list:
        """Get outgoing calls for a call hierarchy item."""
        result = await self.request("callHierarchy/outgoingCalls", {
            "item": item,
        })
        return result or []

    async def get_completion(self, path: str, line: int, column: int) -> dict:
        """Get completions at position."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": column - 1},
        })
        return result

    async def get_code_actions(self, path: str, start_line: int, start_col: int, end_line: int, end_col: int) -> list:
        """Get code actions for a range."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/codeAction", {
            "textDocument": {"uri": uri},
            "range": {
                "start": {"line": start_line - 1, "character": start_col - 1},
                "end": {"line": end_line - 1, "character": end_col - 1},
            },
            "context": {"diagnostics": []},
        })
        return result or []

    async def get_code_lens(self, path: str) -> list:
        """Get code lenses for a file."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/codeLens", {
            "textDocument": {"uri": uri},
        })
        return result or []

    async def get_formatting(self, path: str) -> list:
        """Get formatting edits for a file."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/formatting", {
            "textDocument": {"uri": uri},
            "options": {"tabSize": 4, "insertSpaces": True},
        })
        return result or []

    async def get_range_formatting(self, path: str, start_line: int, start_col: int, end_line: int, end_col: int) -> list:
        """Get formatting edits for a range."""
        await self.open_file(path)
        uri = f"file://{path}"

        result = await self.request("textDocument/rangeFormatting", {
            "textDocument": {"uri": uri},
            "range": {
                "start": {"line": start_line - 1, "character": start_col - 1},
                "end": {"line": end_line - 1, "character": end_col - 1},
            },
            "options": {"tabSize": 4, "insertSpaces": True},
        })
        return result or []

    async def get_selection_ranges(self, path: str, positions: list) -> list:
        """Get selection ranges for positions."""
        await self.open_file(path)
        uri = f"file://{path}"

        lsp_positions = [
            {"line": pos["line"] - 1, "character": pos["column"] - 1}
            for pos in positions
        ]

        result = await self.request("textDocument/selectionRange", {
            "textDocument": {"uri": uri},
            "positions": lsp_positions,
        })
        return result or []


# LSP Symbol kinds
SYMBOL_KIND_MAP = {
    1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class",
    6: "method", 7: "property", 8: "field", 9: "constructor", 10: "enum",
    11: "interface", 12: "function", 13: "variable", 14: "constant",
    15: "string", 16: "number", 17: "boolean", 18: "array", 19: "object",
    20: "key", 21: "null", 22: "enum_member", 23: "struct", 24: "event",
    25: "operator", 26: "type_parameter",
}

SYMBOL_KIND_REVERSE = {v: k for k, v in SYMBOL_KIND_MAP.items()}


def format_location(loc: dict) -> str:
    """Format an LSP location for display."""
    uri = loc.get("uri", "")
    path = uri.replace("file://", "")
    range_ = loc.get("range", {})
    start = range_.get("start", {})
    line = start.get("line", 0) + 1
    col = start.get("character", 0) + 1
    return f"{path}:{line}:{col}"


def format_symbol(
    symbol: dict,
    indent: int = 0,
    filter_kind: int | None = None,
    max_depth: int | None = None,
    allowed_kinds: set | None = None,
    current_depth: int = 0,
) -> list[str]:
    """Format a symbol and its children recursively.

    Args:
        symbol: The symbol dict from LSP
        indent: Current indentation level for formatting
        filter_kind: If set, only show symbols of this specific kind
        max_depth: Maximum depth to traverse (None = unlimited)
        allowed_kinds: Set of allowed symbol kind numbers (None = all allowed)
        current_depth: Current depth in the tree (internal tracking)
    """
    # Check depth limit
    if max_depth is not None and current_depth > max_depth:
        return []

    lines = []
    kind_num = symbol.get("kind", 0)
    kind_name = SYMBOL_KIND_MAP.get(kind_num, "unknown")
    name = symbol.get("name", "?")
    range_ = symbol.get("range", symbol.get("location", {}).get("range", {}))
    start = range_.get("start", {})
    line = start.get("line", 0) + 1

    # Check if this symbol kind is allowed
    kind_allowed = allowed_kinds is None or kind_num in allowed_kinds
    matches_filter = filter_kind is None or kind_num == filter_kind

    if kind_allowed and matches_filter:
        prefix = "  " * indent
        lines.append(f"{prefix}{kind_name} {name} (line {line})")

    children = symbol.get("children", [])
    for child in children:
        child_indent = indent + 1 if (kind_allowed and matches_filter) else indent
        lines.extend(format_symbol(
            child, child_indent, filter_kind, max_depth, allowed_kinds, current_depth + 1
        ))

    return lines


def format_hover(hover: dict) -> str:
    """Format hover result for display."""
    if not hover:
        return "No hover information available"

    contents = hover.get("contents", {})
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return contents.get("value", str(contents))
    if isinstance(contents, list):
        return "\n".join(
            c.get("value", str(c)) if isinstance(c, dict) else str(c)
            for c in contents
        )
    return str(contents)
