# copy_paste

```python
copy_paste(operations, file_map=None)
```

Copy text ranges between files in batch.

## Parameters
- **operations**: List of tuples `(from_file, start_line, start_col, end_line, end_col, to_file, to_line, to_col)`
  - `end_line=None` means end of file
  - `end_col=None` means end of line
- **file_map**: Optional dict mapping short names to full paths

## Example

```python
copy_paste([
    ("src", 1, 1, 50, None, "dest", 1, 1),  # lines 1-50 from src
    ("src", 60, 1, None, None, "dest2", 1, 1),  # line 60 to end of file
], file_map={
    "src": "/path/to/source.py",
    "dest": "/path/to/dest.py",
    "dest2": "/path/to/dest2.py",
})
```
