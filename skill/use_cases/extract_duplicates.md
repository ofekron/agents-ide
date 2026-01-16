# Extract Duplicate Code

Find duplicate code blocks and consolidate into shared functions.

## Tools Used
- `duplicates` - Find duplicate code blocks
- `structure` - Understand code structure
- `move` - Move extracted function
- `find_and_replace` - Update call sites

## Workflow

### 1. Find duplicates
```python
duplicates("/src/handlers.py", minLines=6)
```

### 2. Analyze the duplicates
```python
# Read the duplicate blocks
structure("/src/handlers.py")
```

### 3. Extract to shared function
Create new function with the common logic, then move if needed:
```python
move(
    "/src/handlers.py",
    "shared_logic",
    "/src/common.py",
    phase="apply"
)
```

### 4. Replace duplicates with calls
```python
find_and_replace([
    (("/src", True), "# duplicate block pattern", "shared_logic(args)", True),
], phase="preview")
```

## Example: Consolidate validation logic

```python
# 1. Find duplicates
duplicates("/src/api/endpoints.py")
# Output:
#   Lines 45-52 duplicated at 120-127
#   Lines 45-52 duplicated at 198-205

# 2. See what it is
# (read lines 45-52 - it's input validation)

# 3. Create shared function
# def validate_input(data):
#     ... (the common logic)

# 4. Move to validators
move("/src/api/endpoints.py", "validate_input", "/src/validators.py")

# 5. Replace all occurrences
# Update lines 45-52, 120-127, 198-205 with:
#   from validators import validate_input
#   validate_input(data)
```

## Cross-file duplicates

```python
# Check multiple files
for f in ["/src/a.py", "/src/b.py", "/src/c.py"]:
    print(f"=== {f} ===")
    duplicates(f, minLines=5)
```

## Tips
- Lower `minLines` to catch smaller duplicates
- Duplicates often indicate missing abstraction
- Parameterize differences when extracting
- Consider if duplication is intentional (sometimes OK)
