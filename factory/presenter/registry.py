from __future__ import annotations

from typing import Any

from factory.presenter.base import PresenterProvider
from factory.presenter.providers.gary import GaryPresenterProvider
from factory.presenter.providers.darla_ltx_a2v import DarlaLtxA2VPresenterProvider
from factory.presenter.providers.ltx25 import Ltx25LizPresenterProvider
from factory.presenter.providers.none import NonePresenterProvider


def create_presenter(config: dict[str, Any]) -> PresenterProvider:
    provider = str(config.get("provider") or "gary").lower()
    if provider == "gary":
        return GaryPresenterProvider()
    if provider in {"liz", "ltx25_liz"}:
        return Ltx25LizPresenterProvider(
            frames=int(config.get("frames", 193)),
            fps=int(config.get("fps", 24)),
            seed=int(config.get("seed", 250901)),
        )
    if provider in {"darla", "ltx25_darla"}:
        return DarlaLtxA2VPresenterProvider(
            fps=int(config.get("fps", 24)),
            seed=int(config.get("seed", 250901)),
        )
    if provider == "none":
        return NonePresenterProvider()
    raise ValueError(f"Unknown presenter provider: {provider}")
