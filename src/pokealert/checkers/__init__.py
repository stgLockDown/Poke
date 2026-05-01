"""Checker registry."""
from __future__ import annotations

from ..http_client import PoliteHttpClient
from .amazon import AmazonChecker
from .base import BaseChecker
from .bestbuy import BestBuyChecker
from .costco import CostcoChecker
from .gamestop import GameStopChecker
from .pokemoncenter import PokemonCenterChecker
from .target import TargetChecker
from .walmart import WalmartChecker

CHECKER_CLASSES: dict[str, type[BaseChecker]] = {
    "pokemoncenter": PokemonCenterChecker,
    "target": TargetChecker,
    "bestbuy": BestBuyChecker,
    "walmart": WalmartChecker,
    "gamestop": GameStopChecker,
    "amazon": AmazonChecker,
    "costco": CostcoChecker,
}


def build_checkers(http: PoliteHttpClient) -> dict[str, BaseChecker]:
    return {name: cls(http) for name, cls in CHECKER_CLASSES.items()}


__all__ = ["BaseChecker", "CHECKER_CLASSES", "build_checkers"]