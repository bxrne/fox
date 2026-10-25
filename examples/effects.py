"""Check an ordinary write-then-read workflow with replaceable I/O."""

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
    requires=lambda path, content: bool(path),
    ensures=lambda path, content, result: result == content.strip(),
)
def save_and_read(path: str, content: str) -> str:
    write_note(path, content.strip())
    return read_note(path)


def main() -> None:
    if __debug__:
        memory: dict[str, str] = {}
        fox.check(
            save_and_read,
            handlers={read_note: memory.__getitem__, write_note: memory.__setitem__},
        )
        print("Generated checks passed with separate dict-backed read/write handlers.")

        preview: dict[str, str] = {}
        with fox.intercept({read_note: preview.__getitem__, write_note: preview.__setitem__}):
            print("Scoped override:", save_and_read("draft", "  Preview copy  "))
    else:
        print("Production mode: generated checks and interception are disabled.")

    with TemporaryDirectory() as directory:
        path = str(Path(directory) / "note.txt")
        result = save_and_read(path, "  Hello from a local file.  ")
        print("Local round-trip:", result)
        print("Local file contents:", Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
