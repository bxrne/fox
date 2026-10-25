from collections.abc import Generator
from contextvars import Context
from typing import Any

import pytest

from fox import EffectCall, EffectError, PostconditionError, PreconditionError, fox


def test_generator_checks_final_result_and_requires_before_body() -> None:
    calls = []

    @fox(requires=lambda n: n > 0, ensures=lambda result: result == 2, effects="io")
    def run(n: int) -> Generator[EffectCall, Any, int]:
        calls.append(n)
        return (yield fox.perform("io", lambda: n + 1))

    with pytest.raises(PreconditionError):
        run(0)
    assert calls == []
    assert run(1) == 2
    with pytest.raises(PostconditionError):
        run(2)


def test_effects_forward_arguments_results_and_handle_failures() -> None:
    events = []

    def read(path: str, *, encoding: str) -> str:
        events.append((path, encoding))
        raise OSError("offline")

    @fox(effects="io")
    def run() -> Generator[EffectCall, Any, str]:
        try:
            yield fox.perform("io", read, "note.txt", encoding="utf-8")
        except OSError:
            value = yield fox.perform("io", str, "fallback")
            return value
        finally:
            events.append("closed")
        return "unexpected"

    assert run() == "fallback"
    assert events == [("note.txt", "utf-8"), "closed"]
    with fox.intercept("io", lambda request: "mocked"):
        assert run() == "unexpected"
    assert events[-1] == "closed"


def test_interceptors_are_nested_scoped_and_context_local() -> None:
    @fox(effects="io")
    def read() -> Generator[EffectCall, Any, str]:
        return (yield fox.perform("io", lambda: "real"))

    with fox.intercept("io", lambda request: "outer"):
        assert read() == "outer"
        assert Context().run(read) == "real"
        with pytest.raises(ValueError), fox.intercept("io", lambda request: "inner"):
            assert read() == "inner"
            raise ValueError("leave handler")
        assert read() == "outer"
    assert read() == "real"


def test_handler_exceptions_are_thrown_at_the_yield() -> None:
    @fox(effects="io")
    def read() -> Generator[EffectCall, Any, str]:
        try:
            return (yield fox.perform("io", lambda: "real"))
        except FileNotFoundError:
            return "missing"

    def fail(request: EffectCall) -> None:
        raise FileNotFoundError("fake path")

    with fox.intercept("io", fail):
        assert read() == "missing"


def test_invalid_yield_closes_generator_and_restores_effect_stack() -> None:
    events = []

    @fox
    def invalid() -> Generator[Any, Any, None]:
        try:
            yield "not an effect"
        finally:
            events.append("closed")

    with pytest.raises(TypeError, match="must yield"):
        invalid()
    assert events == ["closed"]

    @fox(effects="io")
    def next_call() -> Generator[EffectCall, Any, int]:
        return (yield fox.perform("io", int, 1))

    assert next_call() == 1


def test_dynamic_nested_effects_are_checked_before_preconditions() -> None:
    events = []

    def requires() -> bool:
        events.append("precondition")
        return True

    @fox(effects="io", requires=requires)
    def io() -> int:
        return 1

    @fox
    def pure(callback: Any) -> int:
        return callback()

    with pytest.raises(EffectError, match="io"):
        pure(io)
    assert events == []


def test_generator_delegation_and_nested_decorated_calls() -> None:
    def helper() -> Generator[EffectCall, Any, int]:
        return (yield fox.perform("io", int, 1))

    @fox(effects="io")
    def inner() -> Generator[EffectCall, Any, int]:
        return (yield from helper())

    @fox(effects="io")
    def outer() -> Generator[EffectCall, Any, int]:
        result = inner()
        return result + (yield from helper())

    with fox.intercept("io", lambda request: 3):
        assert outer() == 6


def test_requests_reject_pure_and_invalid_callables() -> None:
    with pytest.raises(ValueError, match="pure"):
        fox.perform("pure", int, 1)

    async def async_call() -> int:
        return 1

    with pytest.raises(TypeError, match="not async"):
        fox.perform("io", async_call)

    async def async_handler(request: EffectCall) -> int:
        return 1

    with pytest.raises(TypeError, match="not async"), fox.intercept("io", async_handler):
        pass


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
