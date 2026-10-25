"""Generate calls for pure @fox functions and let the contract judge them."""

from __future__ import annotations

import inspect
import math
import types
from collections.abc import Mapping
from contextlib import ExitStack
from typing import Annotated, Any, Callable, Union, cast, get_args, get_origin, get_type_hints

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from hypothesis.errors import Unsatisfiable
from typing_extensions import ParamSpec

from fox import Contracted, Spec, fox, pure_functions
from fox.contract import call_predicate
from fox.effects import Between, Effect, EffectCall
from fox.runtime import _checking

P = ParamSpec("P")
_UNIONS = (Union, getattr(types, "UnionType", Union))


def strategy_for(annotation: Any) -> st.SearchStrategy[Any]:
    """Build a Hypothesis strategy for a parameter annotation.

    Supported forms are ``bool``, ``int``, ``str``, ``float``, ``None``,
    ``list[T]``, ``Optional[T]``, and ``Annotated[T, fox.between(...)]``.
    ``fox.between`` is the only bound. Without it, the draw is unbounded.
    """

    return _strategy_for(annotation)


def _strategy_for(
    annotation: Any,
    low: float | None = None,
    high: float | None = None,
) -> st.SearchStrategy[Any]:
    if get_origin(annotation) is Annotated:
        annotation, *meta = get_args(annotation)
        for item in meta:
            if isinstance(item, Between):
                low = item.low
                high = item.high

    if annotation is bool:
        return st.booleans()
    if annotation is int:
        minimum = None if low is None else math.ceil(low)
        maximum = None if high is None else math.floor(high)
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"fox.between({low!r}, {high!r}) contains no representable integer")
        return st.integers(
            min_value=minimum,
            max_value=maximum,
        )
    if annotation is str:
        return st.text()
    if annotation is float:
        return st.floats(min_value=low, max_value=high)
    if annotation is type(None):
        return st.none()
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list and len(args) == 1:
        return st.lists(strategy_for(args[0]))
    if origin in _UNIONS and args:
        return st.one_of(*(_strategy_for(arg, low, high) for arg in args))
    raise TypeError(f"fox has no generator for {annotation!r}")


def check(
    func: Contracted[P, Any],
    *,
    handlers: Mapping[Effect | str, Callable[[EffectCall], Any]] | None = None,
) -> None:
    """Draw arguments from the annotations and call ``func``.

    Draws that fail ``requires`` are discarded. ``ensures`` and ``fox.claim``
    inside the call are the test. Effectful checks require a generator and a
    handler for each declared effect. Interception applies only to explicit
    ``fox.perform(...)`` requests; it does not sandbox arbitrary I/O in a body.
    """

    signature = inspect.signature(func)
    spec: Spec = func.__fox__

    supplied = {key if isinstance(key, Effect) else Effect(key) for key in (handlers or {})}
    missing = spec.effects - supplied
    if not spec.pure and missing:
        names = ", ".join(sorted(item.name for item in missing))
        raise TypeError(f"fox.check needs handlers for declared effects: {names}")

    original = inspect.unwrap(func)
    target_name = getattr(original, "__qualname__", repr(func))
    if not spec.pure and not inspect.isgeneratorfunction(original):
        raise TypeError(f"fox.check requires effectful function {target_name} to be a generator")

    # Hints live on the user's function. The wrapper's globals cannot see fox.between.
    hints = get_type_hints(original, include_extras=True)

    names: list[str] = []
    parts: list[st.SearchStrategy[Any]] = []

    for parameter in signature.parameters.values():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise TypeError(f"{func.__name__} uses *args or **kwargs, which fox does not generate")
        annotation = hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Parameter.empty:
            raise TypeError(f"{func.__name__} parameter {parameter.name} needs a type")
        names.append(parameter.name)
        parts.append(strategy_for(annotation))

    @settings(
        database=None,
        deadline=None,
        suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
    )
    @given(st.tuples(*parts))
    def run(values: tuple[Any, ...]) -> None:
        bound = inspect.BoundArguments(signature, dict(zip(names, values)))

        # A draw outside requires is not a bug. Skip it and keep searching.
        for predicate in spec.requires:
            assume(call_predicate(predicate, bound.arguments))

        cast(Callable[..., Any], func)(*bound.args, **bound.kwargs)

    try:
        with ExitStack() as stack:
            for named_effect, handler in (handlers or {}).items():
                stack.enter_context(fox.intercept(named_effect, handler))
            token = _checking.set(True)
            try:
                run()
            finally:
                _checking.reset(token)
    except Unsatisfiable as error:
        raise Unsatisfiable(
            f"fox.check could not generate a valid call for {target_name}: {error}"
        ) from error


def check_pure() -> int:
    """Check every pure function registered in this process. Return how many ran."""

    count = 0
    for func in tuple(pure_functions):
        check(func)
        count += 1
    return count
