# fox

Delete the unit tests. Keep one end-to-end path. The contracts are the property tests.

A unit test restates a function in another file, with three examples you thought of. It goes stale the week the function changes. Fox puts the rule on the function. Calling it checks the rule. `python -m fox` draws the inputs. You stop writing that file.

End-to-end tests stay. A property cannot click through a login or prove the row landed. One e2e path plus the contracts is the suite.
Fox can be left out when hitting production.

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

`requires` binds the caller. `ensures` binds the function. Leave `effects` off and the function is pure, so Fox memoises it and generates its calls. `fox.between` is the only bound. Fox invents no range.

An effect is a name you choose.

```python
@fox(effects=http)
def post_note():
    ...
```

`fox.track(jsonify, http)` says that calling `jsonify` performs `http`. Calling another `@fox` function performs the effects that function names. A pure function that reaches HTTP fails at the definition.

For an effect that tests need to replace, write a generator and yield an explicit request:

```python
@fox(effects="io")
def read_note(path: str) -> str:
    return (yield fox.perform("io", Path(path).read_text))
```

Normal calls drive the generator and invoke each request. Tests can intercept requests with
`fox.intercept("io", handler)`, or pass `handlers={"io": handler}` to `fox.check` to generate
calls without touching the real world. The handler receives an `EffectCall` containing the
effect name, callable, positional arguments, and keyword arguments. `fox.check` refuses an
effectful function without handlers. Interception and contract checks are disabled by
`python -O`; production still drives yielded requests against their real callables.

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

Ship with the checks compiled out. Pure, non-generator functions stay memoised; generator
functions are always executed and are never memoised.

```bash
python -O -m yourapp
```

## Lineage

- Design by contract. Bertrand Meyer, Eiffel `require` and `ensure`. [Design by contract](https://en.wikipedia.org/wiki/Design_by_contract), [Eiffel](https://www.eiffel.org/).
- The same idea on Python functions. [icontract](https://github.com/Parquery/icontract), [deal](https://github.com/life4/deal), [dpcontracts](https://github.com/deadpixi/contracts).
- The property is the test. [QuickCheck](https://hackage.haskell.org/package/QuickCheck) (Claessen and Hughes), [Hypothesis](https://hypothesis.readthedocs.io/) (MacIver and Hatfield-Dodds).
- Effects are part of the interface. [Plotkin and Pretnar](https://homepages.inf.ed.ac.uk/gdp/publications/Effect_Handlers.html), [Koka](https://koka-lang.github.io/koka/doc/book.html) (Leijen).
