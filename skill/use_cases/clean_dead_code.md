# Clean Up Dead Code

Find and remove unused code safely.

## Tools Used
- `dead_code` - Find unused imports, functions, variables
- `structure` - Verify what's defined
- `dependencies` - Check what imports this file
- `toggle_comment` - Disable before deleting (safe test)

## Workflow

### 1. Find dead code
```python
dead_code("/src/utils.py")
```

Output shows:
- Unused imports
- Unused functions
- Unused variables
- Unused classes

### 2. Verify it's truly unused
```python
# Check if other files import it
dependencies("/src/utils.py")

# Search for usages
code_search("function_name", path="/src")
```

### 3. Safe removal - comment first
```python
toggle_comment([
    ("/src/utils.py", 45, 50),  # unused function
])
```

### 4. Run tests

### 5. Delete if tests pass

## Example: Clean a module

```python
# 1. Scan for dead code
dead_code("/src/legacy.py")
# Output:
#   L12: unused import 'os'
#   L45: unused function 'old_helper'
#   L78: unused variable 'DEPRECATED_FLAG'

# 2. Check dependencies
dependencies("/src/legacy.py")
# See what imports this file

# 3. Search for hidden usages
code_search("old_helper")
# Confirm no usages

# 4. Comment out first
toggle_comment([
    ("/src/legacy.py", 12, 12),  # unused import
    ("/src/legacy.py", 45, 55),  # unused function
    ("/src/legacy.py", 78, 78),  # unused variable
])

# 5. Run tests
# 6. If green, delete the commented lines
```

## Batch cleanup

```python
# Find dead code across package
for file in ["/src/a.py", "/src/b.py", "/src/c.py"]:
    print(f"=== {file} ===")
    dead_code(file)
```

## Tips
- `dead_code` may have false positives (dynamic usage, __getattr__)
- Always verify with `code_search` before deleting
- Comment first, test, then delete
- Check `dependencies` to find hidden importers
