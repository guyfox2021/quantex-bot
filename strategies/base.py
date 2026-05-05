from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Literal


SignalType = Literal["BUY", "SELL", "HOLD", "INFO", "WARNING"]


@dataclass
class StrategySignal:
    signal_type: SignalType
    strategy_name: str
    reason: str
    recommended_action: str
    amount_usdt: float = 0.0
    amount_btc_percent: float = 0.0
    trigger_type: Optional[str] = None
    level_percent: Optional[float] = None
    buyback_cycle_id: Optional[int] = None


class BaseStrategy(ABC):
    name: str
    title: str
    description: str

    @abstractmethod
    def check(self, portfolio: dict, market_data: dict, settings: dict, triggers: list) -> StrategySignal:
        pass

    @abstractmethod
    def get_default_triggers(self) -> list[dict]:
        pass

    @abstractmethod
    def get_parameters_text(self) -> str:
        pass
