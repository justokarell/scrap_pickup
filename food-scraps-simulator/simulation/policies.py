from datetime import datetime, timedelta
from .models import Scenario
from .state import SystemState

def requested_locations(scenario: Scenario, state: SystemState, elapsed_hours: float) -> list[str]:
    now = datetime.fromisoformat(scenario.simulation.start_date) + timedelta(hours=elapsed_hours)
    weekday = now.weekday()
    out = []
    for loc in scenario.locations:
        scheduled = weekday in (loc.scheduled_weekdays or scenario.policy.weekdays)
        b = state.bins[loc.id]
        threshold_hit = loc.capacity_lbs > 0 and b.inventory_lbs / loc.capacity_lbs >= loc.threshold
        if scenario.policy.type == "fixed" and scheduled: out.append(loc.id)
        elif scenario.policy.type == "threshold" and threshold_hit: out.append(loc.id)
        elif scenario.policy.type == "hybrid" and (scheduled or threshold_hit): out.append(loc.id)
    return out
