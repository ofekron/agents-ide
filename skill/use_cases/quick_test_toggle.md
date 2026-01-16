# Quick Test With/Without Code

Toggle parts of code on/off to quickly test behavior changes.

## Tools Used
- `toggle_comment` - Comment/uncomment code blocks
- `structure` - Find code sections to toggle

## Workflow

### 1. Find the code section
```python
structure("/src/processor.py", symbolTypes="function")
```

### 2. Toggle off to test without
```python
toggle_comment([
    ("/src/processor.py", 45, 60),  # disable validation
])
```

### 3. Run tests, observe behavior

### 4. Toggle back on
```python
toggle_comment([
    ("/src/processor.py", 45, 60),  # re-enable
])
```

## Example: Test with/without caching

```python
# Find cache-related code
code_search("cache", symbolTypes="function", path="/src")

# Disable caching temporarily
toggle_comment([
    ("/src/cache.py", 10, 25),   # cache_get
    ("/src/cache.py", 27, 40),   # cache_set
])

# Run tests without cache
# ...

# Re-enable
toggle_comment([
    ("/src/cache.py", 10, 25),
    ("/src/cache.py", 27, 40),
])
```

## Tips
- Comment multiple related sections in one call
- Use `structure` to find exact line ranges
- Keep toggle pairs symmetric for easy re-enable
