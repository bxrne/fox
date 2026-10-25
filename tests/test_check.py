from __future__ import annotations

from typing import Annotated, Optional

import pytest
from hypothesis import find, settings
from hypothesis.errors import NoSuchExample, Unsatisfiable

from fox import EffectError, effect, fox
from fox.check import check, strategy_for
from fox.runtime import _checking

_FIND_SETTINGS = settings(database=None, max_examples=100)
_POSITIONAL_INT = Annotated[int, fox.between(7, 7)]
_KEYWORD_INT = Annotated[int, fox.between(8, 8)]


def test_integer_bounds_round_inward_and_reject_empty_interval() -> None:
    strategy = strategy_for(Annotated[int, fox.between(1.2, 2.8)])

    assert find(strategy, lambda value: value == 2, settings=_FIND_SETTINGS) == 2
    with pytest.raises(NoSuchExample):
        find(strategy, lambda value: value != 2, settings=_FIND_SETTINGS)

    with pytest.raises(ValueError, match="no representable integer"):
        strategy_for(Annotated[int, fox.between(1.1, 1.9)])


def test_bounds_apply_to_non_none_union_branches() -> None:
    strategy = strategy_for(Annotated[Optional[int], fox.between(5, 5)])

    assert find(strategy, lambda value: value is None, settings=_FIND_SETTINGS) is None
    assert find(strategy, lambda value: value == 5, settings=_FIND_SETTINGS) == 5
    with pytest.raises(NoSuchExample):
        find(
            strategy,
            lambda value: value is not None and value != 5,
            settings=_FIND_SETTINGS,
        )


def test_check_binds_positional_only_and_keyword_only_arguments() -> None:
    calls: list[tuple[int, int]] = []

    @fox
    def target(positional: _POSITIONAL_INT, /, *, keyword: _KEYWORD_INT) -> None:
        calls.append((positional, keyword))

    check(target)

    assert calls
    assert set(calls) == {(7, 8)}


def test_check_bypasses_memoization_during_generated_runs() -> None:
    calls: list[int] = []

    @fox
    def target(value: Annotated[int, fox.between(4, 4)]) -> None:
        calls.append(value)

    check(target)
    check(target)

    assert len(calls) == 2
    assert _checking.get() is False


def test_missing_boundary_handler_prevents_real_io() -> None:
    body_calls: list[int] = []

    @effect("io")
    def read(value: int) -> int:
        body_calls.append(value)
        return value

    @fox(effects="io")
    def target(value: int) -> int:
        return read(value)

    with pytest.raises(EffectError, match=r"handler.*read"):
        check(target)

    assert body_calls == []
    assert _checking.get() is False


def test_nested_ordinary_calls_use_boundary_handlers() -> None:
    body_calls: list[int] = []

    @effect("io")
    def read(value: int) -> int:
        body_calls.append(value)
        return value

    @fox(effects="io")
    def inner(value: int) -> int:
        return read(value)

    @fox(effects="io", ensures=lambda result: result == 4)
    def caller(value: int) -> int:
        return inner(value)

    with pytest.raises(EffectError, match="handler"):
        check(caller)

    check(caller, handlers={read: lambda value: 4})

    assert body_calls == []
    assert _checking.get() is False


def test_handlers_receive_normal_positional_and_keyword_arguments() -> None:
    calls: list[tuple[int, int]] = []

    @effect("io")
    def add(number: int, /, *, step: int) -> int:
        raise AssertionError("real boundary executed")

    @fox(effects="io")
    def target(value: Annotated[int, fox.between(3, 3)]) -> None:
        result = add(value, step=1)
        fox.claim(result == 4)

    def handle(number: int, /, *, step: int) -> int:
        calls.append((number, step))
        return number + step

    check(target, handlers={add: handle})

    assert calls
    assert set(calls) == {(3, 1)}


def test_boundaries_with_the_same_effect_need_their_own_handlers() -> None:
    real_calls: list[str] = []

    @effect("io")
    def read() -> str:
        real_calls.append("read")
        return "real"

    @effect("io")
    def write(value: str) -> None:
        real_calls.append("write")

    @fox(effects="io")
    def copy() -> None:
        write(read())

    with pytest.raises(EffectError, match=r"handler.*write"):
        check(copy, handlers={read: lambda: "fake"})
    assert real_calls == []

    written: list[str] = []
    check(copy, handlers={read: lambda: "fake", write: written.append})
    assert written == ["fake"]
    assert real_calls == []


def test_unused_effect_declarations_do_not_need_handlers() -> None:
    @fox(effects=("io", "db"), ensures=lambda value, result: value == result)
    def no_io(value: int) -> int:
        return value

    check(no_io)


def test_predicates_use_handlers_during_generated_checks() -> None:
    @effect("io")
    def valid(value: int) -> bool:
        raise AssertionError("real boundary executed")

    @fox(effects="io", requires=lambda value: valid(value))
    def target(value: int) -> int:
        return value

    check(target, handlers={valid: lambda value: True})


def test_filtering_does_not_bypass_predicate_effect_declarations() -> None:
    @effect("io")
    def valid(value: int) -> bool:
        raise AssertionError("real boundary executed")

    @fox(requires=lambda value: valid(value))
    def target(value: int) -> int:
        return value

    with pytest.raises(EffectError, match="io"):
        check(target, handlers={valid: lambda value: False})


def test_check_does_not_leak_handlers_into_later_calls() -> None:
    @effect("io")
    def read() -> str:
        return "real"

    @fox(effects="io")
    def target() -> str:
        return read()

    check(target, handlers={read: lambda: "fake"})
    assert target() == "real"


def test_unsatisfiable_precondition_error_includes_target_name_and_cause() -> None:
    @fox(requires=lambda value: False)
    def never_satisfied(value: int) -> int:
        return value

    with pytest.raises(Unsatisfiable, match="never_satisfied") as raised:
        check(never_satisfied)

    assert isinstance(raised.value.__cause__, Unsatisfiable)
    assert "assumptions" in str(raised.value.__cause__)
