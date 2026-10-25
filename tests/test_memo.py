import math
import subprocess
import sys
import textwrap

import pytest

from fox import fox


@pytest.mark.parametrize("flags", [[], ["-O"]])
def test_memoisation_preserves_types_and_mutability(flags: list[str]) -> None:
    script = textwrap.dedent("""\
        from fox import fox
        @fox
        def describe(value):
            return type(value[0]).__name__
        print(describe((True,)), describe((1.0,)), describe((1,)))
        @fox
        def fresh():
            return {"items": []}
        fresh()["items"].append("changed")
        print(fresh())
        @fox
        def stream():
            return (n for n in range(2))
        print(list(stream()), list(stream()))
    """)
    result = subprocess.run(
        [sys.executable, *flags, "-c", script], check=True, capture_output=True, text=True
    )
    assert result.stdout.splitlines() == ["bool float int", "{'items': []}", "[0, 1] [0, 1]"]


def test_memoisation_preserves_signed_zero() -> None:
    @fox
    def sign(value: float) -> float:
        return math.copysign(1.0, value)

    assert sign(0.0) == 1.0
    assert sign(-0.0) == -1.0


def test_memoisation_can_be_disabled() -> None:
    calls = []

    @fox(memoize=False)
    def identity(n: int) -> int:
        calls.append(n)
        return n

    assert identity(1) == identity(1) == 1
    assert calls == [1, 1]


def test_memoisation_is_bounded() -> None:
    calls = []

    @fox
    def identity(n: int) -> int:
        calls.append(n)
        return n

    for n in range(129):
        assert identity(n) == n
    assert identity(128) == 128
    assert len(calls) == 129
    assert identity(0) == 0
    assert len(calls) == 130


def test_unhashable_arguments_do_not_mask_body_errors() -> None:
    calls = []

    @fox
    def broken(values: list[int]) -> int:
        calls.append(values)
        raise TypeError("body failed")

    with pytest.raises(TypeError, match="body failed"):
        broken([1])
    assert calls == [[1]]
