import subprocess
import sys
import textwrap

import pytest

from fox import FailedClaim, fox


def test_lazy_claims_validate_their_result() -> None:
    fox.claim(lambda: True)
    with pytest.raises(FailedClaim, match="not positive"):
        fox.claim(lambda: False, "not positive")


def test_production_does_not_evaluate_lazy_checks_or_import_the_checker() -> None:
    script = textwrap.dedent('''\
        import sys
        from fox import fox
        def fail(*args, **kwargs):
            raise RuntimeError("test code ran")
        @fox(requires=fail, ensures=fail, effects="io")
        def run():
            fox.claim(fail)
            return (yield fox.perform("io", lambda: "real"))
        print(run())
        print(hasattr(run, "__fox__"))
        print("hypothesis" in sys.modules)
    ''')
    result = subprocess.run(
        [sys.executable, "-O", "-c", script], check=True, capture_output=True, text=True
    )
    assert result.stdout.splitlines() == ["real", "False", "False"]


@pytest.mark.parametrize("flags", [[], ["-O"]])
def test_async_functions_are_rejected_instead_of_caching_coroutines(flags: list[str]) -> None:
    script = textwrap.dedent('''\
        from fox import fox
        async def coroutine():
            return 1
        async def stream():
            yield 1
        for function in (coroutine, stream):
            try:
                fox(function)
            except TypeError as error:
                print(error)
    ''')
    result = subprocess.run(
        [sys.executable, *flags, "-c", script], check=True, capture_output=True, text=True
    )
    assert result.stdout.splitlines() == [
        "fox supports synchronous functions and generators, not async",
        "fox supports synchronous functions and generators, not async",
    ]
