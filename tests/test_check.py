from __future__ import annotations

from typing import Annotated, Optional

import pytest
from hypothesis import find, settings
from hypothesis.errors import NoSuchExample, Unsatisfiable

from fox import fox
from fox.check import check, strategy_for
from fox.effects import EffectCall
from fox.runtime import _checking

_FIND_SETTINGS = settings(database=None, max_examples=100)


def test_integer_bounds_round_outwards_and_reject_empty_interval() -> None:
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
    def target(positional: Annotated[int, fox.between(7, 7)], /, *, keyword: Annotated[int, fox.between(8, 8)]) -> None:
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


def test_effectful_non_generator_is_rejected_even_with_handler() -> None:
    body_calls: list[int] = []
    handler_calls: list[EffectCall] = []

    @fox(effects="io")
    def target(value: int) -> int:
        body_calls.append(value)
        return value

    with pytest.raises(TypeError, match=r"requires effectful function.*generator"):
        check(target, handlers={"io": handler_calls.append})

    assert body_calls == []
    assert handler_calls == []


def test_nested_effectful_non_generator_fails_closed_during_check() -> None:
    body_calls: list[int] = []

    @fox(effects="io")
    def direct_io(value: int) -> int:
        body_calls.append(value)
        return value

    @fox(effects="io")
    def caller(value: int) -> int:
        direct_io(value)
        if False:
            yield fox.perform("io", lambda: None)

    with pytest.raises(TypeError, match="generated effectful calls must be generators"):
        check(caller, handlers={"io": lambda request: None})

    assert body_calls == []
    assert _checking.get() is False


def test_generator_effect_checks_keep_explicit_handlers_working() -> None:
    requests: list[EffectCall] = []

    @fox(effects="io")
    def target(value: Annotated[int, fox.between(3, 3)]):
        result = yield fox.perform("io", lambda number: number + 1, value)
        fox.claim(result == 4)

    with pytest.raises(TypeError, match="needs handlers for declared effects: io"):
        check(target)
    assert requests == []

    def handle(request: EffectCall) -> int:
        requests.append(request)
        return request.args[0] + 1

    check(target, handlers={"io": handle})

    assert requests
    assert all(request.args == (3,) for request in requests)


def test_unsatisfiable_precondition_error_includes_target_name_and_cause() -> None:
    @fox(requires=lambda value: False)
    def never_satisfied(value: int) -> int:
        return value

    with pytest.raises(Unsatisfiable, match="never_satisfied") as raised:
        check(never_satisfied)

    assert isinstance(raised.value.__cause__, Unsatisfiable)
    assert "assumptions" in str(raised.value.__cause__)
