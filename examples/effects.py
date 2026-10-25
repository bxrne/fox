"""Ordinary calls around replaceable I/O boundaries."""

from pathlib import Path
from tempfile import TemporaryDirectory

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


def main() -> None:
    fox.check(title, handlers={read_note: lambda path: "  Hello, Fox!\n"})
    fox.check(save_note, handlers={write_note: lambda path, content: None})
    print("Generated checks passed with separate read/write fakes.")

    with TemporaryDirectory() as directory:
        path = Path(directory) / "note.txt"
        path.write_text("  Hello, Fox!  \n", encoding="utf-8")
        print("real local title:", title(str(path)))
        save_note(str(path), "Updated locally.\n")
        print("real local contents:", path.read_text(encoding="utf-8").strip())

    with fox.intercept(
        {
            read_note: lambda path: "  Preview copy  \n",
            write_note: lambda path, content: None,
        }
    ):
        print("scoped override:", title("unused.txt"))
        save_note("also-unused.txt", "not written\n")


if __name__ == "__main__":
    main()
