import gc
import weakref

import pytest

from fox import fox
from fox.errors import EffectError
from fox.trace import tracked


def _global_action() -> str:
    return "global"


def test_multiline_signature_detects_tracked_io() -> None:
    def write() -> None:
        pass

    fox.track(write, "io")

    with pytest.raises(EffectError, match="io"):

        @fox
        def load(
            path: str,
        ) -> None:
            write()


def test_unhashable_untracked_callable_is_ignored() -> None:
    class UnhashableCallable:
        __hash__ = None

        def __call__(self) -> None:
            pass

    callback = UnhashableCallable()

    @fox
    def call_callback() -> None:
        callback()

    call_callback()


def test_parameter_and_closure_bindings_shadow_globals() -> None:
    fox.track(_global_action, "io")

    @fox
    def parameter_shadow(_global_action: object) -> object:
        return _global_action()

    assert parameter_shadow(lambda: "parameter") == "parameter"

    def closure_case() -> str:
        def _global_action() -> str:
            return "closure"

        fox.track(_global_action, "db")

        @fox(effects="db")
        def closure_shadow() -> str:
            return _global_action()

        return closure_shadow()

    assert closure_case() == "closure"


def test_definition_expressions_and_nested_bodies_are_not_scanned() -> None:
    def action() -> None:
        pass

    fox.track(action, "io")

    def decorator_factory() -> object:
        return lambda function: function

    fox.track(decorator_factory, "io")

    def default_value() -> int:
        return 1

    fox.track(default_value, "io")

    @fox
    @decorator_factory()
    def pure(value: int = default_value()) -> int:
        def never_called() -> None:
            action()

        return value

    assert pure() == 1


def test_tracked_callables_are_released() -> None:
    before = len(tracked)

    def callback() -> None:
        pass

    callback_ref = weakref.ref(callback)
    fox.track(callback, "io")
    assert len(tracked) == before + 1

    del callback
    gc.collect()

    assert callback_ref() is None
    assert len(tracked) == before
