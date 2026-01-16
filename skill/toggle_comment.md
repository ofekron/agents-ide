# toggle_comment

```python
toggle_comment(operations, file_map=None)
```

Toggle comment on lines in batch.

## Parameters
- **operations**: List of tuples `(filePath, startLine, endLine)`
  - `endLine=None` means end of file
- **file_map**: Optional dict mapping short names to full paths

## Example

```python
toggle_comment([
    ("a", 10, 20),
    ("b", 50, None),  # line 50 to end of file
], file_map={"a": "/a.py", "b": "/b.py"})
```
