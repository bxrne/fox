import subprocess
import sys
from typing import Annotated

import pytest
from hypothesis import given

from fox import EffectError, FailedClaim, PostconditionError, PreconditionError, effect, fox
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


def test_caller_must_name_callee_effects() -> None:
    @fox(effects="io")
    def read() -> int:
        return 1

    with pytest.raises(EffectError):

        @fox
        def pure_caller() -> int:
            return read()


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
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == ["1", "9", "9", "2", "False"]


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
