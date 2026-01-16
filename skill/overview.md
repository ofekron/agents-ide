# Why Use agents-ide Tools

## structure vs Read
- **Token savings**: Get file outline without reading entire content
- **Filtering**: Only classes, only functions, only lambdas
- **Package view**: One call for all files in package
- **AST-powered**: Find lambdas (impossible with Grep)

## code_search vs Grep
- **Structured results**: Returns symbol line ranges, not just matching lines
- **Semantic filters**: Filter by symbolTypes, visibility, argName
- **Actionable output**: file → match → line-range ready for Read/Edit

## symbol_search vs Glob+Grep
- **Fuzzy matching**: Find "MyClss" when you meant "MyClass"
- **Workspace-wide**: No need to know file patterns

## Refactoring vs Edit
- **rename/rename_local**: Batch rename with file/line filters
- **move**: Moves symbol and updates all imports
- **change_signature**: Updates all call sites
- **find_and_replace**: Batch regex/literal replace with preview
- **toggle_comment**: Batch comment/uncomment
