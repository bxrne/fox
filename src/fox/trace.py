"""Which effects a function body performs, read from the calls it writes."""

from __future__ import annotations

import ast
import builtins
import inspect
import textwrap
from collections.abc import Callable
from types import FunctionType
from typing import Any

from fox.contract import Spec, performed
from fox.effects import Effect
from fox.errors import EffectError

tracked: dict[int, set[Effect]] = {}


def function_source(func: FunctionType) -> str:
    """Read the function text, including its decorator line.

    ``inspect.getsource`` can stop on the decorator and drop the ``def``.
    The effect scan needs the body, so this walks the lines itself.
    """

    if func.__code__.co_filename.startswith("<"):
        return textwrap.dedent(inspect.getsource(func))
    with open(func.__code__.co_filename, encoding="utf-8") as handle:
        lines = handle.readlines()
    index = func.__code__.co_firstlineno - 1
    while index > 0 and lines[index - 1].lstrip().startswith("@"):
        index -= 1

    base = len(lines[index]) - len(lines[index].lstrip())
    chunk: list[str] = []
    seen_def = False

    for line in lines[index:]:
        if line.strip() == "":
            chunk.append(line)
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent < base or (indent == base and seen_def):
            break
        if stripped.startswith(("def ", "async def ")):
            seen_def = True
        chunk.append(line)
    return textwrap.dedent("".join(chunk))


def callee_names(func: Callable[..., Any]) -> list[str]:
    if not isinstance(func, FunctionType):
        return []
    try:
        source = function_source(func)
    except (OSError, TypeError):
        return []
    tree = ast.parse(source)
    names: list[str] = []

    def walk(node: ast.AST, *, nested: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                if not nested:
                    walk(child, nested=True)
                continue
            if nested and isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                names.append(child.func.id)

            walk(child, nested=nested)

    walk(tree, nested=False)
    return names


def lookup(func: FunctionType, name: str) -> Any:
    if name in func.__globals__:
        return func.__globals__[name]

    closure = inspect.getclosurevars(func)
    if name in closure.nonlocals:
        return closure.nonlocals[name]

    # print and open live on builtins, not in the module dict.
    return getattr(builtins, name, None)


def effects_used(func: Callable[..., Any]) -> set[Effect]:
    """Effects of the calls written in ``func``. Unknown calls perform nothing."""

    if not isinstance(func, FunctionType):
        return set()
    used: set[Effect] = set()
    for name in callee_names(func):
        callee = lookup(func, name)
        if callee is None:
            continue
        used.update(tracked.get(id(callee), ()))
        callee_spec = getattr(callee, "__fox__", None)
        if isinstance(callee_spec, Spec):
            used.update(performed(callee_spec))
    return used


def reject_unnamed(declared: frozenset[Effect], used: set[Effect]) -> None:
    extra = used - set(declared)
    if not extra:
        return
    names = ", ".join(sorted(item.name for item in extra))
    raise EffectError(f"call performs {names}, which this function does not name")
