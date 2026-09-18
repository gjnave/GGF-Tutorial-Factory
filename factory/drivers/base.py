from __future__ import annotations

from abc import abstractmethod
from typing import Any

from factory.adapters.base import ApplicationAdapter


class ApplicationDriver(ApplicationAdapter):
    """A persistent application-specific semantic automation layer."""

    @abstractmethod
    def capabilities(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def execute_operation(self, name: str, value: Any = None, **kwargs: Any) -> Any:
        raise NotImplementedError

    def supports_operation(self, name: str) -> bool:
        item = self.capabilities().get(name) or {}
        return bool(item.get("verified", False))
