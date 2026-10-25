from typing import Annotated

from fox import effect, fox


def test_bound_handlers_use_normal_arguments_and_only_the_selected_instance() -> None:
    real_calls: list[str] = []

    class Device:
        @effect("io")
        def send(self, item: str, /, *, urgent: bool = False) -> str:
            real_calls.append(item)
            return "real"

    first, second = Device(), Device()

    def fake(item: str, /, *, urgent: bool = False) -> str:
        return f"{item}:{urgent}"

    with fox.intercept({first.send: fake}):
        assert first.send("outer", urgent=True) == "outer:True"
        assert second.send("other") == "real"
        with fox.intercept({first.send: lambda item: "inner"}):
            assert first.send("nested") == "inner"
        assert first.send("restored") == "restored:False"

    assert first.send("outside") == "real"
    assert real_calls == ["other", "outside"]


def test_unbound_method_handlers_receive_the_instance() -> None:
    class Device:
        @effect("io")
        def send(self, item: str) -> str:
            raise AssertionError("real boundary executed")

    device = Device()
    with fox.intercept({Device.send: lambda self, item: (self, item)}):
        assert device.send("message") == (device, "message")


def test_generated_method_predicates_receive_the_bound_instance() -> None:
    real_calls: list[int] = []

    class Counter:
        offset = 1

        @effect("io")
        def read(self, value: int) -> int:
            real_calls.append(value)
            return value + self.offset

        @fox(
            effects="io",
            requires=lambda self, value: self.offset > 0,
            ensures=lambda self, value, result: result == value + self.offset,
        )
        def run(self, value: Annotated[int, fox.between(0, 5)]) -> int:
            return self.read(value)

    counter = Counter()
    fox.check(counter.run, handlers={counter.read: lambda value: value + counter.offset})
    assert real_calls == []
    assert counter.run(1) == 2
    assert real_calls == [1]


def test_class_method_handlers_and_predicates_receive_the_bound_class() -> None:
    class Counter:
        offset = 2

        @classmethod
        @effect("io")
        def read(cls, value: int) -> int:
            raise AssertionError("real boundary executed")

        @classmethod
        @fox(
            effects="io",
            requires=lambda cls, value: cls.offset > 0,
            ensures=lambda cls, value, result: result == value + cls.offset,
        )
        def run(cls, value: Annotated[int, fox.between(0, 5)]) -> int:
            return cls.read(value)

    fox.check(Counter.run, handlers={Counter.read: lambda value: value + Counter.offset})
