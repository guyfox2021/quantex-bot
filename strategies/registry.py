from strategies.accumulation import AccumulationStrategy
from strategies.accumulation_v2 import AccumulationV2Strategy

STRATEGIES = {
    "accumulation": AccumulationStrategy(),
    "accumulation_v2": AccumulationV2Strategy(),
}


def get_strategy(name: str):
    return STRATEGIES.get(name, STRATEGIES["accumulation"])


def list_strategies():
    return list(STRATEGIES.values())
