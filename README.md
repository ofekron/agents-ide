# Agents IDE

AI-powered IDE tools via MCP (Model Context Protocol).

A shared LSP daemon with MCP bridge that allows AI agents to use IDE tools like code navigation, refactoring, and analysis.

## Features

- **Shared LSP Daemon**: Single pyright-langserver instance shared across all AI agents
- **MCP Bridge**: Exposes IDE tools via MCP protocol for AI agent integration
- **Code Navigation**: Go to definition, find references, hover info
- **Refactoring**: Rename symbols, change signatures, move code
- **Analysis**: Complexity metrics, dead code detection, duplicate finder

## Installation

### Quick Install (Recommended)

Clone and run the install script:

```bash
git clone https://github.com/ofekron/agents-ide.git
cd agents-ide
```

**macOS / Linux:**
```bash
./install-unix.sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File install-windows.ps1
```

### Manual Install

**Requirements:**
- Python 3.11+
- Node.js

```bash
# Install pyright LSP server
npm install -g pyright

# Install agents-ide
pip install agents-ide
```

## Usage

### As MCP Server

Add to your Claude Code settings:

```json
{
  "mcpServers": {
    "agents-ide": {
      "command": "python",
      "args": ["-m", "agents_ide"]
    }
  }
}
```

### Daemon Management

```bash
# Start the daemon
agents-ide-daemon start

# Check status
agents-ide-daemon status

# Stop the daemon
agents-ide-daemon stop
```

## Available Tools

### Structure & Search
- `structure` - Get file/package structure with filtering
- `symbol_search` - Fuzzy search for symbols workspace-wide
- `code_search` - Grep + structure for semantic search

### Refactoring
- `rename` - Batch rename symbols across files
- `rename_local` - Rename local variables
- `move` - Move symbol and update imports
- `change_signature` - Change function params and update call sites
- `find_and_replace` - Batch find/replace with preview
- `toggle_comment` - Batch comment/uncomment

### Code Quality
- `complexity` - Cyclomatic complexity analysis
- `dead_code` - Find unused code
- `duplicates` - Find duplicate code blocks
- `dependencies` - Analyze import relationships
- `coupling` - Coupling metrics
- `loc` - Lines of code statistics

## License

MIT
