"""Generate fair bill splits and catch a floor-only allocation bug."""

from typing import Annotated

from fox import PostconditionError, fox


def is_fair_split(cents: int, people: int, shares: list[int]) -> bool:
    if cents < 0 or people < 1 or len(shares) != people:
        return False
    each, extra = divmod(cents, people)
    return (
        sum(shares) == cents
        and all(share in (each, each + 1) for share in shares)
        and sum(share == each + 1 for share in shares) == extra
    )


@fox(
    requires=lambda cents, people: cents >= 0 and people > 0,
    ensures=is_fair_split,
)
def split_bill(
    cents: Annotated[int, fox.between(0, 10_000)],
    people: Annotated[int, fox.between(1, 50)],
) -> list[int]:
    each, extra = divmod(cents, people)
    return [each + 1 if index < extra else each for index in range(people)]


def main() -> None:
    fox.check(split_bill)
    print("1,000 cents split three ways:", split_bill(1_000, 3))

    @fox(
        requires=lambda cents, people: cents >= 0 and people > 0,
        ensures=is_fair_split,
    )
    def floor_only(
        cents: Annotated[int, fox.between(0, 10_000)],
        people: Annotated[int, fox.between(1, 50)],
    ) -> list[int]:
        return [cents // people for _ in range(people)]

    try:
        fox.check(floor_only)
    except PostconditionError:
        print("Generated check caught the floor-only split dropping remainder cents.")
    else:
        raise AssertionError("The generated check should catch the floor-only split.")


if __name__ == "__main__":
    main()
