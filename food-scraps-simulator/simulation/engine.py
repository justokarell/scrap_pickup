Library
/
engine.py


from datetime import datetime, timedelta

from .demand import arrivals
from .models import Scenario
from .policies import requested_locations
from .processing import advance_processing
from .routing import execute_greedy_route
from .state import BinState, SiteState, SystemState, TruckState


class SimulationEngine:
    def __init__(
        self,
        scenario: Scenario,
        seed: int = 42,
        stochastic: bool = False,
    ):
        self.scenario = scenario
        self.seed = seed
        self.stochastic = stochastic
        self.state = SystemState(
            bins={
                x.id: BinState(inventory_lbs=x.initial_lbs)
                for x in scenario.locations
            },
            trucks={
                x.id: TruckState()
                for x in scenario.trucks
            },
            sites={
                x.id: SiteState()
                for x in scenario.processing_sites
            },
        )
        self.state.total_source_lbs = sum(
            x.initial_lbs for x in scenario.locations
        )

    def _assert_mass_balance(self):
        residual = self.state.mass_balance_residual()
        if abs(residual) > 1e-6:
            raise RuntimeError(
                f"Mass balance failed; residual={residual}"
            )

    def run(self):
        cfg = self.scenario.simulation
        dt = cfg.state_step_hours
        steps = int(round(cfg.duration_days * 24 / dt))
        start = datetime.fromisoformat(cfg.start_date)

        for step in range(steps):
            t1 = (step + 1) * dt

            for loc in self.scenario.locations:
                quantity = arrivals(
                    loc,
                    dt,
                    self.seed,
                    step,
                    self.stochastic,
                )
                bin_state = self.state.bins[loc.id]

                bin_state.arrivals_lbs += quantity
                self.state.total_source_lbs += quantity

                raw = bin_state.inventory_lbs + quantity
                overflow = max(
                    0.0,
                    raw - loc.capacity_lbs,
                )

                if overflow > 1e-12:
                    bin_state.overflow_lbs += overflow
                    bin_state.overflow_events += 1
                    self.state.total_overflow_lbs += overflow

                bin_state.inventory_lbs = min(
                    loc.capacity_lbs,
                    raw,
                )
                bin_state.max_inventory_lbs = max(
                    bin_state.max_inventory_lbs,
                    bin_state.inventory_lbs,
                )
                bin_state.inventory_sum += (
                    bin_state.inventory_lbs
                )
                bin_state.samples += 1

            advance_processing(
                self.scenario,
                self.state,
                dt,
            )

            now = start + timedelta(hours=t1)

            if (
                now.hour == cfg.decision_epoch_hour
                and now.minute == 0
            ):
                execute_greedy_route(
                    self.scenario,
                    self.state,
                    requested_locations(
                        self.scenario,
                        self.state,
                        t1,
                    ),
                    t1,
                )

            self._assert_mass_balance()

            if abs(t1 % 24.0) < 1e-9:
                self.state.time_series.append(
                    {
                        "hour": t1,
                        "bins": {
                            key: value.inventory_lbs
                            for key, value
                            in self.state.bins.items()
                        },
                        "processing": {
                            key: value.inventory_lbs
                            for key, value
                            in self.state.sites.items()
                        },
                    }
                )

        return self._result()

    def _result(self):
        miles = sum(
            x.miles for x in self.state.trucks.values()
        )
        labor = sum(
            x.labor_hours for x in self.state.trucks.values()
        )
        routes = sum(
            x.routes for x in self.state.trucks.values()
        )
        tons = self.state.total_collected_lbs / 2000.0

        summary = {
            "total_arrivals_lbs": self.state.total_source_lbs,
            "total_collected_lbs": (
                self.state.total_collected_lbs
            ),
            "total_overflow_lbs": (
                self.state.total_overflow_lbs
            ),
            "overflow_events": sum(
                x.overflow_events
                for x in self.state.bins.values()
            ),
            "capture_rate": (
                self.state.total_collected_lbs
                / self.state.total_source_lbs
                if self.state.total_source_lbs > 0
                else 1.0
            ),
            "routes_executed": routes,
            "miles_driven": miles,
            "labor_hours": labor,
            "operating_cost": self.state.operating_cost,
            "cost_per_ton": (
                self.state.operating_cost / tons
                if tons > 0
                else None
            ),
            "remaining_bin_inventory_lbs": sum(
                x.inventory_lbs
                for x in self.state.bins.values()
            ),
            "processing_backlog_lbs": sum(
                x.inventory_lbs
                for x in self.state.sites.values()
            ),
            "processed_lbs": self.state.total_processed_lbs,
        }

        loc_lookup = {
            x.id: x for x in self.scenario.locations
        }

        locations = [
            {
                "id": location_id,
                "name": loc_lookup[location_id].name,
                "address": loc_lookup[location_id].address,
                "latitude": loc_lookup[location_id].latitude,
                "longitude": loc_lookup[location_id].longitude,
                "arrivals_lbs": (
                    bin_state.arrivals_lbs
                    + loc_lookup[location_id].initial_lbs
                ),
                "collected_lbs": bin_state.collected_lbs,
                "overflow_lbs": bin_state.overflow_lbs,
                "overflow_events": bin_state.overflow_events,
                "pickups": bin_state.pickups,
                "average_inventory_lbs": (
                    bin_state.inventory_sum
                    / bin_state.samples
                    if bin_state.samples
                    else bin_state.inventory_lbs
                ),
                "peak_inventory_lbs": (
                    bin_state.max_inventory_lbs
                ),
                "service_level": 1.0 - (
                    bin_state.overflow_events
                    / bin_state.samples
                    if bin_state.samples
                    else 0.0
                ),
            }
            for location_id, bin_state
            in self.state.bins.items()
        ]

        trucks = [
            {
                "id": truck_id,
                "routes": truck_state.routes,
                "miles": truck_state.miles,
                "labor_hours": truck_state.labor_hours,
                "peak_load_lbs": truck_state.max_load_lbs,
                "final_load_lbs": truck_state.load_lbs,
            }
            for truck_id, truck_state
            in self.state.trucks.items()
        ]

        site_lookup = {
            x.id: x for x in self.scenario.processing_sites
        }

        sites = [
            {
                "id": site_id,
                "name": site_lookup[site_id].name,
                "address": site_lookup[site_id].address,
                "latitude": site_lookup[site_id].latitude,
                "longitude": site_lookup[site_id].longitude,
                "received_lbs": site_state.received_lbs,
                "processed_lbs": site_state.processed_lbs,
                "backlog_lbs": site_state.inventory_lbs,
                "peak_backlog_lbs": (
                    site_state.max_inventory_lbs
                ),
            }
            for site_id, site_state
            in self.state.sites.items()
        ]

        return {
            "status": "complete",
            "valid": True,
            "validation": {
                "mass_balance_passed": True,
                "mass_balance_residual_lbs": (
                    self.state.mass_balance_residual()
                ),
            },
            "summary": summary,
            "locations": locations,
            "trucks": trucks,
            "processing_sites": sites,
            "failures": [
                failure.__dict__
                for failure in self.state.failures
            ],
            "time_series": self.state.time_series,
            "routes": self.state.routes,
        }
