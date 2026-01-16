#!/usr/bin/env python3
"""Code generation tools: generate_class, generate_function, etc."""

from ._core import mcp, http_post, format_result


@mcp.tool()
async def generate_class(
    filePath: str,
    className: str,
    methods: list[str] = None,
    attributes: list[str] = None,
    bases: list[str] = None,
    docstring: str = None,
    phase: str = "preview"
) -> str:
    """
    Generate a new class.

    Args:
        filePath: Absolute path to the target Python file
        className: Name for the new class
        methods: List of method names to generate
        attributes: List of attribute names
        bases: List of base class names
        docstring: Class docstring
        phase: "preview", "changes", or "apply"
    """
    result = await http_post("generate_class", {
        "filePath": filePath,
        "className": className,
        "methods": methods or [],
        "attributes": attributes or [],
        "bases": bases or [],
        "docstring": docstring,
        "phase": phase
    })
    return format_result(result)


@mcp.tool()
async def generate_function(
    filePath: str,
    functionName: str,
    params: list[str] = None,
    returnType: str = None,
    docstring: str = None,
    isAsync: bool = False,
    phase: str = "preview"
) -> str:
    """
    Generate a new function.

    Args:
        filePath: Absolute path to the target Python file
        functionName: Name for the new function
        params: List of parameter definitions (e.g., ["x: int", "y: str = 'default'"])
        returnType: Return type annotation
        docstring: Function docstring
        isAsync: If True, generate async function
        phase: "preview", "changes", or "apply"
    """
    result = await http_post("generate_function", {
        "filePath": filePath,
        "functionName": functionName,
        "params": params or [],
        "returnType": returnType,
        "docstring": docstring,
        "isAsync": isAsync,
        "phase": phase
    })
    return format_result(result)


@mcp.tool()
async def generate_module(
    filePath: str,
    imports: list[str] = None,
    docstring: str = None,
    phase: str = "preview"
) -> str:
    """
    Generate a new Python module file.

    Args:
        filePath: Path for the new module
        imports: List of imports to include
        docstring: Module docstring
        phase: "preview", "changes", or "apply"
    """
    result = await http_post("generate_module", {
        "filePath": filePath,
        "imports": imports or [],
        "docstring": docstring,
        "phase": phase
    })
    return format_result(result)


@mcp.tool()
async def generate_package(
    dirPath: str,
    modules: list[str] = None,
    phase: str = "preview"
) -> str:
    """
    Generate a new Python package.

    Args:
        dirPath: Directory path for the package
        modules: List of module names to create
        phase: "preview", "changes", or "apply"
    """
    result = await http_post("generate_package", {
        "dirPath": dirPath,
        "modules": modules or [],
        "phase": phase
    })
    return format_result(result)


@mcp.tool()
async def generate_variable(
    filePath: str,
    variableName: str,
    value: str,
    typeAnnotation: str = None,
    phase: str = "preview"
) -> str:
    """
    Generate a module-level variable.

    Args:
        filePath: Absolute path to the Python file
        variableName: Name for the variable
        value: Value expression
        typeAnnotation: Type annotation (optional)
        phase: "preview", "changes", or "apply"
    """
    result = await http_post("generate_variable", {
        "filePath": filePath,
        "variableName": variableName,
        "value": value,
        "typeAnnotation": typeAnnotation,
        "phase": phase
    })
    return format_result(result)
