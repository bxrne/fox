"""Contracts and named effects for ordinary Python functions.

``@fox`` keeps the wrapped signature. Pure functions can memoise immutable
values. ``python -O`` compiles the checks out and leaves memoisation enabled.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from typing import Any, TypeVar, cast, overload

from typing_extensions import ParamSpec, Protocol

from fox.contract import (
    EffectInput,
    Predicate,
    Spec,
    check_ensures,
    check_requires,
    effects_of,
    one_effect,
    performed,
    predicates,
)
from fox.effects import PURE, Between, Effect, EffectCall, effect, synchronous
from fox.errors import EffectError, FailedClaim, PostconditionError, PreconditionError
from fox.memo import memoized
from fox.runtime import _checking, _drive, _handlers, _stack
from fox.trace import effects_used, reject_unnamed, tracked

P = ParamSpec("P")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)
R_call = TypeVar("R_call")

pure_functions: list[Contracted[Any, Any]] = []


class Contracted(Protocol[P, R_co]):
    """A ``@fox`` function.

    ``__fox__`` is present when checks are compiled in. ``python -O`` returns
    the memoised function and does not set ``__fox__``.
    """

    __fox__: Spec
    __name__: str
    __wrapped__: Any

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R_co: ...


class FoxDecorator(Protocol):
    @overload
    def __call__(
        self, func: Callable[P, Generator[EffectCall, Any, R_call]]
    ) -> Contracted[P, R_call]: ...

    @overload
    def __call__(self, func: Callable[P, R_call]) -> Contracted[P, R_call]: ...


def _checked(
    target: Callable[P, R],
    runner: Callable[P, R],
    *,
    spec: Spec,
    is_generator: bool,
) -> Contracted[P, R]:
    signature = inspect.signature(target)
    reject_unnamed(performed(spec), effects_used(target))

    @functools.wraps(target)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        if _checking.get() and not spec.pure and not is_generator:
            raise TypeError(
                "generated effectful calls must be generators yielding fox.perform(...)"
            )
        parent = _stack.get()
        if parent:
            reject_unnamed(performed(parent[-1]), set(performed(spec)))
        token = _stack.set((*parent, spec))
        try:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = bound.arguments
            check_requires(spec, arguments)
            result = runner(*args, **kwargs)
            check_ensures(spec, arguments, result)
            return result
        finally:
            _stack.reset(token)

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

    Pure non-generator functions use a bounded cache for immutable built-in
    values, unless ``memoize=False``. Generators are driven and never memoised.
    ``python -O`` drops the contracts and effect checks. Use a lazy callable
    with ``fox.claim`` to skip evaluating the condition in optimised builds.

    Register an effectful call with ``fox.track(print, log)``. Calling another
    ``@fox`` function performs the effects that function names.
    """

    @overload
    def __new__(cls, func: Callable[P, Generator[EffectCall, Any, R]], /) -> Contracted[P, R]: ...

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
        memoize: bool = True,
    ) -> FoxDecorator: ...

    def __new__(
        cls,
        func: Callable[P, R] | None = None,
        /,
        *,
        requires: Predicate | Iterable[Predicate] | None = None,
        ensures: Predicate | Iterable[Predicate] | None = None,
        effects: EffectInput = PURE,
        memoize: bool = True,
    ) -> Contracted[P, R] | Callable[[Callable[P, R]], Contracted[P, R]]:
        declared = effects_of(effects)
        if not isinstance(memoize, bool):
            raise TypeError("memoize must be a bool")
        spec = Spec(predicates(requires), predicates(ensures), declared) if __debug__ else None

        def decorate(target: Callable[P, R]) -> Contracted[P, R]:
            synchronous(target, "fox")
            call = target.__call__
            is_generator = inspect.isgeneratorfunction(target) or inspect.isgeneratorfunction(call)
            if is_generator:

                @functools.wraps(target)
                def runner(*args: P.args, **kwargs: P.kwargs) -> R:
                    return cast(R, _drive(target(*args, **kwargs), checked=__debug__))

            else:
                runner = memoized(target) if memoize and PURE in declared else target
            if spec is not None:
                return _checked(
                    target,
                    runner,
                    spec=spec,
                    is_generator=is_generator,
                )
            return cast(Contracted[P, R], runner)

        if func is not None:
            return decorate(func)
        return decorate

    @staticmethod
    def claim(condition: bool | Callable[[], bool], message: str = "") -> None:
        """Check a fact. A lazy callable is not evaluated under ``python -O``."""

        if __debug__:
            _claim(condition() if callable(condition) else condition, message)

    @staticmethod
    def track(func: Callable[..., Any], *effects: Effect | str) -> None:
        """Record that calling ``func`` performs these effects."""

        if not callable(func):
            raise TypeError("fox.track expects a callable")
        if not effects:
            raise TypeError("fox.track expects at least one effect")
        chosen = {one_effect(item) for item in effects}
        if PURE in chosen:
            raise ValueError("pure is not an effect a call performs")
        try:
            tracked.setdefault(func, set()).update(chosen)
        except TypeError as error:
            raise TypeError("fox.track requires a weak-referenceable, hashable callable") from error

    @staticmethod
    def perform(
        named_effect: Effect | str,
        function: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> EffectCall:
        """Yield an interceptable call from a generator decorated with ``@fox``."""

        return EffectCall(one_effect(named_effect), function, args, kwargs)

    @staticmethod
    @contextmanager
    def intercept(
        named_effect: Effect | str, handler: Callable[[EffectCall], Any]
    ) -> Generator[None, None, None]:
        """Handle one yielded effect in the current context; intended for tests."""

        if not __debug__:
            raise RuntimeError("fox effect interception is disabled under python -O")
        synchronous(handler, "fox.intercept")
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
    def check(
        func: Contracted[P, Any],
        *,
        handlers: Mapping[Effect | str, Callable[[EffectCall], Any]] | None = None,
    ) -> None:
        """Generate calls and check contracts, optionally replacing yielded effects."""

        from fox.check import check

        check(func, handlers=handlers)

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
