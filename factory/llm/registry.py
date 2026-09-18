from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from factory.llm.base import LLMCapabilities, LLMProvider
from factory.llm.qwen_local import QwenLocalProvider


def load_llm_config(factory_root: Path) -> dict[str, Any]:
    path = factory_root.resolve() / "config" / "providers.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = payload.get("llm") or {}
    return config if isinstance(config, dict) else {}


def resolve_llm_provider(factory_root: Path) -> tuple[LLMProvider | None, LLMCapabilities]:
    config = load_llm_config(factory_root)
    provider_name = str(config.get("provider") or "none")
    if not bool(config.get("enabled", True)) or provider_name in {"none", "disabled", ""}:
        status = LLMCapabilities(False, provider_name or "none", "", detail="LLM reasoning disabled; deterministic fallback active")
        return None, status
    if provider_name != "qwen_local":
        status = LLMCapabilities(False, provider_name, str(config.get("endpoint") or ""), detail="Unknown LLM provider")
        return None, status
    provider = QwenLocalProvider(config)
    status = provider.probe()
    return (provider if status.available else None), status
