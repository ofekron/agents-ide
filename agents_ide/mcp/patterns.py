#!/usr/bin/env python3
"""Design pattern generation tools."""

from ._core import mcp, http_post, format_result


@mcp.tool()
async def pattern_singleton(className: str, threadSafe: bool = True) -> str:
    """
    Generate Singleton pattern code.

    Args:
        className: Name for the singleton class
        threadSafe: If True, generate thread-safe singleton
    """
    result = await http_post("pattern/singleton", {
        "className": className,
        "threadSafe": threadSafe
    })
    return format_result(result)


@mcp.tool()
async def pattern_factory(
    factoryName: str,
    products: list[str],
    abstractProduct: str = "Product"
) -> str:
    """
    Generate Factory pattern code.

    Args:
        factoryName: Name for the factory class
        products: List of concrete product class names
        abstractProduct: Name for the abstract product class
    """
    result = await http_post("pattern/factory", {
        "factoryName": factoryName,
        "products": products,
        "abstractProduct": abstractProduct
    })
    return format_result(result)


@mcp.tool()
async def pattern_builder(
    className: str,
    attributes: list[str]
) -> str:
    """
    Generate Builder pattern code.

    Args:
        className: Name for the class to build
        attributes: List of attribute names
    """
    result = await http_post("pattern/builder", {
        "className": className,
        "attributes": attributes
    })
    return format_result(result)


@mcp.tool()
async def pattern_observer(
    subjectName: str,
    observerName: str = "Observer"
) -> str:
    """
    Generate Observer pattern code.

    Args:
        subjectName: Name for the subject class
        observerName: Name for the observer interface
    """
    result = await http_post("pattern/observer", {
        "subjectName": subjectName,
        "observerName": observerName
    })
    return format_result(result)


@mcp.tool()
async def pattern_strategy(
    contextName: str,
    strategyName: str,
    strategies: list[str]
) -> str:
    """
    Generate Strategy pattern code.

    Args:
        contextName: Name for the context class
        strategyName: Name for the strategy interface
        strategies: List of concrete strategy class names
    """
    result = await http_post("pattern/strategy", {
        "contextName": contextName,
        "strategyName": strategyName,
        "strategies": strategies
    })
    return format_result(result)


@mcp.tool()
async def pattern_decorator(
    decoratorName: str,
    wrappedName: str = "Component"
) -> str:
    """
    Generate Decorator pattern code.

    Args:
        decoratorName: Name for the decorator class
        wrappedName: Name for the wrapped component interface
    """
    result = await http_post("pattern/decorator", {
        "decoratorName": decoratorName,
        "wrappedName": wrappedName
    })
    return format_result(result)
