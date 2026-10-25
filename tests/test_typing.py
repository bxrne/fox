from collections.abc import Callable
from typing import TYPE_CHECKING

from typing_extensions import assert_type

from fox import Contracted, effect, fox


def test_configured_decorators_preserve_argument_and_return_types() -> None:
    decorate_effect = effect("io")
    decorate_contract = fox(effects="io")

    @decorate_effect
    def text(value: int, /) -> str:
        return str(value)

    @decorate_contract
    def caller(value: int, /) -> str:
        return text(value)

    if TYPE_CHECKING:
        typed_text: Callable[[int], str] = text
        assert_type(typed_text(1), str)
        assert_type(caller, Contracted[[int], str])
    assert assert_type(text(1), str) == "1"
    assert assert_type(caller(1), str) == "1"
