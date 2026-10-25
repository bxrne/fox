import subprocess
import sys
import textwrap
from collections.abc import Callable
from typing import Annotated

import pytest
from hypothesis import given

from fox import (
    EffectError,
    FailedClaim,
    PostconditionError,
    PreconditionError,
    effect,
    fox,
)
from fox.check import check, strategy_for


def test_requires_rejects_caller() -> None:
    @fox(requires=lambda n: n >= 0)
    def absolute(n: int) -> int:
        return n

    with pytest.raises(PreconditionError):
        absolute(-1)


def test_ensures_rejects_function() -> None:
    @fox(ensures=lambda n, result: result == n + 1)
    def increment(n: int) -> int:
        return n

    with pytest.raises(PostconditionError):
        increment(1)


def test_claim_inside_body() -> None:
    @fox(effects=(effect("reads"), "io"), ensures=lambda result: result == 2)
    def load(n: int) -> int:
        fox.claim(n > 0, "n must be positive here")
        return n + 1

    assert load(1) == 2


def test_unnamed_effect_fails() -> None:
    def write(line: str) -> None:
        del line

    fox.track(write, "io")

    with pytest.raises(EffectError):

        @fox
        def noisy() -> None:
            write("x")

    @fox(effects="io")
    def loud() -> None:
        write("x")

    loud()


@pytest.mark.parametrize("decorate", [effect("io"), fox(effects="io")])
def test_caller_must_name_callee_effects(
    decorate: Callable[[Callable[[], int]], Callable[[], int]],
) -> None:
    real_calls: list[str] = []

    @decorate
    def read() -> int:
        real_calls.append("read")
        return 1

    with pytest.raises(EffectError):

        @fox
        def pure_caller() -> int:
            return read()

    assert real_calls == []

    @fox(effects="io")
    def io_caller() -> int:
        return read()

    assert io_caller() == 1


def test_pure_calls_are_memoised() -> None:
    calls = 0

    @fox
    def square(n: int) -> int:
        nonlocal calls
        calls += 1
        return n * n

    assert square(4) == 16
    assert square(4) == 16
    assert calls == 1


def test_claim_failure() -> None:
    @fox()
    def positive(n: int) -> int:
        fox.claim(n > 0)
        return n

    with pytest.raises(FailedClaim):
        positive(0)


def test_user_named_effect() -> None:
    db = effect("db")

    def query() -> int:
        return 1

    fox.track(query, db)

    @fox(effects="db")
    def load() -> int:
        return query()

    assert load() == 1

    with pytest.raises(EffectError):

        @fox
        def quiet() -> int:
            return query()


def test_check_rejects_a_broken_pure_function() -> None:
    @fox(ensures=lambda n, result: result == n)
    def broken(n: int) -> int:
        return n + 1

    with pytest.raises(PostconditionError):
        check(broken)


def test_optimize_keeps_memo_and_drops_checks() -> None:
    script = (
        "from fox import fox\n"
        "calls = 0\n"
        "@fox(requires=lambda n: n >= 0)\n"
        "def square(n: int) -> int:\n"
        "    global calls\n"
        "    calls += 1\n"
        "    return n * n\n"
        "print(square(-1))\n"
        "print(square(3))\n"
        "print(square(3))\n"
        "print(calls)\n"
        "print(hasattr(square, '__fox__'))\n"
        "@fox\n"
        "def total(values: list[int]) -> int:\n"
        "    return sum(values)\n"
        "print(total([1, 2]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == ["1", "9", "9", "2", "False", "3"]


def test_between_is_the_users_bound() -> None:
    strategy = strategy_for(Annotated[int, fox.between(2, 2)])

    @given(strategy)
    def draw(n: int) -> None:
        assert n == 2

    draw()


def test_spec_is_stored() -> None:
    @fox(requires=lambda n: n > 0, effects="io")
    def shown(n: int) -> int:
        return n

    assert shown.__fox__.pure is False
    assert len(shown.__fox__.requires) == 1


def test_check_uses_boundary_handlers_without_sandboxing_python_calls() -> None:
    real_calls: list[str] = []
    unwrapped_calls: list[str] = []

    @effect("io")
    def read(path: str) -> str:
        real_calls.append(path)
        return "real"

    def unwrapped(path: str) -> None:
        unwrapped_calls.append(path)

    @fox(effects="io", ensures=lambda path, result: result == "stubbed")
    def load(path: str) -> str:
        unwrapped(path)
        return read(path)

    with pytest.raises(EffectError) as error:
        fox.check(load)
    message = str(error.value).lower()
    assert "handler" in message and "read" in message
    assert unwrapped_calls
    assert real_calls == []

    handled_calls: list[str] = []
    fox.check(load, handlers={read: lambda path: handled_calls.append(path) or "stubbed"})
    assert handled_calls
    assert unwrapped_calls
    assert real_calls == []

    with pytest.raises(PostconditionError):
        fox.check(load, handlers={read: lambda path: "wrong"})
    assert real_calls == []


def test_effect_boundaries_and_checking_are_disabled_in_optimized_mode() -> None:
    script = textwrap.dedent("""\
        from fox import effect, fox
        @effect("io")
        def read():
            return "real"
        @fox
        def load():
            return read()
        print(load())
        try:
            with fox.intercept({read: lambda: "fake"}):
                print("intercepted")
        except RuntimeError:
            print("interception-disabled")
        try:
            fox.check(load)
        except RuntimeError:
            print("check-disabled")
    """)
    result = subprocess.run(
        [sys.executable, "-O", "-c", script], check=True, capture_output=True, text=True
    )
    assert result.stdout.splitlines() == ["real", "interception-disabled", "check-disabled"]


def test_dynamic_effect_boundaries_are_rejected_before_their_body() -> None:
    body_calls: list[str] = []

    @effect("io")
    def read() -> int:
        body_calls.append("read")
        return 1

    @fox
    def indirect(callback: Callable[[], int]) -> int:
        return callback()

    with pytest.raises(EffectError, match="io"):
        indirect(read)
    assert body_calls == []
