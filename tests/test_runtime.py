from contextvars import Context
from typing import Any

import pytest

from fox import EffectError, PostconditionError, PreconditionError, effect, fox


def test_contracts_apply_before_and_after_effect_boundary_calls() -> None:
    real_calls: list[int] = []

    @effect("io")
    def read(value: int) -> int:
        real_calls.append(value)
        return value + 1

    @fox(
        effects="io",
        requires=lambda value: value > 0,
        ensures=lambda value, result: result == value + 1,
    )
    def run(value: int) -> int:
        return read(value)

    with pytest.raises(PreconditionError):
        run(0)
    assert real_calls == []
    assert run(1) == 2

    with fox.intercept({read: lambda value: value + 1}):
        assert run(2) == 3
    with fox.intercept({read: lambda value: 0}):
        with pytest.raises(PostconditionError):
            run(2)
    assert real_calls == [1]


def test_replacements_forward_arguments_and_distinguish_same_named_effects() -> None:
    real_calls: list[str] = []
    replacement_calls: list[tuple[str, str, str]] = []

    @effect("io")
    def read(path: str, *, encoding: str = "utf-8") -> str:
        real_calls.append("read")
        return f"real-read:{path}:{encoding}"

    @effect("io")
    def write(path: str, contents: str) -> str:
        real_calls.append("write")
        return f"real-write:{path}:{contents}"

    @fox(effects="io")
    def read_default(path: str) -> str:
        return read(path)

    @fox(effects="io")
    def read_encoded(path: str, *, encoding: str) -> str:
        return read(path, encoding=encoding)

    @fox(effects="io")
    def write_file(path: str, contents: str) -> str:
        return write(path, contents)

    def fake_read(path: str, *, encoding: str = "utf-8") -> str:
        replacement_calls.append(("read", path, encoding))
        return f"fake-read:{path}:{encoding}"

    def fake_write(path: str, contents: str) -> str:
        replacement_calls.append(("write", path, contents))
        return f"fake-write:{path}:{contents}"

    with fox.intercept({read: fake_read, write: fake_write}):
        assert read_default("notes.txt") == "fake-read:notes.txt:utf-8"
        assert read_encoded("notes.txt", encoding="utf-16") == "fake-read:notes.txt:utf-16"
        assert write_file("notes.txt", "hello") == "fake-write:notes.txt:hello"

    assert replacement_calls == [
        ("read", "notes.txt", "utf-8"),
        ("read", "notes.txt", "utf-16"),
        ("write", "notes.txt", "hello"),
    ]
    assert real_calls == []


def test_interceptors_nest_restore_after_errors_and_are_context_local() -> None:
    @effect("io")
    def read() -> str:
        return "real-read"

    @effect("io")
    def write() -> str:
        return "real-write"

    @fox(effects="io")
    def both() -> tuple[str, str]:
        return read(), write()

    outer = {read: lambda: "outer-read", write: lambda: "outer-write"}
    with fox.intercept(outer):
        assert both() == ("outer-read", "outer-write")
        with fox.intercept({read: lambda: "inner-read"}):
            assert both() == ("inner-read", "outer-write")
            with pytest.raises(ValueError):
                with fox.intercept({read: lambda: "failed-scope"}):
                    assert both() == ("failed-scope", "outer-write")
                    raise ValueError("leave handler scope")
            assert both() == ("inner-read", "outer-write")
        assert both() == ("outer-read", "outer-write")
        assert Context().run(both) == ("real-read", "real-write")
    assert both() == ("real-read", "real-write")


def test_handler_errors_follow_normal_try_finally_flow() -> None:
    real_calls: list[str] = []
    cleanup: list[str] = []

    @effect("io")
    def read() -> str:
        real_calls.append("called")
        raise OSError("offline")

    @fox(effects="io")
    def load() -> str:
        try:
            return read()
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "offline"
        finally:
            cleanup.append("closed")

    assert load() == "offline"

    def fail() -> str:
        raise FileNotFoundError("fake path")

    with fox.intercept({read: fail}):
        assert load() == "missing"

    assert real_calls == ["called"]
    assert cleanup == ["closed", "closed"]


def test_dynamic_effect_calls_fail_before_the_boundary_body() -> None:
    body_calls: list[str] = []

    @effect("io")
    def read() -> int:
        body_calls.append("read")
        return 1

    @fox
    def indirect(callback: Any) -> int:
        return callback()

    with pytest.raises(EffectError, match="io"):
        indirect(read)
    assert body_calls == []


def test_interceptors_reject_invalid_boundaries_and_replacements() -> None:
    @effect("io")
    def read() -> str:
        return "real"

    def unmarked() -> str:
        return "unmarked"

    async def async_replacement() -> str:
        return "async"

    def generator_replacement() -> Any:
        yield "generator"

    invalid_handlers: list[Any] = [
        {unmarked: lambda: "fake"},
        {"io": lambda: "fake"},
        {read: object()},
        {read: async_replacement},
        {read: generator_replacement},
    ]
    for handlers in invalid_handlers:
        with pytest.raises(TypeError):
            with fox.intercept(handlers):
                pass

    with pytest.raises(ValueError, match="pure"):
        effect("pure")(lambda: None)


def test_invalid_tracking_does_not_partially_register_effects() -> None:
    from fox.trace import tracked

    def call() -> None:
        pass

    with pytest.raises(ValueError, match="pure"):
        fox.track(call, "io", "pure")
    assert call not in tracked


def test_tracking_rejects_non_callable_objects() -> None:
    class NotCallable:
        pass

    value: Any = NotCallable()
    with pytest.raises(TypeError, match="expects a callable"):
        fox.track(value, "io")
