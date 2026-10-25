from functools import partial
from typing import Any

import pytest

from fox import PostconditionError, PreconditionError, fox


@pytest.mark.parametrize("rule", [1, "not callable", [lambda: True, None]])
def test_invalid_predicates_fail_at_decoration(rule: Any) -> None:
    with pytest.raises(TypeError, match="callables"):
        fox(requires=rule)(lambda: None)
    with pytest.raises(TypeError, match="callables"):
        fox(ensures=rule)(lambda: None)


def test_predicates_support_positional_only_defaults_and_keywords() -> None:
    def requires(n: int, /, default: int = 1, *, limit: int = 10) -> bool:
        return default <= n <= limit

    def ensures(result: int, /, **arguments: Any) -> bool:
        return result == arguments["n"]

    @fox(requires=requires, ensures=ensures)
    def identity(n: int) -> int:
        return n

    assert identity(1) == 1
    with pytest.raises(PreconditionError):
        identity(0)


def test_callable_objects_and_partials_report_contract_failures() -> None:
    class Positive:
        def __call__(self, n: int) -> bool:
            return n > 0

    @fox(requires=Positive())
    def identity(n: int) -> int:
        return n

    with pytest.raises(PreconditionError, match="Positive"):
        identity(-1)

    def greater(result: int, minimum: int) -> bool:
        return result > minimum

    @fox(ensures=partial(greater, minimum=2))
    def too_small() -> int:
        return 1

    with pytest.raises(PostconditionError, match="partial"):
        too_small()


def test_predicate_non_bool_and_unknown_names_are_helpful_errors() -> None:
    @fox(requires=lambda missing: True)
    def missing_arg(n: int) -> int:
        return n

    with pytest.raises(TypeError, match="expects missing"):
        missing_arg(1)

    @fox(ensures=lambda result: result)
    def not_bool() -> int:
        return 1

    with pytest.raises(TypeError, match="expected bool"):
        not_bool()


def test_decorator_configuration_can_be_reused() -> None:
    decorate = fox(
        requires=(rule for rule in [lambda n: n > 0]),
        effects=(name for name in ["io"]),
    )

    @decorate
    def first(n: int) -> int:
        return n

    @decorate
    def second(n: int) -> int:
        return n

    for function in (first, second):
        assert not function.__fox__.pure
        with pytest.raises(PreconditionError):
            function(0)
