# Fox

Check what ordinary Python functions promise across generated calls—without changing their call style or turning I/O into generators.

```python
from typing import Annotated

from fox import fox


@fox(
    requires=lambda cents, people: cents >= 0 and people > 0,
    ensures=lambda cents, people, result: (
        len(result) == people and sum(result) == cents and max(result) - min(result) <= 1
    ),
)
def split_bill(
    cents: Annotated[int, fox.between(0, 10_000)],
    people: Annotated[int, fox.between(1, 50)],
) -> list[int]:
    each, extra = divmod(cents, people)
    return [each + 1 if index < extra else each for index in range(people)]


fox.check(split_bill)
```

Fox generates inputs and checks conservation and fairness. The runnable example also checks a floor-only implementation and reports the generated counterexample.

## Ordinary calls around effects

```python
from pathlib import Path

from fox import effect, fox


@effect("io")
def read_note(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


@effect("io")
def write_note(path: str, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")


@fox(effects="io", ensures=lambda path, content, result: result == content.strip())
def save_and_read(path: str, content: str) -> str:
    write_note(path, content.strip())
    return read_note(path)


memory: dict[str, str] = {}
fox.check(
    save_and_read,
    handlers={read_note: memory.__getitem__, write_note: memory.__setitem__},
)
```

An effect marks a replaceable synchronous boundary; the function still receives normal arguments and returns a normal value. Handlers are keyed by boundary function, not the shared `"io"` label, and only reached boundaries need one.

Contracts check outcomes for the calls they exercise; they do not prove every possible execution or that an arbitrary external side effect occurred. Only calls routed through `@effect` are replaceable—unwrapped I/O in a function, predicate, or handler remains real. Async and generator functions are unsupported. Under `python -O`, contracts and effect checks are removed; `fox.check` and `fox.intercept` are unavailable.

## Run the showcase

```sh
uv run python -m fox examples/contracts.py
uv run python examples/contracts.py
uv run python examples/effects.py
uv run python -O examples/effects.py
```
