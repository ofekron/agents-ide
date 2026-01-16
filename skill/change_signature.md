# change_signature

```
change_signature(filePath, functionName, newParams, phase="apply")
```

Change function signature and update all call sites.

## Parameters
- **filePath**: Python file path
- **functionName**: Name of function
- **newParams**: New params list, e.g., `["x: int", "y: str = 'default'"]`
- **phase**: `"preview"` | `"changes"` | `"apply"`
