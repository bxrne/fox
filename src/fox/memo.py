"""Conservative, bounded memoisation for functions declared pure."""

from __future__ import annotations

import functools
import struct
from collections import OrderedDict
from collections.abc import Callable
from threading import RLock
from typing import Any, TypeVar

from typing_extensions import ParamSpec

from fox.runtime import _checking

P = ParamSpec("P")
R = TypeVar("R")
_UNSAFE = object()
_LIMIT = 128


def _key(value: Any) -> Any:
    kind = type(value)
    if kind in (type(None), bool, int, str, bytes):
        return kind, value
    if kind is float:
        return kind, struct.pack("!d", value)
    if kind is complex:
        return kind, struct.pack("!dd", value.real, value.imag)
    if kind in (tuple, frozenset):
        parts = tuple(_key(item) for item in value)
        if any(part is _UNSAFE for part in parts):
            return _UNSAFE
        return kind, frozenset(parts) if kind is frozenset else parts
    return _UNSAFE


def memoized(target: Callable[P, R]) -> Callable[P, R]:
    cache: OrderedDict[Any, R] = OrderedDict()
    lock = RLock()

    @functools.wraps(target)
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        if __debug__ and _checking.get():
            return target(*args, **kwargs)
        key = _key((args, tuple(kwargs.items())))
        if key is _UNSAFE:
            return target(*args, **kwargs)
        with lock:
            if key in cache:
                cache.move_to_end(key)
                return cache[key]
        result = target(*args, **kwargs)
        if _key(result) is not _UNSAFE:
            with lock:
                cache[key] = result
                cache.move_to_end(key)
                if len(cache) > _LIMIT:
                    cache.popitem(last=False)
        return result

    return call
