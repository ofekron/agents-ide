# find_and_replace

```python
find_and_replace(operations, phase="apply", file_map=None)
```

Find and replace text in files or directories.

## Parameters
- **operations**: List of tuples `(paths, find, replace, is_regex?)`
  - `paths`: filePath, `(dirPath, recursive)`, or list of either
- **phase**: `"preview"` | `"changes"` | `"apply"`
- **file_map**: Optional dict mapping short names to full paths

## Example

```python
find_and_replace([
    ("f", "old", "new"),
    (("pkg", True), r"\bfoo\b", "bar", True),
], phase="preview", file_map={"f": "/file.py", "pkg": "/src/pkg"})
```

### Find/replace across package with preview
```python
find_and_replace([
    (("/src", True), "old_func", "new_func"),
], phase="preview")  # see counts
# then phase="changes" to see diffs
# then phase="apply" to execute
```
