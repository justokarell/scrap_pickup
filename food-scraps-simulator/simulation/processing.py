from .models import Scenario
from .state import SystemState

def advance_processing(scenario: Scenario, state: SystemState, dt_hours: float) -> None:
    for site in scenario.processing_sites:
        ss = state.sites[site.id]
        qty = min(ss.inventory_lbs, max(0.0, site.processing_lbs_per_day * dt_hours / 24.0))
        ss.inventory_lbs -= qty
        ss.processed_lbs += qty
        state.total_processed_lbs += qty
