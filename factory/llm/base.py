from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LLMCapabilities:
    available: bool
    provider: str
    endpoint: str
    model: str | None = None
    context_limit: int | None = None
    openai_compatible: bool = False
    tool_calling: bool = False
    structured_json: str = "unavailable"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMProvider(ABC):
    """Reasoning only. Providers never execute actions or mutate applications."""

    @abstractmethod
    def probe(self) -> LLMCapabilities:
        raise NotImplementedError

    @abstractmethod
    def complete_json(
        self,
        *,
        task: str,
        system: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        audit_dir: Path,
    ) -> dict[str, Any]:
        raise NotImplementedError
