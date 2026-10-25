"""A pure contract for integer square roots, plus a caught off-by-one bug."""

import math
from typing import Annotated

from fox import PostconditionError, fox


def is_floor_sqrt(n: int, result: int) -> bool:
    return result >= 0 and result * result <= n < (result + 1) ** 2


@fox(
    requires=lambda n: n >= 0,
    ensures=is_floor_sqrt,
)
def floor_sqrt(n: Annotated[int, fox.between(0, 10_000)]) -> int:
    return math.isqrt(n)


def main() -> None:
    @fox(requires=lambda n: n >= 0, ensures=is_floor_sqrt)
    def off_by_one(n: int) -> int:
        return math.isqrt(n) + 1

    try:
        off_by_one(0)
    except PostconditionError:
        print("Contract caught the off-by-one at n=0.")
    else:
        raise AssertionError("The off-by-one example should violate its contract.")


if __name__ == "__main__":
    main()
