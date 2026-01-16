# symbol_search

```
symbol_search(query)
```

Fuzzy search for symbols across workspace.

## Parameters
- **query**: Symbol name to search for (supports fuzzy matching)

## Output format
```
<kind> <name> in <container> (<path>:<line>)
```

## Example

```python
symbol_search("proc")
```
```
method process in MyClass (/src/models/user.py:45)
function helper in module (/src/utils.py:12)
class Config in module (/src/config.py:8)
```
