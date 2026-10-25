"""Effect names, and the bounds a user puts on a generated draw."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Effect:
    """A named effect a function may perform.

    Two effects with the same name are equal. ``pure`` means the function
    performs no effect. It cannot be combined with any other name.
    """

    name: str

    def __post_init__(self) -> None:
        if self.name == "" or any(character.isspace() for character in self.name):
            raise ValueError("effect name must be a non-empty token")


def effect(name: str) -> Effect:
    """Return the effect with this name.

    ``effect("log")`` and the string ``"log"`` name the same effect.
    """

    return Effect(name)


class Between:
    """A domain bound the user wrote on an annotation.

    ``fox.between(0, 100)`` on ``Annotated[int, ...]`` tells the checker the
    integers to draw. Omit either end to leave that side open.
    """

    def __init__(self, low: float | None, high: float | None) -> None:
        self.low = low
        self.high = high


PURE: Effect = effect("pure")
