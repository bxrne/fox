"""Ordinary-call effect boundaries and context-local development hooks."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from typing_extensions import ParamSpec, Protocol

from fox.contract import Spec, performed
from fox.effects import Effect, synchronous
from fox.errors import EffectError
from fox.trace import reject_unnamed

P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)
Handlers = Mapping[Callable[..., Any], Callable[..., Any]]
_UNBOUND = object()


@dataclass(frozen=True)
class _Handler:
    function: Callable[..., Any]
    receiver: Any = _UNBOUND


_stack: ContextVar[tuple[Spec, ...]] = ContextVar("fox_stack", default=())
_handlers: ContextVar[dict[tuple[Callable[..., Any], int | None], _Handler] | None] = ContextVar(
    "fox_handlers", default=None
)
_checking: ContextVar[bool] = ContextVar("fox_checking", default=False)


class _Boundary(Protocol[P, R_co]):
    __fox_effect__: Effect
    __fox_boundary__: Callable[..., Any]

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R_co: ...


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
        active_handlers = _handlers.get() or {}
        bound_handler = active_handlers.get((call, id(args[0]))) if args else None
        if bound_handler is not None and bound_handler.receiver is args[0]:
            return bound_handler.function(*args[1:], **kwargs)
        handler = active_handlers.get((call, None))
        if handler is not None:
            return handler.function(*args, **kwargs)
        if _checking.get():
            name = getattr(function, "__qualname__", repr(function))
            raise EffectError(f"fox.check needs a handler for {name} ({named_effect.name})")
        return function(*args, **kwargs)

    decorated = cast(_Boundary[P, R], call)
    decorated.__fox_effect__ = named_effect
    decorated.__fox_boundary__ = call
    return decorated


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
        receiver = function.__self__ if inspect.ismethod(function) else _UNBOUND
        key = (original, None if receiver is _UNBOUND else id(receiver))
        active[key] = _Handler(handler, receiver)
    token = _handlers.set(active)
    try:
        yield
    finally:
        _handlers.reset(token)
