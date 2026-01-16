# Code Quality Tools

## complexity

```
complexity(filePath)
```

Analyze cyclomatic complexity and maintainability using `radon` library.

**Returns:**
- Per-function complexity with rank (A-F)
- Total and average complexity
- Maintainability index (0-100)
- Halstead metrics (effort, predicted bugs)

**Ranks:**
| Rank | Complexity | Meaning |
|------|------------|---------|
| A | 1-5 | Simple |
| B | 6-10 | Moderate |
| C | 11-20 | Complex |
| D | 21-30 | Alarming |
| E | 31-40 | Unstable |
| F | 41+ | Untestable |

## dead_code

```
dead_code(filePath)
```

Find potentially unused code using `vulture` library.

**Finds:**
- Unused imports
- Unused variables
- Unused functions
- Unused classes
- Unused attributes

## duplicates

```
duplicates(filePath, minLines=6)
```

Find duplicate code blocks (AST-based).

**Parameters:**
- **minLines**: Minimum lines for a duplicate block (default: 6)

## dependencies

```
dependencies(filePath)
```

Analyze imports and dependencies.

**Returns:**
- What the file imports
- What files import this file

## loc

```
loc(filePath)
```

Count lines of code.

**Returns:**
- Total lines
- Code lines
- Comment lines
- Blank lines

## coupling

```
coupling(filePath)
```

Analyze coupling metrics.

**Returns:**
- Afferent coupling (who depends on this)
- Efferent coupling (what this depends on)

## dependency_graph

```
dependency_graph(filePath=None, depth=3)
```

Generate import dependency graph.

**Parameters:**
- **filePath**: Starting file (default: workspace root)
- **depth**: Maximum depth to traverse (default: 3)

## Requirements

```bash
pip install vulture radon
```
