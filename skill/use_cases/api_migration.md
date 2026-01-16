# API Migration

Update function signatures and call sites across the codebase.

## Tools Used
- `change_signature` - Update function parameters
- `find_and_replace` - Batch update patterns
- `code_search` - Find all usages
- `rename` - Rename if API name changes

## Workflow

### 1. Find all usages
```python
code_search("old_api_call", path="/src")
```

### 2. Update the signature
```python
change_signature(
    "/src/api.py",
    "old_api_call",
    ["data: dict", "timeout: int = 30", "retry: bool = True"],
    phase="preview"
)
```

### 3. Update call sites with new args
```python
find_and_replace([
    (("/src", True), r"old_api_call\((\w+)\)", r"old_api_call(\1, timeout=60)", True),
], phase="preview")
```

### 4. Rename if needed
```python
rename([
    ("/src/api.py", 25, 4, "new_api_call"),
], phase="apply")
```

## Example: Add required parameter

```python
# Old: process(data)
# New: process(data, config)

# 1. Find all calls
code_search("process(", path="/src")
# Found 45 usages

# 2. Update signature
change_signature(
    "/src/processor.py",
    "process",
    ["data: dict", "config: Config"],
    phase="apply"
)

# 3. Update calls - add default config
find_and_replace([
    (("/src", True), r"process\(([^)]+)\)", r"process(\1, default_config)", True),
], phase="preview")

# Review changes, then apply
find_and_replace([...], phase="apply")
```

## Example: Deprecate and rename

```python
# 1. Rename old function
rename([
    ("/src/api.py", 50, 4, "_deprecated_fetch"),
], phase="apply")

# 2. Create new function with new signature
# (manual: write new_fetch function)

# 3. Update all callers
find_and_replace([
    (("/src", True), "_deprecated_fetch", "new_fetch"),
], phase="apply")
```

## Tips
- Always preview before applying
- Use regex in find_and_replace for complex patterns
- Test after each step
- For large migrations, do in batches
