from collections.abc import Generator
from typing import TYPE_CHECKING, Any

from typing_extensions import assert_type

from fox import Contracted, EffectCall, fox


def test_configured_decorators_preserve_argument_and_return_types() -> None:
    decorate = fox()

    @decorate
    def text(value: int, /) -> str:
        return str(value)

    @decorate
    def number(value: str, /) -> int:
        return int(value)

    @fox(effects="io")
    def flow(value: int, /) -> Generator[EffectCall, Any, str]:
        return (yield fox.perform("io", str, value))

    if TYPE_CHECKING:
        assert_type(text, Contracted[[int], str])
        assert_type(number, Contracted[[str], int])
        assert_type(flow, Contracted[[int], str])
    assert assert_type(text(1), str) == "1"
    assert assert_type(number("1"), int) == 1
    assert assert_type(flow(1), str) == "1"
