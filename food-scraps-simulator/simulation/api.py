from .models import Scenario
from .engine import SimulationEngine

def simulate(scenario: Scenario, seed: int=42, stochastic: bool=False) -> dict:
    return SimulationEngine(scenario, seed, stochastic).run()
