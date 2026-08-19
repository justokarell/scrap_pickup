from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal

PolicyType = Literal["fixed", "threshold", "hybrid"]
LoadingMethod = Literal["bulk_dump", "swapped_containers", "bags_totes", "custom"]

@dataclass(frozen=True)
class CollectionLocation:
    id: str
    name: str
    capacity_lbs: float
    initial_lbs: float = 0.0
    demand_lbs_per_day: float = 0.0
    service_minutes: float = 5.0
    scheduled_weekdays: tuple[int, ...] = ()
    threshold: float = 0.8

@dataclass(frozen=True)
class Truck:
    id: str
    name: str
    max_weight_lbs: float
    cost_per_mile: float = 0.70
    cost_per_hour: float = 35.0
    loading_method: LoadingMethod = "bulk_dump"

@dataclass(frozen=True)
class ProcessingSite:
    id: str
    name: str
    storage_capacity_lbs: float
    processing_lbs_per_day: float
    unload_minutes: float = 12.0

@dataclass(frozen=True)
class PolicyConfig:
    type: PolicyType = "fixed"
    weekdays: tuple[int, ...] = (0, 3)
    threshold: float = 0.8

@dataclass(frozen=True)
class SimulationSettings:
    start_date: str = "2026-09-07"
    duration_days: int = 7
    state_step_hours: float = 1.0
    decision_epoch_hour: int = 8

@dataclass(frozen=True)
class Scenario:
    schema_version: int
    name: str
    simulation: SimulationSettings
    locations: tuple[CollectionLocation, ...]
    trucks: tuple[Truck, ...]
    processing_sites: tuple[ProcessingSite, ...]
    policy: PolicyConfig
    route_base_miles: float = 4.0
    route_miles_per_stop: float = 1.5
    route_miles_per_unload: float = 2.0
    average_speed_mph: float = 20.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scenario":
        sim = data.get("simulation", {})
        settings = SimulationSettings(
            start_date=sim.get("start_date", "2026-09-07"),
            duration_days=int(sim.get("duration_days", 7)),
            state_step_hours=float(sim.get("state_step_hours", 1.0)),
            decision_epoch_hour=int(sim.get("decision_epoch_hour", 8)),
        )
        locations = tuple(CollectionLocation(
            id=str(x["id"]), name=str(x.get("name", x["id"])),
            capacity_lbs=float(x.get("capacity_lbs", 180)),
            initial_lbs=float(x.get("initial_lbs", 0)),
            demand_lbs_per_day=float(x.get("demand_lbs_per_day", 12)),
            service_minutes=float(x.get("service_minutes", 5)),
            scheduled_weekdays=tuple(int(v) for v in x.get("scheduled_weekdays", [])),
            threshold=float(x.get("threshold", 0.8)),
        ) for x in data.get("locations", []))
        trucks = tuple(Truck(
            id=str(x["id"]), name=str(x.get("name", x["id"])),
            max_weight_lbs=float(x.get("max_weight_lbs", 800)),
            cost_per_mile=float(x.get("cost_per_mile", 0.70)),
            cost_per_hour=float(x.get("cost_per_hour", 35)),
            loading_method=x.get("loading_method", "bulk_dump"),
        ) for x in data.get("trucks", []))
        sites = tuple(ProcessingSite(
            id=str(x["id"]), name=str(x.get("name", x["id"])),
            storage_capacity_lbs=float(x.get("storage_capacity_lbs", 5000)),
            processing_lbs_per_day=float(x.get("processing_lbs_per_day", 500)),
            unload_minutes=float(x.get("unload_minutes", 12)),
        ) for x in data.get("processing_sites", []))
        p = data.get("policy", {})
        policy = PolicyConfig(
            type=p.get("type", "fixed"),
            weekdays=tuple(int(v) for v in p.get("weekdays", [0, 3])),
            threshold=float(p.get("threshold", 0.8)),
        )
        if not locations: raise ValueError("Scenario requires at least one collection location.")
        if not trucks: raise ValueError("Scenario requires at least one truck.")
        if not sites: raise ValueError("Scenario requires at least one processing site.")
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            name=str(data.get("name", "Untitled scenario")), simulation=settings,
            locations=locations, trucks=trucks, processing_sites=sites, policy=policy,
            route_base_miles=float(data.get("route_base_miles", 4.0)),
            route_miles_per_stop=float(data.get("route_miles_per_stop", 1.5)),
            route_miles_per_unload=float(data.get("route_miles_per_unload", 2.0)),
            average_speed_mph=float(data.get("average_speed_mph", 20.0)),
        )
