"""The boundary a function promises: requirements, results, and effects."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Union, cast

from typing_extensions import Protocol

from fox.effects import PURE, Effect, effect
from fox.errors import PostconditionError, PreconditionError


class Predicate(Protocol):
    """A callable that returns a bool."""

    def __call__(self, *args: Any, **kwargs: Any) -> bool: ...


EffectInput = Union[Effect, str, Iterable[Union[Effect, str]]]


@dataclass(frozen=True)
class Spec:
    """The boundary stored on ``function.__fox__`` while checks are compiled in."""

    requires: tuple[Predicate, ...]
    ensures: tuple[Predicate, ...]
    effects: frozenset[Effect]

    @property
    def pure(self) -> bool:
        """True when the function names no effect."""

        return self.effects == frozenset({PURE})


def predicates(value: Predicate | Iterable[Predicate] | None) -> tuple[Predicate, ...]:
    """Accept one predicate or several. ``None`` means the caller wrote no rule."""

    if value is None:
        return ()

    if callable(value):
        return (cast(Predicate, value),)
    if not isinstance(value, Iterable):
        raise TypeError("requires and ensures must be callables")

    found = tuple(value)
    for predicate in found:
        if not callable(predicate):
            raise TypeError("requires and ensures must be callables")

    return found


def one_effect(value: Effect | str) -> Effect:
    """``effect("http")`` and ``"http"`` are one effect, so callers can write either."""

    if isinstance(value, Effect):
        return value

    return effect(value)


def effects_of(value: EffectInput) -> frozenset[Effect]:
    """Normalise the decorator argument.

    Omitting effects means pure. Naming ``pure`` beside another effect is a mistake,
    because a pure function is one that performs nothing.
    """

    if isinstance(value, (Effect, str)):
        named = frozenset({one_effect(value)})
    else:
        named = frozenset(one_effect(item) for item in value)

    if not named or named == frozenset({PURE}):
        return frozenset({PURE})

    if PURE in named:
        raise ValueError("pure cannot be combined with other effects")

    return named


def performed(spec: Spec) -> frozenset[Effect]:
    """Effects a call of this function actually performs. Pure performs none."""

    if spec.pure:
        return frozenset()
    return spec.effects


def bind(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Name every argument, including defaults, so predicates can use keywords."""

    signature = inspect.signature(func)
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def predicate_name(predicate: Predicate) -> str:
    return getattr(predicate, "__name__", type(predicate).__name__)


def call_predicate(predicate: Predicate, arguments: Mapping[str, Any]) -> bool:
    """Project named arguments onto a predicate's Python calling convention."""

    signature = inspect.signature(predicate)
    values: dict[str, Any] = {}
    extras = dict(arguments)
    missing: list[str] = []
    variadic = None
    for name, parameter in signature.parameters.items():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            variadic = name
        elif name in arguments:
            values[name] = extras.pop(name)
        elif parameter.default is inspect.Parameter.empty and parameter.kind is not (
            inspect.Parameter.VAR_POSITIONAL
        ):
            missing.append(name)
    if missing:
        names = ", ".join(missing)
        raise TypeError(
            f"predicate {predicate_name(predicate)} expects {names}, "
            "which this function does not provide"
        )
    if variadic is not None:
        values[variadic] = extras
    bound = inspect.BoundArguments(signature, values)
    bound.apply_defaults()
    outcome: Any = predicate(*bound.args, **bound.kwargs)
    if not isinstance(outcome, bool):
        found = type(outcome).__name__
        raise TypeError(f"predicate {predicate_name(predicate)} returned {found}, expected bool")
    return outcome


def check_requires(spec: Spec, arguments: Mapping[str, Any]) -> None:
    """Stop before the body. A failed precondition is the caller's bug."""

    for predicate in spec.requires:
        if not call_predicate(predicate, arguments):
            raise PreconditionError(f"requires failed for {predicate_name(predicate)}")


def check_ensures(spec: Spec, arguments: Mapping[str, Any], result: Any) -> None:
    """Judge the result. ``result`` is passed so the predicate can name it."""

    payload = dict(arguments)
    payload["result"] = result

    for predicate in spec.ensures:
        if not call_predicate(predicate, payload):
            raise PostconditionError(f"ensures failed for {predicate_name(predicate)}")
