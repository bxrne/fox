"""Integer square root. The contract is the test.

    uv run python -m fox examples/isqrt.py
"""

from typing import Annotated

from fox import fox


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


def main() -> None:
    print(isqrt(10))


if __name__ == "__main__":
    main()
