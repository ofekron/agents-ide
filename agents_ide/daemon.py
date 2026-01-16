#!/usr/bin/env python3
"""
Agents IDE Daemon

A shared HTTP server that wraps pyright-langserver, allowing multiple agents
(regardless of provider - Claude, Qwen, Codex, Gemini, etc.) to share a single
LSP instance with shared indexing.

Usage:
    python tools/agents_ide_daemon.py [--port 7900] [--workspace /path/to/workspace]

    # Or run in background:
    python tools/agents_ide_daemon.py --port 7900 &

Endpoints:
    # Discovery (start here!)
    GET  /                  - Index of all endpoints with descriptions and examples
    GET  /endpoints         - Same as above
    POST /pydoc             - Fetch Python documentation for any module/class/function

    # Navigation
    POST /definition        - Get definition location
    POST /declaration       - Get declaration location
    POST /type_definition   - Go to type's definition
    POST /implementation    - Find implementations of interface/abstract
    POST /references        - Find all references

    # Information
    POST /hover             - Get type info and docs
    POST /signature_help    - Get function signature/parameter info
    POST /document_highlight - Highlight all occurrences in file

    # Structure
    POST /file_structure    - Get file outline (classes, functions, etc.)
    POST /symbol_search     - Search symbols across workspace
    POST /folding_ranges    - Get collapsible code regions
    POST /selection_ranges  - Get smart selection expansion

    # Call Hierarchy
    POST /call_hierarchy    - Get incoming/outgoing calls for a function

    # Code Intelligence
    POST /completion        - Get code completions
    POST /code_actions      - Get quick fixes and refactors
    POST /diagnostics       - Get errors/warnings
    POST /code_lens         - Get inline hints (reference counts, etc.)

    # Formatting
    POST /formatting        - Format entire document
    POST /range_formatting  - Format selection

    # Refactoring
    POST /rename            - Rename symbol across files

    # Management
    POST /index_files       - Force index specific files
    GET  /health            - Health check
    GET  /stats             - Index statistics

Example:
    curl -X POST http://localhost:7900/definition \\
      -H "Content-Type: application/json" \\
      -d '{"filePath": "/path/to/file.py", "line": 42, "column": 10}'
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from aiohttp import web

# Shared LSP client
from agents_ide_lsp import (
    LSPClient,
    format_symbol,
    format_location,
    format_hover,
    SYMBOL_KIND_MAP,
    SYMBOL_KIND_REVERSE,
)

# Action history for reverting changes
from agents_ide_history import get_history, ActionHistory


class AgentsIDEDaemon:
    def __init__(self, workspace: str, port: int = 7900):
        self.workspace = workspace
        self.port = port
        self.lsp_client: LSPClient | None = None
        self.app = web.Application()
        self._setup_routes()
        self._indexed_files: set[str] = set()
        self._request_count = 0
        self._history = get_history()  # SQLite action history

    def _setup_routes(self):
        # Discovery & Documentation
        self.app.router.add_get("/", self.handle_endpoints_index)
        self.app.router.add_get("/endpoints", self.handle_endpoints_index)
        self.app.router.add_post("/pydoc", self.handle_pydoc)

        # Source & Dependencies
        self.app.router.add_post("/source", self.handle_source)
        self.app.router.add_post("/imports", self.handle_imports)
        self.app.router.add_post("/dependencies", self.handle_dependencies)
        self.app.router.add_get("/installed_packages", self.handle_installed_packages)

        # Search & Analysis
        self.app.router.add_post("/grep", self.handle_grep)
        self.app.router.add_post("/find_files", self.handle_find_files)
        self.app.router.add_post("/ast", self.handle_ast)
        self.app.router.add_post("/ast_search", self.handle_ast_search)
        self.app.router.add_post("/code_search", self.handle_code_search)
        self.app.router.add_post("/complexity", self.handle_complexity)
        self.app.router.add_post("/dead_code", self.handle_dead_code)

        # Typing
        self.app.router.add_post("/typecheck", self.handle_typecheck)
        self.app.router.add_post("/typecheck_code", self.handle_typecheck_code)

        # Profiling
        self.app.router.add_post("/profile", self.handle_profile)
        self.app.router.add_post("/memory_profile", self.handle_memory_profile)

        # Refactoring (rope-based, multi-phased)
        self.app.router.add_post("/extract_function", self.handle_extract_function)
        self.app.router.add_post("/extract_variable", self.handle_extract_variable)
        self.app.router.add_post("/inline_variable", self.handle_inline_variable)
        self.app.router.add_post("/rename_local", self.handle_rename_local)
        self.app.router.add_post("/move", self.handle_move)
        self.app.router.add_post("/change_signature", self.handle_change_signature)
        self.app.router.add_post("/introduce_parameter", self.handle_introduce_parameter)
        self.app.router.add_post("/introduce_factory", self.handle_introduce_factory)
        self.app.router.add_post("/encapsulate_field", self.handle_encapsulate_field)
        self.app.router.add_post("/local_to_field", self.handle_local_to_field)
        self.app.router.add_post("/method_to_object", self.handle_method_to_object)
        self.app.router.add_post("/use_function", self.handle_use_function)
        self.app.router.add_post("/restructure", self.handle_restructure)

        # Inheritance Refactoring (AST-based, multi-phased)
        self.app.router.add_post("/extract_superclass", self.handle_extract_superclass)
        self.app.router.add_post("/pull_up_member", self.handle_pull_up_member)
        self.app.router.add_post("/push_down_member", self.handle_push_down_member)
        self.app.router.add_post("/extract_protocol", self.handle_extract_protocol)
        self.app.router.add_post("/add_base_class", self.handle_add_base_class)
        self.app.router.add_post("/remove_base_class", self.handle_remove_base_class)
        self.app.router.add_post("/implement_methods", self.handle_implement_methods)
        self.app.router.add_post("/override_method", self.handle_override_method)

        # Design Patterns
        self.app.router.add_post("/pattern/singleton", self.handle_pattern_singleton)
        self.app.router.add_post("/pattern/factory", self.handle_pattern_factory)
        self.app.router.add_post("/pattern/builder", self.handle_pattern_builder)
        self.app.router.add_post("/pattern/observer", self.handle_pattern_observer)
        self.app.router.add_post("/pattern/decorator", self.handle_pattern_decorator)
        self.app.router.add_post("/pattern/strategy", self.handle_pattern_strategy)

        # Code Generation (rope.contrib.generate)
        self.app.router.add_post("/generate_function", self.handle_generate_function)
        self.app.router.add_post("/generate_class", self.handle_generate_class)
        self.app.router.add_post("/generate_module", self.handle_generate_module)
        self.app.router.add_post("/generate_package", self.handle_generate_package)
        self.app.router.add_post("/generate_variable", self.handle_generate_variable)

        # Code Metrics
        self.app.router.add_post("/loc", self.handle_loc)
        self.app.router.add_post("/duplicates", self.handle_duplicates)
        self.app.router.add_post("/coupling", self.handle_coupling)
        self.app.router.add_post("/dependency_graph", self.handle_dependency_graph)

        # Linting & Style
        self.app.router.add_post("/lint", self.handle_lint)
        self.app.router.add_post("/autofix", self.handle_autofix)
        self.app.router.add_post("/format_check", self.handle_format_check)
        self.app.router.add_post("/sort_imports", self.handle_sort_imports)

        # Runtime & Debug
        self.app.router.add_post("/parse_traceback", self.handle_parse_traceback)
        self.app.router.add_post("/find_exception_handlers", self.handle_find_exception_handlers)

        # Navigation
        self.app.router.add_post("/definition", self.handle_definition)
        self.app.router.add_post("/declaration", self.handle_declaration)
        self.app.router.add_post("/type_definition", self.handle_type_definition)
        self.app.router.add_post("/implementation", self.handle_implementation)
        self.app.router.add_post("/references", self.handle_references)

        # Information
        self.app.router.add_post("/hover", self.handle_hover)
        self.app.router.add_post("/signature_help", self.handle_signature_help)
        self.app.router.add_post("/document_highlight", self.handle_document_highlight)

        # Structure
        self.app.router.add_post("/file_structure", self.handle_file_structure)
        self.app.router.add_post("/symbol_search", self.handle_symbol_search)
        self.app.router.add_post("/folding_ranges", self.handle_folding_ranges)
        self.app.router.add_post("/selection_ranges", self.handle_selection_ranges)

        # Call Hierarchy
        self.app.router.add_post("/call_hierarchy", self.handle_call_hierarchy)

        # Code Intelligence
        self.app.router.add_post("/completion", self.handle_completion)
        self.app.router.add_post("/code_actions", self.handle_code_actions)
        self.app.router.add_post("/diagnostics", self.handle_diagnostics)
        self.app.router.add_post("/code_lens", self.handle_code_lens)

        # Formatting
        self.app.router.add_post("/formatting", self.handle_formatting)
        self.app.router.add_post("/range_formatting", self.handle_range_formatting)

        # Refactoring
        self.app.router.add_post("/rename", self.handle_rename)

        # Management
        self.app.router.add_post("/index_files", self.handle_index)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/stats", self.handle_stats)

        # History & Revert
        self.app.router.add_get("/history", self.handle_history)
        self.app.router.add_get("/history/stats", self.handle_history_stats)
        self.app.router.add_post("/history/file", self.handle_history_file)
        self.app.router.add_post("/can_revert", self.handle_can_revert)
        self.app.router.add_post("/revert", self.handle_revert)
        self.app.router.add_post("/revert_to_time", self.handle_revert_to_time)

    async def start(self):
        """Initialize LSP client and start HTTP server."""
        print(f"Starting LSP HTTP Daemon...", file=sys.stderr)
        print(f"  Workspace: {self.workspace}", file=sys.stderr)
        print(f"  Port: {self.port}", file=sys.stderr)

        # Start LSP client
        self.lsp_client = LSPClient(self.workspace)
        try:
            await self.lsp_client.start()
            print("  LSP initialized successfully", file=sys.stderr)
        except Exception as e:
            print(f"  Failed to initialize LSP: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"\nReady! Listening on http://localhost:{self.port}", file=sys.stderr)

    async def stop(self):
        """Stop the LSP client."""
        if self.lsp_client:
            await self.lsp_client.stop()

    def _json_response(self, data: dict, status: int = 200) -> web.Response:
        return web.json_response(data, status=status)

    def _error_response(self, message: str, status: int = 400) -> web.Response:
        return self._json_response({"error": message}, status=status)

    async def _get_json_body(self, request: web.Request) -> dict:
        try:
            return await request.json()
        except json.JSONDecodeError:
            return {}

    async def _ensure_indexed(self, file_path: str):
        """Open a file to ensure it's indexed."""
        if file_path not in self._indexed_files:
            await self.lsp_client.open_file(file_path)
            self._indexed_files.add(file_path)

    # --- Endpoints ---

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return self._json_response({
            "status": "ok",
            "lsp_initialized": self.lsp_client is not None and self.lsp_client._initialized,
        })

    async def handle_stats(self, request: web.Request) -> web.Response:
        """Return daemon statistics."""
        return self._json_response({
            "indexed_files_count": len(self._indexed_files),
            "indexed_files": sorted(self._indexed_files)[-20:],  # Last 20
            "request_count": self._request_count,
            "workspace": self.workspace,
        })

    # --- History & Revert ---

    async def handle_history(self, request: web.Request) -> web.Response:
        """Get recent action history."""
        limit = int(request.query.get("limit", "50"))
        entries = self._history.get_recent(limit=limit)
        return self._json_response({
            "entries": [
                {
                    "id": e.id,
                    "timestamp": e.timestamp,
                    "action": e.action,
                    "file_path": e.file_path,
                    "reverted": e.reverted,
                    "metadata": e.metadata,
                }
                for e in entries
            ]
        })

    async def handle_history_stats(self, request: web.Request) -> web.Response:
        """Get history statistics."""
        return self._json_response(self._history.get_stats())

    async def handle_history_file(self, request: web.Request) -> web.Response:
        """Get history for a specific file."""
        body = await self._get_json_body(request)
        file_path = body.get("filePath")
        if not file_path:
            return self._error_response("Required: filePath")
        history = self._history.get_file_history(file_path)
        return self._json_response({"file": file_path, "history": history})

    async def handle_can_revert(self, request: web.Request) -> web.Response:
        """Check if an action can be reverted without conflicts."""
        body = await self._get_json_body(request)
        entry_id = body.get("entryId")
        if entry_id is None:
            return self._error_response("Required: entryId")
        result = self._history.can_revert(entry_id)
        return self._json_response(result)

    async def handle_revert(self, request: web.Request) -> web.Response:
        """Revert a specific action by entry ID.

        If force=true, will overwrite with original content even on conflict.
        """
        body = await self._get_json_body(request)
        entry_id = body.get("entryId")
        force = body.get("force", False)
        if entry_id is None:
            return self._error_response("Required: entryId")
        result = self._history.revert(entry_id, force=force)
        if result.get("success"):
            return self._json_response(result)
        # Return full result including can_force hint
        return self._json_response(result, status=400 if result.get("can_force") else 400)

    async def handle_revert_to_time(self, request: web.Request) -> web.Response:
        """Revert a file to its state at a specific timestamp."""
        body = await self._get_json_body(request)
        file_path = body.get("filePath")
        target_time = body.get("targetTime")
        if not file_path or target_time is None:
            return self._error_response("Required: filePath, targetTime")
        result = self._history.revert_file_to_time(file_path, target_time)
        if result.get("success"):
            return self._json_response(result)
        return self._error_response(result.get("error", "Revert failed"))

    def _record_file_change(
        self,
        action: str,
        file_path: str,
        before_content: str | None,
        after_content: str | None,
        metadata: dict | None = None
    ) -> int:
        """Record a file change in history. Returns the entry ID."""
        return self._history.record(
            action=action,
            file_path=file_path,
            before_content=before_content,
            after_content=after_content,
            metadata=metadata
        )

    async def handle_endpoints_index(self, request: web.Request) -> web.Response:
        """Return index of all available endpoints for agent discovery."""
        endpoints = {
            "name": "LSP HTTP Daemon",
            "description": "Shared pyright LSP server for Python code intelligence. All agents can use these endpoints.",
            "workspace": self.workspace,
            "categories": {
                "discovery": {
                    "description": "Discover available endpoints and fetch documentation",
                    "endpoints": [
                        {
                            "path": "/",
                            "method": "GET",
                            "description": "This index - list all available endpoints",
                            "params": None,
                        },
                        {
                            "path": "/pydoc",
                            "method": "POST",
                            "description": "Fetch Python documentation for a module, class, or function",
                            "params": {
                                "module": "Module name (e.g., 'os', 'json', 'asyncio.tasks')",
                                "symbol": "(optional) Symbol within module (e.g., 'path.join', 'dumps')",
                            },
                            "example": {"module": "json", "symbol": "dumps"},
                        },
                    ],
                },
                "source_and_dependencies": {
                    "description": "Get source code and analyze dependencies",
                    "endpoints": [
                        {
                            "path": "/source",
                            "method": "POST",
                            "description": "Get source code of any function/class (including from installed packages)",
                            "params": {
                                "module": "(option 1) Module name",
                                "symbol": "(option 1) Symbol within module",
                                "filePath": "(option 2) File path",
                                "line": "(option 2, optional) Line number to find function/class at",
                            },
                            "examples": [
                                {"module": "json", "symbol": "dumps"},
                                {"filePath": "/path/to/file.py", "line": 42},
                            ],
                        },
                        {
                            "path": "/imports",
                            "method": "POST",
                            "description": "Analyze imports in a file - what it imports and what imports it",
                            "params": {
                                "filePath": "File to analyze",
                                "findReverse": "(optional) If true, also find files that import this file",
                            },
                        },
                        {
                            "path": "/dependencies",
                            "method": "POST",
                            "description": "Get package dependencies (pip show style info)",
                            "params": {
                                "package": "(optional) Specific package name. If omitted, reads requirements.txt",
                            },
                        },
                        {
                            "path": "/installed_packages",
                            "method": "GET",
                            "description": "List all installed Python packages with versions",
                            "params": None,
                        },
                    ],
                },
                "search_and_analysis": {
                    "description": "Search codebase and analyze code quality",
                    "endpoints": [
                        {
                            "path": "/grep",
                            "method": "POST",
                            "description": "Search codebase using ripgrep (with grep fallback)",
                            "params": {
                                "pattern": "Search pattern (regex)",
                                "path": "(optional) Directory to search (default: workspace)",
                                "filePattern": "(optional) File glob pattern (e.g., '*.py')",
                                "caseSensitive": "(optional) Default: true",
                                "maxResults": "(optional) Default: 100",
                                "contextLines": "(optional) Lines of context around matches",
                            },
                            "example": {"pattern": "def main", "filePattern": "*.py"},
                        },
                        {
                            "path": "/find_files",
                            "method": "POST",
                            "description": "Find files matching a glob pattern",
                            "params": {
                                "pattern": "Glob pattern (default: **/*.py)",
                                "path": "(optional) Base directory",
                                "maxResults": "(optional) Default: 500",
                            },
                            "example": {"pattern": "**/*test*.py"},
                        },
                        {
                            "path": "/ast",
                            "method": "POST",
                            "description": "Parse and return AST of a file or code snippet",
                            "params": {
                                "filePath": "(option 1) File to parse",
                                "code": "(option 2) Code string to parse",
                                "includeLocations": "(optional) Include line/column info (default: true)",
                                "maxDepth": "(optional) Max AST depth (default: 10)",
                            },
                        },
                        {
                            "path": "/complexity",
                            "method": "POST",
                            "description": "Calculate code metrics using radon library (cyclomatic complexity, maintainability index, Halstead metrics)",
                            "params": {
                                "filePath": "(option 1) File to analyze",
                                "code": "(option 2) Code to analyze",
                            },
                            "returns": {
                                "functions": "List of functions with complexity scores (A-F rating)",
                                "maintainability_index": "Overall maintainability score",
                                "halstead_metrics": "Vocabulary, difficulty, effort, estimated bugs",
                            },
                        },
                        {
                            "path": "/dead_code",
                            "method": "POST",
                            "description": "Find unused code using vulture library (imports, variables, functions, classes)",
                            "params": {
                                "filePath": "(option 1) Single file to analyze",
                                "scanDirectory": "(option 2) Directory to scan recursively",
                                "minConfidence": "(optional) Confidence threshold 0-100 (default: 60)",
                            },
                            "returns": {
                                "unused_code": "All unused items with confidence scores",
                                "by_type": "Categorized by imports, variables, functions, classes, attributes",
                            },
                        },
                    ],
                },
                "navigation": {
                    "description": "Jump to code locations",
                    "endpoints": [
                        {
                            "path": "/definition",
                            "method": "POST",
                            "description": "Go to where a symbol is defined",
                            "params": {"filePath": "Absolute file path", "line": "Line number (1-indexed)", "column": "Column number (1-indexed)"},
                            "example": {"filePath": "/path/to/file.py", "line": 42, "column": 10},
                        },
                        {
                            "path": "/declaration",
                            "method": "POST",
                            "description": "Go to where a symbol is declared",
                            "params": {"filePath": "str", "line": "int", "column": "int"},
                        },
                        {
                            "path": "/type_definition",
                            "method": "POST",
                            "description": "Go to the type's definition (e.g., from variable to its class)",
                            "params": {"filePath": "str", "line": "int", "column": "int"},
                        },
                        {
                            "path": "/implementation",
                            "method": "POST",
                            "description": "Find all implementations of an interface/abstract class",
                            "params": {"filePath": "str", "line": "int", "column": "int"},
                        },
                        {
                            "path": "/references",
                            "method": "POST",
                            "description": "Find all references to a symbol across the codebase",
                            "params": {"filePath": "str", "line": "int", "column": "int"},
                        },
                    ],
                },
                "information": {
                    "description": "Get information about code at a position",
                    "endpoints": [
                        {
                            "path": "/hover",
                            "method": "POST",
                            "description": "Get type information and documentation for a symbol",
                            "params": {"filePath": "str", "line": "int", "column": "int"},
                        },
                        {
                            "path": "/signature_help",
                            "method": "POST",
                            "description": "Get function signature and parameter info (useful when inside function call)",
                            "params": {"filePath": "str", "line": "int", "column": "int"},
                        },
                        {
                            "path": "/document_highlight",
                            "method": "POST",
                            "description": "Highlight all occurrences of a symbol in the same file",
                            "params": {"filePath": "str", "line": "int", "column": "int"},
                        },
                    ],
                },
                "structure": {
                    "description": "Understand code structure",
                    "endpoints": [
                        {
                            "path": "/file_structure",
                            "method": "POST",
                            "description": "Get outline of a file (classes, functions, methods, variables)",
                            "params": {
                                "filePath": "Absolute file path",
                                "symbolType": "(optional) Filter: class, function, method, variable, property, constant, enum, interface",
                            },
                            "example": {"filePath": "/path/to/file.py", "symbolType": "class"},
                        },
                        {
                            "path": "/symbol_search",
                            "method": "POST",
                            "description": "Search for symbols by name across workspace (fuzzy match)",
                            "params": {
                                "query": "Symbol name to search",
                                "indexPaths": "(optional) Array of file paths to index before searching",
                                "symbolType": "(optional) Filter by type",
                            },
                            "example": {"query": "Server", "symbolType": "class"},
                        },
                        {
                            "path": "/folding_ranges",
                            "method": "POST",
                            "description": "Get collapsible code regions (functions, classes, etc.)",
                            "params": {"filePath": "str"},
                        },
                        {
                            "path": "/selection_ranges",
                            "method": "POST",
                            "description": "Get smart selection expansion (select increasingly larger syntax elements)",
                            "params": {"filePath": "str", "positions": "Array of {line, column}"},
                        },
                    ],
                },
                "call_hierarchy": {
                    "description": "Understand function call relationships",
                    "endpoints": [
                        {
                            "path": "/call_hierarchy",
                            "method": "POST",
                            "description": "Get incoming calls (who calls this?) and outgoing calls (what does this call?)",
                            "params": {
                                "filePath": "str",
                                "line": "int",
                                "column": "int",
                                "direction": "(optional) 'incoming', 'outgoing', or 'both' (default: 'both')",
                            },
                            "example": {"filePath": "/path/to/file.py", "line": 42, "column": 10, "direction": "incoming"},
                        },
                    ],
                },
                "code_intelligence": {
                    "description": "Smart code assistance",
                    "endpoints": [
                        {
                            "path": "/completion",
                            "method": "POST",
                            "description": "Get code completions at position",
                            "params": {
                                "filePath": "str",
                                "line": "int",
                                "column": "int",
                                "limit": "(optional) Max completions to return (default: 50)",
                            },
                        },
                        {
                            "path": "/code_actions",
                            "method": "POST",
                            "description": "Get available quick fixes and refactoring options",
                            "params": {
                                "filePath": "str",
                                "line": "int (or startLine)",
                                "column": "(optional) int (or startColumn)",
                                "endLine": "(optional) int",
                                "endColumn": "(optional) int",
                            },
                        },
                        {
                            "path": "/diagnostics",
                            "method": "POST",
                            "description": "Get errors and warnings for a file",
                            "params": {"filePath": "str"},
                        },
                        {
                            "path": "/code_lens",
                            "method": "POST",
                            "description": "Get inline hints (like reference counts)",
                            "params": {"filePath": "str"},
                        },
                    ],
                },
                "formatting": {
                    "description": "Code formatting",
                    "endpoints": [
                        {
                            "path": "/formatting",
                            "method": "POST",
                            "description": "Get formatting edits for entire document",
                            "params": {"filePath": "str"},
                        },
                        {
                            "path": "/range_formatting",
                            "method": "POST",
                            "description": "Get formatting edits for a specific range",
                            "params": {"filePath": "str", "startLine": "int", "startColumn": "int", "endLine": "int", "endColumn": "int"},
                        },
                    ],
                },
                "refactoring": {
                    "description": "Code refactoring using rope library (multi-phased: preview->changes->apply)",
                    "phased_workflow": {
                        "phase_1_preview": "Default. Shows summary: files affected, estimated changes",
                        "phase_2_changes": "Shows detailed diff of all changes before applying",
                        "phase_3_apply": "Actually applies the changes to files",
                    },
                    "endpoints": [
                        {
                            "path": "/rename",
                            "method": "POST",
                            "description": "Rename a symbol across all files (LSP-based, immediate)",
                            "params": {"filePath": "str", "line": "int", "column": "int", "newName": "str"},
                        },
                        {
                            "path": "/rename_local",
                            "method": "POST",
                            "description": "Rename a symbol using rope (multi-phased)",
                            "params": {"filePath": "str", "line": "int", "column": "int", "newName": "str", "phase": "str"},
                        },
                        {
                            "path": "/extract_function",
                            "method": "POST",
                            "description": "Extract code selection into a new function",
                            "params": {"filePath": "str", "startLine": "int", "endLine": "int", "functionName": "str", "phase": "str"},
                        },
                        {
                            "path": "/extract_variable",
                            "method": "POST",
                            "description": "Extract an expression into a variable",
                            "params": {"filePath": "str", "line": "int", "startColumn": "int", "endColumn": "int", "variableName": "str", "phase": "str"},
                        },
                        {
                            "path": "/inline_variable",
                            "method": "POST",
                            "description": "Inline a variable (replace usages with value)",
                            "params": {"filePath": "str", "line": "int", "column": "int", "phase": "str"},
                        },
                        {
                            "path": "/move",
                            "method": "POST",
                            "description": "Move module, class, function, or method to another location",
                            "params": {"filePath": "str", "line": "(optional) int", "destination": "target module/class path", "phase": "str"},
                        },
                        {
                            "path": "/change_signature",
                            "method": "POST",
                            "description": "Change a function's signature (add/remove/reorder parameters)",
                            "params": {"filePath": "str", "line": "int", "newSignature": "list of param defs", "phase": "str"},
                        },
                        {
                            "path": "/introduce_parameter",
                            "method": "POST",
                            "description": "Add a new parameter to a function, replacing a value with it",
                            "params": {"filePath": "str", "line": "int", "parameterName": "str", "phase": "str"},
                        },
                        {
                            "path": "/introduce_factory",
                            "method": "POST",
                            "description": "Replace constructor calls with a factory method",
                            "params": {"filePath": "str", "line": "int (class def)", "factoryName": "str (default: create)", "phase": "str"},
                        },
                        {
                            "path": "/encapsulate_field",
                            "method": "POST",
                            "description": "Create getter/setter methods for a field",
                            "params": {"filePath": "str", "line": "int (field def)", "getterName": "(optional) str", "setterName": "(optional) str", "phase": "str"},
                        },
                        {
                            "path": "/local_to_field",
                            "method": "POST",
                            "description": "Promote a local variable to an instance field",
                            "params": {"filePath": "str", "line": "int", "column": "int", "phase": "str"},
                        },
                        {
                            "path": "/method_to_object",
                            "method": "POST",
                            "description": "Convert a method to a callable class (method object/functor)",
                            "params": {"filePath": "str", "line": "int (method def)", "className": "str", "phase": "str"},
                        },
                        {
                            "path": "/use_function",
                            "method": "POST",
                            "description": "Replace similar code patterns with calls to an existing function",
                            "params": {"filePath": "str", "line": "int (function def)", "phase": "str"},
                        },
                        {
                            "path": "/restructure",
                            "method": "POST",
                            "description": "Pattern-based code transformation (AST-aware search & replace)",
                            "params": {"pattern": "e.g. '${x}.append(${y})'", "goal": "e.g. '${x} += [${y}]'", "imports": "(optional) list", "phase": "str"},
                            "example": {"pattern": "${x}.append(${y})", "goal": "${x} += [${y}]", "phase": "preview"},
                        },
                    ],
                },
                "code_generation": {
                    "description": "Generate new code elements using rope.contrib.generate",
                    "endpoints": [
                        {
                            "path": "/generate_function",
                            "method": "POST",
                            "description": "Generate a function stub at given location (e.g., from an undefined call)",
                            "params": {
                                "filePath": "File where function call exists",
                                "line": "Line with the function call",
                                "column": "Column position",
                            },
                        },
                        {
                            "path": "/generate_class",
                            "method": "POST",
                            "description": "Generate a class stub (e.g., from an undefined class instantiation)",
                            "params": {
                                "filePath": "File where class reference exists",
                                "line": "Line with the class reference",
                                "column": "Column position",
                            },
                        },
                        {
                            "path": "/generate_module",
                            "method": "POST",
                            "description": "Generate a new module file",
                            "params": {
                                "moduleName": "Module name (e.g., 'utils.helpers')",
                                "parentPath": "(optional) Parent directory path",
                            },
                        },
                        {
                            "path": "/generate_package",
                            "method": "POST",
                            "description": "Generate a new package (directory with __init__.py)",
                            "params": {
                                "packageName": "Package name",
                                "parentPath": "(optional) Parent directory path",
                            },
                        },
                        {
                            "path": "/generate_variable",
                            "method": "POST",
                            "description": "Generate a variable assignment from an undefined name",
                            "params": {
                                "filePath": "File with undefined variable",
                                "line": "Line with the variable",
                                "column": "Column position",
                            },
                        },
                    ],
                },
                "code_metrics": {
                    "description": "Analyze code quality and structure metrics",
                    "endpoints": [
                        {
                            "path": "/loc",
                            "method": "POST",
                            "description": "Lines of code statistics (LOC, SLOC, comments, blanks)",
                            "params": {
                                "filePath": "(option 1) Single file to analyze",
                                "scanDirectory": "(option 2) Directory to scan recursively",
                            },
                            "returns": {
                                "loc": "Total lines of code",
                                "sloc": "Source lines (excluding comments/blanks)",
                                "lloc": "Logical lines of code",
                                "comments": "Comment lines",
                                "multi": "Multi-line string lines",
                                "blank": "Blank lines",
                            },
                        },
                        {
                            "path": "/duplicates",
                            "method": "POST",
                            "description": "Find duplicate/similar code blocks (AST-based)",
                            "params": {
                                "filePath": "(option 1) Single file",
                                "scanDirectory": "(option 2) Directory to scan",
                                "minLines": "(optional) Minimum lines for a block (default: 5)",
                            },
                            "returns": {
                                "duplicates": "List of duplicate groups with locations",
                                "total_duplicate_lines": "Total lines that are duplicated",
                            },
                        },
                        {
                            "path": "/coupling",
                            "method": "POST",
                            "description": "Module coupling analysis (afferent/efferent coupling, instability)",
                            "params": {
                                "filePath": "(option 1) Analyze single module",
                                "scanDirectory": "(option 2) Analyze all modules in directory",
                            },
                            "returns": {
                                "Ca": "Afferent coupling (modules that depend on this)",
                                "Ce": "Efferent coupling (modules this depends on)",
                                "instability": "I = Ce / (Ca + Ce), 0=stable, 1=unstable",
                            },
                        },
                        {
                            "path": "/dependency_graph",
                            "method": "POST",
                            "description": "Generate import dependency graph",
                            "params": {
                                "scanDirectory": "(optional) Directory to analyze (default: workspace)",
                                "format": "(optional) 'json', 'dot' (Graphviz), or 'mermaid' (default: json)",
                                "maxDepth": "(optional) Maximum import depth to follow",
                            },
                            "example": {"scanDirectory": "/path/to/package", "format": "mermaid"},
                        },
                    ],
                },
                "linting_and_style": {
                    "description": "Code linting, style checking, and auto-formatting",
                    "endpoints": [
                        {
                            "path": "/lint",
                            "method": "POST",
                            "description": "Run linter (ruff, pylint, or flake8)",
                            "params": {
                                "filePath": "(option 1) Single file",
                                "scanDirectory": "(option 2) Directory to scan",
                                "linter": "(optional) 'ruff' (default), 'pylint', or 'flake8'",
                                "select": "(optional) Rules to enable (e.g., 'E,W,F')",
                                "ignore": "(optional) Rules to ignore",
                            },
                        },
                        {
                            "path": "/autofix",
                            "method": "POST",
                            "description": "Auto-fix lint issues using ruff --fix",
                            "params": {
                                "filePath": "(option 1) Single file",
                                "scanDirectory": "(option 2) Directory to fix",
                                "dryRun": "(optional) If true, show diff without applying (default: false)",
                            },
                        },
                        {
                            "path": "/format_check",
                            "method": "POST",
                            "description": "Check formatting with black and isort (without modifying)",
                            "params": {
                                "filePath": "(option 1) Single file",
                                "scanDirectory": "(option 2) Directory to check",
                            },
                            "returns": {
                                "black_would_change": "Files that black would reformat",
                                "isort_would_change": "Files with unsorted imports",
                            },
                        },
                        {
                            "path": "/sort_imports",
                            "method": "POST",
                            "description": "Sort imports using isort",
                            "params": {
                                "filePath": "(option 1) Single file",
                                "scanDirectory": "(option 2) Directory to process",
                                "dryRun": "(optional) If true, show diff without applying",
                            },
                        },
                    ],
                },
                "runtime_and_debug": {
                    "description": "Runtime analysis and debugging helpers",
                    "endpoints": [
                        {
                            "path": "/parse_traceback",
                            "method": "POST",
                            "description": "Parse and analyze a Python traceback/stack trace",
                            "params": {
                                "traceback": "The traceback text to parse",
                            },
                            "returns": {
                                "exception_type": "Type of exception raised",
                                "exception_message": "The error message",
                                "frames": "List of stack frames with file, line, function, code",
                                "suggestions": "Possible fixes based on exception type",
                            },
                        },
                        {
                            "path": "/find_exception_handlers",
                            "method": "POST",
                            "description": "Find where exceptions are caught in the codebase",
                            "params": {
                                "filePath": "(option 1) Search single file",
                                "scanDirectory": "(option 2) Search directory",
                                "exceptionType": "(optional) Filter by exception type (e.g., 'ValueError')",
                            },
                            "returns": {
                                "handlers": "List of try/except blocks with location and caught types",
                                "by_exception": "Handlers grouped by exception type",
                                "bare_excepts": "Locations of bare except: clauses",
                            },
                        },
                    ],
                },
                "inheritance_refactoring": {
                    "description": "Inheritance hierarchy refactoring (AST-based, multi-phased)",
                    "phased_workflow": {
                        "phase_1_preview": "Shows summary of planned changes",
                        "phase_2_changes": "Shows detailed diff/new code",
                        "phase_3_apply": "Applies the changes",
                    },
                    "endpoints": [
                        {
                            "path": "/extract_superclass",
                            "method": "POST",
                            "description": "Extract a superclass from a class, moving selected members to it",
                            "params": {
                                "filePath": "File containing the class",
                                "className": "Class to extract from",
                                "newClassName": "Name for the new superclass",
                                "members": "List of method/attribute names to extract",
                                "phase": "preview/changes/apply",
                            },
                            "example": {
                                "filePath": "/path/to/file.py",
                                "className": "Dog",
                                "newClassName": "Animal",
                                "members": ["eat", "sleep"],
                                "phase": "preview",
                            },
                        },
                        {
                            "path": "/pull_up_member",
                            "method": "POST",
                            "description": "Move a member from a subclass up to its parent class",
                            "params": {
                                "filePath": "File containing the subclass",
                                "className": "Subclass containing the member",
                                "memberName": "Method/attribute to pull up",
                                "parentClass": "(optional) Target parent class name",
                                "parentFile": "(optional) File containing parent (if different)",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/push_down_member",
                            "method": "POST",
                            "description": "Move a member from parent class down to subclass(es)",
                            "params": {
                                "filePath": "File containing the parent class",
                                "className": "Parent class containing the member",
                                "memberName": "Method/attribute to push down",
                                "targetSubclasses": "(optional) List of specific subclass names",
                                "scanDirectory": "(optional) Where to find subclasses",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/extract_protocol",
                            "method": "POST",
                            "description": "Create a typing.Protocol from a class's methods",
                            "params": {
                                "filePath": "File containing the class",
                                "className": "Class to extract protocol from",
                                "protocolName": "Name for the new Protocol",
                                "methods": "(optional) List of methods to include (default: all public)",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/add_base_class",
                            "method": "POST",
                            "description": "Add a base class to an existing class",
                            "params": {
                                "filePath": "File containing the class",
                                "className": "Class to modify",
                                "baseClass": "Base class to add",
                                "position": "(optional) 'first' or 'last' (default: first)",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/remove_base_class",
                            "method": "POST",
                            "description": "Remove a base class from an existing class",
                            "params": {
                                "filePath": "File containing the class",
                                "className": "Class to modify",
                                "baseClass": "Base class to remove",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/implement_methods",
                            "method": "POST",
                            "description": "Generate stub implementations for abstract/interface methods",
                            "params": {
                                "filePath": "File containing the class",
                                "className": "Class to add implementations to",
                                "methods": "(optional) Specific methods to implement",
                                "raiseNotImplemented": "(optional) If true, raise NotImplementedError",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/override_method",
                            "method": "POST",
                            "description": "Override a parent class method with super() call",
                            "params": {
                                "filePath": "File containing the subclass",
                                "className": "Subclass to add override to",
                                "methodName": "Method to override",
                                "callSuper": "(optional) Include super() call (default: true)",
                                "phase": "preview/changes/apply",
                            },
                        },
                    ],
                },
                "design_patterns": {
                    "description": "Generate design pattern implementations from templates",
                    "endpoints": [
                        {
                            "path": "/pattern/singleton",
                            "method": "POST",
                            "description": "Convert a class to Singleton pattern",
                            "params": {
                                "filePath": "File containing the class",
                                "className": "Class to convert",
                                "threadSafe": "(optional) Thread-safe implementation (default: false)",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/pattern/factory",
                            "method": "POST",
                            "description": "Generate Factory pattern for creating objects",
                            "params": {
                                "filePath": "File to add factory to",
                                "baseClass": "Base class/interface for products",
                                "products": "List of concrete product class names",
                                "factoryName": "(optional) Name for factory class",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/pattern/builder",
                            "method": "POST",
                            "description": "Generate Builder pattern for a class",
                            "params": {
                                "filePath": "File containing the class",
                                "className": "Class to create builder for",
                                "builderName": "(optional) Name for builder class",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/pattern/observer",
                            "method": "POST",
                            "description": "Add Observer pattern to a class",
                            "params": {
                                "filePath": "File containing the class",
                                "className": "Class to make observable",
                                "events": "List of event names to observe",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/pattern/decorator",
                            "method": "POST",
                            "description": "Generate Decorator pattern structure",
                            "params": {
                                "filePath": "File to add decorator to",
                                "componentClass": "Base component class/interface",
                                "decoratorName": "Name for decorator base class",
                                "phase": "preview/changes/apply",
                            },
                        },
                        {
                            "path": "/pattern/strategy",
                            "method": "POST",
                            "description": "Generate Strategy pattern structure",
                            "params": {
                                "filePath": "File to add strategy to",
                                "strategyName": "Name for strategy interface",
                                "strategies": "List of concrete strategy names",
                                "contextClass": "(optional) Class to use strategies",
                                "phase": "preview/changes/apply",
                            },
                        },
                    ],
                },
                "management": {
                    "description": "Server management",
                    "endpoints": [
                        {
                            "path": "/index_files",
                            "method": "POST",
                            "description": "Force index specific files (makes them searchable)",
                            "params": {"paths": "Array of absolute file paths"},
                            "example": {"paths": ["/path/to/file1.py", "/path/to/file2.py"]},
                        },
                        {
                            "path": "/health",
                            "method": "GET",
                            "description": "Health check",
                            "params": None,
                        },
                        {
                            "path": "/stats",
                            "method": "GET",
                            "description": "Get daemon statistics (indexed files, request count)",
                            "params": None,
                        },
                    ],
                },
            },
            "usage_examples": {
                "curl": {
                    "get_definition": 'curl -X POST http://localhost:7900/definition -H "Content-Type: application/json" -d \'{"filePath": "/path/to/file.py", "line": 42, "column": 10}\'',
                    "search_symbols": 'curl -X POST http://localhost:7900/symbol_search -H "Content-Type: application/json" -d \'{"query": "MyClass", "symbolType": "class"}\'',
                    "get_docs": 'curl -X POST http://localhost:7900/pydoc -H "Content-Type: application/json" -d \'{"module": "json", "symbol": "dumps"}\'',
                },
                "python": """import requests
response = requests.post('http://localhost:7900/definition', json={
    'filePath': '/path/to/file.py',
    'line': 42,
    'column': 10
})
print(response.json())""",
            },
            "notes": [
                "All line and column numbers are 1-indexed",
                "Files must be indexed before they appear in symbol_search results",
                "Use /index_files to force index specific files, or any operation on a file auto-indexes it",
                "Pyright uses fuzzy matching for symbol_search",
            ],
        }
        return self._json_response(endpoints)

    async def handle_pydoc(self, request: web.Request) -> web.Response:
        """Fetch Python documentation for a module, class, or function."""
        self._request_count += 1
        body = await self._get_json_body(request)

        module_name = body.get("module")
        symbol = body.get("symbol")

        if not module_name:
            return self._error_response("Required: module (e.g., 'os', 'json', 'asyncio.tasks')")

        try:
            import importlib
            import inspect
            import pydoc

            # Import the module
            try:
                module = importlib.import_module(module_name)
            except ImportError as e:
                return self._error_response(f"Cannot import module '{module_name}': {e}", 404)

            # Get the target object
            target = module
            target_name = module_name
            if symbol:
                parts = symbol.split(".")
                for part in parts:
                    try:
                        target = getattr(target, part)
                        target_name = f"{target_name}.{part}"
                    except AttributeError:
                        return self._error_response(f"Symbol '{part}' not found in '{target_name}'", 404)

            # Gather documentation
            result = {
                "name": target_name,
                "type": type(target).__name__,
                "doc": inspect.getdoc(target) or "No documentation available",
            }

            # Add signature for callables
            if callable(target):
                try:
                    sig = inspect.signature(target)
                    result["signature"] = str(sig)
                    result["parameters"] = {}
                    for param_name, param in sig.parameters.items():
                        param_info = {"kind": str(param.kind).split(".")[-1]}
                        if param.default is not inspect.Parameter.empty:
                            param_info["default"] = repr(param.default)
                        if param.annotation is not inspect.Parameter.empty:
                            param_info["annotation"] = str(param.annotation)
                        result["parameters"][param_name] = param_info
                except (ValueError, TypeError):
                    pass

            # Add module info
            if inspect.ismodule(target):
                result["file"] = getattr(target, "__file__", None)
                # List public members
                members = []
                for name in dir(target):
                    if not name.startswith("_"):
                        obj = getattr(target, name, None)
                        if obj is not None:
                            members.append({
                                "name": name,
                                "type": type(obj).__name__,
                            })
                result["members"] = members[:50]  # Limit to 50

            # Add class info
            elif inspect.isclass(target):
                result["bases"] = [b.__name__ for b in target.__bases__]
                result["mro"] = [c.__name__ for c in target.__mro__]
                # List methods
                methods = []
                for name, method in inspect.getmembers(target, predicate=inspect.isfunction):
                    if not name.startswith("_") or name in ("__init__", "__call__", "__enter__", "__exit__"):
                        doc = inspect.getdoc(method)
                        methods.append({
                            "name": name,
                            "doc": doc[:100] + "..." if doc and len(doc) > 100 else doc,
                        })
                result["methods"] = methods

            # Add source file location if available
            try:
                source_file = inspect.getfile(target)
                result["source_file"] = source_file
                try:
                    _, line_number = inspect.getsourcelines(target)
                    result["source_line"] = line_number
                except (OSError, TypeError):
                    pass
            except TypeError:
                pass

            return self._json_response(result)

        except Exception as e:
            return self._error_response(f"Error fetching documentation: {e}", 500)

    # --- Source & Dependencies handlers ---

    async def handle_source(self, request: web.Request) -> web.Response:
        """Get source code of any function/class (including from installed packages)."""
        self._request_count += 1
        body = await self._get_json_body(request)

        # Can specify either module+symbol or filePath+line
        module_name = body.get("module")
        symbol = body.get("symbol")
        file_path = body.get("filePath")
        line = body.get("line")

        try:
            import inspect
            import importlib

            if module_name:
                # Get source from module
                try:
                    module = importlib.import_module(module_name)
                except ImportError as e:
                    return self._error_response(f"Cannot import module '{module_name}': {e}", 404)

                target = module
                target_name = module_name
                if symbol:
                    parts = symbol.split(".")
                    for part in parts:
                        try:
                            target = getattr(target, part)
                            target_name = f"{target_name}.{part}"
                        except AttributeError:
                            return self._error_response(f"Symbol '{part}' not found in '{target_name}'", 404)

                try:
                    source = inspect.getsource(target)
                    source_file = inspect.getfile(target)
                    _, line_number = inspect.getsourcelines(target)
                    return self._json_response({
                        "name": target_name,
                        "source": source,
                        "file": source_file,
                        "line": line_number,
                        "lines": len(source.splitlines()),
                    })
                except (OSError, TypeError) as e:
                    return self._error_response(f"Cannot get source for '{target_name}': {e}", 404)

            elif file_path:
                # Get source from file
                try:
                    with open(file_path, 'r') as f:
                        source_lines = f.readlines()
                except Exception as e:
                    return self._error_response(f"Cannot read file '{file_path}': {e}", 404)

                if line:
                    # Get source of function/class at this line using AST
                    import ast
                    source_text = ''.join(source_lines)
                    try:
                        tree = ast.parse(source_text)
                    except SyntaxError as e:
                        return self._error_response(f"Syntax error in file: {e}", 400)

                    # Find the node at the given line
                    target_node = None
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if hasattr(node, 'lineno') and node.lineno <= line:
                                if hasattr(node, 'end_lineno') and node.end_lineno >= line:
                                    target_node = node

                    if target_node:
                        start_line = target_node.lineno
                        end_line = target_node.end_lineno or start_line
                        source = ''.join(source_lines[start_line - 1:end_line])
                        return self._json_response({
                            "name": target_node.name,
                            "type": type(target_node).__name__.replace("Def", "").replace("Async", "async ").lower(),
                            "source": source,
                            "file": file_path,
                            "line": start_line,
                            "endLine": end_line,
                            "lines": end_line - start_line + 1,
                        })
                    else:
                        return self._error_response(f"No function/class found at line {line}", 404)
                else:
                    # Return entire file
                    return self._json_response({
                        "source": ''.join(source_lines),
                        "file": file_path,
                        "lines": len(source_lines),
                    })
            else:
                return self._error_response("Required: either (module, symbol?) or (filePath, line?)")

        except Exception as e:
            return self._error_response(f"Error getting source: {e}", 500)

    async def handle_imports(self, request: web.Request) -> web.Response:
        """Analyze imports in a file - what it imports and optionally what imports it."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        find_reverse = body.get("findReverse", False)  # Find files that import this file

        if not file_path:
            return self._error_response("Required: filePath")

        try:
            import ast

            with open(file_path, 'r') as f:
                source = f.read()

            try:
                tree = ast.parse(source)
            except SyntaxError as e:
                return self._error_response(f"Syntax error in file: {e}", 400)

            imports = []
            from_imports = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append({
                            "module": alias.name,
                            "alias": alias.asname,
                            "line": node.lineno,
                        })
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        from_imports.append({
                            "module": module,
                            "name": alias.name,
                            "alias": alias.asname,
                            "line": node.lineno,
                            "level": node.level,  # For relative imports
                        })

            result = {
                "file": file_path,
                "imports": imports,
                "from_imports": from_imports,
                "total_imports": len(imports) + len(from_imports),
            }

            # Find reverse imports if requested
            if find_reverse:
                import os
                import glob

                # Get the module name from file path
                file_name = os.path.basename(file_path).replace(".py", "")
                reverse_imports = []

                # Search Python files in workspace
                for py_file in glob.glob(os.path.join(self.workspace, "**/*.py"), recursive=True):
                    if py_file == file_path:
                        continue
                    try:
                        with open(py_file, 'r') as f:
                            other_source = f.read()
                        other_tree = ast.parse(other_source)
                        for node in ast.walk(other_tree):
                            if isinstance(node, ast.Import):
                                for alias in node.names:
                                    if file_name in alias.name:
                                        reverse_imports.append({
                                            "file": py_file,
                                            "module": alias.name,
                                            "line": node.lineno,
                                        })
                            elif isinstance(node, ast.ImportFrom):
                                if node.module and file_name in node.module:
                                    reverse_imports.append({
                                        "file": py_file,
                                        "module": node.module,
                                        "line": node.lineno,
                                    })
                    except:
                        pass

                result["imported_by"] = reverse_imports[:50]  # Limit results

            return self._json_response(result)

        except Exception as e:
            return self._error_response(f"Error analyzing imports: {e}", 500)

    async def handle_dependencies(self, request: web.Request) -> web.Response:
        """Get package dependencies (pip show style info)."""
        self._request_count += 1
        body = await self._get_json_body(request)

        package = body.get("package")

        try:
            import subprocess
            import importlib.metadata

            if package:
                # Get info for specific package
                try:
                    metadata = importlib.metadata.metadata(package)
                    requires = importlib.metadata.requires(package) or []

                    return self._json_response({
                        "name": metadata.get("Name"),
                        "version": metadata.get("Version"),
                        "summary": metadata.get("Summary"),
                        "author": metadata.get("Author"),
                        "license": metadata.get("License"),
                        "location": str(importlib.metadata.files(package)[0].locate().parent) if importlib.metadata.files(package) else None,
                        "requires": requires,
                        "requires_count": len(requires),
                    })
                except importlib.metadata.PackageNotFoundError:
                    return self._error_response(f"Package '{package}' not found", 404)
            else:
                # Try to read requirements.txt from workspace
                import os
                req_files = ["requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py"]
                requirements = {}

                for req_file in req_files:
                    req_path = os.path.join(self.workspace, req_file)
                    if os.path.exists(req_path):
                        with open(req_path, 'r') as f:
                            content = f.read()
                        if req_file == "requirements.txt" or req_file == "requirements-dev.txt":
                            # Parse requirements.txt
                            deps = []
                            for line in content.splitlines():
                                line = line.strip()
                                if line and not line.startswith("#"):
                                    deps.append(line)
                            requirements[req_file] = deps
                        else:
                            requirements[req_file] = {"exists": True, "preview": content[:500]}

                return self._json_response({
                    "workspace": self.workspace,
                    "requirement_files": requirements,
                })

        except Exception as e:
            return self._error_response(f"Error getting dependencies: {e}", 500)

    async def handle_installed_packages(self, request: web.Request) -> web.Response:
        """List installed Python packages with versions."""
        self._request_count += 1

        try:
            import importlib.metadata

            packages = []
            for dist in importlib.metadata.distributions():
                packages.append({
                    "name": dist.metadata["Name"],
                    "version": dist.metadata["Version"],
                })

            # Sort by name
            packages.sort(key=lambda x: x["name"].lower())

            return self._json_response({
                "packages": packages,
                "count": len(packages),
            })

        except Exception as e:
            return self._error_response(f"Error listing packages: {e}", 500)

    # --- Search & Analysis handlers ---

    async def handle_grep(self, request: web.Request) -> web.Response:
        """Search codebase using ripgrep."""
        self._request_count += 1
        body = await self._get_json_body(request)

        pattern = body.get("pattern")
        path = body.get("path", self.workspace)
        file_pattern = body.get("filePattern")  # e.g., "*.py"
        case_sensitive = body.get("caseSensitive", True)
        max_results = body.get("maxResults", 100)
        context_lines = body.get("contextLines", 0)

        if not pattern:
            return self._error_response("Required: pattern")

        try:
            import subprocess

            cmd = ["rg", "--json"]

            if not case_sensitive:
                cmd.append("-i")

            if file_pattern:
                cmd.extend(["-g", file_pattern])

            if context_lines:
                cmd.extend(["-C", str(context_lines)])

            cmd.extend(["-m", str(max_results)])
            cmd.append(pattern)
            cmd.append(path)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            matches = []
            import json as json_lib
            for line in result.stdout.splitlines():
                try:
                    data = json_lib.loads(line)
                    if data.get("type") == "match":
                        match_data = data.get("data", {})
                        path_data = match_data.get("path", {})
                        matches.append({
                            "file": path_data.get("text", ""),
                            "line": match_data.get("line_number"),
                            "text": match_data.get("lines", {}).get("text", "").strip(),
                        })
                except:
                    pass

            # Compact: just matches array, add "more" flag only if truncated
            resp: dict = {"matches": matches}
            if len(matches) >= max_results:
                resp["more"] = True
            return self._json_response(resp)

        except FileNotFoundError:
            # Fallback to grep if ripgrep not installed
            try:
                import subprocess
                cmd = ["grep", "-r", "-n"]
                if not case_sensitive:
                    cmd.append("-i")
                if file_pattern and file_pattern.endswith(".py"):
                    cmd.extend(["--include", file_pattern])
                cmd.extend([pattern, path])

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                matches = []
                for line in result.stdout.splitlines()[:max_results]:
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        matches.append({
                            "file": parts[0],
                            "line": int(parts[1]) if parts[1].isdigit() else 0,
                            "text": parts[2].strip(),
                        })
                return self._json_response({"matches": matches})
            except Exception as e:
                return self._error_response(f"Search failed: {e}", 500)

        except subprocess.TimeoutExpired:
            return self._error_response("Search timed out", 504)
        except Exception as e:
            return self._error_response(f"Search failed: {e}", 500)

    async def handle_find_files(self, request: web.Request) -> web.Response:
        """Find files matching a glob pattern."""
        self._request_count += 1
        body = await self._get_json_body(request)

        pattern = body.get("pattern", "**/*.py")
        path = body.get("path", self.workspace)
        max_results = body.get("maxResults", 500)

        try:
            import glob
            import os

            full_pattern = os.path.join(path, pattern)
            files = glob.glob(full_pattern, recursive=True)

            # Sort by modification time (newest first)
            files_with_info = []
            for f in files[:max_results]:
                try:
                    stat = os.stat(f)
                    files_with_info.append({
                        "path": os.path.relpath(f, self.workspace),
                        "size": stat.st_size,
                        "modified": int(stat.st_mtime),
                    })
                except:
                    files_with_info.append({"path": f})

            files_with_info.sort(key=lambda x: x.get("modified", 0), reverse=True)

            resp: dict = {"files": files_with_info}
            if len(files) > max_results:
                resp["truncated"] = True
            return self._json_response(resp)

        except Exception as e:
            return self._error_response(f"Error finding files: {e}", 500)

    async def handle_ast(self, request: web.Request) -> web.Response:
        """Parse and return AST of a file or code snippet."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        code = body.get("code")
        node_type = body.get("nodeType")  # Filter by specific node type
        include_locations = body.get("includeLocations", True)
        max_depth = body.get("maxDepth", 10)

        if not file_path and not code:
            return self._error_response("Required: filePath or code")

        try:
            import ast

            if file_path:
                with open(file_path, 'r') as f:
                    code = f.read()

            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return self._error_response(f"Syntax error: {e}", 400)

            # If nodeType filter is specified, find matching nodes
            if node_type:
                matches = []
                for node in ast.walk(tree):
                    if type(node).__name__ == node_type:
                        match_info = {
                            "_type": node_type,
                        }
                        if hasattr(node, 'lineno'):
                            match_info["line"] = node.lineno
                        if hasattr(node, 'end_lineno'):
                            match_info["endLine"] = node.end_lineno
                        if hasattr(node, 'col_offset'):
                            match_info["column"] = node.col_offset

                        # Extract relevant info based on node type
                        if hasattr(node, 'name'):
                            match_info["name"] = node.name
                        if hasattr(node, 'id'):
                            match_info["id"] = node.id
                        if hasattr(node, 'attr'):
                            match_info["attr"] = node.attr
                        if hasattr(node, 'arg'):
                            match_info["arg"] = node.arg
                        if hasattr(node, 'value') and not isinstance(node.value, ast.AST):
                            match_info["value"] = node.value
                        if hasattr(node, 's'):  # string constant
                            match_info["s"] = node.s[:100] if len(str(node.s)) > 100 else node.s
                        if hasattr(node, 'n'):  # numeric constant
                            match_info["n"] = node.n

                        # For function/class defs, include extra info
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            match_info["args"] = [arg.arg for arg in node.args.args]
                            match_info["async"] = isinstance(node, ast.AsyncFunctionDef)
                        if isinstance(node, ast.ClassDef):
                            match_info["bases"] = [
                                ast.unparse(b) if hasattr(ast, 'unparse') else str(b)
                                for b in node.bases
                            ]

                        # Get source code if unparse available
                        if hasattr(ast, 'unparse'):
                            try:
                                unparsed = ast.unparse(node)
                                if len(unparsed) <= 200:
                                    match_info["source"] = unparsed
                            except Exception:
                                pass

                        matches.append(match_info)

                return self._json_response({
                    "file": file_path,
                    "nodeType": node_type,
                    "count": len(matches),
                    "matches": matches,
                })

            # Default: return summary
            summary = {
                "imports": [],
                "classes": [],
                "functions": [],
            }

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        summary["imports"].append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    summary["imports"].append(f"{module}.{', '.join(a.name for a in node.names)}")
                elif isinstance(node, ast.ClassDef):
                    summary["classes"].append({
                        "name": node.name,
                        "line": node.lineno,
                        "bases": [ast.unparse(b) if hasattr(ast, 'unparse') else str(b) for b in node.bases],
                    })
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    # Only include top-level functions (not methods)
                    if not any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree)):
                        summary["functions"].append({
                            "name": node.name,
                            "line": node.lineno,
                            "async": isinstance(node, ast.AsyncFunctionDef),
                            "args": [arg.arg for arg in node.args.args],
                        })

            # Add methods to classes
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    methods = []
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods.append({
                                "name": item.name,
                                "line": item.lineno,
                                "async": isinstance(item, ast.AsyncFunctionDef),
                                "args": [arg.arg for arg in item.args.args],
                            })
                    # Find the class in summary and add methods
                    for cls in summary["classes"]:
                        if cls["name"] == node.name and cls["line"] == node.lineno:
                            cls["methods"] = methods
                            break

            # Compact response: no formatted text, structured data only
            return self._json_response({
                "imports": summary["imports"],
                "classes": summary["classes"],
                "functions": summary["functions"],
            })

        except Exception as e:
            return self._error_response(f"Error parsing AST: {e}", 500)

    async def handle_ast_search(self, request: web.Request) -> web.Response:
        """Search for AST patterns in a Python file.

        Supports common pattern searches like:
        - "raise" - find all raise statements
        - "if __name__" - find if __name__ == '__main__' blocks
        - "try" - find all try/except blocks
        - "assert" - find all assert statements
        - "global" - find all global statements
        - "yield" - find all yield statements
        - "await" - find all await expressions
        - "lambda" - find all lambda expressions
        - "comprehension" - find all list/dict/set comprehensions
        - "decorator" - find all decorated functions/classes
        - "docstring" - find all docstrings
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        pattern = body.get("pattern")

        if not file_path:
            return self._error_response("Required: filePath")
        if not pattern:
            return self._error_response("Required: pattern")

        try:
            import ast
            with open(file_path, 'r') as f:
                code = f.read()
                lines = code.split('\n')

            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return self._error_response(f"Syntax error: {e}", 400)

            matches = []
            pattern_lower = pattern.lower()

            def get_source_line(lineno):
                """Get source code line (1-indexed)."""
                if 1 <= lineno <= len(lines):
                    return lines[lineno - 1].strip()
                return ""

            def add_match(node, match_type, extra=None):
                """Add a match to results."""
                match = {
                    "type": match_type,
                    "line": node.lineno,
                    "endLine": getattr(node, 'end_lineno', node.lineno),
                    "source": get_source_line(node.lineno),
                }
                if extra:
                    match.update(extra)
                matches.append(match)

            for node in ast.walk(tree):
                # Raise statements
                if pattern_lower == "raise" and isinstance(node, ast.Raise):
                    exc_type = ""
                    if node.exc:
                        if hasattr(ast, 'unparse'):
                            exc_type = ast.unparse(node.exc)[:50]
                    add_match(node, "Raise", {"exception": exc_type})

                # If __name__ == '__main__' blocks
                elif pattern_lower in ("if __name__", "main", "__main__") and isinstance(node, ast.If):
                    if hasattr(ast, 'unparse'):
                        test_str = ast.unparse(node.test)
                        if "__name__" in test_str and ("__main__" in test_str or "'__main__'" in test_str):
                            add_match(node, "IfMain")

                # Try/except blocks
                elif pattern_lower == "try" and isinstance(node, ast.Try):
                    handlers = []
                    for h in node.handlers:
                        if h.type:
                            handlers.append(ast.unparse(h.type) if hasattr(ast, 'unparse') else str(h.type))
                        else:
                            handlers.append("bare except")
                    add_match(node, "Try", {"handlers": handlers})

                # Assert statements
                elif pattern_lower == "assert" and isinstance(node, ast.Assert):
                    test_str = ""
                    if hasattr(ast, 'unparse'):
                        test_str = ast.unparse(node.test)[:80]
                    add_match(node, "Assert", {"test": test_str})

                # Global statements
                elif pattern_lower == "global" and isinstance(node, ast.Global):
                    add_match(node, "Global", {"names": node.names})

                # Yield statements
                elif pattern_lower == "yield" and isinstance(node, (ast.Yield, ast.YieldFrom)):
                    yield_type = "YieldFrom" if isinstance(node, ast.YieldFrom) else "Yield"
                    add_match(node, yield_type)

                # Await expressions
                elif pattern_lower == "await" and isinstance(node, ast.Await):
                    add_match(node, "Await")

                # Lambda expressions
                elif pattern_lower == "lambda" and isinstance(node, ast.Lambda):
                    args = [arg.arg for arg in node.args.args]
                    add_match(node, "Lambda", {"args": args})

                # Comprehensions
                elif pattern_lower in ("comprehension", "comp") and isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
                    comp_type = {
                        ast.ListComp: "ListComp",
                        ast.DictComp: "DictComp",
                        ast.SetComp: "SetComp",
                        ast.GeneratorExp: "GeneratorExp",
                    }.get(type(node), "Comprehension")
                    add_match(node, comp_type)

                # Decorators
                elif pattern_lower in ("decorator", "decorated") and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.decorator_list:
                        decorators = []
                        for d in node.decorator_list:
                            if hasattr(ast, 'unparse'):
                                decorators.append(ast.unparse(d))
                        add_match(node, "Decorated", {
                            "name": node.name,
                            "decorators": decorators,
                            "kind": "class" if isinstance(node, ast.ClassDef) else "function"
                        })

                # Docstrings
                elif pattern_lower in ("docstring", "doc") and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                    docstring = ast.get_docstring(node)
                    if docstring:
                        name = getattr(node, 'name', '<module>')
                        add_match(node, "Docstring", {
                            "name": name,
                            "docstring": docstring[:200] + "..." if len(docstring) > 200 else docstring
                        })

                # String literals containing pattern
                elif pattern_lower.startswith("string:") and isinstance(node, ast.Constant) and isinstance(node.value, str):
                    search_str = pattern[7:]  # Remove "string:" prefix
                    if search_str.lower() in node.value.lower():
                        add_match(node, "StringLiteral", {
                            "value": node.value[:100] + "..." if len(node.value) > 100 else node.value
                        })

                # Function calls matching pattern
                elif pattern_lower.startswith("call:") and isinstance(node, ast.Call):
                    search_name = pattern[5:]  # Remove "call:" prefix
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    if search_name.lower() in func_name.lower():
                        add_match(node, "Call", {"function": func_name})

            # Sort by line number
            matches.sort(key=lambda m: m["line"])

            return self._json_response({
                "file": file_path,
                "pattern": pattern,
                "count": len(matches),
                "matches": matches,
                "supportedPatterns": [
                    "raise", "if __name__", "try", "assert", "global",
                    "yield", "await", "lambda", "comprehension", "decorator",
                    "docstring", "string:<search>", "call:<function>"
                ]
            })

        except Exception as e:
            return self._error_response(f"Error in AST search: {e}", 500)

    async def handle_code_search(self, request: web.Request) -> web.Response:
        """Code search: combines grep with file_structure to return structured results.

        First greps for a pattern, then extracts the containing symbol for each match
        with full structure information.

        Parameters:
            pattern: Search pattern (regex for grep)
            symbolTypes: Filter search to specific symbol types (class, function, method, etc.)
            visibility: Filter search by visibility (public, protected, private, dunder)
            filePattern: Glob pattern for files to search (default: "*.py")
            maxResults: Limit results (default: 50)
            path: Directory to search in (default: workspace)

            expand: How to expand each match (optional dict):
                    - mode: "source" (include raw source code) or "structure" (include children)
                    - depth: For mode="structure" - max depth (None = unlimited)
                    - visibility: For mode="structure" - filter children visibility
                    - depthTypes: For mode="structure" - {depth: [types]} filtering

        Example:
            {
                "pattern": "class.*Handler",
                "symbolTypes": "class",
                "expand": {
                    "mode": "structure",
                    "depth": 1,
                    "visibility": ["public", "protected"]
                }
            }
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        # Search parameters
        pattern = body.get("pattern")
        symbol_types = body.get("symbolTypes")  # Filter search results
        visibility_filter = body.get("visibility")  # Filter search results
        file_pattern = body.get("filePattern", "*.py")
        max_results = body.get("maxResults", 50)
        search_path = body.get("path", self.workspace)

        # Expand parameters (separate from search filters)
        expand_config = body.get("expand")  # dict or None
        expand_mode = None
        expand_depth = None
        expand_visibility = None
        expand_depth_types = None

        if expand_config:
            if isinstance(expand_config, str):
                # Simple mode: expand="source" or expand="structure"
                expand_mode = expand_config
            elif isinstance(expand_config, dict):
                expand_mode = expand_config.get("mode")
                expand_depth = expand_config.get("depth")
                expand_visibility = expand_config.get("visibility")
                expand_depth_types = expand_config.get("depthTypes")
            else:
                return self._error_response("expand must be string or dict")

            if expand_mode and expand_mode not in ("source", "structure"):
                return self._error_response("expand.mode must be 'source' or 'structure'")

        if not pattern:
            return self._error_response("Required: pattern")

        # Normalize filters
        allowed_types = None
        if symbol_types:
            if isinstance(symbol_types, str):
                allowed_types = {symbol_types}
            else:
                allowed_types = set(symbol_types)

        allowed_visibility = None
        if visibility_filter:
            if isinstance(visibility_filter, str):
                allowed_visibility = {visibility_filter}
            else:
                allowed_visibility = set(visibility_filter)

        try:
            import ast
            import subprocess

            # Step 1: Run grep to find matches
            cmd = ["rg", "--json", "-g", file_pattern, "-m", str(max_results * 2)]  # Get more to filter
            cmd.append(pattern)
            cmd.append(search_path)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            # Parse grep results
            grep_matches = []
            import json as json_lib
            for line in result.stdout.splitlines():
                try:
                    data = json_lib.loads(line)
                    if data.get("type") == "match":
                        match_data = data.get("data", {})
                        path_data = match_data.get("path", {})
                        grep_matches.append({
                            "file": path_data.get("text", ""),
                            "line": match_data.get("line_number"),
                            "text": match_data.get("lines", {}).get("text", "").strip(),
                        })
                except:
                    pass

            if not grep_matches:
                return self._json_response({"results": [], "count": 0})

            # Helper functions for symbol extraction
            def get_visibility(name: str) -> str:
                if name.startswith('__') and name.endswith('__'):
                    return "dunder"
                elif name.startswith('__'):
                    return "private"
                elif name.startswith('_'):
                    return "protected"
                return "public"

            def get_decorators(node) -> list[str]:
                decorators = []
                for dec in getattr(node, 'decorator_list', []):
                    if isinstance(dec, ast.Name):
                        decorators.append(dec.id)
                    elif isinstance(dec, ast.Attribute):
                        decorators.append(ast.unparse(dec) if hasattr(ast, 'unparse') else dec.attr)
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name):
                            decorators.append(dec.func.id)
                        elif isinstance(dec.func, ast.Attribute):
                            decorators.append(ast.unparse(dec.func) if hasattr(ast, 'unparse') else dec.func.attr)
                return decorators

            def get_type_annotation(node) -> str | None:
                if node is None:
                    return None
                try:
                    return ast.unparse(node) if hasattr(ast, 'unparse') else None
                except Exception:
                    return None

            # Normalize expand visibility filter
            expand_allowed_visibility = None
            if expand_visibility:
                if isinstance(expand_visibility, str):
                    expand_allowed_visibility = {expand_visibility}
                else:
                    expand_allowed_visibility = set(expand_visibility)

            # Build expand depth types lookup
            def get_expand_allowed_types(d: int) -> set | None:
                """Get allowed types for a specific depth in expand mode."""
                if not expand_depth_types:
                    return None  # No type filtering
                str_depth = str(d)
                if str_depth in expand_depth_types:
                    return set(expand_depth_types[str_depth])
                if "*" in expand_depth_types:
                    return set(expand_depth_types["*"])
                return None

            def extract_symbol(node, parent_name: str | None = None, current_depth: int = 0) -> dict | None:
                """Extract symbol info from AST node.

                Children are only included when expand.mode="structure" and within depth limit.
                """
                result = None
                include_children = expand_mode == "structure"
                max_depth = expand_depth

                if isinstance(node, ast.ClassDef):
                    result = {
                        "name": node.name,
                        "kind": "class",
                        "line": node.lineno,
                        "endLine": node.end_lineno,
                        "visibility": get_visibility(node.name),
                    }
                    if parent_name:
                        result["parent"] = parent_name
                    if node.bases:
                        result["bases"] = [ast.unparse(b) if hasattr(ast, 'unparse') else str(b) for b in node.bases]
                    decorators = get_decorators(node)
                    if decorators:
                        result["decorators"] = decorators

                    # Add children only for expand="structure"
                    if include_children and (max_depth is None or current_depth < max_depth):
                        children = []
                        # Get expand filters for the child depth
                        child_allowed_types = get_expand_allowed_types(current_depth + 1)
                        for item in node.body:
                            child = extract_symbol(item, parent_name=node.name, current_depth=current_depth + 1)
                            if child:
                                # Apply expand filters to children
                                if child_allowed_types and child["kind"] not in child_allowed_types:
                                    continue
                                if expand_allowed_visibility and child.get("visibility") not in expand_allowed_visibility:
                                    continue
                                children.append(child)
                        if children:
                            result["children"] = children

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_async = isinstance(node, ast.AsyncFunctionDef)
                    is_method = parent_name is not None

                    if is_method:
                        kind = "async_method" if is_async else "method"
                    else:
                        kind = "async_function" if is_async else "function"

                    decorators = get_decorators(node)
                    if "property" in decorators:
                        kind = "property"
                    elif "staticmethod" in decorators:
                        kind = "staticmethod"
                    elif "classmethod" in decorators:
                        kind = "classmethod"

                    # Build args with type annotations
                    args_info = []
                    for arg in node.args.args:
                        arg_str = arg.arg
                        if arg.annotation:
                            type_ann = get_type_annotation(arg.annotation)
                            if type_ann:
                                arg_str = f"{arg.arg}: {type_ann}"
                        args_info.append(arg_str)

                    result = {
                        "name": node.name,
                        "kind": kind,
                        "line": node.lineno,
                        "endLine": node.end_lineno,
                        "visibility": get_visibility(node.name),
                        "args": args_info,
                    }
                    if parent_name:
                        result["parent"] = parent_name

                    if node.returns:
                        return_type = get_type_annotation(node.returns)
                        if return_type:
                            result["returns"] = return_type

                    if decorators:
                        result["decorators"] = decorators

                    # Add children (nested functions/classes) only for expand="structure"
                    if include_children and (max_depth is None or current_depth < max_depth):
                        children = []
                        # Get expand filters for the child depth
                        child_allowed_types = get_expand_allowed_types(current_depth + 1)
                        for item in node.body:
                            child = extract_symbol(item, current_depth=current_depth + 1)
                            if child:
                                # Apply expand filters to children
                                if child_allowed_types and child["kind"] not in child_allowed_types:
                                    continue
                                if expand_allowed_visibility and child.get("visibility") not in expand_allowed_visibility:
                                    continue
                                children.append(child)
                        if children:
                            result["children"] = children

                # Apply filters
                if result:
                    if allowed_types and result["kind"] not in allowed_types:
                        return None
                    if allowed_visibility and result.get("visibility") not in allowed_visibility:
                        return None

                return result

            def find_containing_symbol(tree, target_line: int, parent_name: str | None = None) -> dict | None:
                """Find the innermost symbol containing the target line."""
                for node in ast.iter_child_nodes(tree):
                    if not hasattr(node, 'lineno'):
                        continue

                    # Account for decorators - they come before the def/class line
                    start_line = node.lineno
                    if hasattr(node, 'decorator_list') and node.decorator_list:
                        first_decorator = node.decorator_list[0]
                        if hasattr(first_decorator, 'lineno'):
                            start_line = first_decorator.lineno
                    end_line = getattr(node, 'end_lineno', start_line)

                    if start_line <= target_line <= end_line:
                        # This node contains the target line
                        # Check for nested symbols first (prefer innermost)
                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            nested = find_containing_symbol(node, target_line, parent_name=node.name)
                            if nested:
                                return nested
                            # No nested match, return this symbol
                            return extract_symbol(node, parent_name=parent_name)

                return None

            # Step 2: Process matches and find containing symbols
            results = []
            processed_files = {}  # Cache parsed ASTs

            for match in grep_matches:
                file_path = match["file"]
                match_line = match["line"]

                # Skip non-Python files
                if not file_path.endswith('.py'):
                    continue

                # Parse file if not cached (cache both AST and source lines)
                if file_path not in processed_files:
                    try:
                        with open(file_path, 'r') as f:
                            code = f.read()
                        source_lines = code.split('\n')
                        processed_files[file_path] = (ast.parse(code), source_lines)
                    except:
                        processed_files[file_path] = (None, None)
                        continue

                tree, source_lines = processed_files[file_path]
                if tree is None:
                    continue

                # Find containing symbol
                symbol = find_containing_symbol(tree, match_line)
                if symbol:
                    result_item = {
                        "file": file_path,
                        "match": match["text"],
                        "matchLine": match_line,
                        "symbol": symbol,
                    }

                    # Include source code if expand="source"
                    if expand_mode == "source" and source_lines:
                        start = symbol.get("line", 1) - 1  # 0-indexed
                        end = symbol.get("endLine", start + 1)
                        result_item["source"] = '\n'.join(source_lines[start:end])

                    results.append(result_item)

                if len(results) >= max_results:
                    break

            # Deduplicate by (file, symbol name, symbol line) to avoid multiple matches in same symbol
            seen = set()
            unique_results = []
            for r in results:
                key = (r["file"], r["symbol"]["name"], r["symbol"]["line"])
                if key not in seen:
                    seen.add(key)
                    unique_results.append(r)

            return self._json_response({
                "results": unique_results,
                "count": len(unique_results),
                "totalMatches": len(grep_matches),
            })

        except FileNotFoundError:
            return self._error_response("ripgrep (rg) not found. Install it with: brew install ripgrep", 500)
        except Exception as e:
            return self._error_response(f"Error in smart search: {e}", 500)

    async def handle_complexity(self, request: web.Request) -> web.Response:
        """Calculate cyclomatic complexity metrics using radon library."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        code = body.get("code")

        if not file_path and not code:
            return self._error_response("Required: filePath or code")

        try:
            from radon.complexity import cc_visit, cc_rank
            from radon.metrics import mi_visit, h_visit

            if file_path:
                with open(file_path, 'r') as f:
                    code = f.read()

            # Calculate cyclomatic complexity
            try:
                cc_results = cc_visit(code)
            except SyntaxError as e:
                return self._error_response(f"Syntax error: {e}", 400)

            functions = []
            total_complexity = 0

            for block in cc_results:
                complexity = block.complexity
                total_complexity += complexity
                rank = cc_rank(complexity)

                functions.append({
                    "name": block.name,
                    "line": block.lineno,
                    "complexity": complexity,
                    "rank": rank,
                    "classname": getattr(block, 'classname', None),
                })

            # Sort by complexity (highest first)
            functions.sort(key=lambda x: x["complexity"], reverse=True)

            avg_complexity = total_complexity / len(functions) if functions else 0

            # Calculate Maintainability Index
            try:
                mi_score = round(mi_visit(code, multi=False), 2)
            except:
                mi_score = None

            # Calculate Halstead metrics
            try:
                h_results = h_visit(code)
                halstead = {
                    "effort": round(sum(h.effort for h in h_results), 2) if h_results else 0,
                    "bugs": round(sum(h.bugs for h in h_results), 4) if h_results else 0,
                } if h_results else None
            except:
                halstead = None

            return self._json_response({
                "functions": functions,
                "total_complexity": total_complexity,
                "average_complexity": round(avg_complexity, 2),
                "maintainability_index": mi_score,
                "halstead": halstead,
            })

        except ImportError:
            return self._error_response("radon not installed. Install with: pip install radon", 500)
        except Exception as e:
            return self._error_response(f"Error calculating complexity: {e}", 500)

    async def handle_dead_code(self, request: web.Request) -> web.Response:
        """Find potentially unused code using vulture library."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        scan_directory = body.get("scanDirectory")
        min_confidence = body.get("minConfidence", 60)  # Vulture confidence threshold (0-100)

        if not file_path and not scan_directory:
            return self._error_response("Required: filePath or scanDirectory")

        try:
            from vulture import Vulture
            import os

            v = Vulture()

            # Scan the specified paths
            paths = []
            if file_path:
                paths.append(file_path)
            elif scan_directory:
                scan_path = os.path.join(self.workspace, scan_directory) if not os.path.isabs(scan_directory) else scan_directory
                paths.append(scan_path)

            v.scavenge(paths)

            # Collect results
            unused_code = []

            for item in v.get_unused_code(min_confidence=min_confidence):
                unused_code.append({
                    "name": item.name,
                    "file": os.path.relpath(item.filename, self.workspace),
                    "line": item.first_lineno,
                    "confidence": item.confidence,
                    "type": item.typ,
                })

            # Sort by file and line
            unused_code.sort(key=lambda x: (x["file"], x["line"]))

            return self._json_response({"items": unused_code})

        except ImportError:
            return self._error_response("vulture not installed. Install with: pip install vulture", 500)
        except Exception as e:
            return self._error_response(f"Error analyzing dead code: {e}", 500)

    # --- Typing handlers ---

    async def handle_typecheck(self, request: web.Request) -> web.Response:
        """Run pyright type checker on file(s) or directory."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        directory = body.get("directory")
        strict = body.get("strict", False)

        if not file_path and not directory:
            return self._error_response("Required: filePath or directory")

        try:
            import subprocess
            import json as json_lib

            target = file_path or directory or self.workspace
            cmd = ["pyright", "--outputjson"]

            if strict:
                cmd.append("--strict")

            cmd.append(target)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            try:
                output = json_lib.loads(result.stdout)
            except json_lib.JSONDecodeError:
                # Fallback to parsing text output
                return self._json_response({
                    "raw_output": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                })

            diagnostics = []
            for diag in output.get("generalDiagnostics", []):
                diagnostics.append({
                    "file": diag.get("file", ""),
                    "line": diag.get("range", {}).get("start", {}).get("line", 0) + 1,
                    "column": diag.get("range", {}).get("start", {}).get("character", 0) + 1,
                    "severity": diag.get("severity", "error"),
                    "message": diag.get("message", ""),
                    "rule": diag.get("rule", ""),
                })

            summary = output.get("summary", {})
            return self._json_response({
                "target": target,
                "diagnostics": diagnostics,
                "error_count": summary.get("errorCount", len([d for d in diagnostics if d["severity"] == "error"])),
                "warning_count": summary.get("warningCount", len([d for d in diagnostics if d["severity"] == "warning"])),
                "info_count": summary.get("informationCount", 0),
                "files_analyzed": summary.get("filesAnalyzed", 0),
                "time_seconds": summary.get("timeInSec", 0),
            })

        except FileNotFoundError:
            return self._error_response("pyright not installed. Install with: pip install pyright", 500)
        except subprocess.TimeoutExpired:
            return self._error_response("Type check timed out", 504)
        except Exception as e:
            return self._error_response(f"Type check failed: {e}", 500)

    async def handle_typecheck_code(self, request: web.Request) -> web.Response:
        """Type check a code snippet (writes to temp file)."""
        self._request_count += 1
        body = await self._get_json_body(request)

        code = body.get("code")
        if not code:
            return self._error_response("Required: code")

        try:
            import subprocess
            import tempfile
            import os
            import json as json_lib

            # Write code to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_path = f.name

            try:
                cmd = ["pyright", "--outputjson", temp_path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                try:
                    output = json_lib.loads(result.stdout)
                except json_lib.JSONDecodeError:
                    return self._json_response({
                        "raw_output": result.stdout,
                        "returncode": result.returncode,
                    })

                diagnostics = []
                for diag in output.get("generalDiagnostics", []):
                    diagnostics.append({
                        "line": diag.get("range", {}).get("start", {}).get("line", 0) + 1,
                        "column": diag.get("range", {}).get("start", {}).get("character", 0) + 1,
                        "severity": diag.get("severity", "error"),
                        "message": diag.get("message", ""),
                        "rule": diag.get("rule", ""),
                    })

                return self._json_response({
                    "diagnostics": diagnostics,
                    "error_count": len([d for d in diagnostics if d["severity"] == "error"]),
                    "warning_count": len([d for d in diagnostics if d["severity"] == "warning"]),
                    "is_valid": len([d for d in diagnostics if d["severity"] == "error"]) == 0,
                })
            finally:
                os.unlink(temp_path)

        except FileNotFoundError:
            return self._error_response("pyright not installed", 500)
        except Exception as e:
            return self._error_response(f"Type check failed: {e}", 500)

    # --- Profiling handlers ---

    async def handle_profile(self, request: web.Request) -> web.Response:
        """Profile Python code execution using cProfile."""
        self._request_count += 1
        body = await self._get_json_body(request)

        code = body.get("code")
        file_path = body.get("filePath")
        function_name = body.get("functionName")
        sort_by = body.get("sortBy", "cumulative")  # cumulative, time, calls
        limit = body.get("limit", 30)

        if not code and not file_path:
            return self._error_response("Required: code or filePath")

        try:
            import cProfile
            import pstats
            import io

            if file_path:
                with open(file_path, 'r') as f:
                    code = f.read()

            # Create profiler
            profiler = cProfile.Profile()

            # Execute and profile
            local_vars = {}
            try:
                profiler.enable()
                exec(code, {"__name__": "__main__"}, local_vars)
                profiler.disable()
            except Exception as e:
                profiler.disable()
                return self._error_response(f"Execution error: {e}", 400)

            # Get stats
            stream = io.StringIO()
            stats = pstats.Stats(profiler, stream=stream)

            if sort_by == "time":
                stats.sort_stats("time")
            elif sort_by == "calls":
                stats.sort_stats("calls")
            else:
                stats.sort_stats("cumulative")

            stats.print_stats(limit)
            profile_output = stream.getvalue()

            # Parse into structured data
            functions = []
            for func, (cc, nc, tt, ct, callers) in stats.stats.items():
                file_name, line_no, func_name = func
                functions.append({
                    "function": func_name,
                    "file": file_name,
                    "line": line_no,
                    "calls": nc,
                    "total_time": round(tt, 6),
                    "cumulative_time": round(ct, 6),
                    "time_per_call": round(tt / nc, 6) if nc > 0 else 0,
                })

            # Sort by the requested field
            sort_key = {"time": "total_time", "calls": "calls", "cumulative": "cumulative_time"}.get(sort_by, "cumulative_time")
            functions.sort(key=lambda x: x[sort_key], reverse=True)

            return self._json_response({
                "functions": functions[:limit],
                "total_calls": sum(f["calls"] for f in functions),
                "total_time": round(sum(f["total_time"] for f in functions), 6),
                "raw_output": profile_output,
            })

        except Exception as e:
            return self._error_response(f"Profiling failed: {e}", 500)

    async def handle_memory_profile(self, request: web.Request) -> web.Response:
        """Profile memory usage of Python code."""
        self._request_count += 1
        body = await self._get_json_body(request)

        code = body.get("code")
        if not code:
            return self._error_response("Required: code")

        try:
            import tracemalloc
            import sys

            # Start tracing
            tracemalloc.start()

            # Execute code
            local_vars = {}
            try:
                exec(code, {"__name__": "__main__"}, local_vars)
            except Exception as e:
                tracemalloc.stop()
                return self._error_response(f"Execution error: {e}", 400)

            # Get snapshot
            snapshot = tracemalloc.take_snapshot()
            tracemalloc.stop()

            # Get top memory allocations
            top_stats = snapshot.statistics('lineno')

            allocations = []
            for stat in top_stats[:30]:
                frame = stat.traceback[0] if stat.traceback else None
                allocations.append({
                    "file": frame.filename if frame else "unknown",
                    "line": frame.lineno if frame else 0,
                    "size_bytes": stat.size,
                    "size_human": self._format_bytes(stat.size),
                    "count": stat.count,
                })

            current, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (0, 0)

            return self._json_response({
                "allocations": allocations,
                "total_allocations": len(top_stats),
                "current_memory": self._format_bytes(sum(s.size for s in top_stats)),
                "peak_memory": self._format_bytes(peak),
            })

        except Exception as e:
            return self._error_response(f"Memory profiling failed: {e}", 500)

    def _format_bytes(self, size: int) -> str:
        """Format bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"

    # --- Refactoring handlers ---

    # --- Rope-based Refactoring (Multi-phased) ---
    # Phase 1 (default): Preview - show how many changes will occur
    # Phase 2 (phase=changes): Show the actual changes/diffs
    # Phase 3 (phase=apply): Apply the changes to files

    def _get_rope_project(self, file_path: str = None):
        """Get or create a rope project for refactoring."""
        from rope.base.project import Project
        import os

        # Use workspace as project root
        project_path = self.workspace
        if file_path:
            # Ensure file is within a valid project
            if not file_path.startswith(self.workspace):
                project_path = os.path.dirname(file_path)

        return Project(project_path)

    async def handle_extract_function(self, request: web.Request) -> web.Response:
        """Extract code selection into a new function using rope library.

        Multi-phased refactoring:
        - phase=preview (default): Shows summary of changes that will be made
        - phase=changes: Shows detailed diff of all changes
        - phase=apply: Applies the changes to the file
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        start_line = body.get("startLine")
        end_line = body.get("endLine")
        start_col = body.get("startColumn", 0)
        end_col = body.get("endColumn")
        function_name = body.get("functionName", "extracted_function")
        phase = body.get("phase", "preview")  # preview, changes, apply

        if not file_path:
            return self._error_response("Required: filePath (rope requires file on disk)")
        if not start_line or not end_line:
            return self._error_response("Required: startLine, endLine")

        try:
            from rope.base import libutils
            from rope.refactor.extract import ExtractMethod
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                # Read file content to calculate offsets
                with open(file_path, 'r') as f:
                    content = f.read()
                    lines = content.splitlines(keepends=True)

                # Calculate byte offsets from line/column
                start_offset = sum(len(lines[i]) for i in range(start_line - 1)) + start_col
                if end_col:
                    end_offset = sum(len(lines[i]) for i in range(end_line - 1)) + end_col
                else:
                    end_offset = sum(len(lines[i]) for i in range(end_line))

                # Create extractor
                extractor = ExtractMethod(project, resource, start_offset, end_offset)

                # Get the changes
                changes = extractor.get_changes(function_name)

                # Build response based on phase
                if phase == "preview":
                    # Phase 1: Just show summary
                    changed_files = []
                    for change in changes.get_changed_resources():
                        changed_files.append(os.path.relpath(change.path, self.workspace))

                    return self._json_response({
                        "phase": "preview",
                        "operation": "extract_function",
                        "function_name": function_name,
                        "selection": {"startLine": start_line, "endLine": end_line},
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call again with phase='changes' to see detailed diff, or phase='apply' to execute",
                    })

                elif phase == "changes":
                    # Phase 2: Show detailed changes
                    file_changes = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        new_content = changes.get_changed_contents().get(change, "")

                        # Get original content
                        try:
                            with open(change.path, 'r') as f:
                                old_content = f.read()
                        except:
                            old_content = ""

                        # Simple diff (line-by-line)
                        old_lines = old_content.splitlines()
                        new_lines = new_content.splitlines() if new_content else []

                        file_changes.append({
                            "file": rel_path,
                            "lines_before": len(old_lines),
                            "lines_after": len(new_lines),
                            "new_content": new_content,
                        })

                    return self._json_response({
                        "phase": "changes",
                        "operation": "extract_function",
                        "function_name": function_name,
                        "changes": file_changes,
                        "next_step": "Call again with phase='apply' to execute these changes",
                    })

                elif phase == "apply":
                    # Phase 3: Apply changes with history recording
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        # Read after content
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="extract_function",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"function_name": function_name}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "extract_function",
                        "function_name": function_name,
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": f"Successfully extracted function '{function_name}'",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}. Use 'preview', 'changes', or 'apply'")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Extract function failed: {e}", 500)

    async def handle_extract_variable(self, request: web.Request) -> web.Response:
        """Extract an expression into a variable using rope library.

        Multi-phased refactoring:
        - phase=preview (default): Shows summary of changes
        - phase=changes: Shows detailed diff
        - phase=apply: Applies the changes
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        start_col = body.get("startColumn")
        end_col = body.get("endColumn")
        variable_name = body.get("variableName", "extracted_var")
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath (rope requires file on disk)")
        if not line or not start_col or not end_col:
            return self._error_response("Required: line, startColumn, endColumn")

        try:
            from rope.base import libutils
            from rope.refactor.extract import ExtractVariable
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                # Read file to calculate offsets
                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)

                # Calculate byte offsets
                start_offset = sum(len(lines[i]) for i in range(line - 1)) + (start_col - 1)
                end_offset = sum(len(lines[i]) for i in range(line - 1)) + (end_col - 1)

                # Create extractor
                extractor = ExtractVariable(project, resource, start_offset, end_offset)
                changes = extractor.get_changes(variable_name)

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "extract_variable",
                        "variable_name": variable_name,
                        "selection": {"line": line, "startColumn": start_col, "endColumn": end_col},
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' to see diff, or phase='apply' to execute",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "extract_variable",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="extract_variable",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"variable_name": variable_name}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "extract_variable",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": f"Successfully extracted variable '{variable_name}'",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Extract variable failed: {e}", 500)

    async def handle_inline_variable(self, request: web.Request) -> web.Response:
        """Inline a variable using rope library.

        Multi-phased refactoring:
        - phase=preview: Shows how many usages will be inlined
        - phase=changes: Shows the detailed changes
        - phase=apply: Applies the inlining
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line (where variable is defined)")

        try:
            from rope.base import libutils
            from rope.refactor.inline import create_inline
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                # Calculate offset
                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)

                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                # Create inline refactoring
                inliner = create_inline(project, resource, offset)
                changes = inliner.get_changes()

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "inline_variable",
                        "location": {"line": line, "column": column},
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' to see diff, or phase='apply' to execute",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        with open(change.path, 'r') as f:
                            old_content = f.read()
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "lines_removed": old_content.count('\n') - new_content.count('\n'),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "inline_variable",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="inline_variable",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"line": line, "column": column}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "inline_variable",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": "Successfully inlined variable",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Inline variable failed: {e}", 500)

    async def handle_rename_local(self, request: web.Request) -> web.Response:
        """Rename a symbol using rope library.

        Multi-phased refactoring:
        - phase=preview: Shows how many occurrences and files will change
        - phase=changes: Shows all the changes that will be made
        - phase=apply: Applies the rename
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        new_name = body.get("newName")
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line")
        if not new_name:
            return self._error_response("Required: newName")

        try:
            from rope.base import libutils
            from rope.refactor.rename import Rename
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                # Calculate offset
                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)

                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                # Create rename refactoring
                renamer = Rename(project, resource, offset)

                # Get old name for reference
                old_name = renamer.get_old_name()

                changes = renamer.get_changes(new_name)

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]

                    # Count occurrences by analyzing changes
                    total_occurrences = 0
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        # Count how many times new_name appears (rough estimate)
                        total_occurrences += new_content.count(new_name)

                    return self._json_response({
                        "phase": "preview",
                        "operation": "rename",
                        "old_name": old_name,
                        "new_name": new_name,
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "estimated_occurrences": total_occurrences,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' to see all changes, or phase='apply' to execute",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        new_content = changes.get_changed_contents().get(change, "")

                        try:
                            with open(change.path, 'r') as f:
                                old_content = f.read()
                        except:
                            old_content = ""

                        # Find changed lines
                        old_lines = old_content.splitlines()
                        new_lines = new_content.splitlines()

                        changed_line_numbers = []
                        for i, (old, new) in enumerate(zip(old_lines, new_lines)):
                            if old != new:
                                changed_line_numbers.append(i + 1)

                        file_changes.append({
                            "file": rel_path,
                            "changed_lines": changed_line_numbers,
                            "change_count": len(changed_line_numbers),
                            "new_content": new_content,
                        })

                    return self._json_response({
                        "phase": "changes",
                        "operation": "rename",
                        "old_name": old_name,
                        "new_name": new_name,
                        "changes": file_changes,
                        "total_files": len(file_changes),
                        "next_step": "Call with phase='apply' to execute these changes",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="rename_local",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"old_name": old_name, "new_name": new_name}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "rename",
                        "old_name": old_name,
                        "new_name": new_name,
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": f"Successfully renamed '{old_name}' to '{new_name}' across {len(applied_files)} file(s)",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}. Use 'preview', 'changes', or 'apply'")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Rename failed: {e}", 500)

    async def handle_move(self, request: web.Request) -> web.Response:
        """Move a module, class, function, or method to another location.

        Multi-phased refactoring:
        - phase=preview: Shows what will be moved and affected files
        - phase=changes: Shows detailed changes
        - phase=apply: Applies the move
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        destination = body.get("destination")  # Target module path or class
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not destination:
            return self._error_response("Required: destination (target module or class)")

        try:
            from rope.base import libutils
            from rope.refactor.move import create_move
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                # Calculate offset if line provided
                offset = None
                if line:
                    with open(file_path, 'r') as f:
                        lines = f.read().splitlines(keepends=True)
                    offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                # Create move refactoring
                mover = create_move(project, resource, offset)

                # Get destination resource
                dest_resource = libutils.path_to_resource(project, destination)
                changes = mover.get_changes(dest_resource)

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "move",
                        "destination": destination,
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "move",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="move",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"destination": destination}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "move",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": f"Successfully moved to {destination}",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Move failed: {e}", 500)

    async def handle_change_signature(self, request: web.Request) -> web.Response:
        """Change a function's signature (add/remove/reorder parameters).

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        new_signature = body.get("newSignature")  # List of parameter definitions
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line (function definition line)")
        if not new_signature:
            return self._error_response("Required: newSignature (list of parameter defs)")

        try:
            from rope.base import libutils
            from rope.refactor.change_signature import ChangeSignature, ArgumentNormalizer
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                changer = ChangeSignature(project, resource, offset)

                # Get current signature info
                signature_info = changer.get_args()

                # Apply new signature
                changes = changer.get_changes(ArgumentNormalizer(new_signature))

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "change_signature",
                        "current_args": signature_info,
                        "new_signature": new_signature,
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "change_signature",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="change_signature",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"new_signature": new_signature}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "change_signature",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": "Successfully changed function signature",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Change signature failed: {e}", 500)

    async def handle_introduce_parameter(self, request: web.Request) -> web.Response:
        """Add a new parameter to a function, replacing a value with the parameter.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        parameter_name = body.get("parameterName")
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line (position of value to parameterize)")
        if not parameter_name:
            return self._error_response("Required: parameterName")

        try:
            from rope.base import libutils
            from rope.refactor.introduce_parameter import IntroduceParameter
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                introducer = IntroduceParameter(project, resource, offset)
                changes = introducer.get_changes(parameter_name)

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "introduce_parameter",
                        "parameter_name": parameter_name,
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "introduce_parameter",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="introduce_parameter",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"parameter_name": parameter_name}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "introduce_parameter",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": f"Successfully introduced parameter '{parameter_name}'",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Introduce parameter failed: {e}", 500)

    async def handle_introduce_factory(self, request: web.Request) -> web.Response:
        """Replace constructor calls with a factory method.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        factory_name = body.get("factoryName", "create")
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line (class definition line)")

        try:
            from rope.base import libutils
            from rope.refactor.introduce_factory import IntroduceFactory
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                introducer = IntroduceFactory(project, resource, offset)
                changes = introducer.get_changes(factory_name)

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "introduce_factory",
                        "factory_name": factory_name,
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "introduce_factory",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="introduce_factory",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"factory_name": factory_name}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "introduce_factory",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": f"Successfully introduced factory method '{factory_name}'",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Introduce factory failed: {e}", 500)

    async def handle_encapsulate_field(self, request: web.Request) -> web.Response:
        """Create getter/setter methods for a field (encapsulation).

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        getter_name = body.get("getterName")  # Optional, will be auto-generated
        setter_name = body.get("setterName")  # Optional, will be auto-generated
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line (field definition)")

        try:
            from rope.base import libutils
            from rope.refactor.encapsulate_field import EncapsulateField
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                encapsulator = EncapsulateField(project, resource, offset)
                changes = encapsulator.get_changes(getter=getter_name, setter=setter_name)

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "encapsulate_field",
                        "getter_name": getter_name or "(auto-generated)",
                        "setter_name": setter_name or "(auto-generated)",
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "encapsulate_field",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="encapsulate_field",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"getter_name": getter_name, "setter_name": setter_name}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "encapsulate_field",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": "Successfully encapsulated field with getter/setter",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Encapsulate field failed: {e}", 500)

    async def handle_local_to_field(self, request: web.Request) -> web.Response:
        """Promote a local variable to an instance field.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line (local variable position)")

        try:
            from rope.base import libutils
            from rope.refactor.localtofield import LocalToField
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                converter = LocalToField(project, resource, offset)
                changes = converter.get_changes()

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "local_to_field",
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "local_to_field",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="local_to_field",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"line": line, "column": column}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "local_to_field",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": "Successfully promoted local variable to field",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Local to field failed: {e}", 500)

    async def handle_method_to_object(self, request: web.Request) -> web.Response:
        """Convert a method with complex local state to a method object (functor).

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        class_name = body.get("className")  # Name for the new class
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line (method definition)")

        try:
            from rope.base import libutils
            from rope.refactor.method_object import MethodObject
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                converter = MethodObject(project, resource, offset)
                changes = converter.get_changes(class_name)

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "method_to_object",
                        "class_name": class_name,
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "method_to_object",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="method_to_object",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"class_name": class_name}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "method_to_object",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": f"Successfully converted method to class '{class_name}'",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Method to object failed: {e}", 500)

    async def handle_use_function(self, request: web.Request) -> web.Response:
        """Replace code with calls to an existing function that does the same thing.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        phase = body.get("phase", "preview")

        if not file_path:
            return self._error_response("Required: filePath")
        if not line:
            return self._error_response("Required: line (function to use)")

        try:
            from rope.base import libutils
            from rope.refactor.usefunction import UseFunction
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                user = UseFunction(project, resource, offset)
                changes = user.get_changes()

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "use_function",
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "use_function",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="use_function",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"line": line}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "use_function",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": "Successfully replaced code with function calls",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Use function failed: {e}", 500)

    async def handle_restructure(self, request: web.Request) -> web.Response:
        """Pattern-based code restructuring (search and replace with AST awareness).

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        pattern = body.get("pattern")  # Pattern to match (e.g., "${x}.append(${y})")
        goal = body.get("goal")  # Replacement pattern (e.g., "${x} += [${y}]")
        imports = body.get("imports", [])  # Additional imports needed
        phase = body.get("phase", "preview")

        if not pattern:
            return self._error_response("Required: pattern (e.g., '${x}.append(${y})')")
        if not goal:
            return self._error_response("Required: goal (e.g., '${x} += [${y}]')")

        try:
            from rope.refactor.restructure import Restructure
            import os

            project = self._get_rope_project()
            try:
                restructurer = Restructure(project, pattern, goal)

                # Add any required imports
                for imp in imports:
                    restructurer.add_import(imp)

                changes = restructurer.get_changes()

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "restructure",
                        "pattern": pattern,
                        "goal": goal,
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                        "next_step": "Call with phase='changes' or phase='apply'",
                    })

                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({
                            "file": os.path.relpath(change.path, self.workspace),
                            "new_content": new_content,
                        })
                    return self._json_response({
                        "phase": "changes",
                        "operation": "restructure",
                        "changes": file_changes,
                        "next_step": "Call with phase='apply' to execute",
                    })

                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="restructure",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"pattern": pattern, "goal": goal}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "operation": "restructure",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": "Successfully restructured code",
                    })

                else:
                    return self._error_response(f"Invalid phase: {phase}")

            finally:
                project.close()

        except ImportError:
            return self._error_response("rope not installed. Install with: pip install rope", 500)
        except Exception as e:
            return self._error_response(f"Restructure failed: {e}", 500)

    # --- Inheritance Refactoring (AST-based) ---

    async def handle_extract_superclass(self, request: web.Request) -> web.Response:
        """Extract a superclass from a class, moving selected members to it.

        Multi-phased refactoring:
        - preview: Show what will be extracted
        - changes: Show the new superclass and modified subclass
        - apply: Create the superclass and update the class
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        new_class_name = body.get("newClassName")
        members = body.get("members", [])  # List of method/attribute names to extract
        phase = body.get("phase", "preview")

        if not file_path or not class_name or not new_class_name:
            return self._error_response("Required: filePath, className, newClassName")
        if not members:
            return self._error_response("Required: members (list of method/attribute names to extract)")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found in {file_path}")

            # Find members to extract
            extracted_members = []
            remaining_members = []
            member_sources = {}

            lines = source.splitlines(keepends=True)

            for item in target_class.body:
                item_name = None
                if isinstance(item, ast.FunctionDef):
                    item_name = item.name
                elif isinstance(item, ast.AsyncFunctionDef):
                    item_name = item.name
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            item_name = target.id
                            break
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    item_name = item.target.id

                if item_name and item_name in members:
                    extracted_members.append(item)
                    # Get source lines for this member
                    start_line = item.lineno - 1
                    end_line = item.end_lineno
                    member_source = "".join(lines[start_line:end_line])
                    member_sources[item_name] = member_source
                elif item_name:
                    remaining_members.append(item)

            if not extracted_members:
                return self._error_response(f"No matching members found. Available: {[m.name if hasattr(m, 'name') else str(m) for m in target_class.body if hasattr(m, 'name')]}")

            if phase == "preview":
                extracted_names = [m.name if hasattr(m, "name") else "attribute" for m in extracted_members]
                return self._json_response({
                    "phase": "preview",
                    "operation": "extract_superclass",
                    "source_class": class_name,
                    "new_superclass": new_class_name,
                    "members_to_extract": extracted_names,
                    "members_remaining": [m.name if hasattr(m, "name") else "attribute" for m in remaining_members],
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' to see diff, or phase='apply' to execute",
                })

            # Build the new superclass
            indent = "    "
            superclass_lines = [f"class {new_class_name}:"]
            if not extracted_members:
                superclass_lines.append(f"{indent}pass")
            else:
                for name in members:
                    if name in member_sources:
                        superclass_lines.append(member_sources[name].rstrip())

            new_superclass_code = "\n".join(superclass_lines) + "\n\n"

            # Modify the original class to inherit from the new superclass
            # and remove the extracted members
            new_bases = [new_class_name]
            for base in target_class.bases:
                if isinstance(base, ast.Name):
                    new_bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    new_bases.append(ast.unparse(base))

            # Build new class definition
            class_start = target_class.lineno - 1
            class_header_end = target_class.body[0].lineno - 1 if target_class.body else class_start + 1

            # Get decorators if any
            decorator_start = target_class.decorator_list[0].lineno - 1 if target_class.decorator_list else class_start

            # Build new source
            new_lines = lines[:decorator_start]

            # Add new superclass before the class
            new_lines.append(new_superclass_code)

            # Rebuild class header with new base
            bases_str = ", ".join(new_bases)
            new_lines.append(f"class {class_name}({bases_str}):\n")

            # Add remaining members
            remaining_added = False
            for item in target_class.body:
                item_name = None
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    item_name = item.name
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            item_name = target.id
                            break
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    item_name = item.target.id

                if item_name not in members:
                    start_line = item.lineno - 1
                    end_line = item.end_lineno
                    new_lines.extend(lines[start_line:end_line])
                    remaining_added = True

            if not remaining_added:
                new_lines.append(f"{indent}pass\n")

            # Add rest of file after the class
            new_lines.extend(lines[target_class.end_lineno:])

            new_source = "".join(new_lines)

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "extract_superclass",
                    "new_superclass": new_class_name,
                    "new_content": new_source,
                    "next_step": "Call with phase='apply' to execute",
                })

            elif phase == "apply":
                with open(file_path, "w") as f:
                    f.write(new_source)
                # Record history
                history_id = self._record_file_change(
                    action="extract_superclass",
                    file_path=file_path,
                    before_content=source,
                    after_content=new_source,
                    metadata={"class_name": class_name, "new_class_name": new_class_name, "members": members}
                )
                return self._json_response({
                    "phase": "apply",
                    "operation": "extract_superclass",
                    "success": True,
                    "history_id": history_id,
                    "message": f"Created superclass {new_class_name} and updated {class_name}",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Extract superclass failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_pull_up_member(self, request: web.Request) -> web.Response:
        """Pull a member (method/attribute) from a subclass up to its parent class.

        Uses LSP for cross-file resolution - can find parent classes in any file.
        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")  # Subclass containing the member
        member_name = body.get("memberName")  # Method/attribute to pull up
        parent_class = body.get("parentClass")  # Target parent class (optional, uses first base if not specified)
        phase = body.get("phase", "preview")

        if not file_path or not class_name or not member_name:
            return self._error_response("Required: filePath, className, memberName")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the subclass
            subclass = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    subclass = node
                    break

            if not subclass:
                return self._error_response(f"Class '{class_name}' not found")

            # Find the member to pull up
            member_node = None
            member_source = ""
            for item in subclass.body:
                item_name = None
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    item_name = item.name
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            item_name = target.id
                            break
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    item_name = item.target.id

                if item_name == member_name:
                    member_node = item
                    start_line = item.lineno - 1
                    end_line = item.end_lineno
                    member_source = "".join(lines[start_line:end_line])
                    break

            if not member_node:
                return self._error_response(f"Member '{member_name}' not found in class '{class_name}'")

            # Determine parent class and find its location using LSP
            if not subclass.bases:
                return self._error_response(f"Class '{class_name}' has no base classes")

            # Get the first base class (or the specified one)
            target_base = None
            target_base_name = parent_class
            for base in subclass.bases:
                base_name = None
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr

                if not parent_class:
                    # Use first base
                    target_base = base
                    target_base_name = base_name
                    break
                elif base_name == parent_class:
                    target_base = base
                    break

            if not target_base:
                return self._error_response(f"Base class '{parent_class}' not found in class definition")

            # Use LSP to find the parent class definition (cross-file!)
            await self._ensure_indexed(file_path)
            base_line = target_base.lineno
            base_col = target_base.col_offset + 1  # LSP is 1-indexed

            definition_result = await self.lsp_client.get_definition(file_path, base_line, base_col)

            parent_file = None
            parent_line = None

            if definition_result:
                if isinstance(definition_result, list) and len(definition_result) > 0:
                    loc = definition_result[0]
                else:
                    loc = definition_result

                # Extract file path from LSP result
                if hasattr(loc, 'uri'):
                    parent_file = loc.uri.replace('file://', '')
                elif isinstance(loc, dict) and 'uri' in loc:
                    parent_file = loc['uri'].replace('file://', '')
                elif isinstance(loc, dict) and 'targetUri' in loc:
                    parent_file = loc['targetUri'].replace('file://', '')

                # Extract line from LSP result
                if hasattr(loc, 'range'):
                    parent_line = loc.range.start.line + 1
                elif isinstance(loc, dict) and 'range' in loc:
                    parent_line = loc['range']['start']['line'] + 1
                elif isinstance(loc, dict) and 'targetRange' in loc:
                    parent_line = loc['targetRange']['start']['line'] + 1

            if not parent_file:
                # Fallback: try same file
                parent_file = file_path

            # Read parent file and find the class
            if parent_file == file_path:
                parent_source = source
                parent_lines = lines
                parent_tree = tree
            else:
                with open(parent_file, "r") as f:
                    parent_source = f.read()
                parent_tree = ast.parse(parent_source)
                parent_lines = parent_source.splitlines(keepends=True)

            parent_node = None
            for node in ast.walk(parent_tree):
                if isinstance(node, ast.ClassDef) and node.name == target_base_name:
                    parent_node = node
                    break

            if not parent_node:
                return self._error_response(f"Parent class '{target_base_name}' not found in {parent_file}")

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "pull_up_member",
                    "member": member_name,
                    "from_class": class_name,
                    "to_class": target_base_name,
                    "from_file": os.path.basename(file_path),
                    "to_file": os.path.basename(parent_file),
                    "same_file": parent_file == file_path,
                    "lsp_resolved": parent_file != file_path,  # Shows if LSP found cross-file
                    "next_step": "Call with phase='changes' to see diff, or phase='apply' to execute",
                })

            # Build new parent class with the member added
            # Insert after the last existing member or after class header
            if parent_node.body:
                insert_after_line = parent_node.body[-1].end_lineno
            else:
                insert_after_line = parent_node.lineno

            new_parent_lines = parent_lines[:insert_after_line]
            new_parent_lines.append("\n" + member_source)
            new_parent_lines.extend(parent_lines[insert_after_line:])
            new_parent_source = "".join(new_parent_lines)

            # Remove member from subclass
            member_start = member_node.lineno - 1
            member_end = member_node.end_lineno
            new_sub_lines = lines[:member_start] + lines[member_end:]

            # Check if class body is now empty
            remaining_body = [item for item in subclass.body if item != member_node]
            if not remaining_body:
                # Add pass statement
                class_body_start = subclass.body[0].lineno - 1 if subclass.body else subclass.lineno
                new_sub_lines = lines[:class_body_start]
                new_sub_lines.append("    pass\n")
                new_sub_lines.extend(lines[member_end:])

            new_sub_source = "".join(new_sub_lines)

            if phase == "changes":
                result = {
                    "phase": "changes",
                    "operation": "pull_up_member",
                    "member": member_name,
                }
                if parent_file == file_path:
                    # Need to handle both changes in same file
                    result["combined_changes"] = {
                        "file": os.path.basename(file_path),
                        "description": f"Add {member_name} to {target_base_name} and remove from {class_name}",
                    }
                else:
                    result["parent_file"] = {
                        "file": os.path.basename(parent_file),
                        "new_content": new_parent_source,
                    }
                    result["subclass_file"] = {
                        "file": os.path.basename(file_path),
                        "new_content": new_sub_source,
                    }
                result["next_step"] = "Call with phase='apply' to execute"
                return self._json_response(result)

            elif phase == "apply":
                history_ids = []
                if parent_file == file_path:
                    # Both classes in same file - need careful handling
                    # Re-parse and apply both changes
                    with open(file_path, "r") as f:
                        before_source = f.read()

                    tree = ast.parse(before_source)
                    lines = before_source.splitlines(keepends=True)

                    # Find both classes again
                    parent_node = None
                    subclass_node = None
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            if node.name == target_base_name:
                                parent_node = node
                            elif node.name == class_name:
                                subclass_node = node

                    # Get member source from subclass
                    member_node = None
                    for item in subclass_node.body:
                        item_name = getattr(item, "name", None)
                        if not item_name and isinstance(item, ast.Assign):
                            for t in item.targets:
                                if isinstance(t, ast.Name):
                                    item_name = t.id
                                    break
                        if item_name == member_name:
                            member_node = item
                            member_source = "".join(lines[item.lineno-1:item.end_lineno])
                            break

                    # Determine which class comes first
                    if parent_node.lineno < subclass_node.lineno:
                        # Parent first - add to parent, then remove from subclass
                        insert_line = parent_node.body[-1].end_lineno if parent_node.body else parent_node.lineno
                        remove_start = member_node.lineno - 1
                        remove_end = member_node.end_lineno

                        new_lines = lines[:insert_line]
                        new_lines.append("\n" + member_source)
                        new_lines.extend(lines[insert_line:remove_start])
                        new_lines.extend(lines[remove_end:])
                    else:
                        # Subclass first - remove from subclass, then add to parent
                        remove_start = member_node.lineno - 1
                        remove_end = member_node.end_lineno
                        insert_line = parent_node.body[-1].end_lineno if parent_node.body else parent_node.lineno

                        new_lines = lines[:remove_start]
                        new_lines.extend(lines[remove_end:insert_line])
                        new_lines.append("\n" + member_source)
                        new_lines.extend(lines[insert_line:])

                    after_source = "".join(new_lines)
                    with open(file_path, "w") as f:
                        f.write(after_source)
                    # Record history
                    history_ids.append(self._record_file_change(
                        action="pull_up_member",
                        file_path=file_path,
                        before_content=before_source,
                        after_content=after_source,
                        metadata={"class_name": class_name, "member_name": member_name, "target_class": target_base_name}
                    ))
                else:
                    # Different files - read before content
                    with open(parent_file, "r") as f:
                        before_parent = f.read()
                    with open(file_path, "r") as f:
                        before_sub = f.read()
                    # Write changes
                    with open(parent_file, "w") as f:
                        f.write(new_parent_source)
                    with open(file_path, "w") as f:
                        f.write(new_sub_source)
                    # Record history for both files
                    history_ids.append(self._record_file_change(
                        action="pull_up_member",
                        file_path=parent_file,
                        before_content=before_parent,
                        after_content=new_parent_source,
                        metadata={"class_name": target_base_name, "member_name": member_name, "operation": "add_member"}
                    ))
                    history_ids.append(self._record_file_change(
                        action="pull_up_member",
                        file_path=file_path,
                        before_content=before_sub,
                        after_content=new_sub_source,
                        metadata={"class_name": class_name, "member_name": member_name, "operation": "remove_member"}
                    ))

                return self._json_response({
                    "phase": "apply",
                    "operation": "pull_up_member",
                    "success": True,
                    "history_ids": history_ids,
                    "message": f"Pulled '{member_name}' from {class_name} up to {target_base_name}",
                    "parent_file": parent_file,
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Pull up member failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_push_down_member(self, request: web.Request) -> web.Response:
        """Push a member (method/attribute) from a parent class down to subclass(es).

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")  # Parent class containing the member
        member_name = body.get("memberName")  # Method/attribute to push down
        target_subclasses = body.get("targetSubclasses", [])  # Specific subclasses (optional, all if not specified)
        scan_directory = body.get("scanDirectory")  # Where to look for subclasses
        phase = body.get("phase", "preview")

        if not file_path or not class_name or not member_name:
            return self._error_response("Required: filePath, className, memberName")

        try:
            import ast
            import os
            from pathlib import Path

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the parent class
            parent_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    parent_class = node
                    break

            if not parent_class:
                return self._error_response(f"Class '{class_name}' not found")

            # Find the member
            member_node = None
            member_source = ""
            for item in parent_class.body:
                item_name = None
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    item_name = item.name
                elif isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            item_name = target.id
                            break
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    item_name = item.target.id

                if item_name == member_name:
                    member_node = item
                    start_line = item.lineno - 1
                    end_line = item.end_lineno
                    member_source = "".join(lines[start_line:end_line])
                    break

            if not member_node:
                return self._error_response(f"Member '{member_name}' not found in class '{class_name}'")

            # Find subclasses
            scan_dir = scan_directory or self.workspace
            subclasses = []

            for py_file in Path(scan_dir).rglob("*.py"):
                try:
                    with open(py_file, "r") as f:
                        file_source = f.read()
                    file_tree = ast.parse(file_source)

                    for node in ast.walk(file_tree):
                        if isinstance(node, ast.ClassDef):
                            for base in node.bases:
                                base_name = None
                                if isinstance(base, ast.Name):
                                    base_name = base.id
                                elif isinstance(base, ast.Attribute):
                                    base_name = base.attr

                                if base_name == class_name:
                                    if not target_subclasses or node.name in target_subclasses:
                                        subclasses.append({
                                            "name": node.name,
                                            "file": str(py_file),
                                            "line": node.lineno,
                                        })
                except Exception:
                    continue

            if not subclasses:
                return self._error_response(f"No subclasses of '{class_name}' found")

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "push_down_member",
                    "member": member_name,
                    "from_class": class_name,
                    "to_subclasses": [s["name"] for s in subclasses],
                    "files_affected": list(set(s["file"] for s in subclasses)) + [file_path],
                    "next_step": "Call with phase='changes' to see diff, or phase='apply' to execute",
                })

            elif phase == "changes":
                changes = []
                for sub in subclasses:
                    changes.append({
                        "file": os.path.basename(sub["file"]),
                        "class": sub["name"],
                        "action": f"Add {member_name}",
                    })
                changes.append({
                    "file": os.path.basename(file_path),
                    "class": class_name,
                    "action": f"Remove {member_name}",
                })
                return self._json_response({
                    "phase": "changes",
                    "operation": "push_down_member",
                    "changes": changes,
                    "member_source": member_source,
                    "next_step": "Call with phase='apply' to execute",
                })

            elif phase == "apply":
                # Add member to each subclass
                modified_files = set()
                for sub in subclasses:
                    with open(sub["file"], "r") as f:
                        sub_source = f.read()
                    sub_tree = ast.parse(sub_source)
                    sub_lines = sub_source.splitlines(keepends=True)

                    # Find the subclass
                    for node in ast.walk(sub_tree):
                        if isinstance(node, ast.ClassDef) and node.name == sub["name"]:
                            # Insert at end of class body
                            if node.body:
                                insert_line = node.body[-1].end_lineno
                            else:
                                insert_line = node.lineno

                            new_sub_lines = sub_lines[:insert_line]
                            new_sub_lines.append("\n" + member_source)
                            new_sub_lines.extend(sub_lines[insert_line:])

                            with open(sub["file"], "w") as f:
                                f.write("".join(new_sub_lines))
                            modified_files.add(sub["file"])
                            break

                # Remove member from parent class
                member_start = member_node.lineno - 1
                member_end = member_node.end_lineno
                new_lines = lines[:member_start] + lines[member_end:]

                # Check if class body is now empty
                remaining = [item for item in parent_class.body if item != member_node]
                if not remaining:
                    new_lines = lines[:member_start]
                    new_lines.append("    pass\n")
                    new_lines.extend(lines[member_end:])

                with open(file_path, "w") as f:
                    f.write("".join(new_lines))
                modified_files.add(file_path)

                return self._json_response({
                    "phase": "apply",
                    "operation": "push_down_member",
                    "success": True,
                    "message": f"Pushed '{member_name}' from {class_name} down to {len(subclasses)} subclass(es)",
                    "modified_files": list(modified_files),
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Push down member failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_extract_protocol(self, request: web.Request) -> web.Response:
        """Extract a typing.Protocol from a class's methods.

        Creates a Protocol interface that the class implicitly implements.
        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        protocol_name = body.get("protocolName")
        methods = body.get("methods", [])  # Methods to include (empty = all public methods)
        phase = body.get("phase", "preview")

        if not file_path or not class_name or not protocol_name:
            return self._error_response("Required: filePath, className, protocolName")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found")

            # Find methods to include in protocol
            protocol_methods = []
            for item in target_class.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Skip private methods unless explicitly requested
                    if not methods and item.name.startswith("_"):
                        continue
                    if methods and item.name not in methods:
                        continue

                    # Extract method signature
                    args = []
                    for arg in item.args.args:
                        arg_str = arg.arg
                        if arg.annotation:
                            arg_str += f": {ast.unparse(arg.annotation)}"
                        args.append(arg_str)

                    returns = ""
                    if item.returns:
                        returns = f" -> {ast.unparse(item.returns)}"

                    is_async = isinstance(item, ast.AsyncFunctionDef)
                    async_prefix = "async " if is_async else ""

                    protocol_methods.append({
                        "name": item.name,
                        "signature": f"{async_prefix}def {item.name}({', '.join(args)}){returns}: ...",
                        "docstring": ast.get_docstring(item),
                    })

            if not protocol_methods:
                return self._error_response(f"No public methods found in class '{class_name}'")

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "extract_protocol",
                    "source_class": class_name,
                    "protocol_name": protocol_name,
                    "methods": [m["name"] for m in protocol_methods],
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' to see the protocol, or phase='apply' to create it",
                })

            # Build the Protocol class
            indent = "    "
            protocol_lines = [
                "from typing import Protocol",
                "",
                "",
                f"class {protocol_name}(Protocol):",
            ]

            if not protocol_methods:
                protocol_lines.append(f"{indent}pass")
            else:
                for method in protocol_methods:
                    if method["docstring"]:
                        protocol_lines.append(f'{indent}{method["signature"]}')
                        # Add docstring
                        doc_lines = method["docstring"].split("\n")
                        if len(doc_lines) == 1:
                            protocol_lines.append(f'{indent}{indent}"""{doc_lines[0]}"""')
                        else:
                            protocol_lines.append(f'{indent}{indent}"""')
                            for line in doc_lines:
                                protocol_lines.append(f'{indent}{indent}{line}')
                            protocol_lines.append(f'{indent}{indent}"""')
                        protocol_lines.append("")
                    else:
                        protocol_lines.append(f'{indent}{method["signature"]}')

            protocol_code = "\n".join(protocol_lines) + "\n\n"

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "extract_protocol",
                    "protocol_code": protocol_code,
                    "next_step": "Call with phase='apply' to add the Protocol to the file",
                })

            elif phase == "apply":
                # Check if typing import exists
                has_typing_import = False
                has_protocol_import = False
                import_line = 0

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == "typing":
                        has_typing_import = True
                        import_line = node.lineno
                        if any(alias.name == "Protocol" for alias in node.names):
                            has_protocol_import = True
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == "typing":
                                has_typing_import = True
                                import_line = node.lineno

                # Find where to insert the Protocol (before the class)
                insert_line = target_class.lineno - 1
                if target_class.decorator_list:
                    insert_line = target_class.decorator_list[0].lineno - 1

                new_lines = []

                # Add Protocol import if needed
                if not has_protocol_import:
                    if has_typing_import:
                        # Modify existing import
                        for i, line in enumerate(lines):
                            if i == import_line - 1:
                                # Add Protocol to existing import
                                if "from typing import" in line:
                                    line = line.rstrip().rstrip(")").rstrip()
                                    if line.endswith(","):
                                        new_lines.append(line + " Protocol\n")
                                    else:
                                        new_lines.append(line + ", Protocol\n")
                                else:
                                    new_lines.append(line)
                            else:
                                new_lines.append(line)
                    else:
                        # Add new import at top
                        new_lines.append("from typing import Protocol\n")
                        new_lines.extend(lines)
                else:
                    new_lines = list(lines)

                # Insert Protocol class
                protocol_without_import = "\n".join(protocol_lines[3:]) + "\n\n"  # Skip import lines
                new_lines.insert(insert_line, protocol_without_import)

                with open(file_path, "w") as f:
                    f.write("".join(new_lines))

                return self._json_response({
                    "phase": "apply",
                    "operation": "extract_protocol",
                    "success": True,
                    "message": f"Created Protocol '{protocol_name}' from class '{class_name}'",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Extract protocol failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_add_base_class(self, request: web.Request) -> web.Response:
        """Add a base class to an existing class.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        base_class = body.get("baseClass")
        position = body.get("position", "first")  # "first" or "last" in the bases list
        phase = body.get("phase", "preview")

        if not file_path or not class_name or not base_class:
            return self._error_response("Required: filePath, className, baseClass")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found")

            # Get current bases
            current_bases = []
            for base in target_class.bases:
                if isinstance(base, ast.Name):
                    current_bases.append(base.id)
                else:
                    current_bases.append(ast.unparse(base))

            if base_class in current_bases:
                return self._error_response(f"Class '{class_name}' already inherits from '{base_class}'")

            # Build new bases list
            if position == "first":
                new_bases = [base_class] + current_bases
            else:
                new_bases = current_bases + [base_class]

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "add_base_class",
                    "class": class_name,
                    "adding_base": base_class,
                    "current_bases": current_bases,
                    "new_bases": new_bases,
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                })

            # Build new class header
            bases_str = ", ".join(new_bases)
            keywords = []
            for kw in target_class.keywords:
                keywords.append(f"{kw.arg}={ast.unparse(kw.value)}")

            if keywords:
                class_header = f"class {class_name}({bases_str}, {', '.join(keywords)}):\n"
            else:
                class_header = f"class {class_name}({bases_str}):\n"

            # Find the class header line
            class_line = target_class.lineno - 1

            # Get everything before class header (including decorators)
            decorator_start = target_class.decorator_list[0].lineno - 1 if target_class.decorator_list else class_line
            prefix = lines[:decorator_start]

            # Add decorators if any
            for dec in target_class.decorator_list:
                dec_source = "".join(lines[dec.lineno-1:dec.end_lineno])
                prefix.append(dec_source)

            # Add new class header
            prefix.append(class_header)

            # Add class body
            body_start = target_class.body[0].lineno - 1 if target_class.body else class_line + 1
            suffix = lines[body_start:]

            new_source = "".join(prefix) + "".join(suffix)

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "add_base_class",
                    "new_class_header": class_header.strip(),
                    "next_step": "Call with phase='apply' to execute",
                })

            elif phase == "apply":
                with open(file_path, "w") as f:
                    f.write(new_source)
                return self._json_response({
                    "phase": "apply",
                    "operation": "add_base_class",
                    "success": True,
                    "message": f"Added '{base_class}' as base class of '{class_name}'",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Add base class failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_remove_base_class(self, request: web.Request) -> web.Response:
        """Remove a base class from an existing class.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        base_class = body.get("baseClass")
        phase = body.get("phase", "preview")

        if not file_path or not class_name or not base_class:
            return self._error_response("Required: filePath, className, baseClass")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found")

            # Get current bases
            current_bases = []
            for base in target_class.bases:
                if isinstance(base, ast.Name):
                    current_bases.append(base.id)
                else:
                    current_bases.append(ast.unparse(base))

            if base_class not in current_bases:
                return self._error_response(f"Class '{class_name}' doesn't inherit from '{base_class}'")

            # Build new bases list
            new_bases = [b for b in current_bases if b != base_class]

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "remove_base_class",
                    "class": class_name,
                    "removing_base": base_class,
                    "current_bases": current_bases,
                    "new_bases": new_bases,
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                })

            # Build new class header
            keywords = []
            for kw in target_class.keywords:
                keywords.append(f"{kw.arg}={ast.unparse(kw.value)}")

            if new_bases or keywords:
                parts = new_bases + keywords
                class_header = f"class {class_name}({', '.join(parts)}):\n"
            else:
                class_header = f"class {class_name}:\n"

            # Find the class header line
            class_line = target_class.lineno - 1

            # Get everything before class header (including decorators)
            decorator_start = target_class.decorator_list[0].lineno - 1 if target_class.decorator_list else class_line
            prefix = lines[:decorator_start]

            # Add decorators if any
            for dec in target_class.decorator_list:
                dec_source = "".join(lines[dec.lineno-1:dec.end_lineno])
                prefix.append(dec_source)

            # Add new class header
            prefix.append(class_header)

            # Add class body
            body_start = target_class.body[0].lineno - 1 if target_class.body else class_line + 1
            suffix = lines[body_start:]

            new_source = "".join(prefix) + "".join(suffix)

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "remove_base_class",
                    "new_class_header": class_header.strip(),
                    "next_step": "Call with phase='apply' to execute",
                })

            elif phase == "apply":
                with open(file_path, "w") as f:
                    f.write(new_source)
                return self._json_response({
                    "phase": "apply",
                    "operation": "remove_base_class",
                    "success": True,
                    "message": f"Removed '{base_class}' from base classes of '{class_name}'",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Remove base class failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_implement_methods(self, request: web.Request) -> web.Response:
        """Generate stub implementations for abstract/interface methods.

        Finds unimplemented abstract methods from base classes and generates stubs.
        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        methods = body.get("methods", [])  # Specific methods, or empty for all
        raise_not_implemented = body.get("raiseNotImplemented", False)
        phase = body.get("phase", "preview")

        if not file_path or not class_name:
            return self._error_response("Required: filePath, className")

        try:
            import ast
            import os
            import inspect as py_inspect

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found")

            # Get existing method names
            existing_methods = set()
            for item in target_class.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    existing_methods.add(item.name)

            # Find abstract methods from base classes
            abstract_methods = []
            lsp_resolved_bases = []

            # Helper to extract abstract methods from a class node
            def extract_abstract_methods(base_node, base_name):
                found = []
                for item in base_node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Check if it's abstract (has @abstractmethod or body is just ...)
                        is_abstract = False
                        for dec in item.decorator_list:
                            if isinstance(dec, ast.Name) and dec.id == "abstractmethod":
                                is_abstract = True
                            elif isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod":
                                is_abstract = True

                        # Also check if body is just ... or pass or raise NotImplementedError
                        if len(item.body) == 1:
                            body_item = item.body[0]
                            if isinstance(body_item, ast.Expr) and isinstance(body_item.value, ast.Constant):
                                if body_item.value.value is ...:
                                    is_abstract = True
                            elif isinstance(body_item, ast.Pass):
                                is_abstract = True
                            elif isinstance(body_item, ast.Raise):
                                is_abstract = True

                        if is_abstract and item.name not in existing_methods:
                            if not methods or item.name in methods:
                                # Extract signature
                                args = []
                                for arg in item.args.args:
                                    arg_str = arg.arg
                                    if arg.annotation:
                                        arg_str += f": {ast.unparse(arg.annotation)}"
                                    args.append(arg_str)

                                returns = ""
                                if item.returns:
                                    returns = f" -> {ast.unparse(item.returns)}"

                                is_async_method = isinstance(item, ast.AsyncFunctionDef)

                                found.append({
                                    "name": item.name,
                                    "args": args,
                                    "returns": returns,
                                    "is_async": is_async_method,
                                    "from_class": base_name,
                                })
                return found

            # First check classes in the same file
            same_file_classes = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    same_file_classes[node.name] = node

            for base in target_class.bases:
                base_name = None
                base_line = None
                base_col = None

                if isinstance(base, ast.Name):
                    base_name = base.id
                    base_line = base.lineno
                    base_col = base.col_offset + 1  # LSP is 1-indexed
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                    base_line = base.lineno
                    base_col = base.col_offset + 1

                if not base_name:
                    continue

                # First try same file
                if base_name in same_file_classes:
                    base_node = same_file_classes[base_name]
                    abstract_methods.extend(extract_abstract_methods(base_node, base_name))
                    continue

                # Use LSP to find base class in other files
                if base_line and base_col:
                    await self._ensure_indexed(file_path)
                    definition_result = await self.lsp_client.get_definition(file_path, base_line, base_col)

                    base_file = None
                    base_def_line = None

                    if definition_result:
                        if isinstance(definition_result, list) and len(definition_result) > 0:
                            loc = definition_result[0]
                        else:
                            loc = definition_result

                        # Extract file path from LSP result
                        if hasattr(loc, 'uri'):
                            base_file = loc.uri.replace('file://', '')
                        elif isinstance(loc, dict) and 'uri' in loc:
                            base_file = loc['uri'].replace('file://', '')
                        elif isinstance(loc, dict) and 'targetUri' in loc:
                            base_file = loc['targetUri'].replace('file://', '')

                        # Extract line from LSP result
                        if hasattr(loc, 'range'):
                            base_def_line = loc.range.start.line + 1
                        elif isinstance(loc, dict) and 'range' in loc:
                            base_def_line = loc['range']['start']['line'] + 1
                        elif isinstance(loc, dict) and 'targetRange' in loc:
                            base_def_line = loc['targetRange']['start']['line'] + 1

                    if base_file and base_file != file_path:
                        lsp_resolved_bases.append({
                            "base_class": base_name,
                            "resolved_file": base_file,
                            "resolved_line": base_def_line
                        })

                        # Read and parse the base class file
                        try:
                            with open(base_file, "r") as bf:
                                base_source = bf.read()
                            base_tree = ast.parse(base_source)

                            # Find the class at the resolved line
                            for node in ast.walk(base_tree):
                                if isinstance(node, ast.ClassDef) and node.name == base_name:
                                    abstract_methods.extend(extract_abstract_methods(node, base_name))
                                    break
                        except Exception:
                            # If we can't read the file, skip this base
                            pass

            if not abstract_methods:
                return self._json_response({
                    "phase": "preview",
                    "operation": "implement_methods",
                    "message": "No unimplemented abstract methods found",
                    "existing_methods": list(existing_methods),
                })

            if phase == "preview":
                response = {
                    "phase": "preview",
                    "operation": "implement_methods",
                    "class": class_name,
                    "methods_to_implement": [m["name"] for m in abstract_methods],
                    "details": abstract_methods,
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                }
                if lsp_resolved_bases:
                    response["lsp_resolved"] = lsp_resolved_bases
                return self._json_response(response)

            # Generate method stubs
            indent = "    "
            method_stubs = []
            for method in abstract_methods:
                async_prefix = "async " if method["is_async"] else ""
                args_str = ", ".join(method["args"])
                stub_lines = [f"{indent}{async_prefix}def {method['name']}({args_str}){method['returns']}:"]
                if raise_not_implemented:
                    stub_lines.append(f'{indent}{indent}raise NotImplementedError("{method["name"]} not implemented")')
                else:
                    stub_lines.append(f"{indent}{indent}pass")
                method_stubs.append("\n".join(stub_lines))

            stubs_code = "\n\n".join(method_stubs) + "\n"

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "implement_methods",
                    "stubs": stubs_code,
                    "next_step": "Call with phase='apply' to add implementations",
                })

            elif phase == "apply":
                # Insert at end of class body
                if target_class.body:
                    insert_line = target_class.body[-1].end_lineno
                else:
                    insert_line = target_class.lineno

                new_lines = lines[:insert_line]
                new_lines.append("\n" + stubs_code)
                new_lines.extend(lines[insert_line:])

                with open(file_path, "w") as f:
                    f.write("".join(new_lines))

                return self._json_response({
                    "phase": "apply",
                    "operation": "implement_methods",
                    "success": True,
                    "message": f"Added {len(abstract_methods)} method stub(s) to {class_name}",
                    "methods": [m["name"] for m in abstract_methods],
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Implement methods failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_override_method(self, request: web.Request) -> web.Response:
        """Override a parent class method with super() call.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        method_name = body.get("methodName")
        call_super = body.get("callSuper", True)
        phase = body.get("phase", "preview")

        if not file_path or not class_name or not method_name:
            return self._error_response("Required: filePath, className, methodName")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found")

            # Check if method already exists
            for item in target_class.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return self._error_response(f"Method '{method_name}' already exists in {class_name}")

            # Find the method in parent classes
            parent_method = None
            parent_class_name = None
            lsp_resolved_base = None

            # First check classes in the same file
            same_file_classes = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    same_file_classes[node.name] = node

            for base in target_class.bases:
                base_name = None
                base_line = None
                base_col = None

                if isinstance(base, ast.Name):
                    base_name = base.id
                    base_line = base.lineno
                    base_col = base.col_offset + 1  # LSP is 1-indexed
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                    base_line = base.lineno
                    base_col = base.col_offset + 1

                if not base_name:
                    continue

                # First try same file
                if base_name in same_file_classes:
                    base_node = same_file_classes[base_name]
                    for item in base_node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                            parent_method = item
                            parent_class_name = base_name
                            break
                    if parent_method:
                        break
                    continue

                # Use LSP to find base class in other files
                if base_line and base_col:
                    await self._ensure_indexed(file_path)
                    definition_result = await self.lsp_client.get_definition(file_path, base_line, base_col)

                    base_file = None
                    base_def_line = None

                    if definition_result:
                        if isinstance(definition_result, list) and len(definition_result) > 0:
                            loc = definition_result[0]
                        else:
                            loc = definition_result

                        # Extract file path from LSP result
                        if hasattr(loc, 'uri'):
                            base_file = loc.uri.replace('file://', '')
                        elif isinstance(loc, dict) and 'uri' in loc:
                            base_file = loc['uri'].replace('file://', '')
                        elif isinstance(loc, dict) and 'targetUri' in loc:
                            base_file = loc['targetUri'].replace('file://', '')

                        # Extract line from LSP result
                        if hasattr(loc, 'range'):
                            base_def_line = loc.range.start.line + 1
                        elif isinstance(loc, dict) and 'range' in loc:
                            base_def_line = loc['range']['start']['line'] + 1
                        elif isinstance(loc, dict) and 'targetRange' in loc:
                            base_def_line = loc['targetRange']['start']['line'] + 1

                    if base_file and base_file != file_path:
                        # Read and parse the base class file
                        try:
                            with open(base_file, "r") as bf:
                                base_source = bf.read()
                            base_tree = ast.parse(base_source)

                            # Find the class and method
                            for node in ast.walk(base_tree):
                                if isinstance(node, ast.ClassDef) and node.name == base_name:
                                    for item in node.body:
                                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                                            parent_method = item
                                            parent_class_name = base_name
                                            lsp_resolved_base = {
                                                "base_class": base_name,
                                                "resolved_file": base_file,
                                                "resolved_line": base_def_line
                                            }
                                            break
                                    break
                        except Exception:
                            # If we can't read the file, skip this base
                            pass

                    if parent_method:
                        break

            if not parent_method:
                return self._error_response(f"Method '{method_name}' not found in any parent class")

            # Extract signature from parent method
            args = []
            for arg in parent_method.args.args:
                arg_str = arg.arg
                if arg.annotation:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                args.append(arg_str)

            returns = ""
            if parent_method.returns:
                returns = f" -> {ast.unparse(parent_method.returns)}"

            is_async = isinstance(parent_method, ast.AsyncFunctionDef)

            if phase == "preview":
                response = {
                    "phase": "preview",
                    "operation": "override_method",
                    "class": class_name,
                    "method": method_name,
                    "parent_class": parent_class_name,
                    "signature": f"def {method_name}({', '.join(args)}){returns}",
                    "is_async": is_async,
                    "will_call_super": call_super,
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                }
                if lsp_resolved_base:
                    response["lsp_resolved"] = lsp_resolved_base
                return self._json_response(response)

            # Generate override method
            indent = "    "
            async_prefix = "async " if is_async else ""
            await_prefix = "await " if is_async else ""

            method_lines = [f"{indent}{async_prefix}def {method_name}({', '.join(args)}){returns}:"]

            if call_super:
                # Build super() call with appropriate args
                call_args = [arg.split(":")[0].strip() for arg in args if arg != "self"]
                super_call = f"super().{method_name}({', '.join(call_args)})"
                if is_async:
                    super_call = f"await {super_call}"

                if returns and returns != " -> None":
                    method_lines.append(f"{indent}{indent}result = {super_call}")
                    method_lines.append(f"{indent}{indent}# Add your code here")
                    method_lines.append(f"{indent}{indent}return result")
                else:
                    method_lines.append(f"{indent}{indent}{super_call}")
                    method_lines.append(f"{indent}{indent}# Add your code here")
            else:
                method_lines.append(f"{indent}{indent}# TODO: Implement {method_name}")
                method_lines.append(f"{indent}{indent}pass")

            override_code = "\n".join(method_lines) + "\n"

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "override_method",
                    "override_code": override_code,
                    "next_step": "Call with phase='apply' to add override",
                })

            elif phase == "apply":
                # Insert at end of class body
                if target_class.body:
                    insert_line = target_class.body[-1].end_lineno
                else:
                    insert_line = target_class.lineno

                new_lines = lines[:insert_line]
                new_lines.append("\n" + override_code)
                new_lines.extend(lines[insert_line:])

                with open(file_path, "w") as f:
                    f.write("".join(new_lines))

                return self._json_response({
                    "phase": "apply",
                    "operation": "override_method",
                    "success": True,
                    "message": f"Added override for '{method_name}' in {class_name}",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Override method failed: {e}\n{traceback.format_exc()}", 500)

    # --- Design Patterns ---

    async def handle_pattern_singleton(self, request: web.Request) -> web.Response:
        """Convert a class to Singleton pattern.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        thread_safe = body.get("threadSafe", False)
        phase = body.get("phase", "preview")

        if not file_path or not class_name:
            return self._error_response("Required: filePath, className")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found")

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "pattern_singleton",
                    "class": class_name,
                    "thread_safe": thread_safe,
                    "will_add": ["_instance class variable", "__new__ method"],
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                })

            # Generate singleton code
            indent = "    "
            if thread_safe:
                singleton_code = f'''
{indent}_instance = None
{indent}_lock = __import__('threading').Lock()

{indent}def __new__(cls, *args, **kwargs):
{indent}{indent}if cls._instance is None:
{indent}{indent}{indent}with cls._lock:
{indent}{indent}{indent}{indent}if cls._instance is None:
{indent}{indent}{indent}{indent}{indent}cls._instance = super().__new__(cls)
{indent}{indent}return cls._instance
'''
            else:
                singleton_code = f'''
{indent}_instance = None

{indent}def __new__(cls, *args, **kwargs):
{indent}{indent}if cls._instance is None:
{indent}{indent}{indent}cls._instance = super().__new__(cls)
{indent}{indent}return cls._instance
'''

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "pattern_singleton",
                    "singleton_code": singleton_code,
                    "next_step": "Call with phase='apply' to add singleton pattern",
                })

            elif phase == "apply":
                # Insert at start of class body
                if target_class.body:
                    insert_line = target_class.body[0].lineno - 1
                else:
                    insert_line = target_class.lineno

                new_lines = lines[:insert_line]
                new_lines.append(singleton_code)
                new_lines.extend(lines[insert_line:])

                with open(file_path, "w") as f:
                    f.write("".join(new_lines))

                return self._json_response({
                    "phase": "apply",
                    "operation": "pattern_singleton",
                    "success": True,
                    "message": f"Converted {class_name} to Singleton pattern",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Singleton pattern failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_pattern_factory(self, request: web.Request) -> web.Response:
        """Generate Factory pattern for creating objects.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        base_class = body.get("baseClass")
        products = body.get("products", [])
        factory_name = body.get("factoryName", f"{base_class}Factory")
        phase = body.get("phase", "preview")

        if not file_path or not base_class or not products:
            return self._error_response("Required: filePath, baseClass, products (list of class names)")

        try:
            import os

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "pattern_factory",
                    "base_class": base_class,
                    "factory_name": factory_name,
                    "products": products,
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                })

            # Generate factory code
            indent = "    "
            product_cases = []
            for product in products:
                product_cases.append(f'{indent}{indent}"{product.lower()}": {product},')

            factory_code = f'''
class {factory_name}:
{indent}"""Factory for creating {base_class} instances."""

{indent}_creators = {{
{chr(10).join(product_cases)}
{indent}}}

{indent}@classmethod
{indent}def create(cls, product_type: str, *args, **kwargs) -> "{base_class}":
{indent}{indent}"""Create a product by type name.

{indent}{indent}Args:
{indent}{indent}{indent}product_type: Type of product to create ({", ".join(f'"{p.lower()}"' for p in products)})
{indent}{indent}{indent}*args, **kwargs: Arguments passed to the product constructor

{indent}{indent}Returns:
{indent}{indent}{indent}Instance of the requested product type

{indent}{indent}Raises:
{indent}{indent}{indent}ValueError: If product_type is unknown
{indent}{indent}"""
{indent}{indent}creator = cls._creators.get(product_type.lower())
{indent}{indent}if creator is None:
{indent}{indent}{indent}raise ValueError(f"Unknown product type: {{product_type}}")
{indent}{indent}return creator(*args, **kwargs)

{indent}@classmethod
{indent}def register(cls, product_type: str, creator: type) -> None:
{indent}{indent}"""Register a new product type."""
{indent}{indent}cls._creators[product_type.lower()] = creator
'''

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "pattern_factory",
                    "factory_code": factory_code,
                    "next_step": "Call with phase='apply' to add factory",
                })

            elif phase == "apply":
                with open(file_path, "r") as f:
                    source = f.read()

                # Append factory to end of file
                new_source = source.rstrip() + "\n\n" + factory_code + "\n"

                with open(file_path, "w") as f:
                    f.write(new_source)

                return self._json_response({
                    "phase": "apply",
                    "operation": "pattern_factory",
                    "success": True,
                    "message": f"Created {factory_name} for {base_class}",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Factory pattern failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_pattern_builder(self, request: web.Request) -> web.Response:
        """Generate Builder pattern for a class.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        builder_name = body.get("builderName", f"{class_name}Builder")
        phase = body.get("phase", "preview")

        if not file_path or not class_name:
            return self._error_response("Required: filePath, className")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found")

            # Find __init__ to extract attributes
            init_args = []
            for item in target_class.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    for arg in item.args.args:
                        if arg.arg != "self":
                            arg_type = ""
                            if arg.annotation:
                                arg_type = ast.unparse(arg.annotation)
                            init_args.append({
                                "name": arg.arg,
                                "type": arg_type,
                            })
                    break

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "pattern_builder",
                    "class": class_name,
                    "builder_name": builder_name,
                    "attributes": [a["name"] for a in init_args],
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                })

            # Generate builder code
            indent = "    "
            setter_methods = []
            for arg in init_args:
                type_hint = f": {arg['type']}" if arg["type"] else ""
                setter_methods.append(f'''
{indent}def with_{arg["name"]}(self, {arg["name"]}{type_hint}) -> "{builder_name}":
{indent}{indent}"""Set {arg["name"]}."""
{indent}{indent}self._{arg["name"]} = {arg["name"]}
{indent}{indent}return self''')

            init_attrs = "\n".join(f'{indent}{indent}self._{arg["name"]} = None' for arg in init_args)
            build_args = ", ".join(f'{arg["name"]}=self._{arg["name"]}' for arg in init_args)

            builder_code = f'''
class {builder_name}:
{indent}"""Builder for {class_name}."""

{indent}def __init__(self):
{init_attrs}
{"".join(setter_methods)}

{indent}def build(self) -> "{class_name}":
{indent}{indent}"""Build and return the {class_name} instance."""
{indent}{indent}return {class_name}({build_args})
'''

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "pattern_builder",
                    "builder_code": builder_code,
                    "next_step": "Call with phase='apply' to add builder",
                })

            elif phase == "apply":
                # Append builder to end of file
                new_source = source.rstrip() + "\n\n" + builder_code + "\n"

                with open(file_path, "w") as f:
                    f.write(new_source)

                return self._json_response({
                    "phase": "apply",
                    "operation": "pattern_builder",
                    "success": True,
                    "message": f"Created {builder_name} for {class_name}",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Builder pattern failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_pattern_observer(self, request: web.Request) -> web.Response:
        """Add Observer pattern to a class.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        class_name = body.get("className")
        events = body.get("events", ["change"])
        phase = body.get("phase", "preview")

        if not file_path or not class_name:
            return self._error_response("Required: filePath, className")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)
            lines = source.splitlines(keepends=True)

            # Find the target class
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{class_name}' not found")

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "pattern_observer",
                    "class": class_name,
                    "events": events,
                    "will_add": ["_observers dict", "subscribe()", "unsubscribe()", "notify()"],
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                })

            # Generate observer code
            indent = "    "
            events_dict = ", ".join(f'"{e}": []' for e in events)

            observer_code = f'''
{indent}_observers: dict = {{{events_dict}}}

{indent}def subscribe(self, event: str, callback) -> None:
{indent}{indent}"""Subscribe to an event.

{indent}{indent}Args:
{indent}{indent}{indent}event: Event name ({", ".join(f'"{e}"' for e in events)})
{indent}{indent}{indent}callback: Function to call when event is triggered
{indent}{indent}"""
{indent}{indent}if event not in self._observers:
{indent}{indent}{indent}self._observers[event] = []
{indent}{indent}self._observers[event].append(callback)

{indent}def unsubscribe(self, event: str, callback) -> None:
{indent}{indent}"""Unsubscribe from an event."""
{indent}{indent}if event in self._observers:
{indent}{indent}{indent}self._observers[event].remove(callback)

{indent}def notify(self, event: str, *args, **kwargs) -> None:
{indent}{indent}"""Notify all subscribers of an event."""
{indent}{indent}for callback in self._observers.get(event, []):
{indent}{indent}{indent}callback(*args, **kwargs)
'''

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "pattern_observer",
                    "observer_code": observer_code,
                    "next_step": "Call with phase='apply' to add observer pattern",
                })

            elif phase == "apply":
                # Insert at start of class body
                if target_class.body:
                    insert_line = target_class.body[0].lineno - 1
                else:
                    insert_line = target_class.lineno

                new_lines = lines[:insert_line]
                new_lines.append(observer_code)
                new_lines.extend(lines[insert_line:])

                with open(file_path, "w") as f:
                    f.write("".join(new_lines))

                return self._json_response({
                    "phase": "apply",
                    "operation": "pattern_observer",
                    "success": True,
                    "message": f"Added Observer pattern to {class_name}",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Observer pattern failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_pattern_decorator(self, request: web.Request) -> web.Response:
        """Generate Decorator pattern structure.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        component_class = body.get("componentClass")
        decorator_name = body.get("decoratorName", f"{component_class}Decorator")
        phase = body.get("phase", "preview")

        if not file_path or not component_class:
            return self._error_response("Required: filePath, componentClass")

        try:
            import ast
            import os

            with open(file_path, "r") as f:
                source = f.read()

            tree = ast.parse(source)

            # Find the component class to get its methods
            target_class = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == component_class:
                    target_class = node
                    break

            if not target_class:
                return self._error_response(f"Class '{component_class}' not found")

            # Get public methods
            methods = []
            for item in target_class.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not item.name.startswith("_") or item.name in ("__init__", "__call__"):
                        args = []
                        for arg in item.args.args:
                            arg_str = arg.arg
                            if arg.annotation:
                                arg_str += f": {ast.unparse(arg.annotation)}"
                            args.append(arg_str)

                        returns = ""
                        if item.returns:
                            returns = f" -> {ast.unparse(item.returns)}"

                        methods.append({
                            "name": item.name,
                            "args": args,
                            "returns": returns,
                            "is_async": isinstance(item, ast.AsyncFunctionDef),
                        })

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "pattern_decorator",
                    "component": component_class,
                    "decorator_name": decorator_name,
                    "methods_to_wrap": [m["name"] for m in methods],
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                })

            # Generate decorator code
            indent = "    "
            method_wrappers = []
            for method in methods:
                if method["name"] == "__init__":
                    continue
                async_prefix = "async " if method["is_async"] else ""
                await_prefix = "await " if method["is_async"] else ""
                args_str = ", ".join(method["args"])
                call_args = ", ".join(a.split(":")[0].strip() for a in method["args"] if a != "self")

                method_wrappers.append(f'''
{indent}{async_prefix}def {method["name"]}({args_str}){method["returns"]}:
{indent}{indent}return {await_prefix}self._component.{method["name"]}({call_args})''')

            decorator_code = f'''
class {decorator_name}({component_class}):
{indent}"""Decorator base class for {component_class}."""

{indent}def __init__(self, component: "{component_class}"):
{indent}{indent}self._component = component
{"".join(method_wrappers)}


class Concrete{decorator_name}({decorator_name}):
{indent}"""Concrete decorator example - extend this."""

{indent}def __init__(self, component: "{component_class}"):
{indent}{indent}super().__init__(component)
{indent}{indent}# Add decorator state here
'''

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "pattern_decorator",
                    "decorator_code": decorator_code,
                    "next_step": "Call with phase='apply' to add decorator pattern",
                })

            elif phase == "apply":
                new_source = source.rstrip() + "\n\n" + decorator_code + "\n"

                with open(file_path, "w") as f:
                    f.write(new_source)

                return self._json_response({
                    "phase": "apply",
                    "operation": "pattern_decorator",
                    "success": True,
                    "message": f"Created {decorator_name} for {component_class}",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Decorator pattern failed: {e}\n{traceback.format_exc()}", 500)

    async def handle_pattern_strategy(self, request: web.Request) -> web.Response:
        """Generate Strategy pattern structure.

        Multi-phased refactoring.
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        strategy_name = body.get("strategyName", "Strategy")
        strategies = body.get("strategies", [])
        context_class = body.get("contextClass")
        phase = body.get("phase", "preview")

        if not file_path or not strategies:
            return self._error_response("Required: filePath, strategies (list of strategy names)")

        try:
            import os

            if phase == "preview":
                return self._json_response({
                    "phase": "preview",
                    "operation": "pattern_strategy",
                    "strategy_interface": strategy_name,
                    "strategies": strategies,
                    "context_class": context_class,
                    "file": os.path.basename(file_path),
                    "next_step": "Call with phase='changes' or phase='apply'",
                })

            # Generate strategy code
            indent = "    "
            strategy_classes = []
            for strategy in strategies:
                strategy_classes.append(f'''
class {strategy}({strategy_name}):
{indent}"""Concrete strategy: {strategy}."""

{indent}def execute(self, *args, **kwargs):
{indent}{indent}# TODO: Implement {strategy} strategy
{indent}{indent}pass
''')

            context_code = ""
            if context_class:
                context_code = f'''

class {context_class}:
{indent}"""Context class that uses a strategy."""

{indent}def __init__(self, strategy: "{strategy_name}"):
{indent}{indent}self._strategy = strategy

{indent}@property
{indent}def strategy(self) -> "{strategy_name}":
{indent}{indent}return self._strategy

{indent}@strategy.setter
{indent}def strategy(self, strategy: "{strategy_name}") -> None:
{indent}{indent}self._strategy = strategy

{indent}def execute_strategy(self, *args, **kwargs):
{indent}{indent}"""Execute the current strategy."""
{indent}{indent}return self._strategy.execute(*args, **kwargs)
'''

            strategy_code = f'''
from abc import ABC, abstractmethod


class {strategy_name}(ABC):
{indent}"""Strategy interface."""

{indent}@abstractmethod
{indent}def execute(self, *args, **kwargs):
{indent}{indent}"""Execute the strategy."""
{indent}{indent}pass
{"".join(strategy_classes)}{context_code}'''

            if phase == "changes":
                return self._json_response({
                    "phase": "changes",
                    "operation": "pattern_strategy",
                    "strategy_code": strategy_code,
                    "next_step": "Call with phase='apply' to add strategy pattern",
                })

            elif phase == "apply":
                with open(file_path, "r") as f:
                    source = f.read()

                new_source = source.rstrip() + "\n\n" + strategy_code + "\n"

                with open(file_path, "w") as f:
                    f.write(new_source)

                return self._json_response({
                    "phase": "apply",
                    "operation": "pattern_strategy",
                    "success": True,
                    "message": f"Created Strategy pattern with {len(strategies)} strategies",
                })

            else:
                return self._error_response(f"Invalid phase: {phase}")

        except Exception as e:
            import traceback
            return self._error_response(f"Strategy pattern failed: {e}\n{traceback.format_exc()}", 500)

    # --- Code Generation (rope.contrib.generate) ---

    async def handle_generate_function(self, request: web.Request) -> web.Response:
        """Generate a function at a call site where it doesn't exist yet."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        phase = body.get("phase", "preview")

        if not file_path or not line:
            return self._error_response("Required: filePath, line")

        try:
            from rope.base import libutils
            from rope.contrib.generate import create_generate
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)

                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                generator = create_generate(project, resource, offset)
                changes = generator.get_changes()

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({
                        "phase": "preview",
                        "operation": "generate_function",
                        "files_affected": len(changed_files),
                        "affected_files": changed_files,
                        "description": changes.description,
                    })
                elif phase == "changes":
                    file_changes = []
                    for change in changes.get_changed_resources():
                        new_content = changes.get_changed_contents().get(change, "")
                        file_changes.append({"file": os.path.relpath(change.path, self.workspace), "new_content": new_content})
                    return self._json_response({"phase": "changes", "changes": file_changes})
                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="generate_function",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"line": line, "column": column}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids,
                        "message": "Function generated"
                    })
                else:
                    return self._error_response(f"Invalid phase: {phase}")
            finally:
                project.close()
        except ImportError:
            return self._error_response("rope not installed", 500)
        except Exception as e:
            return self._error_response(f"Generate function failed: {e}", 500)

    async def handle_generate_class(self, request: web.Request) -> web.Response:
        """Generate a class at a location where it's referenced but doesn't exist."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        phase = body.get("phase", "preview")

        if not file_path or not line:
            return self._error_response("Required: filePath, line")

        try:
            from rope.base import libutils
            from rope.contrib.generate import create_generate
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)
                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                generator = create_generate(project, resource, offset)
                changes = generator.get_changes()

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({"phase": "preview", "operation": "generate_class", "files_affected": len(changed_files), "affected_files": changed_files})
                elif phase == "changes":
                    file_changes = [{"file": os.path.relpath(c.path, self.workspace), "new_content": changes.get_changed_contents().get(c, "")} for c in changes.get_changed_resources()]
                    return self._json_response({"phase": "changes", "changes": file_changes})
                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="generate_class",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"line": line, "column": column}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids
                    })
                else:
                    return self._error_response(f"Invalid phase: {phase}")
            finally:
                project.close()
        except Exception as e:
            return self._error_response(f"Generate class failed: {e}", 500)

    async def handle_generate_module(self, request: web.Request) -> web.Response:
        """Generate a new module file."""
        self._request_count += 1
        body = await self._get_json_body(request)

        module_name = body.get("moduleName")
        parent_path = body.get("parentPath", self.workspace)
        phase = body.get("phase", "preview")

        if not module_name:
            return self._error_response("Required: moduleName")

        try:
            from rope.contrib.generate import create_module
            import os

            project = self._get_rope_project()
            try:
                parent_resource = project.get_resource(os.path.relpath(parent_path, self.workspace)) if parent_path != self.workspace else project.root

                if phase == "preview":
                    module_path = os.path.join(parent_path, f"{module_name}.py")
                    return self._json_response({
                        "phase": "preview",
                        "operation": "generate_module",
                        "module_name": module_name,
                        "will_create": os.path.relpath(module_path, self.workspace),
                    })
                elif phase == "apply":
                    new_module = create_module(project, module_name, parent_resource)
                    module_path = os.path.join(self.workspace, new_module.path)

                    # Record history for the new module
                    try:
                        with open(module_path, 'r') as f:
                            after_content = f.read()
                    except:
                        after_content = ""

                    entry_id = self._record_file_change(
                        action="generate_module",
                        file_path=module_path,
                        before_content=None,  # New file
                        after_content=after_content,
                        metadata={"module_name": module_name}
                    )

                    return self._json_response({
                        "phase": "apply",
                        "success": True,
                        "created": new_module.path,
                        "history_id": entry_id
                    })
                else:
                    return self._error_response(f"Invalid phase: {phase}")
            finally:
                project.close()
        except Exception as e:
            return self._error_response(f"Generate module failed: {e}", 500)

    async def handle_generate_package(self, request: web.Request) -> web.Response:
        """Generate a new package (directory with __init__.py)."""
        self._request_count += 1
        body = await self._get_json_body(request)

        package_name = body.get("packageName")
        parent_path = body.get("parentPath", self.workspace)
        phase = body.get("phase", "preview")

        if not package_name:
            return self._error_response("Required: packageName")

        try:
            from rope.contrib.generate import create_package
            import os

            project = self._get_rope_project()
            try:
                parent_resource = project.get_resource(os.path.relpath(parent_path, self.workspace)) if parent_path != self.workspace else project.root

                if phase == "preview":
                    package_path = os.path.join(parent_path, package_name)
                    return self._json_response({
                        "phase": "preview",
                        "operation": "generate_package",
                        "package_name": package_name,
                        "will_create": [
                            os.path.relpath(package_path, self.workspace),
                            os.path.relpath(os.path.join(package_path, "__init__.py"), self.workspace),
                        ],
                    })
                elif phase == "apply":
                    new_package = create_package(project, package_name, parent_resource)
                    init_path = os.path.join(self.workspace, new_package.path, "__init__.py")

                    # Record history for the new __init__.py
                    try:
                        with open(init_path, 'r') as f:
                            after_content = f.read()
                    except:
                        after_content = ""

                    entry_id = self._record_file_change(
                        action="generate_package",
                        file_path=init_path,
                        before_content=None,  # New file
                        after_content=after_content,
                        metadata={"package_name": package_name}
                    )

                    return self._json_response({
                        "phase": "apply",
                        "success": True,
                        "created": new_package.path,
                        "history_id": entry_id
                    })
                else:
                    return self._error_response(f"Invalid phase: {phase}")
            finally:
                project.close()
        except Exception as e:
            return self._error_response(f"Generate package failed: {e}", 500)

    async def handle_generate_variable(self, request: web.Request) -> web.Response:
        """Generate a variable at a location where it's used but not defined."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column", 1)
        phase = body.get("phase", "preview")

        if not file_path or not line:
            return self._error_response("Required: filePath, line")

        try:
            from rope.base import libutils
            from rope.contrib.generate import create_generate
            import os

            project = self._get_rope_project(file_path)
            try:
                resource = libutils.path_to_resource(project, file_path)
                with open(file_path, 'r') as f:
                    lines = f.read().splitlines(keepends=True)
                offset = sum(len(lines[i]) for i in range(line - 1)) + (column - 1)

                generator = create_generate(project, resource, offset)
                changes = generator.get_changes()

                if phase == "preview":
                    changed_files = [os.path.relpath(c.path, self.workspace) for c in changes.get_changed_resources()]
                    return self._json_response({"phase": "preview", "operation": "generate_variable", "files_affected": len(changed_files)})
                elif phase == "changes":
                    file_changes = [{"file": os.path.relpath(c.path, self.workspace), "new_content": changes.get_changed_contents().get(c, "")} for c in changes.get_changed_resources()]
                    return self._json_response({"phase": "changes", "changes": file_changes})
                elif phase == "apply":
                    # Read before content for history
                    before_contents = {}
                    for change in changes.get_changed_resources():
                        try:
                            with open(change.path, 'r') as f:
                                before_contents[change.path] = f.read()
                        except:
                            before_contents[change.path] = None

                    project.do(changes)

                    # Record history for each changed file
                    applied_files = []
                    history_ids = []
                    for change in changes.get_changed_resources():
                        rel_path = os.path.relpath(change.path, self.workspace)
                        applied_files.append(rel_path)
                        try:
                            with open(change.path, 'r') as f:
                                after_content = f.read()
                        except:
                            after_content = ""
                        entry_id = self._record_file_change(
                            action="generate_variable",
                            file_path=change.path,
                            before_content=before_contents.get(change.path),
                            after_content=after_content,
                            metadata={"line": line, "column": column}
                        )
                        history_ids.append(entry_id)

                    return self._json_response({
                        "phase": "apply",
                        "success": True,
                        "applied_to": applied_files,
                        "history_ids": history_ids
                    })
                else:
                    return self._error_response(f"Invalid phase: {phase}")
            finally:
                project.close()
        except Exception as e:
            return self._error_response(f"Generate variable failed: {e}", 500)

    # --- Code Metrics ---

    async def handle_loc(self, request: web.Request) -> web.Response:
        """Calculate lines of code statistics using radon."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        directory = body.get("directory")

        if not file_path and not directory:
            return self._error_response("Required: filePath or directory")

        try:
            from radon.raw import analyze
            import os
            import glob

            results = []
            total = {"loc": 0, "lloc": 0, "sloc": 0, "comments": 0, "multi": 0, "blank": 0, "single_comments": 0}

            def analyze_file(path):
                try:
                    with open(path, 'r') as f:
                        code = f.read()
                    metrics = analyze(code)
                    return {
                        "file": os.path.relpath(path, self.workspace),
                        "loc": metrics.loc,           # Total lines
                        "lloc": metrics.lloc,         # Logical lines
                        "sloc": metrics.sloc,         # Source lines
                        "comments": metrics.comments, # Comment lines
                        "multi": metrics.multi,       # Multi-line strings
                        "blank": metrics.blank,       # Blank lines
                        "single_comments": metrics.single_comments,
                    }
                except:
                    return None

            if file_path:
                result = analyze_file(file_path)
                if result:
                    results.append(result)
            elif directory:
                scan_path = os.path.join(self.workspace, directory) if not os.path.isabs(directory) else directory
                for py_file in glob.glob(os.path.join(scan_path, "**/*.py"), recursive=True):
                    result = analyze_file(py_file)
                    if result:
                        results.append(result)
                        for key in total:
                            total[key] += result[key]

            return self._json_response({
                "files": results,
                "file_count": len(results),
                "total": total if directory else None,
            })

        except ImportError:
            return self._error_response("radon not installed. Install with: pip install radon", 500)
        except Exception as e:
            return self._error_response(f"LOC analysis failed: {e}", 500)

    async def handle_duplicates(self, request: web.Request) -> web.Response:
        """Find duplicate code blocks."""
        self._request_count += 1
        body = await self._get_json_body(request)

        directory = body.get("directory", ".")
        min_lines = body.get("minLines", 4)

        try:
            import ast
            import os
            import glob
            from collections import defaultdict

            # Simple duplicate detection using AST node hashing
            code_blocks = defaultdict(list)

            scan_path = os.path.join(self.workspace, directory) if not os.path.isabs(directory) else directory

            for py_file in glob.glob(os.path.join(scan_path, "**/*.py"), recursive=True):
                try:
                    with open(py_file, 'r') as f:
                        source = f.read()
                    tree = ast.parse(source)
                    lines = source.splitlines()

                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if hasattr(node, 'end_lineno') and (node.end_lineno - node.lineno + 1) >= min_lines:
                                # Get function body as string for comparison
                                func_lines = lines[node.lineno - 1:node.end_lineno]
                                func_body = '\n'.join(line.strip() for line in func_lines[1:] if line.strip())  # Skip def line

                                if len(func_body) > 50:  # Skip very short functions
                                    code_blocks[hash(func_body)].append({
                                        "file": os.path.relpath(py_file, self.workspace),
                                        "name": node.name,
                                        "start_line": node.lineno,
                                        "end_line": node.end_lineno,
                                        "lines": node.end_lineno - node.lineno + 1,
                                    })
                except:
                    pass

            # Find duplicates (more than one occurrence)
            duplicates = []
            for block_hash, occurrences in code_blocks.items():
                if len(occurrences) > 1:
                    duplicates.append({
                        "occurrences": len(occurrences),
                        "locations": occurrences,
                    })

            # Sort by number of occurrences
            duplicates.sort(key=lambda x: x["occurrences"], reverse=True)

            return self._json_response({
                "duplicates": duplicates[:50],  # Limit results
                "total_duplicate_groups": len(duplicates),
                "min_lines": min_lines,
            })

        except Exception as e:
            return self._error_response(f"Duplicate detection failed: {e}", 500)

    async def handle_coupling(self, request: web.Request) -> web.Response:
        """Analyze module coupling for a single file."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        if not file_path:
            return self._error_response("Required: filePath")

        try:
            import ast
            import os
            import glob

            # Parse the target file
            with open(file_path, 'r') as f:
                source = f.read()
            tree = ast.parse(source)

            # Get this file's imports (efferent coupling - what it depends on)
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append({"module": alias.name, "line": node.lineno})
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        names = [a.name for a in node.names]
                        imports.append({
                            "module": node.module,
                            "names": names,
                            "line": node.lineno,
                        })

            # Find files that import this module (afferent coupling - what depends on it)
            rel_path = os.path.relpath(file_path, self.workspace)
            module_name = rel_path.replace("/", ".").replace("\\", ".").replace(".py", "")
            base_name = os.path.basename(file_path).replace(".py", "")

            imported_by = []
            # Only scan nearby files to keep it fast
            search_dir = os.path.dirname(file_path) or self.workspace
            for py_file in glob.glob(os.path.join(search_dir, "**/*.py"), recursive=True):
                if py_file == file_path:
                    continue
                try:
                    with open(py_file, 'r') as f:
                        content = f.read()
                    # Quick check before parsing
                    if base_name not in content and module_name not in content:
                        continue
                    other_tree = ast.parse(content)
                    for node in ast.walk(other_tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                if alias.name == module_name or alias.name.endswith(f".{base_name}"):
                                    imported_by.append(os.path.relpath(py_file, self.workspace))
                                    break
                        elif isinstance(node, ast.ImportFrom):
                            if node.module and (node.module == module_name or node.module.endswith(f".{base_name}") or base_name in [a.name for a in node.names]):
                                imported_by.append(os.path.relpath(py_file, self.workspace))
                                break
                except:
                    pass

            efferent = len(imports)
            afferent = len(imported_by)
            instability = efferent / (afferent + efferent) if (afferent + efferent) > 0 else 0

            # Build formatted summary
            lines = [f"File: {rel_path}"]
            lines.append(f"Efferent coupling (imports): {efferent}")
            lines.append(f"Afferent coupling (imported by): {afferent}")
            lines.append(f"Instability: {instability:.2f} (0=stable, 1=unstable)")
            if imports:
                lines.append("\nImports:")
                for imp in imports[:15]:
                    if "names" in imp:
                        lines.append(f"  from {imp['module']} import {', '.join(imp['names'][:5])} (line {imp['line']})")
                    else:
                        lines.append(f"  import {imp['module']} (line {imp['line']})")
            if imported_by:
                lines.append("\nImported by:")
                for f in imported_by[:10]:
                    lines.append(f"  {f}")

            return self._json_response({
                "file": rel_path,
                "efferent_coupling": efferent,
                "afferent_coupling": afferent,
                "instability": round(instability, 2),
                "imports": imports[:20],
                "imported_by": imported_by[:20],
                "formatted": "\n".join(lines),
            })

        except Exception as e:
            return self._error_response(f"Coupling analysis failed: {e}", 500)

    async def handle_dependency_graph(self, request: web.Request) -> web.Response:
        """Generate a dependency graph of imports."""
        self._request_count += 1
        body = await self._get_json_body(request)

        directory = body.get("directory", ".")
        format_type = body.get("format", "json")  # json, dot, mermaid

        try:
            import ast
            import os
            import glob

            scan_path = os.path.join(self.workspace, directory) if not os.path.isabs(directory) else directory

            nodes = set()
            edges = []

            for py_file in glob.glob(os.path.join(scan_path, "**/*.py"), recursive=True):
                try:
                    rel_path = os.path.relpath(py_file, self.workspace)
                    module_name = rel_path.replace("/", ".").replace("\\", ".").replace(".py", "").replace(".__init__", "")

                    nodes.add(module_name)

                    with open(py_file, 'r') as f:
                        source = f.read()
                    tree = ast.parse(source)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                edges.append({"from": module_name, "to": alias.name})
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                edges.append({"from": module_name, "to": node.module})
                except:
                    pass

            result = {
                "nodes": sorted(list(nodes)),
                "edges": edges,
                "node_count": len(nodes),
                "edge_count": len(edges),
            }

            if format_type == "dot":
                # Generate DOT format for Graphviz
                dot_lines = ["digraph dependencies {", "  rankdir=LR;"]
                for edge in edges:
                    dot_lines.append(f'  "{edge["from"]}" -> "{edge["to"]}";')
                dot_lines.append("}")
                result["dot"] = "\n".join(dot_lines)

            elif format_type == "mermaid":
                # Generate Mermaid format
                mermaid_lines = ["graph LR"]
                for i, edge in enumerate(edges[:100]):  # Limit for readability
                    safe_from = edge["from"].replace(".", "_")
                    safe_to = edge["to"].replace(".", "_")
                    mermaid_lines.append(f"  {safe_from}[{edge['from']}] --> {safe_to}[{edge['to']}]")
                result["mermaid"] = "\n".join(mermaid_lines)

            return self._json_response(result)

        except Exception as e:
            return self._error_response(f"Dependency graph failed: {e}", 500)

    # --- Linting & Style ---

    async def handle_lint(self, request: web.Request) -> web.Response:
        """Run linter (ruff, pylint, or flake8) on code."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        directory = body.get("directory")
        linter = body.get("linter", "ruff")  # ruff, pylint, flake8

        if not file_path and not directory:
            return self._error_response("Required: filePath or directory")

        target = file_path or directory or self.workspace

        try:
            import subprocess
            import json as json_lib

            if linter == "ruff":
                cmd = ["ruff", "check", "--output-format=json", target]
            elif linter == "pylint":
                cmd = ["pylint", "--output-format=json", target]
            elif linter == "flake8":
                cmd = ["flake8", "--format=json", target]
            else:
                return self._error_response(f"Unknown linter: {linter}. Use ruff, pylint, or flake8")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            issues = []
            try:
                if linter == "ruff":
                    raw_issues = json_lib.loads(result.stdout) if result.stdout else []
                    for issue in raw_issues:
                        issues.append({
                            "file": issue.get("filename", ""),
                            "line": issue.get("location", {}).get("row", 0),
                            "column": issue.get("location", {}).get("column", 0),
                            "code": issue.get("code", ""),
                            "message": issue.get("message", ""),
                            "severity": "error" if issue.get("code", "").startswith("E") else "warning",
                            "fix_available": issue.get("fix") is not None,
                        })
                elif linter == "pylint":
                    raw_issues = json_lib.loads(result.stdout) if result.stdout else []
                    for issue in raw_issues:
                        issues.append({
                            "file": issue.get("path", ""),
                            "line": issue.get("line", 0),
                            "column": issue.get("column", 0),
                            "code": issue.get("message-id", ""),
                            "message": issue.get("message", ""),
                            "severity": issue.get("type", "warning"),
                            "symbol": issue.get("symbol", ""),
                        })
            except json_lib.JSONDecodeError:
                # Return raw output if JSON parsing fails
                return self._json_response({
                    "linter": linter,
                    "raw_output": result.stdout,
                    "stderr": result.stderr,
                })

            # Compact response: just issues array (count derivable from len)
            return self._json_response({"issues": issues})

        except FileNotFoundError:
            return self._error_response(f"{linter} not installed. Install with: pip install {linter}", 500)
        except subprocess.TimeoutExpired:
            return self._error_response("Lint timed out", 504)
        except Exception as e:
            return self._error_response(f"Lint failed: {e}", 500)

    async def handle_autofix(self, request: web.Request) -> web.Response:
        """Auto-fix lint issues using ruff."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        directory = body.get("directory")
        dry_run = body.get("dryRun", True)  # Default to dry run for safety

        if not file_path and not directory:
            return self._error_response("Required: filePath or directory")

        target = file_path or directory

        try:
            import subprocess

            cmd = ["ruff", "check", "--fix"]
            if dry_run:
                cmd.append("--diff")
            cmd.append(target)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            # Compact response: only include relevant fields
            resp: dict = {"ok": True}
            if dry_run and result.stdout:
                resp["diff"] = result.stdout
            if result.stderr:
                resp["stderr"] = result.stderr
            return self._json_response(resp)

        except FileNotFoundError:
            return self._error_response("ruff not installed. Install with: pip install ruff", 500)
        except Exception as e:
            return self._error_response(f"Autofix failed: {e}", 500)

    async def handle_format_check(self, request: web.Request) -> web.Response:
        """Check code formatting with black and isort."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        directory = body.get("directory")

        if not file_path and not directory:
            return self._error_response("Required: filePath or directory")

        target = file_path or directory

        try:
            import subprocess

            results = {}

            # Check with black
            try:
                black_result = subprocess.run(
                    ["black", "--check", "--diff", target],
                    capture_output=True, text=True, timeout=60
                )
                results["black"] = {
                    "formatted": black_result.returncode == 0,
                    "diff": black_result.stdout if black_result.returncode != 0 else None,
                }
            except FileNotFoundError:
                results["black"] = {"error": "black not installed"}

            # Check with isort
            try:
                isort_result = subprocess.run(
                    ["isort", "--check-only", "--diff", target],
                    capture_output=True, text=True, timeout=60
                )
                results["isort"] = {
                    "sorted": isort_result.returncode == 0,
                    "diff": isort_result.stdout if isort_result.returncode != 0 else None,
                }
            except FileNotFoundError:
                results["isort"] = {"error": "isort not installed"}

            all_formatted = all(
                r.get("formatted", True) and r.get("sorted", True)
                for r in results.values() if "error" not in r
            )

            return self._json_response({
                "target": target,
                "all_formatted": all_formatted,
                "results": results,
            })

        except Exception as e:
            return self._error_response(f"Format check failed: {e}", 500)

    async def handle_sort_imports(self, request: web.Request) -> web.Response:
        """Sort imports with isort."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        directory = body.get("directory")
        dry_run = body.get("dryRun", True)

        if not file_path and not directory:
            return self._error_response("Required: filePath or directory")

        target = file_path or directory

        try:
            import subprocess

            cmd = ["isort"]
            if dry_run:
                cmd.append("--diff")
            cmd.append(target)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            return self._json_response({
                "target": target,
                "dry_run": dry_run,
                "diff": result.stdout if dry_run else None,
                "sorted": not dry_run,
                "message": "Showing diff" if dry_run else "Imports sorted",
            })

        except FileNotFoundError:
            return self._error_response("isort not installed. Install with: pip install isort", 500)
        except Exception as e:
            return self._error_response(f"Sort imports failed: {e}", 500)

    # --- Runtime & Debug ---

    async def handle_parse_traceback(self, request: web.Request) -> web.Response:
        """Parse and analyze a Python traceback."""
        self._request_count += 1
        body = await self._get_json_body(request)

        traceback_text = body.get("traceback")

        if not traceback_text:
            return self._error_response("Required: traceback (the traceback text)")

        try:
            import re

            frames = []
            exception_type = None
            exception_message = None

            # Parse traceback lines
            lines = traceback_text.strip().split('\n')

            # Pattern for frame lines: File "path", line N, in function
            frame_pattern = re.compile(r'File "([^"]+)", line (\d+), in (.+)')

            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # Match frame
                match = frame_pattern.search(line)
                if match:
                    file_path, line_no, func_name = match.groups()
                    code_line = ""
                    if i + 1 < len(lines) and not lines[i + 1].strip().startswith('File'):
                        code_line = lines[i + 1].strip()
                        i += 1

                    frames.append({
                        "file": file_path,
                        "line": int(line_no),
                        "function": func_name,
                        "code": code_line,
                    })

                # Match exception line (usually last meaningful line)
                elif ':' in line and not line.startswith('File') and not line.startswith('Traceback'):
                    if 'Error' in line or 'Exception' in line or 'Warning' in line:
                        parts = line.split(':', 1)
                        exception_type = parts[0].strip()
                        exception_message = parts[1].strip() if len(parts) > 1 else ""

                i += 1

            # Analyze the traceback
            analysis = {
                "exception_type": exception_type,
                "exception_message": exception_message,
                "frames": frames,
                "frame_count": len(frames),
                "origin": frames[-1] if frames else None,  # Where exception was raised
                "entry_point": frames[0] if frames else None,  # Where execution started
            }

            # Add suggestions based on exception type
            suggestions = []
            if exception_type:
                if "KeyError" in exception_type:
                    suggestions.append("Check if the key exists before accessing, or use .get() method")
                elif "IndexError" in exception_type:
                    suggestions.append("Check list/array bounds before accessing")
                elif "AttributeError" in exception_type:
                    suggestions.append("Verify the object has the attribute, check for None values")
                elif "TypeError" in exception_type:
                    suggestions.append("Check argument types and count")
                elif "ValueError" in exception_type:
                    suggestions.append("Validate input values before processing")
                elif "ImportError" in exception_type or "ModuleNotFoundError" in exception_type:
                    suggestions.append("Check if the module is installed and import path is correct")
                elif "FileNotFoundError" in exception_type:
                    suggestions.append("Verify the file path exists")

            analysis["suggestions"] = suggestions

            return self._json_response(analysis)

        except Exception as e:
            return self._error_response(f"Traceback parsing failed: {e}", 500)

    async def handle_find_exception_handlers(self, request: web.Request) -> web.Response:
        """Find all exception handlers (try/except blocks) in code."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        directory = body.get("directory")
        exception_type = body.get("exceptionType")  # Optional: filter by exception type

        if not file_path and not directory:
            return self._error_response("Required: filePath or directory")

        try:
            import ast
            import os
            import glob

            handlers = []

            def analyze_file(path):
                try:
                    with open(path, 'r') as f:
                        source = f.read()
                    tree = ast.parse(source)
                    lines = source.splitlines()

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Try):
                            for handler in node.handlers:
                                # Get exception type(s)
                                if handler.type is None:
                                    exc_types = ["bare except (catches all)"]
                                elif isinstance(handler.type, ast.Tuple):
                                    exc_types = [ast.unparse(t) if hasattr(ast, 'unparse') else str(t) for t in handler.type.elts]
                                else:
                                    exc_types = [ast.unparse(handler.type) if hasattr(ast, 'unparse') else str(handler.type)]

                                # Filter by exception type if specified
                                if exception_type and exception_type not in exc_types:
                                    continue

                                # Get handler code preview
                                handler_code = ""
                                if handler.body and hasattr(handler.body[0], 'lineno'):
                                    start = handler.lineno - 1
                                    end = min(start + 3, len(lines))
                                    handler_code = '\n'.join(lines[start:end])

                                handlers.append({
                                    "file": os.path.relpath(path, self.workspace),
                                    "line": handler.lineno,
                                    "end_line": handler.end_lineno if hasattr(handler, 'end_lineno') else None,
                                    "exception_types": exc_types,
                                    "exception_name": handler.name,  # The 'as e' part
                                    "preview": handler_code,
                                    "is_bare_except": handler.type is None,
                                })
                except:
                    pass

            if file_path:
                analyze_file(file_path)
            elif directory:
                scan_path = os.path.join(self.workspace, directory) if not os.path.isabs(directory) else directory
                for py_file in glob.glob(os.path.join(scan_path, "**/*.py"), recursive=True):
                    analyze_file(py_file)

            # Group by exception type
            by_type = {}
            for h in handlers:
                for exc_type in h["exception_types"]:
                    if exc_type not in by_type:
                        by_type[exc_type] = []
                    by_type[exc_type].append(h)

            return self._json_response({
                "handlers": handlers,
                "total_handlers": len(handlers),
                "by_exception_type": {k: len(v) for k, v in by_type.items()},
                "bare_excepts": [h for h in handlers if h["is_bare_except"]],
                "bare_except_count": len([h for h in handlers if h["is_bare_except"]]),
            })

        except Exception as e:
            return self._error_response(f"Find exception handlers failed: {e}", 500)

    async def handle_definition(self, request: web.Request) -> web.Response:
        """Get definition location of a symbol."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_definition(file_path, line, column)

            if not result:
                return self._json_response({"locations": [], "message": "No definition found"})

            if isinstance(result, list):
                locations = [format_location(loc) for loc in result]
            else:
                locations = [format_location(result)]

            return self._json_response({"locations": locations})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_references(self, request: web.Request) -> web.Response:
        """Find all references to a symbol."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_references(file_path, line, column)

            if not result:
                return self._json_response({"references": [], "count": 0})

            locations = [format_location(loc) for loc in result]
            return self._json_response({"references": locations, "count": len(locations)})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_hover(self, request: web.Request) -> web.Response:
        """Get hover info (type, docs) at position."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_hover(file_path, line, column)
            return self._json_response({"hover": format_hover(result)})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_rename(self, request: web.Request) -> web.Response:
        """Get rename edits for a symbol."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")
        new_name = body.get("newName")

        if not all([file_path, line, column, new_name]):
            return self._error_response("Required: filePath, line, column, newName")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.rename_symbol(file_path, line, column, new_name)

            if not result:
                return self._json_response({"edits": None, "message": "Rename not possible"})

            return self._json_response({"edits": result})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_diagnostics(self, request: web.Request) -> web.Response:
        """Get diagnostics for a file."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        if not file_path:
            return self._error_response("Required: filePath")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_diagnostics(file_path)

            diagnostics = []
            for diag in result:
                severity_map = {1: "error", 2: "warning", 3: "info", 4: "hint"}
                severity = severity_map.get(diag.get("severity", 3), "info")
                range_ = diag.get("range", {})
                start = range_.get("start", {})
                diagnostics.append({
                    "line": start.get("line", 0) + 1,
                    "column": start.get("character", 0) + 1,
                    "severity": severity,
                    "message": diag.get("message", ""),
                })

            return self._json_response({"diagnostics": diagnostics, "count": len(diagnostics)})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_file_structure(self, request: web.Request) -> web.Response:
        """Get structure/outline of a file using AST (hierarchical, not flat LSP).

        Parameters:
            filePath: Path to the Python file
            depth: Max depth to traverse (None = unlimited, 0 = top-level only)
            symbolTypes: List of types to include (default: all)
                        Types: class, function, method, async_function, async_method, variable, constant
            symbol: Filter to children of this symbol name
            visibility: Filter by visibility (public, protected, private, dunder)
        """
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        max_depth = body.get("depth")  # None = unlimited
        symbol_types = body.get("symbolTypes")  # List of types to include
        target_symbol = body.get("symbol")  # Filter to children of this symbol
        visibility_filter = body.get("visibility")  # List of visibility levels to show

        if not file_path:
            return self._error_response("Required: filePath")

        # Normalize visibility filter
        allowed_visibility = None
        if visibility_filter:
            if isinstance(visibility_filter, str):
                allowed_visibility = {visibility_filter}
            else:
                allowed_visibility = set(visibility_filter)

        # Type definitions
        ALL_TYPES = {"class", "function", "method", "async_function", "async_method",
                     "property", "staticmethod", "classmethod", "variable", "constant", "assignment"}

        # Normalize symbol types filter
        if symbol_types:
            if isinstance(symbol_types, str):
                allowed_types = {symbol_types}
            else:
                allowed_types = set(symbol_types)
        else:
            allowed_types = ALL_TYPES  # default: return everything

        def get_allowed_types(depth: int, for_navigation: bool = False) -> set:
            """Get allowed types for a specific depth."""
            return allowed_types

        try:
            import ast

            with open(file_path, 'r') as f:
                code = f.read()

            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return self._error_response(f"Syntax error: {e}", 400)

            def get_visibility(name: str) -> str:
                """Determine visibility from Python naming conventions."""
                if name.startswith('__') and name.endswith('__'):
                    return "dunder"  # Magic/dunder methods
                elif name.startswith('__'):
                    return "private"  # Name mangled
                elif name.startswith('_'):
                    return "protected"  # Convention for internal use
                return "public"

            def get_decorators(node) -> list[str]:
                """Extract decorator names from a node."""
                decorators = []
                for dec in getattr(node, 'decorator_list', []):
                    if isinstance(dec, ast.Name):
                        decorators.append(dec.id)
                    elif isinstance(dec, ast.Attribute):
                        decorators.append(ast.unparse(dec) if hasattr(ast, 'unparse') else dec.attr)
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name):
                            decorators.append(dec.func.id)
                        elif isinstance(dec.func, ast.Attribute):
                            decorators.append(ast.unparse(dec.func) if hasattr(ast, 'unparse') else dec.func.attr)
                return decorators

            def get_type_annotation(node) -> str | None:
                """Extract type annotation as string."""
                if node is None:
                    return None
                try:
                    return ast.unparse(node) if hasattr(ast, 'unparse') else None
                except Exception:
                    return None

            def extract_node(node, depth: int = 0, parent_class: str | None = None, for_navigation: bool = False) -> dict | None:
                """Extract symbol info from AST node with proper hierarchy."""
                # Check depth limit (skip if navigating to find a parent)
                if not for_navigation and max_depth is not None and depth > max_depth:
                    return None

                allowed = get_allowed_types(depth, for_navigation=for_navigation)
                result = None

                if isinstance(node, ast.ClassDef):
                    if "class" in allowed:
                        result = {
                            "name": node.name,
                            "kind": "class",
                            "line": node.lineno,
                            "endLine": node.end_lineno,
                            "visibility": get_visibility(node.name),
                        }
                        if node.bases:
                            result["bases"] = [ast.unparse(b) if hasattr(ast, 'unparse') else str(b) for b in node.bases]
                        # Add decorators
                        decorators = get_decorators(node)
                        if decorators:
                            result["decorators"] = decorators
                        # Process children (methods, nested classes, class variables)
                        children = []
                        for item in node.body:
                            child = extract_node(item, depth + 1, parent_class=node.name, for_navigation=for_navigation)
                            if child:
                                children.append(child)
                        if children:
                            result["children"] = children

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_async = isinstance(node, ast.AsyncFunctionDef)
                    is_method = parent_class is not None

                    # Determine base kind
                    if is_method:
                        kind = "async_method" if is_async else "method"
                    else:
                        kind = "async_function" if is_async else "function"

                    # Detect decorator-based kinds BEFORE checking allowed types
                    decorators = get_decorators(node)
                    if "property" in decorators:
                        kind = "property"
                    elif "staticmethod" in decorators:
                        kind = "staticmethod"
                    elif "classmethod" in decorators:
                        kind = "classmethod"

                    if kind in allowed:
                        # Build args with type annotations
                        args_info = []
                        for arg in node.args.args:
                            arg_str = arg.arg
                            if arg.annotation:
                                type_ann = get_type_annotation(arg.annotation)
                                if type_ann:
                                    arg_str = f"{arg.arg}: {type_ann}"
                            args_info.append(arg_str)

                        result = {
                            "name": node.name,
                            "kind": kind,
                            "line": node.lineno,
                            "endLine": node.end_lineno,
                            "visibility": get_visibility(node.name),
                            "args": args_info,
                        }

                        # Add return type
                        if node.returns:
                            return_type = get_type_annotation(node.returns)
                            if return_type:
                                result["returns"] = return_type

                        # Add decorators
                        if decorators:
                            result["decorators"] = decorators

                        # Process nested functions/classes
                        children = []
                        for item in node.body:
                            child = extract_node(item, depth + 1, for_navigation=for_navigation)
                            if child:
                                children.append(child)
                        if children:
                            result["children"] = children

                elif isinstance(node, ast.Assign):
                    # Module-level or class-level assignments
                    if "variable" in allowed or "constant" in allowed or "assignment" in allowed:
                        names = []
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                names.append(target.id)
                            elif isinstance(target, ast.Tuple):
                                for elt in target.elts:
                                    if isinstance(elt, ast.Name):
                                        names.append(elt.id)
                        if names:
                            # Check if it's a constant (ALL_CAPS)
                            is_constant = all(n.isupper() or n.startswith('_') for n in names)
                            kind = "constant" if is_constant and "constant" in allowed else "variable"
                            if kind in allowed:
                                result = {
                                    "name": ", ".join(names),
                                    "kind": kind,
                                    "line": node.lineno,
                                    "visibility": get_visibility(names[0]) if names else "public",
                                }

                elif isinstance(node, ast.AnnAssign):
                    # Annotated assignments
                    if "variable" in allowed:
                        if isinstance(node.target, ast.Name):
                            name = node.target.id
                            result = {
                                "name": name,
                                "kind": "variable",
                                "line": node.lineno,
                                "visibility": get_visibility(name),
                            }
                            # Add type annotation
                            if node.annotation:
                                type_ann = get_type_annotation(node.annotation)
                                if type_ann:
                                    result["type"] = type_ann

                # Apply visibility filter (skip when navigating)
                if result and not for_navigation and allowed_visibility:
                    if result.get("visibility") not in allowed_visibility:
                        return None

                return result

            def find_symbol(symbols: list, name: str) -> dict | None:
                """Find a symbol by name in the tree. Supports dot notation for nested symbols."""
                parts = name.split(".")
                current_symbols = symbols
                result = None
                for part in parts:
                    result = None
                    for sym in current_symbols:
                        if sym.get("name") == part:
                            result = sym
                            current_symbols = sym.get("children", [])
                            break
                    if result is None:
                        return None
                return result

            # If parent specified, we need to navigate to find it first
            if target_symbol:
                # Extract full tree for navigation (ignore depth/type filters)
                nav_symbols = []
                for node in ast.iter_child_nodes(tree):
                    sym = extract_node(node, depth=0, for_navigation=True)
                    if sym:
                        nav_symbols.append(sym)

                # Find the parent symbol
                parent = find_symbol(nav_symbols, target_symbol)
                if parent is None:
                    return self._json_response({"symbols": [], "error": f"Symbol '{target_symbol}' not found"})

                # Now extract children with proper filtering
                # Find the corresponding AST node for the parent
                parent_line = parent.get("line", 0)

                def find_ast_node(node, target_line: int):
                    """Find AST node at the given line."""
                    if hasattr(node, 'lineno') and node.lineno == target_line:
                        return node
                    for child in ast.iter_child_nodes(node):
                        found = find_ast_node(child, target_line)
                        if found:
                            return found
                    return None

                parent_ast = find_ast_node(tree, parent_line)
                if parent_ast is None:
                    # Fallback: return unfiltered children
                    symbols = parent.get("children", [])
                else:
                    # Re-extract children with proper depth/type filtering
                    symbols = []
                    for item in getattr(parent_ast, 'body', []):
                        # Depth 0 here because these are the immediate children of the parent
                        child = extract_node(item, depth=0, parent_class=parent.get("name") if parent.get("kind") == "class" else None)
                        if child:
                            symbols.append(child)
            else:
                # No parent specified - extract top-level symbols
                symbols = []
                for node in ast.iter_child_nodes(tree):
                    sym = extract_node(node, depth=0)
                    if sym:
                        symbols.append(sym)

            return self._json_response({"symbols": symbols})

        except FileNotFoundError:
            return self._error_response(f"File not found: {file_path}", 404)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_symbol_search(self, request: web.Request) -> web.Response:
        """Search for symbols across workspace."""
        self._request_count += 1
        body = await self._get_json_body(request)

        query = body.get("query")
        index_paths = body.get("indexPaths", [])
        symbol_type = body.get("symbolType")

        if not query:
            return self._error_response("Required: query")

        try:
            # Index requested files first
            indexed_count = 0
            for path in index_paths:
                try:
                    await self._ensure_indexed(path)
                    indexed_count += 1
                except Exception:
                    pass

            if indexed_count > 0:
                await asyncio.sleep(0.3)  # Let pyright process

            filter_kind = None
            if symbol_type:
                filter_kind = SYMBOL_KIND_REVERSE.get(symbol_type.lower())

            result = await self.lsp_client.get_workspace_symbols(query)

            symbols = []
            for sym in result:
                kind_num = sym.get("kind", 0)
                if filter_kind is not None and kind_num != filter_kind:
                    continue

                location = sym.get("location", {})
                uri = location.get("uri", "")
                path = uri.replace("file://", "")
                range_ = location.get("range", {})
                start = range_.get("start", {})

                symbols.append({
                    "name": sym.get("name", "?"),
                    "kind": SYMBOL_KIND_MAP.get(kind_num, "unknown"),
                    "path": path,
                    "line": start.get("line", 0) + 1,
                    "container": sym.get("containerName", ""),
                })

            # Format for display
            formatted_lines = []
            for s in symbols:
                container = f" in {s['container']}" if s['container'] else ""
                formatted_lines.append(f"{s['kind']} {s['name']}{container} ({s['path']}:{s['line']})")

            return self._json_response({
                "symbols": symbols,
                "formatted": "\n".join(formatted_lines) if formatted_lines else "No symbols found",
                "count": len(symbols),
                "indexed_before_search": indexed_count,
            })

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    # --- Navigation handlers ---

    async def handle_declaration(self, request: web.Request) -> web.Response:
        """Get declaration location."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_declaration(file_path, line, column)

            if not result:
                return self._json_response({"locations": [], "message": "No declaration found"})

            if isinstance(result, list):
                locations = [format_location(loc) for loc in result]
            else:
                locations = [format_location(result)]

            return self._json_response({"locations": locations})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_type_definition(self, request: web.Request) -> web.Response:
        """Get type definition location (jump to type's definition)."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_type_definition(file_path, line, column)

            if not result:
                return self._json_response({"locations": [], "message": "No type definition found"})

            if isinstance(result, list):
                locations = [format_location(loc) for loc in result]
            else:
                locations = [format_location(result)]

            return self._json_response({"locations": locations})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_implementation(self, request: web.Request) -> web.Response:
        """Find implementations of an interface/abstract class."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_implementation(file_path, line, column)

            if not result:
                return self._json_response({"implementations": [], "count": 0})

            locations = [format_location(loc) for loc in result]
            return self._json_response({"implementations": locations, "count": len(locations)})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    # --- Information handlers ---

    async def handle_signature_help(self, request: web.Request) -> web.Response:
        """Get function signature/parameter info."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_signature_help(file_path, line, column)

            if not result:
                return self._json_response({"signatures": [], "message": "No signature help available"})

            # Format signatures for display
            signatures = []
            for sig in result.get("signatures", []):
                params = [p.get("label", "") for p in sig.get("parameters", [])]
                signatures.append({
                    "label": sig.get("label", ""),
                    "documentation": sig.get("documentation", {}).get("value", "") if isinstance(sig.get("documentation"), dict) else sig.get("documentation", ""),
                    "parameters": params,
                })

            return self._json_response({
                "signatures": signatures,
                "activeSignature": result.get("activeSignature", 0),
                "activeParameter": result.get("activeParameter", 0),
            })

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_document_highlight(self, request: web.Request) -> web.Response:
        """Highlight all occurrences of symbol in the same file."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_document_highlight(file_path, line, column)

            if not result:
                return self._json_response({"highlights": [], "count": 0})

            highlight_kinds = {1: "text", 2: "read", 3: "write"}
            highlights = []
            for h in result:
                range_ = h.get("range", {})
                start = range_.get("start", {})
                end = range_.get("end", {})
                highlights.append({
                    "startLine": start.get("line", 0) + 1,
                    "startColumn": start.get("character", 0) + 1,
                    "endLine": end.get("line", 0) + 1,
                    "endColumn": end.get("character", 0) + 1,
                    "kind": highlight_kinds.get(h.get("kind", 1), "text"),
                })

            return self._json_response({"highlights": highlights, "count": len(highlights)})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    # --- Structure handlers ---

    async def handle_folding_ranges(self, request: web.Request) -> web.Response:
        """Get collapsible code regions (uses AST-based fallback if LSP unavailable)."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        if not file_path:
            return self._error_response("Required: filePath")

        # Try LSP first
        lsp_result = None
        try:
            await self._ensure_indexed(file_path)
            lsp_result = await self.lsp_client.get_folding_ranges(file_path)
        except Exception:
            pass  # Will use AST fallback

        if lsp_result:
            kind_map = {"comment": "comment", "imports": "imports", "region": "region"}
            ranges = []
            for r in lsp_result:
                ranges.append({
                    "startLine": r.get("startLine", 0) + 1,
                    "endLine": r.get("endLine", 0) + 1,
                    "kind": kind_map.get(r.get("kind"), "region"),
                })
            return self._json_response({"ranges": ranges, "count": len(ranges), "source": "lsp"})

        # AST-based fallback
        try:
            import ast
            with open(file_path, 'r') as f:
                code = f.read()

            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                return self._error_response(f"Syntax error: {e}", 400)

            ranges = []

            # Walk AST to find foldable regions
            for node in ast.walk(tree):
                kind = None
                start_line = None
                end_line = None

                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "function"
                    start_line = node.lineno
                    end_line = node.end_lineno
                elif isinstance(node, ast.ClassDef):
                    kind = "class"
                    start_line = node.lineno
                    end_line = node.end_lineno
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    kind = "for"
                    start_line = node.lineno
                    end_line = node.end_lineno
                elif isinstance(node, ast.While):
                    kind = "while"
                    start_line = node.lineno
                    end_line = node.end_lineno
                elif isinstance(node, ast.If):
                    kind = "if"
                    start_line = node.lineno
                    end_line = node.end_lineno
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    kind = "with"
                    start_line = node.lineno
                    end_line = node.end_lineno
                elif isinstance(node, ast.Try):
                    kind = "try"
                    start_line = node.lineno
                    end_line = node.end_lineno
                elif isinstance(node, ast.Match):
                    kind = "match"
                    start_line = node.lineno
                    end_line = node.end_lineno

                if kind and start_line and end_line and end_line > start_line:
                    ranges.append({
                        "startLine": start_line,
                        "endLine": end_line,
                        "kind": kind,
                    })

            # Find import groups (consecutive import lines)
            import_lines = []
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    import_lines.append((node.lineno, node.end_lineno or node.lineno))

            if import_lines:
                import_lines.sort()
                groups = []
                start, end = import_lines[0]
                for i in range(1, len(import_lines)):
                    curr_start, curr_end = import_lines[i]
                    if curr_start <= end + 1:  # Consecutive or adjacent
                        end = max(end, curr_end)
                    else:
                        groups.append((start, end))
                        start, end = curr_start, curr_end
                groups.append((start, end))

                for start, end in groups:
                    if end > start:
                        ranges.append({
                            "startLine": start,
                            "endLine": end,
                            "kind": "imports",
                        })

            # Sort by start line
            ranges.sort(key=lambda r: (r["startLine"], -r["endLine"]))

            return self._json_response({
                "ranges": ranges,
                "count": len(ranges),
                "source": "ast",
            })

        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_selection_ranges(self, request: web.Request) -> web.Response:
        """Get smart selection expansion ranges."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        positions = body.get("positions", [])

        if not file_path:
            return self._error_response("Required: filePath")
        if not positions:
            return self._error_response("Required: positions (array of {line, column})")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_selection_ranges(file_path, positions)

            if not result:
                return self._json_response({"ranges": []})

            def flatten_selection(sel, depth=0):
                """Flatten nested selection ranges."""
                ranges = []
                if sel:
                    range_ = sel.get("range", {})
                    start = range_.get("start", {})
                    end = range_.get("end", {})
                    ranges.append({
                        "depth": depth,
                        "startLine": start.get("line", 0) + 1,
                        "startColumn": start.get("character", 0) + 1,
                        "endLine": end.get("line", 0) + 1,
                        "endColumn": end.get("character", 0) + 1,
                    })
                    if sel.get("parent"):
                        ranges.extend(flatten_selection(sel["parent"], depth + 1))
                return ranges

            all_ranges = []
            for sel in result:
                all_ranges.append(flatten_selection(sel))

            return self._json_response({"ranges": all_ranges})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    # --- Call Hierarchy handlers ---

    async def handle_call_hierarchy(self, request: web.Request) -> web.Response:
        """Get incoming and outgoing calls for a function."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")
        direction = body.get("direction", "both")  # "incoming", "outgoing", or "both"

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)

            # First, prepare the call hierarchy item
            items = await self.lsp_client.prepare_call_hierarchy(file_path, line, column)

            if not items:
                return self._json_response({
                    "item": None,
                    "incoming": [],
                    "outgoing": [],
                    "message": "No call hierarchy available at this position"
                })

            item = items[0]  # Take the first item

            result = {
                "item": {
                    "name": item.get("name", ""),
                    "kind": SYMBOL_KIND_MAP.get(item.get("kind", 0), "unknown"),
                    "path": item.get("uri", "").replace("file://", ""),
                    "line": item.get("range", {}).get("start", {}).get("line", 0) + 1,
                },
                "incoming": [],
                "outgoing": [],
            }

            # Get incoming calls (who calls this?)
            if direction in ("incoming", "both"):
                incoming = await self.lsp_client.get_incoming_calls(item)
                for call in incoming:
                    from_item = call.get("from", {})
                    result["incoming"].append({
                        "name": from_item.get("name", ""),
                        "kind": SYMBOL_KIND_MAP.get(from_item.get("kind", 0), "unknown"),
                        "path": from_item.get("uri", "").replace("file://", ""),
                        "line": from_item.get("range", {}).get("start", {}).get("line", 0) + 1,
                    })

            # Get outgoing calls (what does this call?)
            if direction in ("outgoing", "both"):
                outgoing = await self.lsp_client.get_outgoing_calls(item)
                for call in outgoing:
                    to_item = call.get("to", {})
                    result["outgoing"].append({
                        "name": to_item.get("name", ""),
                        "kind": SYMBOL_KIND_MAP.get(to_item.get("kind", 0), "unknown"),
                        "path": to_item.get("uri", "").replace("file://", ""),
                        "line": to_item.get("range", {}).get("start", {}).get("line", 0) + 1,
                    })

            return self._json_response(result)

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    # --- Code Intelligence handlers ---

    async def handle_completion(self, request: web.Request) -> web.Response:
        """Get code completions at position."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        line = body.get("line")
        column = body.get("column")
        limit = body.get("limit", 50)  # Limit number of completions

        if not all([file_path, line, column]):
            return self._error_response("Required: filePath, line, column")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_completion(file_path, line, column)

            items = result.get("items", []) if isinstance(result, dict) else result or []

            completions = []
            for item in items[:limit]:
                kind_map = {
                    1: "text", 2: "method", 3: "function", 4: "constructor",
                    5: "field", 6: "variable", 7: "class", 8: "interface",
                    9: "module", 10: "property", 11: "unit", 12: "value",
                    13: "enum", 14: "keyword", 15: "snippet", 16: "color",
                    17: "file", 18: "reference", 19: "folder", 20: "enum_member",
                    21: "constant", 22: "struct", 23: "event", 24: "operator",
                    25: "type_parameter",
                }
                completions.append({
                    "label": item.get("label", ""),
                    "kind": kind_map.get(item.get("kind", 1), "text"),
                    "detail": item.get("detail", ""),
                    "documentation": item.get("documentation", {}).get("value", "") if isinstance(item.get("documentation"), dict) else item.get("documentation", ""),
                    "insertText": item.get("insertText", item.get("label", "")),
                })

            return self._json_response({
                "completions": completions,
                "count": len(completions),
                "isIncomplete": result.get("isIncomplete", False) if isinstance(result, dict) else False,
            })

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_code_actions(self, request: web.Request) -> web.Response:
        """Get available code actions (quick fixes, refactors)."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        start_line = body.get("startLine") or body.get("line")
        start_col = body.get("startColumn") or body.get("column") or 1
        end_line = body.get("endLine") or start_line
        end_col = body.get("endColumn") or start_col

        if not all([file_path, start_line]):
            return self._error_response("Required: filePath, startLine (or line)")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_code_actions(
                file_path, start_line, start_col, end_line, end_col
            )

            if not result:
                return self._json_response({"actions": [], "count": 0})

            action_kind_map = {
                "quickfix": "Quick Fix",
                "refactor": "Refactor",
                "refactor.extract": "Extract",
                "refactor.inline": "Inline",
                "refactor.rewrite": "Rewrite",
                "source": "Source Action",
                "source.organizeImports": "Organize Imports",
            }

            actions = []
            for action in result:
                kind = action.get("kind", "")
                actions.append({
                    "title": action.get("title", ""),
                    "kind": kind,
                    "kindLabel": action_kind_map.get(kind, kind),
                    "isPreferred": action.get("isPreferred", False),
                    "edit": action.get("edit"),  # WorkspaceEdit if available
                })

            return self._json_response({"actions": actions, "count": len(actions)})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    async def handle_code_lens(self, request: web.Request) -> web.Response:
        """Get code lens (inline hints like reference counts)."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        if not file_path:
            return self._error_response("Required: filePath")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_code_lens(file_path)

            if not result:
                return self._json_response({"lenses": [], "count": 0})

            lenses = []
            for lens in result:
                range_ = lens.get("range", {})
                start = range_.get("start", {})
                command = lens.get("command", {})
                lenses.append({
                    "line": start.get("line", 0) + 1,
                    "command": command.get("title", ""),
                    "commandId": command.get("command", ""),
                })

            return self._json_response({"lenses": lenses, "count": len(lenses)})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    # --- Formatting handlers ---

    async def handle_formatting(self, request: web.Request) -> web.Response:
        """Format entire document using ruff (preferred) or black."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        apply = body.get("apply", False)
        if not file_path:
            return self._error_response("Required: filePath")

        try:
            import subprocess
            import shutil

            # Read original content
            with open(file_path, 'r') as f:
                original = f.read()

            # Try ruff first, then black
            formatted = None
            formatter_used = None

            if shutil.which("ruff"):
                result = subprocess.run(
                    ["ruff", "format", "--stdin-filename", file_path, "-"],
                    input=original,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    formatted = result.stdout
                    formatter_used = "ruff"

            if formatted is None and shutil.which("black"):
                result = subprocess.run(
                    ["black", "--quiet", "-"],
                    input=original,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    formatted = result.stdout
                    formatter_used = "black"

            if formatted is None:
                return self._error_response("No formatter available. Install ruff or black.", 500)

            if formatted == original:
                return self._json_response({
                    "formatted": False,
                    "message": "File is already formatted",
                    "formatter": formatter_used,
                })

            # Apply changes if requested
            if apply:
                with open(file_path, 'w') as f:
                    f.write(formatted)

            # Show diff summary
            original_lines = original.splitlines()
            formatted_lines = formatted.splitlines()

            return self._json_response({
                "formatted": True,
                "formatter": formatter_used,
                "applied": apply,
                "original_lines": len(original_lines),
                "formatted_lines": len(formatted_lines),
                "preview": formatted[:2000] + ("..." if len(formatted) > 2000 else ""),
            })

        except Exception as e:
            return self._error_response(f"Formatting failed: {e}", 500)

    async def handle_range_formatting(self, request: web.Request) -> web.Response:
        """Format a specific range."""
        self._request_count += 1
        body = await self._get_json_body(request)

        file_path = body.get("filePath")
        start_line = body.get("startLine")
        start_col = body.get("startColumn", 1)
        end_line = body.get("endLine")
        end_col = body.get("endColumn", 1)

        if not all([file_path, start_line, end_line]):
            return self._error_response("Required: filePath, startLine, endLine")

        try:
            await self._ensure_indexed(file_path)
            result = await self.lsp_client.get_range_formatting(
                file_path, start_line, start_col, end_line, end_col
            )

            if not result:
                return self._json_response({"edits": [], "message": "No formatting changes needed"})

            edits = []
            for edit in result:
                range_ = edit.get("range", {})
                start = range_.get("start", {})
                end = range_.get("end", {})
                edits.append({
                    "startLine": start.get("line", 0) + 1,
                    "startColumn": start.get("character", 0) + 1,
                    "endLine": end.get("line", 0) + 1,
                    "endColumn": end.get("character", 0) + 1,
                    "newText": edit.get("newText", ""),
                })

            return self._json_response({"edits": edits, "count": len(edits)})

        except asyncio.TimeoutError:
            return self._error_response("LSP request timed out", 504)
        except Exception as e:
            return self._error_response(str(e), 500)

    # --- Management handlers ---

    async def handle_index(self, request: web.Request) -> web.Response:
        """Force index specific files."""
        self._request_count += 1
        body = await self._get_json_body(request)

        paths = body.get("paths", [])
        if not paths:
            return self._error_response("Required: paths (array of file paths)")

        indexed = []
        failed = []
        for path in paths:
            try:
                await self.lsp_client.open_file(path)
                self._indexed_files.add(path)
                indexed.append(path)
            except Exception as e:
                failed.append({"path": path, "error": str(e)})

        return self._json_response({
            "indexed": indexed,
            "failed": failed,
            "total_indexed": len(self._indexed_files),
        })

    async def run(self):
        """Run the HTTP server."""
        await self.start()
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", self.port)
        await site.start()

        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
            await runner.cleanup()


async def main():
    parser = argparse.ArgumentParser(description="LSP HTTP Daemon - Shared pyright instance for all agents")
    parser.add_argument("--port", type=int, default=7900, help="HTTP port (default: 7900)")
    parser.add_argument("--workspace", type=str, default=os.getcwd(), help="Workspace root (default: cwd)")
    args = parser.parse_args()

    daemon = AgentsIDEDaemon(workspace=args.workspace, port=args.port)

    try:
        await daemon.run()
    except KeyboardInterrupt:
        print("\nShutting down...", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
