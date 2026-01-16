# Refactor a Function

Rename, change signature, or move a function with all references updated.

## Tools Used
- `rename` - Rename symbol across files
- `change_signature` - Update parameters
- `move` - Move to another file
- `structure` - Understand current structure

## Workflow

### Rename a function
```python
# Preview first
rename([
    ("/src/utils.py", 15, 4, "new_name"),
], phase="preview")

# See changes
rename([...], phase="changes")

# Apply
rename([...], phase="apply")
```

### Change function signature
```python
# Add a parameter with default
change_signature(
    "/src/processor.py",
    "process_data",
    ["data: dict", "validate: bool = True"],
    phase="preview"
)
```

### Move function to another module
```python
# Move and update all imports
move(
    "/src/utils.py",
    "helper_function",
    "/src/helpers/common.py",
    phase="preview"
)
```

## Example: Full refactor

```python
# 1. Understand current state
structure("/src/old_module.py")

# 2. Rename for clarity
rename([
    ("/src/old_module.py", 20, 4, "process_records"),
], phase="apply")

# 3. Add new parameter
change_signature(
    "/src/old_module.py",
    "process_records",
    ["records: list", "batch_size: int = 100"],
    phase="apply"
)

# 4. Move to better location
move(
    "/src/old_module.py",
    "process_records",
    "/src/processing/records.py",
    phase="apply"
)
```

## Tips
- Always preview before applying
- Use `structure` to find exact line/column positions
- Combine multiple renames in one batch call
