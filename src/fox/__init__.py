"""Contracts and named effects for ordinary Python functions.

``@fox`` keeps the wrapped signature. Pure functions can memoise immutable
values. ``python -O`` compiles the checks out and leaves memoisation enabled.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from typing import Any, TypeVar, cast, overload

from typing_extensions import Concatenate, ParamSpec, Protocol

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
from fox.effects import PURE, Between, Effect, effect, synchronous
from fox.errors import EffectError, FailedClaim, PostconditionError, PreconditionError
from fox.memo import memoized
from fox.runtime import Handlers, _stack, intercept
from fox.trace import effects_used, reject_unnamed, tracked

P = ParamSpec("P")
Q = ParamSpec("Q")
R = TypeVar("R")
R_co = TypeVar("R_co", covariant=True)
R_call = TypeVar("R_call")
T = TypeVar("T")

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

    @overload
    def __get__(self, instance: None, owner: type[Any] | None = None) -> Contracted[P, R_co]: ...

    @overload
    def __get__(
        self: Contracted[Concatenate[T, Q], R_co],
        instance: T,
        owner: type[T] | None = None,
    ) -> Contracted[Q, R_co]: ...


class FoxDecorator(Protocol):
    def __call__(self, func: Callable[P, R_call]) -> Contracted[P, R_call]: ...


def _checked(
    target: Callable[P, R],
    runner: Callable[P, R],
    *,
    spec: Spec,
) -> Contracted[P, R]:
    signature = inspect.signature(target)
    reject_unnamed(performed(spec), effects_used(target))

    @functools.wraps(target)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
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

    # The CLI needs no handlers for pure functions.
    if spec.pure:
        pure_functions.append(contracted)
    return contracted


class fox:
    """Attach a boundary contract to a function.

    ``requires`` binds the caller. ``ensures`` binds the function and may take
    the parameter names plus ``result``. ``effects`` names what the body may do.
    The default is ``pure``. Pass one predicate or a sequence of predicates.

    Pure functions use a bounded cache for immutable built-in values, unless
    ``memoize=False``. Decorate I/O boundaries with ``@effect(\"io\")`` and
    call them normally; tests replace these functions with ordinary callables.
    ``python -O`` drops the contracts and effect checks. Use a lazy callable
    with ``fox.claim`` to skip evaluating the condition in optimised builds.

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
            runner = memoized(target) if memoize and PURE in declared else target
            if spec is not None:
                return _checked(
                    target,
                    runner,
                    spec=spec,
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
    def intercept(handlers: Handlers) -> AbstractContextManager[None]:
        """Temporarily replace ``@effect`` functions with ordinary callables."""

        return intercept(handlers)

    @staticmethod
    def check(
        func: Callable[P, Any],
        *,
        handlers: Handlers | None = None,
    ) -> None:
        """Generate calls, replacing effect boundaries with the supplied functions."""

        if not __debug__:
            raise RuntimeError("fox.check is disabled under python -O")

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
    "EffectError",
    "FailedClaim",
    "PostconditionError",
    "PreconditionError",
    "effect",
    "fox",
]
