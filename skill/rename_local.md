# rename_local

```python
rename_local(operations, phase="apply", file_map=None)
```

Batch rename local variables within files.

## Parameters
- **operations**: List of tuples `(filePath, line, column, newName, filters?)`
- **filters**: Optional dict with:
  - `include_lines/exclude_lines`: list of `(start, end)` ranges. `end=None` means no upper bound.
- **phase**: `"preview"` | `"changes"` | `"apply"`
- **file_map**: Optional dict mapping short names to full paths

## Example

```python
rename_local([
    ("a", 10, 5, "new_var"),
    ("b", 20, 3, "x", {"include_lines": [(10, None)]}),  # line 10 to end
], phase="apply", file_map={"a": "/a.py", "b": "/b.py"})
```
