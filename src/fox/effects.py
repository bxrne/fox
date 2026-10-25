"""Effect names, and the bounds a user puts on a generated draw."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from typing_extensions import ParamSpec

P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True)
class Effect:
    """A named effect a function may perform.

    Two effects with the same name are equal. ``pure`` means the function
    performs no effect. It cannot be combined with any other name.
    """

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("effect name must be a string")
        if self.name == "" or any(character.isspace() for character in self.name):
            raise ValueError("effect name must be a non-empty token")

    def __call__(self, function: Callable[P, R]) -> Callable[P, R]:
        """Mark an ordinary function as an interceptable effect boundary."""

        if self == PURE:
            raise ValueError("pure is not an effect a call performs")
        from fox.runtime import boundary

        return boundary(function, self)


def effect(name: str) -> Effect:
    """Name an effect, or decorate its boundary with ``@effect(\"io\")``.

    ``effect("log")`` and the string ``"log"`` name the same effect.
    """

    return Effect(name)


def synchronous(function: Callable[..., Any], label: str) -> None:
    if not callable(function):
        raise TypeError(f"{label} expects a callable")
    if any(
        inspect.iscoroutinefunction(item)
        or inspect.isasyncgenfunction(item)
        or inspect.isgeneratorfunction(item)
        for item in (function, function.__call__)
    ):
        raise TypeError(f"{label} supports synchronous functions, not async or generator functions")


class Between:
    """A domain bound the user wrote on an annotation.

    ``fox.between(0, 100)`` on ``Annotated[int, ...]`` tells the checker the
    integers to draw. Omit either end to leave that side open.
    """

    def __init__(self, low: float | None, high: float | None) -> None:
        self.low = low
        self.high = high


PURE: Effect = effect("pure")
