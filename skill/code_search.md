# code_search

```
code_search(pattern, symbolTypes, visibility, symbolName, argName, filePattern, maxResults, path)
```

Grep + structure: finds matches and returns containing symbol info.

## Parameters
- **pattern**: Search pattern (regex)
- **symbolTypes**: Filter by type (class, function, method, async_function, etc.)
- **visibility**: Filter by visibility (public, protected, private, dunder)
- **symbolName**: Filter by symbol name pattern (regex)
- **argName**: Filter functions/methods that have an argument matching this pattern
- **filePattern**: Glob for files (default: "*.py")
- **maxResults**: Limit results (default: 50)
- **path**: Directory to search (default: workspace root)

## Output format
```
files:
  "<path>":
    "<matching line>": <start>-<end>
count: <total>
```

## Example

```python
code_search("def.*self", symbolTypes="method", path="/src")
```
```
files:
  "/src/api.py":
    "def process(self, data):": 45-80
    "def validate(self, input):": 82-95
  "/src/utils.py":
    "def helper(x, y):": 10-25
count: 3
```

### Find functions by argument
```
code_search(pattern="def", argName="ctx")
```
