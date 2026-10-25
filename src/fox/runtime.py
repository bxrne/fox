"""The synchronous generator runner and context-local development hooks."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from fox.contract import Spec, performed
from fox.effects import Effect, EffectCall
from fox.trace import reject_unnamed

_stack: ContextVar[tuple[Spec, ...]] = ContextVar("fox_stack", default=())
_handlers: ContextVar[dict[Effect, Callable[[EffectCall], Any]] | None] = ContextVar(
    "fox_handlers", default=None
)
_checking: ContextVar[bool] = ContextVar("fox_checking", default=False)


def _dispatch(request: EffectCall, *, checked: bool) -> Any:
    if checked:
        for active in _stack.get():
            reject_unnamed(performed(active), {request.effect})
        handler = (_handlers.get() or {}).get(request.effect)
        if handler is not None:
            return handler(request)
    return request.function(*request.args, **request.kwargs)


def _drive(value: Any, *, checked: bool) -> Any:
    if not inspect.isgenerator(value):
        return value

    generator = value
    try:
        request = next(generator)
        while True:
            if not isinstance(request, EffectCall):
                raise TypeError("@fox generators must yield fox.perform(...) requests")
            try:
                result = _dispatch(request, checked=checked)
            except BaseException as error:
                request = generator.throw(error)
            else:
                request = generator.send(result)
    except StopIteration as finished:
        return finished.value
    finally:
        generator.close()
