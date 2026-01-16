# Understand a Codebase

Quickly explore and understand unfamiliar code.

## Tools Used
- `structure` - Get file/package overview
- `dependency_graph` - Visualize module relationships
- `dependencies` - See what a file imports/exports
- `symbol_search` - Find symbols by name
- `code_search` - Find patterns in code

## Workflow

### 1. Get high-level structure
```python
# Package overview
structure("/src", depth=1)

# Deeper dive
structure("/src/core", depth=2)
```

### 2. Understand dependencies
```python
# Generate dependency graph
dependency_graph("/src", depth=3)

# Check specific file
dependencies("/src/main.py")
```

### 3. Find entry points
```python
code_search("if __name__", path="/src")
code_search("def main", symbolTypes="function")
```

### 4. Trace specific functionality
```python
# Find where something is defined
symbol_search("DatabaseConnection")

# Find where it's used
code_search("DatabaseConnection", path="/src")
```

## Example: Explore new project

```python
# 1. Top-level structure
structure(".", depth=1)
# Shows: src/, tests/, scripts/

# 2. Main source structure
structure("/src", depth=2)
# Shows modules and their classes/functions

# 3. Find the entry point
code_search("def main", symbolTypes="function")
# Found: /src/app.py:15

# 4. See app.py dependencies
dependencies("/src/app.py")
# imports: config, database, handlers

# 5. Trace database module
structure("/src/database", depth=2)
dependencies("/src/database/__init__.py")

# 6. Find all API endpoints
code_search("@app.route", path="/src")
```

## Quick exploration commands

```python
# All classes in a package
structure("/src/models", symbolTypes="class")

# All async functions
structure("/src", symbolTypes="async_function", depth=2)

# Find tests for a module
code_search("test.*process", symbolTypes="function", path="/tests")
```

## Tips
- Start with `structure` at depth=1, then drill down
- Use `dependency_graph` to see the big picture
- `symbol_search` for "I know the name"
- `code_search` for "I know the pattern"
