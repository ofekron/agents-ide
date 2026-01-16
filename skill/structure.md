# structure

```
structure(filePath, depth, reset_depth_per_dir, symbol, symbolTypes, visibility, include, exclude)
```

## Parameters
- **filePath**: Python file or package
- **depth**: 0=top-level, 1=children, None=unlimited
- **symbolTypes**: class, function, method, async_function, async_method, property, lambda, file, variable, constant
  - Default: class, function, method, async_function, async_method, property
- **visibility**: public, protected, private, dunder
- **include/exclude**: glob patterns (e.g., "test_*" or ["api/*", "core/*"])
- **reset_depth_per_dir**: If True, depth resets for each subdirectory (default: False)
- **symbol**: Target symbol, supports dot notation (e.g., "MyClass.method")

## Behavior
- Supports nested directories recursively
- Auto-skips: `__pycache__`, `.git`, `node_modules`, `.venv`, etc.

## Output format
```
<name>: [decorators] [async] <kind>(<args/bases>) [-> return] L<start>-<end> [visibility]
```

| Part | When shown | Examples |
|------|------------|----------|
| decorators | if present | `@mcp.tool`, `@property` |
| async | if async | `async def(...)` |
| kind | always | `def(x, y)`, `class(Base)`, `constant`, `variable` |
| return type | if annotated | `-> str`, `-> List[int]` |
| line range | always | `L10-50`, `L5` |
| visibility | if not public | `protected`, `private`, `dunder` |

## Examples

```python
structure("/src", symbolTypes=["class", "function", "constant"])
```
```
file.py:
  MAX_SIZE: constant L5
  MyClass: class(Base) L10-50
    __init__: def(self, x: int) L12-20 dunder
    process: async def(self, data: list) -> str L22-40
  helper: def(x, y) -> int L55-60
subdir/:
  other.py:
    func: @mcp.tool async def(path: str) -> str L5-20
```

### Find all lambdas
```
structure(packagePath, symbolTypes="lambda")
```

### Understand large file without reading it
```
structure(filePath, depth=0)
structure(filePath, symbol="MyClass")
```

### Explore directory tree with consistent depth
```
structure(dirPath, depth=1, reset_depth_per_dir=True)
```
