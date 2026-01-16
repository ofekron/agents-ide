# Split a Large File

Break a large module into smaller, focused files.

## Tools Used
- `structure` - Understand current structure
- `loc` - Check file size
- `coupling` - Analyze dependencies
- `move` - Move symbols to new files
- `dependencies` - Verify after split

## Workflow

### 1. Assess the file
```python
loc("/src/monolith.py")
structure("/src/monolith.py", depth=1)
```

### 2. Identify logical groups
```python
# See all classes
structure("/src/monolith.py", symbolTypes="class")

# Check coupling
coupling("/src/monolith.py")
```

### 3. Plan the split
Group related functionality:
- Validators → `/src/validators.py`
- Models → `/src/models.py`
- Handlers → `/src/handlers.py`

### 4. Move symbols
```python
# Preview moves
move("/src/monolith.py", "Validator", "/src/validators.py", phase="preview")
move("/src/monolith.py", "UserModel", "/src/models.py", phase="preview")

# Apply
move("/src/monolith.py", "Validator", "/src/validators.py", phase="apply")
move("/src/monolith.py", "UserModel", "/src/models.py", phase="apply")
```

### 5. Verify imports updated
```python
dependencies("/src/validators.py")
dependencies("/src/models.py")
```

## Example: Split 1000-line file

```python
# 1. Check size
loc("/src/api.py")
# 1200 lines

# 2. See structure
structure("/src/api.py", symbolTypes=["class", "function"])
# Shows:
#   RequestValidator, ResponseValidator
#   UserHandler, OrderHandler, PaymentHandler
#   format_response, parse_request

# 3. Group by responsibility
# validators.py: RequestValidator, ResponseValidator
# handlers/user.py: UserHandler
# handlers/order.py: OrderHandler
# handlers/payment.py: PaymentHandler
# utils.py: format_response, parse_request

# 4. Move each
move("/src/api.py", "RequestValidator", "/src/validators.py")
move("/src/api.py", "ResponseValidator", "/src/validators.py")
move("/src/api.py", "UserHandler", "/src/handlers/user.py")
# ... etc

# 5. Verify
loc("/src/api.py")  # Should be much smaller
dependencies("/src/api.py")  # Should import from new modules
```

## Tips
- Move related symbols together
- Create `__init__.py` to re-export for backwards compatibility (if needed)
- Run tests after each move
- Target ~200-400 lines per file
