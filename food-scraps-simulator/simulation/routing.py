from .models import Scenario
from .state import SystemState, Failure

def execute_greedy_route(scenario: Scenario, state: SystemState, requested: list[str], timestamp_hours: float) -> None:
    if not requested: return
    truck = scenario.trucks[0]; ts = state.trucks[truck.id]
    site = scenario.processing_sites[0]; ss = state.sites[site.id]
    locs = {x.id:x for x in scenario.locations}
    served = 0; unloads = 0; service_minutes = 0.0

    def unload() -> bool:
        nonlocal unloads, service_minutes
        if ts.load_lbs <= 1e-12: return True
        if ts.load_lbs > site.storage_capacity_lbs - ss.inventory_lbs + 1e-9:
            state.failures.append(Failure(timestamp_hours,"processing_site_full",f"{site.name} cannot accept {ts.load_lbs:.2f} lbs",truck_id=truck.id,processing_site_id=site.id))
            return False
        q = ts.load_lbs; ts.load_lbs = 0.0
        ss.inventory_lbs += q; ss.received_lbs += q; ss.max_inventory_lbs=max(ss.max_inventory_lbs,ss.inventory_lbs)
        unloads += 1; service_minutes += site.unload_minutes
        return True

    for lid in requested:
        loc=locs[lid]; b=state.bins[lid]; q=b.inventory_lbs
        if q <= 1e-12: continue
        if q > truck.max_weight_lbs + 1e-9:
            state.failures.append(Failure(timestamp_hours,"truck_weight_capacity",f"{loc.name} exceeds truck capacity",location_id=lid,truck_id=truck.id)); continue
        if ts.load_lbs + q > truck.max_weight_lbs + 1e-9 and not unload(): break
        b.inventory_lbs=0.0; b.collected_lbs+=q; b.pickups+=1; state.total_collected_lbs+=q
        ts.load_lbs+=q; ts.max_load_lbs=max(ts.max_load_lbs,ts.load_lbs)
        service_minutes += loc.service_minutes; served += 1
    if ts.load_lbs > 1e-12: unload()
    if served:
        miles=scenario.route_base_miles+scenario.route_miles_per_stop*served+scenario.route_miles_per_unload*unloads
        labor=miles/max(scenario.average_speed_mph,1e-9)+service_minutes/60.0
        ts.miles+=miles; ts.labor_hours+=labor; ts.routes+=1
        state.operating_cost += miles*truck.cost_per_mile + labor*truck.cost_per_hour
