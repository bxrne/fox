import subprocess
import sys
import textwrap

import pytest

from fox import FailedClaim, effect, fox


def test_lazy_claims_validate_their_result() -> None:
    fox.claim(lambda: True)
    with pytest.raises(FailedClaim, match="not positive"):
        fox.claim(lambda: False, "not positive")


def test_optimized_mode_uses_original_functions_and_disables_checks() -> None:
    script = textwrap.dedent("""\
        import sys
        from fox import effect, fox
        def fail(*args, **kwargs):
            raise RuntimeError("test code ran")
        def read_body():
            return "real"
        read = effect("io")(read_body)
        print(read is read_body)
        print(read.__dict__ == {})
        @fox(requires=fail, ensures=fail, effects="io")
        def run():
            fox.claim(fail)
            return read()
        print(run())
        print(hasattr(run, "__fox__"))
        try:
            with fox.intercept({read: lambda: "fake"}):
                print("intercepted")
        except RuntimeError:
            print("interception-disabled")
        try:
            fox.check(run)
        except RuntimeError:
            print("check-disabled")
        print("hypothesis" in sys.modules)
    """)
    result = subprocess.run(
        [sys.executable, "-O", "-c", script], check=True, capture_output=True, text=True
    )
    assert result.stdout.splitlines() == [
        "True",
        "True",
        "real",
        "False",
        "interception-disabled",
        "check-disabled",
        "False",
    ]


def test_importing_fox_does_not_import_hypothesis() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import fox; print('hypothesis' in sys.modules)"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "False"


@pytest.mark.parametrize("flags", [[], ["-O"]])
def test_decorators_reject_async_and_generator_functions(flags: list[str]) -> None:
    script = textwrap.dedent("""\
        from fox import effect, fox
        async def coroutine():
            return 1
        async def async_stream():
            yield 1
        def generator():
            yield 1
        def expect_rejected(decorator, function, kind):
            try:
                decorator(function)
            except TypeError as error:
                message = str(error).lower()
                if kind == "generator":
                    assert "generator" in message
                else:
                    assert "async" in message or "asynchronous" in message
                print("rejected")
            else:
                raise AssertionError(f"accepted {function.__name__}")
        for decorator in (fox, effect("io")):
            expect_rejected(decorator, coroutine, "async")
            expect_rejected(decorator, async_stream, "async")
            expect_rejected(decorator, generator, "generator")
    """)
    result = subprocess.run(
        [sys.executable, *flags, "-c", script], check=True, capture_output=True, text=True
    )
    assert result.stdout.splitlines() == ["rejected"] * 6
