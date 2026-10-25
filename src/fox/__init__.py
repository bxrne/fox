"""Contracts and named effects for ordinary Python functions.

``@fox`` keeps the wrapped signature. Pure functions are memoised in every
build. ``python -O`` compiles the checks out and leaves the memo table.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, TypeVar, cast, overload

from typing_extensions import ParamSpec, Protocol

from fox.contract import (
    EffectInput,
    Predicate,
    Spec,
    bind,
    check_ensures,
    check_requires,
    effects_of,
    one_effect,
    performed,
    predicates,
)
from fox.effects import PURE, Between, Effect, EffectCall, effect
from fox.errors import EffectError, FailedClaim, PostconditionError, PreconditionError
from fox.trace import effects_used, reject_unnamed, tracked

P = ParamSpec("P")
R = TypeVar("R")

_stack: ContextVar[tuple[Spec, ...]] = ContextVar("fox_stack", default=())
_handlers: ContextVar[dict[Effect, Callable[[EffectCall], Any]] | None] = ContextVar(
    "fox_handlers", default=None
)
pure_functions: list[Contracted[Any, Any]] = []


class Contracted(Protocol[P, R]):
    """A ``@fox`` function.

    ``__fox__`` is present when checks are compiled in. ``python -O`` returns
    the memoised function and does not set ``__fox__``.
    """

    __fox__: Spec
    __name__: str
    __wrapped__: Callable[P, R]

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...


def _call(
    runner: Callable[P, R],
    target: Callable[P, R],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> R:
    """Call the memoised function. Unhashable arguments skip the memo table."""

    if runner is target:
        return target(*args, **kwargs)

    # functools.cache turns an unhashable argument into a TypeError that looks like a body bug.
    try:
        hash((args, tuple(kwargs.items())))
    except TypeError:
        return target(*args, **kwargs)

    return runner(*args, **kwargs)


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


def _checked(
    target: Callable[P, R],
    runner: Callable[P, R],
    *,
    requires: Predicate | Iterable[Predicate] | None,
    ensures: Predicate | Iterable[Predicate] | None,
    declared: frozenset[Effect],
) -> Contracted[P, R]:
    spec = Spec(predicates(requires), predicates(ensures), declared)
    reject_unnamed(performed(spec), effects_used(target))

    @functools.wraps(target)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        arguments = bind(target, args, kwargs)
        check_requires(spec, arguments)

        parent = _stack.get()
        if parent:
            reject_unnamed(performed(parent[-1]), set(performed(spec)))

        token: Token[tuple[Spec, ...]] = _stack.set((*parent, spec))
        try:
            result = _drive(_call(runner, target, args, kwargs), checked=True)
        finally:
            _stack.reset(token)

        check_ensures(spec, arguments, result)
        return result

    contracted = cast(Contracted[P, R], wrapper)
    contracted.__fox__ = spec

    # Only pure functions are generated. An effectful call would hit the world.
    if spec.pure:
        pure_functions.append(contracted)
    return contracted


class fox:
    """Attach a boundary contract to a function.

    ``requires`` binds the caller. ``ensures`` binds the function and may take
    the parameter names plus ``result``. ``effects`` names what the body may do.
    The default is ``pure``. Pass one predicate or a sequence of predicates.

    A pure, non-generator function is memoised in development and in the
    optimised build. Generator functions are driven and never memoised.
    ``python -O`` drops ``requires``, ``ensures``, ``fox.claim``, and the effect
    check. The memo table stays.

    Register an effectful call with ``fox.track(print, log)``. Calling another
    ``@fox`` function performs the effects that function names.
    """

    @overload
    def __new__(cls, func: Callable[P, R], /) -> Contracted[P, R]: ...

    @overload
    def __new__(
        cls,
        func: None = None,
        /,
        *,
        requires: Predicate | Iterable[Predicate] | None = None,
        ensures: Predicate | Iterable[Predicate] | None = None,
        effects: EffectInput = PURE,
    ) -> Callable[[Callable[P, R]], Contracted[P, R]]: ...

    def __new__(
        cls,
        func: Callable[P, R] | None = None,
        /,
        *,
        requires: Predicate | Iterable[Predicate] | None = None,
        ensures: Predicate | Iterable[Predicate] | None = None,
        effects: EffectInput = PURE,
    ) -> Contracted[P, R] | Callable[[Callable[P, R]], Contracted[P, R]]:
        def decorate(target: Callable[P, R]) -> Contracted[P, R]:
            declared = effects_of(effects)

            is_generator = inspect.isgeneratorfunction(target)
            # Built outside the debug branch so python -O still memoises pure functions.
            cached = functools.cache(target) if PURE in declared and not is_generator else target
            runner = cast(Callable[P, R], cached)

            if __debug__:
                return _checked(
                    target,
                    runner,
                    requires=requires,
                    ensures=ensures,
                    declared=declared,
                )
            if is_generator:
                @functools.wraps(target)
                def execute(*args: P.args, **kwargs: P.kwargs) -> R:
                    return cast(R, _drive(target(*args, **kwargs), checked=False))

                return cast(Contracted[P, R], execute)
            return cast(Contracted[P, R], runner)

        if func is not None:
            return decorate(func)
        return decorate

    @staticmethod
    def claim(condition: bool, message: str = "") -> None:
        """Check a fact in the body. Compiled out under ``python -O``."""

        if __debug__:
            _claim(condition, message)

    @staticmethod
    def track(func: Callable[..., Any], *effects: Effect | str) -> None:
        """Record that calling ``func`` performs these effects."""

        if not effects:
            raise TypeError("fox.track expects at least one effect")

        try:
            slot = tracked.setdefault(func, set())
        except TypeError as error:
            raise TypeError("fox.track requires a weak-referenceable callable") from error
        for item in effects:
            chosen = one_effect(item)
            if chosen == PURE:
                raise ValueError("pure is not an effect a call performs")
            slot.add(chosen)

    @staticmethod
    def perform(
        named_effect: Effect | str,
        function: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> EffectCall:
        """Yield an interceptable call from a generator decorated with ``@fox``."""

        if not callable(function):
            raise TypeError("fox.perform expects a callable")
        return EffectCall(one_effect(named_effect), function, args, kwargs)

    @staticmethod
    @contextmanager
    def intercept(
        named_effect: Effect | str, handler: Callable[[EffectCall], Any]
    ) -> Generator[None, None, None]:
        """Handle one yielded effect in the current context; intended for tests."""

        if not __debug__:
            raise RuntimeError("fox effect interception is disabled under python -O")
        if not callable(handler):
            raise TypeError("fox.intercept expects a callable handler")
        chosen = one_effect(named_effect)
        if chosen == PURE:
            raise ValueError("pure cannot be intercepted")
        handlers = dict(_handlers.get() or {})
        handlers[chosen] = handler
        token = _handlers.set(handlers)
        try:
            yield
        finally:
            _handlers.reset(token)

    @staticmethod
    def between(low: float | None = None, high: float | None = None) -> Between:
        """Bound one parameter the checker draws. You choose the ends.

        Use it as ``Annotated[int, fox.between(0, 100)]``. An omitted end stays open.
        """

        return Between(low, high)


def _claim(condition: bool, message: str) -> None:
    checked: Any = condition
    if not isinstance(checked, bool):
        raise TypeError("fox.claim expects a bool")
    if not condition:
        detail = message if message else "claim failed"
        raise FailedClaim(detail)


__all__ = [
    "Effect",
    "EffectCall",
    "EffectError",
    "FailedClaim",
    "PostconditionError",
    "PreconditionError",
    "effect",
    "fox",
]
