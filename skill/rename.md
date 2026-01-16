# rename

```python
rename(operations, phase="apply", file_map=None)
```

Batch rename symbols across files with filters.

## Parameters
- **operations**: List of tuples `(filePath, line, column, newName, filters?)`
- **filters**: Optional dict with:
  - `include_files/exclude_files`: glob patterns
  - `include_lines/exclude_lines`: list of `(start, end)` ranges. `end=None` means no upper bound.
- **phase**: `"preview"` | `"changes"` | `"apply"`
- **file_map**: Optional dict mapping short names to full paths

## Example

```python
rename([
    ("a", 10, 5, "new_name"),
    ("b", 20, 3, "other", {
        "include_files": ["*/models/*.py"],
        "exclude_files": ["*_test.py"],
        "include_lines": [(100, None)],  # line 100 to end of file
        "exclude_lines": [(50, 60)]
    }),
], phase="apply", file_map={"a": "/a.py", "b": "/b.py"})
```

### Batch rename with filters
```python
rename([
    ("/models/user.py", 15, 10, "user_id", {
        "exclude_files": ["*_test.py", "*_mock.py"],
        "exclude_lines": [(1, 10)]  # skip imports
    })
], phase="preview")  # check first, then phase="apply"
```
