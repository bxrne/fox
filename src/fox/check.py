"""Generate calls for pure @fox functions and let the contract judge them."""

from __future__ import annotations

import inspect
import types
from typing import Annotated, Any, Callable, Union, cast, get_args, get_origin, get_type_hints

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from typing_extensions import ParamSpec

from fox import Contracted, Spec, pure_functions
from fox.contract import call_predicate
from fox.effects import Between

P = ParamSpec("P")
_UNIONS = (Union, getattr(types, "UnionType", Union))


def strategy_for(annotation: Any) -> st.SearchStrategy[Any]:
    """Build a Hypothesis strategy for a parameter annotation.

    Supported forms are ``bool``, ``int``, ``str``, ``float``, ``None``,
    ``list[T]``, ``Optional[T]``, and ``Annotated[T, fox.between(...)]``.
    ``fox.between`` is the only bound. Without it, the draw is unbounded.
    """

    low: float | None = None
    high: float | None = None
    if get_origin(annotation) is Annotated:
        annotation, *meta = get_args(annotation)
        for item in meta:
            if isinstance(item, Between):
                low = item.low
                high = item.high

    if annotation is bool:
        return st.booleans()
    if annotation is int:
        return st.integers(
            min_value=None if low is None else int(low),
            max_value=None if high is None else int(high),
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
        return st.one_of(*(strategy_for(arg) for arg in args))
    raise TypeError(f"fox has no generator for {annotation!r}")


def check(func: Contracted[P, Any]) -> None:
    """Draw arguments from the annotations and call ``func``.

    Draws that fail ``requires`` are discarded. ``ensures`` and ``fox.claim``
    inside the call are the test. The function must be pure and fully annotated.
    """

    signature = inspect.signature(func)
    spec: Spec = func.__fox__

    # Hints live on the user's function. The wrapper's globals cannot see fox.between.
    original = getattr(func, "__wrapped__", func)
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
        arguments = dict(zip(names, values))

        # A draw outside requires is not a bug. Skip it and keep searching.
        for predicate in spec.requires:
            assume(call_predicate(predicate, arguments))

        cast(Callable[..., Any], func)(**arguments)

    run()


def check_pure() -> int:
    """Check every pure function registered in this process. Return how many ran."""

    count = 0
    for func in tuple(pure_functions):
        check(func)
        count += 1
    return count
