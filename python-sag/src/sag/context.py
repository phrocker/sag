from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Context(Protocol):
    def get(self, path: str) -> Any: ...
    def has(self, path: str) -> bool: ...
    def set(self, path: str, value: Any) -> None: ...
    def as_dict(self) -> dict[str, Any]: ...


class MapContext:
    def __init__(self, data: dict[str, Any] | None = None):
        self._data: dict[str, Any] = dict(data) if data else {}

    def get(self, path: str) -> Any:
        if not path:
            return None

        parts = path.split(".")
        current: Any = self._data

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return None
            else:
                return None

        return current

    def has(self, path: str) -> bool:
        return self.get(path) is not None

    def set(self, path: str, value: Any) -> None:
        if not path:
            return

        parts = path.split(".")
        if len(parts) == 1:
            self._data[path] = value
            return

        current = self._data
        for part in parts[:-1]:
            nxt = current.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                current[part] = nxt
            current = nxt
        current[parts[-1]] = value

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)
