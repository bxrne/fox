"""Check pure ``@fox`` functions in a module. The contracts are the tests.

Usage: ``python -m fox <module.py or module.name>``
"""

import importlib
import runpy
import sys
from pathlib import Path


def _load(target: str) -> None:
    path = Path(target)
    if path.suffix == ".py":
        previous_path = sys.path[:]
        sys.path.insert(0, str(path.resolve().parent))
        try:
            runpy.run_path(str(path), run_name="fox_subject")
        finally:
            sys.path[:] = previous_path
        return
    importlib.import_module(target)


def main() -> None:
    if not __debug__:
        raise SystemExit("python -O drops the checks. Run this without -O.")
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m fox <module.py or module.name>")
    _load(sys.argv[1])
    from fox.check import check_pure

    count = check_pure()
    print(f"fox checked {count} pure function(s)")


if __name__ == "__main__":
    main()
