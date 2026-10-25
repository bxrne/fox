# fox

Delete the unit tests. Keep one end-to-end path. The contracts are the property tests.

A unit test restates a function in another file, with three examples you thought of. It goes stale the week the function changes. Fox puts the rule on the function. Calling it checks the rule. `python -m fox` draws the inputs. You stop writing that file.

End-to-end tests stay. A property cannot click through a login or prove the row landed. One e2e path plus the contracts is the suite.
Fox checks can be disabled in production.

```python
from typing import Annotated

from fox import effect, fox

http = effect("http")

@fox(
    requires=lambda n: n >= 0,
    ensures=lambda n, result: result * result <= n < (result + 1) * (result + 1),
)
def isqrt(n: Annotated[int, fox.between(0, 10_000)]) -> int:
    root = 0
    while (root + 1) * (root + 1) <= n:
        fox.claim(root * root <= n)
        root += 1
    return root
```

`requires` binds the caller. `ensures` binds the function. Leave `effects` off to declare the function pure and let Fox generate its calls. `fox.between` bounds the generated values; integer bounds round inward, and bounds on optional numbers apply to the numeric values.

Pure functions use a bounded cache when their arguments and results are immutable built-in values. Mutable values, custom objects, iterators, and generators are not cached. Use `@fox(memoize=False)` when calls must always run or object identity matters. Declaring a function pure is your promise, not proof that its body is deterministic.

An effect is a name you choose.

```python
@fox(effects=http)
def post_note():
    ...
```

`fox.track(jsonify, http)` says that calling `jsonify` performs `http`. Calling another `@fox` function performs the effects that function names. Fox checks known direct calls at decoration time and nested `@fox` calls at runtime. The source scan is best-effort: it does not infer effects for arbitrary Python code.

For an effect that tests need to replace, write a generator and yield an explicit request:

```python
from collections.abc import Generator
from pathlib import Path
from typing import Any

from fox import EffectCall, fox

@fox(effects="io")
def read_note(path: str) -> Generator[EffectCall, Any, str]:
    return (yield fox.perform("io", Path(path).read_text))
```

Normal calls drive the generator and return its final value. Tests can replace yielded requests with `fox.intercept("io", handler)` or generate calls with explicit handlers:

```python
fox.check(read_note, handlers={"io": lambda request: "a test note"})
```

The handler receives an `EffectCall` containing the effect, callable, positional arguments, and keyword arguments. Handler results are sent back to the generator; exceptions are raised at the yield so normal `try`/`except`/`finally` works. Interceptors are scoped to their context, including nested overrides.

`fox.check` requires a handler for every declared effect and rejects ordinary effectful functions before calling them. All replaceable I/O must go through `fox.perform`: direct calls in the body, predicates, or handlers are still real Python, not sandboxed. Generated checks bypass memoisation so the body is exercised each time.

The decorator preserves argument types and exposes a generator's final return type. Only synchronous functions and generators are supported; async callables are rejected. Under `python -O`, interception is unavailable and yielded requests invoke their real callables.

## Move a project

1. Decorate the pure functions. `requires` and `ensures` replace the example tables. Delete those unit tests.
2. Name the edges. `effect("http")`, `effect("db")`. Fox will not invent those calls. Your e2e test is what runs them.
3. Run the properties. Keep the one test that boots the app and hits the route.

```bash
uv run python -m fox examples/isqrt.py
uv run --group examples python examples/notes.py
```

[`examples/isqrt.py`](examples/isqrt.py) has no unit test. The contract is the property. [`examples/notes.py`](examples/notes.py) is a Flask `POST /notes`: `make_note` is checked for free, and the route is the end-to-end path. A blank note is 400. A real note is 200.

`PreconditionError` is a bad caller. `PostconditionError` is a bad body. `EffectError` is an effect the function did not name.

Ship with the checks compiled out. Eligible pure calls still use the bounded cache; generators always run. `requires` and `ensures` are not evaluated. For body checks, use `fox.claim(lambda: expensive_check())` to skip evaluating the condition as well: Python still evaluates ordinary arguments such as `fox.claim(expensive_check())` before calling Fox.

```bash
python -O -m yourapp
```

## Lineage

- Design by contract. Bertrand Meyer, Eiffel `require` and `ensure`. [Design by contract](https://en.wikipedia.org/wiki/Design_by_contract), [Eiffel](https://www.eiffel.org/).
- The same idea on Python functions. [icontract](https://github.com/Parquery/icontract), [deal](https://github.com/life4/deal), [dpcontracts](https://github.com/deadpixi/contracts).
- The property is the test. [QuickCheck](https://hackage.haskell.org/package/QuickCheck) (Claessen and Hughes), [Hypothesis](https://hypothesis.readthedocs.io/) (MacIver and Hatfield-Dodds).
- Effects are part of the interface. [Plotkin and Pretnar](https://homepages.inf.ed.ac.uk/gdp/publications/Effect_Handlers.html), [Koka](https://koka-lang.github.io/koka/doc/book.html) (Leijen).
