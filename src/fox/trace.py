"""Which effects a function body performs, read from the calls it writes."""

from __future__ import annotations

import ast
import builtins
from contextlib import suppress
import inspect
import linecache
import textwrap
from collections.abc import Callable
from types import FunctionType
from typing import Any
from weakref import WeakKeyDictionary

from fox.contract import Spec, performed
from fox.effects import Effect
from fox.errors import EffectError

tracked: WeakKeyDictionary[Callable[..., Any], set[Effect]] = WeakKeyDictionary()


def function_source(func: FunctionType) -> str:
    """Return the matching definition from cached source, without decorators."""

    source = "".join(linecache.getlines(func.__code__.co_filename, func.__globals__))
    if not source:
        return ""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    first_line = func.__code__.co_firstlineno
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        definition_lines = {node.lineno, *(decorator.lineno for decorator in node.decorator_list)}
        if node.name != func.__name__ or first_line not in definition_lines:
            continue
        segment = ast.get_source_segment(source, node)
        if segment is not None:
            return textwrap.dedent(segment)
    return ""


def callee_names(func: Callable[..., Any]) -> list[str]:
    if not isinstance(func, FunctionType):
        return []
    try:
        source = function_source(func)
    except (OSError, TypeError):
        return []
    if not source:
        return []
    try:
        definition = ast.parse(source).body[0]
    except (IndexError, SyntaxError):
        return []
    if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    names: list[str] = []

    def walk(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.append(node.func.id)
        for child in ast.iter_child_nodes(node):
            walk(child)

    for statement in definition.body:
        walk(statement)
    return names


def lookup(func: FunctionType, name: str) -> Any:
    code = func.__code__
    if name in code.co_varnames or name in code.co_cellvars:
        return None

    if name in code.co_freevars:
        try:
            return inspect.getclosurevars(func).nonlocals.get(name)
        except ValueError:
            return None

    if name in func.__globals__:
        return func.__globals__[name]

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
        with suppress(TypeError):
            used.update(tracked.get(callee, ()))
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
