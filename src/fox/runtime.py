"""Ordinary-call effect boundaries and context-local development hooks."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from typing_extensions import ParamSpec

from fox.contract import Spec, performed
from fox.effects import Effect, synchronous
from fox.errors import EffectError
from fox.trace import reject_unnamed

P = ParamSpec("P")
R = TypeVar("R")
Handlers = Mapping[Callable[..., Any], Callable[..., Any]]

_stack: ContextVar[tuple[Spec, ...]] = ContextVar("fox_stack", default=())
_handlers: ContextVar[Handlers | None] = ContextVar("fox_handlers", default=None)
_checking: ContextVar[bool] = ContextVar("fox_checking", default=False)


def boundary(function: Callable[P, R], named_effect: Effect) -> Callable[P, R]:
    synchronous(function, "effect")
    if not __debug__:
        return function

    signature = inspect.signature(function)

    @functools.wraps(function)
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        for active in _stack.get():
            reject_unnamed(performed(active), {named_effect})
        signature.bind(*args, **kwargs)
        handler = (_handlers.get() or {}).get(call)
        if handler is not None:
            return handler(*args, **kwargs)
        if _checking.get():
            name = getattr(function, "__qualname__", repr(function))
            raise EffectError(f"fox.check needs a handler for {name} ({named_effect.name})")
        return function(*args, **kwargs)

    setattr(call, "__fox_effect__", named_effect)
    setattr(call, "__fox_boundary__", call)
    return call


@contextmanager
def intercept(handlers: Handlers) -> Generator[None, None, None]:
    """Replace boundary functions with ordinary callables in this context."""

    if not __debug__:
        raise RuntimeError("fox effect interception is disabled under python -O")
    if not isinstance(handlers, Mapping):
        raise TypeError("fox.intercept expects a mapping of @effect functions to replacements")
    active = dict(_handlers.get() or {})
    for function, handler in handlers.items():
        original = getattr(function, "__fox_boundary__", None)
        if not callable(original):
            raise TypeError("handler keys must be functions decorated with @effect")
        synchronous(handler, "effect handler")
        active[original] = handler
    token = _handlers.set(active)
    try:
        yield
    finally:
        _handlers.reset(token)
