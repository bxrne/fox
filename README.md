# Fox

Contracts and property checks for ordinary Python functions. Put the rule beside the function; keep its body and call sites normal.

## Start with a pure function

```python
import math
from typing import Annotated

from fox import fox


@fox(
    requires=lambda n: n >= 0,
    ensures=lambda n, result: result >= 0
    and result * result <= n < (result + 1) ** 2,
)
def floor_sqrt(n: Annotated[int, fox.between(0, 10_000)]) -> int:
    return math.isqrt(n)
```

Fox generates inputs for the annotation and checks the precondition and mathematical postcondition. That invariant catches an off-by-one result. The wrapper keeps ordinary positional and keyword calls; `fox.check(func)` generates calls from the annotated signature, checks one function, and bypasses pure-call caching.

## Keep I/O as ordinary calls

Mark the boundary, then call it normally. A boundary stays a synchronous ordinary call: the implementation or fake receives the same arguments, and its return value comes back:

```python
from pathlib import Path

from fox import effect, fox


@effect("io")
def read_note(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


@effect("io")
def write_note(path: str, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")


@fox(
    effects="io",
    requires=lambda path: bool(path),
    ensures=lambda path, result: result == result.strip(),
)
def title(path: str) -> str:
    return read_note(path).strip()


@fox(
    effects="io",
    requires=lambda path, content: bool(path),
    ensures=lambda path, content, result: result == content,
)
def save_note(path: str, content: str) -> str:
    write_note(path, content)
    return content


fox.check(title, handlers={read_note: lambda path: "  Hello\n"})
fox.check(save_note, handlers={write_note: lambda path, content: None})

with fox.intercept({read_note: lambda path: "  Preview\n"}):
    print(title("unused.txt"))
```

`@effect("io")` labels synchronous boundaries. In `fox.check`, handlers are keyed by those decorated functions and receive the same ordinary arguments; the `io` label does not merge `read_note` and `write_note`. Only reached boundaries need handlers. A missing handler raises `EffectError` before that boundary's real body runs. `fox.intercept` provides scoped, context-local overrides and can be nested.

Fox does not sandbox arbitrary Python I/O: only calls routed through an `@effect` boundary are replaceable. Wrapping external operations is the application's responsibility. `fox.track` is an advanced, best-effort static annotation for third-party calls; it does not intercept them.

## Runtime notes

- Eligible pure calls may use a bounded cache for immutable built-in arguments and results. Use `@fox(memoize=False)` to opt out; `fox.check` bypasses the cache.
- Bound generated values with `Annotated[int, fox.between(low, high)]`. `fox.claim(lambda: condition)` checks a body invariant in normal mode and skips evaluating the callable under `python -O`.
- `python -O` removes contracts, effect checks, and effect metadata; `@effect` leaves the original callable and the safe cache remains. `fox.check` and `fox.intercept` raise `RuntimeError` rather than pretending to check. The ordinary `fox` import does not import Hypothesis.
- Functions and effect boundaries must be synchronous. Async and generator functions are rejected with clear errors.
- `PreconditionError`, `PostconditionError`, and `EffectError` identify caller, result, and effect-contract failures.

## Examples

Both scripts use only the standard library beyond Fox. `effects.py` writes only inside a temporary directory.

```sh
uv run python -m fox examples/contracts.py
uv run python examples/contracts.py
uv run python examples/effects.py
```
