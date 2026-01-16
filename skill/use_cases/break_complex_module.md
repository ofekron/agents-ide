# Break Down a Complex Module

Systematically decompose a complex module into manageable pieces.

## Tools Used
- `complexity` - Find complexity hotspots
- `structure` - Understand module layout
- `coupling` - Identify dependencies
- `dependencies` - See import relationships
- `move` - Extract to new modules
- `rename` - Clarify naming

## Workflow

### 1. Assess complexity
```python
complexity("/src/engine.py")
```

Identify functions with rank C or worse (complexity > 10).

### 2. Map the structure
```python
structure("/src/engine.py", depth=2)
```

### 3. Analyze coupling
```python
coupling("/src/engine.py")
dependencies("/src/engine.py")
```

High efferent coupling = does too much (many dependencies).

### 4. Identify logical groups
Look for:
- Classes that belong together
- Helper functions used by one class
- Independent utilities

### 5. Extract modules
```python
# Move related pieces
move("/src/engine.py", "Parser", "/src/engine/parser.py")
move("/src/engine.py", "Executor", "/src/engine/executor.py")
move("/src/engine.py", "Cache", "/src/engine/cache.py")
```

### 6. Verify improvement
```python
complexity("/src/engine.py")
coupling("/src/engine.py")
```

## Example: Decompose 2000-line module

```python
# 1. Check complexity
complexity("/src/processor.py")
# Output:
#   process_all: 35 (E) - needs major refactor
#   validate_input: 22 (D) - needs refactor
#   parse_config: 15 (C) - consider refactor
#   ... 12 more functions

# 2. See full structure
structure("/src/processor.py")
# Shows: ProcessorEngine class with 20 methods
#        5 helper classes
#        10 module-level functions

# 3. Check coupling
coupling("/src/processor.py")
# Efferent: 25 modules (too high!)
# Afferent: 8 modules

# 4. Identify groups:
#    - Validation: validate_*, ValidationError
#    - Parsing: parse_*, Parser class
#    - Execution: execute_*, Executor class
#    - Caching: cache_*, Cache class

# 5. Create subpackage
# mkdir /src/processor/

# 6. Move groups
move("/src/processor.py", "ValidationError", "/src/processor/validation.py")
move("/src/processor.py", "validate_input", "/src/processor/validation.py")
move("/src/processor.py", "validate_output", "/src/processor/validation.py")

move("/src/processor.py", "Parser", "/src/processor/parsing.py")
move("/src/processor.py", "parse_config", "/src/processor/parsing.py")

move("/src/processor.py", "Executor", "/src/processor/execution.py")
move("/src/processor.py", "Cache", "/src/processor/cache.py")

# 7. Create __init__.py for public API
# from .validation import validate_input, ValidationError
# from .parsing import Parser
# from .execution import Executor

# 8. Verify
complexity("/src/processor/__init__.py")  # Should be simple
coupling("/src/processor/validation.py")  # Should be focused
```

## Breaking down complex functions

After extracting modules, tackle complex functions:

```python
# Find the worst offenders
complexity("/src/processor/execution.py")
# execute_all: 35 (E)

# See its structure
structure("/src/processor/execution.py", symbol="execute_all")

# Extract helpers from it
# 1. _prepare_context
# 2. _run_steps
# 3. _handle_errors
# 4. _finalize

# Move if reusable elsewhere
move("/src/processor/execution.py", "_prepare_context", "/src/processor/context.py")
```

## Signs a module needs breaking down

| Symptom | Threshold | Action |
|---------|-----------|--------|
| Lines of code | > 500 | Split by responsibility |
| Complexity (any func) | > 20 (D+) | Extract helpers |
| Efferent coupling | > 15 imports | Split by domain |
| Classes count | > 5 | One class per file |
| Functions count | > 20 | Group into submodules |

## Tips
- Extract one group at a time, test between moves
- Keep public API in `__init__.py`
- Name modules by responsibility, not implementation
- Use `dependencies` after each move to verify imports
