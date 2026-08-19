from dataclasses import dataclass, field
from typing import Any

@dataclass
class BinState:
    inventory_lbs: float = 0.0
    arrivals_lbs: float = 0.0
    collected_lbs: float = 0.0
    overflow_lbs: float = 0.0
    overflow_events: int = 0
    pickups: int = 0
    max_inventory_lbs: float = 0.0
    inventory_sum: float = 0.0
    samples: int = 0

@dataclass
class TruckState:
    load_lbs: float = 0.0
    miles: float = 0.0
    labor_hours: float = 0.0
    routes: int = 0
    max_load_lbs: float = 0.0

@dataclass
class SiteState:
    inventory_lbs: float = 0.0
    received_lbs: float = 0.0
    processed_lbs: float = 0.0
    max_inventory_lbs: float = 0.0

@dataclass
class Failure:
    timestamp_hours: float
    type: str
    message: str
    location_id: str | None = None
    truck_id: str | None = None
    processing_site_id: str | None = None

@dataclass
class SystemState:
    bins: dict[str, BinState]
    trucks: dict[str, TruckState]
    sites: dict[str, SiteState]
    failures: list[Failure] = field(default_factory=list)
    total_source_lbs: float = 0.0
    total_collected_lbs: float = 0.0
    total_overflow_lbs: float = 0.0
    total_processed_lbs: float = 0.0
    operating_cost: float = 0.0
    time_series: list[dict[str, Any]] = field(default_factory=list)

    def mass_balance_residual(self) -> float:
        accounted = (sum(x.inventory_lbs for x in self.bins.values())
            + sum(x.load_lbs for x in self.trucks.values())
            + sum(x.inventory_lbs for x in self.sites.values())
            + self.total_processed_lbs + self.total_overflow_lbs)
        return self.total_source_lbs - accounted
