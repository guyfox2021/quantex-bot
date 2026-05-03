from strategies.accumulation import AccumulationStrategy

STRATEGIES = {
    "accumulation": AccumulationStrategy(),
}


def get_strategy(name: str):
    return STRATEGIES.get(name, STRATEGIES["accumulation"])


def list_strategies():
    return list(STRATEGIES.values())
