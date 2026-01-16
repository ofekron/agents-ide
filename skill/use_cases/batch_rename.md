# Batch Rename Across Codebase

Rename symbols consistently across all files.

## Tools Used
- `symbol_search` - Find symbol definitions
- `code_search` - Find all usages
- `rename` - Batch rename with preview
- `find_and_replace` - For string/comment updates

## Workflow

### 1. Find the symbol
```python
symbol_search("OldClassName")
```

### 2. Find all usages
```python
code_search("OldClassName", path="/src")
```

### 3. Preview rename
```python
rename([
    ("/src/models.py", 15, 6, "NewClassName"),
], phase="preview")
```

### 4. Review changes
```python
rename([...], phase="changes")
```

### 5. Apply
```python
rename([...], phase="apply")
```

### 6. Update strings/comments
```python
find_and_replace([
    (("/src", True), "OldClassName", "NewClassName"),
], phase="apply")
```

## Example: Rename across package

```python
# 1. Find definition
symbol_search("DataProcessor")
# Found: /src/processing/core.py:45

# 2. Check usages
code_search("DataProcessor")
# Found in 12 files

# 3. Preview rename
rename([
    ("/src/processing/core.py", 45, 6, "RecordProcessor"),
], phase="preview")
# Shows: 12 files will be updated

# 4. See all changes
rename([
    ("/src/processing/core.py", 45, 6, "RecordProcessor"),
], phase="changes")

# 5. Apply
rename([
    ("/src/processing/core.py", 45, 6, "RecordProcessor"),
], phase="apply")

# 6. Fix strings/comments
find_and_replace([
    (("/src", True), "DataProcessor", "RecordProcessor"),
    (("/docs", True), "DataProcessor", "RecordProcessor"),
], phase="apply")
```

## Multiple renames at once

```python
rename([
    ("/src/a.py", 10, 4, "new_func_a"),
    ("/src/b.py", 20, 6, "NewClassB"),
    ("/src/c.py", 30, 4, "new_func_c"),
], phase="apply")
```

## Tips
- `rename` handles imports automatically
- Use `find_and_replace` for strings/comments (rename only does code)
- Preview first to catch unexpected changes
- Batch multiple renames in one call
