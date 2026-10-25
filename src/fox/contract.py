"""The boundary a function promises: requirements, results, and effects."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Union, cast

from typing_extensions import Protocol

from fox.effects import PURE, Effect, effect
from fox.errors import PostconditionError, PreconditionError


class Predicate(Protocol):
    """A named callable that returns a bool."""

    __name__: str

    def __call__(self, *args: Any, **kwargs: Any) -> bool: ...


EffectInput = Union[Effect, str, Iterable[Union[Effect, str]]]


class Spec:
    """The boundary stored on ``function.__fox__`` while checks are compiled in."""

    requires: tuple[Predicate, ...]
    ensures: tuple[Predicate, ...]
    effects: frozenset[Effect]

    def __init__(
        self,
        requires: tuple[Predicate, ...],
        ensures: tuple[Predicate, ...],
        effects: frozenset[Effect],
    ) -> None:
        self.requires = requires
        self.ensures = ensures
        self.effects = effects

    @property
    def pure(self) -> bool:
        """True when the function names no effect."""

        return self.effects == frozenset({PURE})


def predicates(value: Predicate | Iterable[Predicate] | None) -> tuple[Predicate, ...]:
    """Accept one predicate or several. ``None`` means the caller wrote no rule."""

    if value is None:
        return ()

    if not isinstance(value, Iterable):
        return (cast(Predicate, value),)

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


def call_predicate(predicate: Predicate, arguments: Mapping[str, Any]) -> bool:
    """Call a predicate with the parameter names it declares.

    ``ensures`` may also take ``result``. A non-bool return is a programmer error.
    """

    signature = inspect.signature(predicate)
    parameters = signature.parameters.values()
    accepts_any = any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters)

    if accepts_any:
        payload = dict(arguments)
    else:
        payload = {name: arguments[name] for name in signature.parameters if name in arguments}
        missing = [
            name
            for name, parameter in signature.parameters.items()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
            and parameter.default is inspect.Parameter.empty
            and name not in payload
        ]
        if missing:
            names = ", ".join(missing)
            message = f"predicate {predicate.__name__} expects {names}"
            message = f"{message}, which this function does not provide"
            raise TypeError(message)

    outcome: Any = predicate(**payload)
    if not isinstance(outcome, bool):
        found = type(outcome).__name__
        raise TypeError(f"predicate {predicate.__name__} returned {found}, expected bool")

    return outcome


def check_requires(spec: Spec, arguments: Mapping[str, Any]) -> None:
    """Stop before the body. A failed precondition is the caller's bug."""

    for predicate in spec.requires:
        if not call_predicate(predicate, arguments):
            raise PreconditionError(f"requires failed for {predicate.__name__}")


def check_ensures(spec: Spec, arguments: Mapping[str, Any], result: Any) -> None:
    """Judge the result. ``result`` is passed so the predicate can name it."""

    payload = dict(arguments)
    payload["result"] = result

    for predicate in spec.ensures:
        if not call_predicate(predicate, payload):
            raise PostconditionError(f"ensures failed for {predicate.__name__}")
