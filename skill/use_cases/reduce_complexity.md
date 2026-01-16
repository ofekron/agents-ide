# Reduce Code Complexity

Identify and fix complex code using metrics and refactoring tools.

## Tools Used
- `complexity` - Find complex functions (cyclomatic complexity)
- `structure` - Understand code structure
- `move` - Extract to new module
- `rename` - Rename for clarity

## Workflow

### 1. Identify complex code
```python
complexity("/src/processor.py")
```

Output shows ranks:
- A (1-5): Simple
- B (6-10): Moderate
- C (11-20): Complex - consider refactoring
- D-F (21+): Refactor required

### 2. Analyze structure
```python
structure("/src/processor.py", symbol="complex_function")
```

### 3. Extract helper functions
Break large function into smaller pieces, then move if needed:
```python
move(
    "/src/processor.py",
    "_validate_input",
    "/src/validators.py",
    phase="apply"
)
```

### 4. Verify improvement
```python
complexity("/src/processor.py")
```

## Example: Refactor rank D function

```python
# 1. Check complexity
complexity("/src/handler.py")
# Shows: handle_request - complexity 28 (D)

# 2. See nested structure
structure("/src/handler.py", symbol="handle_request")

# 3. Extract validation logic
# (manually create _validate_request function)

# 4. Extract processing logic
# (manually create _process_request function)

# 5. Move to dedicated modules
move("/src/handler.py", "_validate_request", "/src/validation.py")
move("/src/handler.py", "_process_request", "/src/processing.py")

# 6. Verify
complexity("/src/handler.py")
# Shows: handle_request - complexity 8 (B)
```

## Complexity Reduction Patterns

| Pattern | Before | After |
|---------|--------|-------|
| Extract method | Nested logic | Function call |
| Early return | Deep nesting | Flat flow |
| Strategy pattern | Switch/if chains | Dispatch dict |
| Guard clauses | Nested ifs | Sequential checks |

## Tips
- Target functions with rank C or worse
- Each extracted function should do one thing
- Aim for complexity under 10 (rank A-B)
