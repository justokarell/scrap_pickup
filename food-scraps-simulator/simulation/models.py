from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

PolicyType = Literal["fixed", "threshold", "hybrid"]
LoadingMethod = Literal["bulk_dump", "swapped_containers", "bags_totes", "custom"]


@dataclass(frozen=True)
class GeoPoint:
    id: str
    name: str
    address: str
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class CollectionLocation:
    id: str
    name: str
    capacity_lbs: float
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
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
    address: str = ""
    latitude: float | None = None
    longitude: float | None = None
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
    depot: GeoPoint
    locations: tuple[CollectionLocation, ...]
    trucks: tuple[Truck, ...]
    processing_sites: tuple[ProcessingSite, ...]
    policy: PolicyConfig

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scenario":
        sim = data.get("simulation", {})
        settings = SimulationSettings(
            start_date=sim.get("start_date", "2026-09-07"),
            duration_days=int(sim.get("duration_days", 7)),
            state_step_hours=float(sim.get("state_step_hours", 1.0)),
            decision_epoch_hour=int(sim.get("decision_epoch_hour", 8)),
        )

        depot_data = data.get("depot")
        if not depot_data:
            raise ValueError(
                "Scenario requires an explicit 'depot' object with at least "
                "id, name, and address. The simulator does not infer a depot "
                "from processing sites."
            )

        depot = GeoPoint(
            id=str(depot_data["id"]),
            name=str(depot_data.get("name", depot_data["id"])),
            address=str(depot_data.get("address", "")),
            latitude=cls._optional_float(depot_data.get("latitude")),
            longitude=cls._optional_float(depot_data.get("longitude")),
        )

        if not depot.address and (
            depot.latitude is None or depot.longitude is None
        ):
            raise ValueError(
                "Depot requires either an address or both latitude and longitude."
            )

        locations = tuple(
            CollectionLocation(
                id=str(x["id"]),
                name=str(x.get("name", x["id"])),
                capacity_lbs=float(x.get("capacity_lbs", 180)),
                address=str(x.get("address", "")),
                latitude=cls._optional_float(x.get("latitude")),
                longitude=cls._optional_float(x.get("longitude")),
                initial_lbs=float(x.get("initial_lbs", 0)),
                demand_lbs_per_day=float(x.get("demand_lbs_per_day", 12)),
                service_minutes=float(x.get("service_minutes", 5)),
                scheduled_weekdays=tuple(
                    int(v) for v in x.get("scheduled_weekdays", [])
                ),
                threshold=float(x.get("threshold", 0.8)),
            )
            for x in data.get("locations", [])
        )

        trucks = tuple(
            Truck(
                id=str(x["id"]),
                name=str(x.get("name", x["id"])),
                max_weight_lbs=float(x.get("max_weight_lbs", 800)),
                cost_per_mile=float(x.get("cost_per_mile", 0.70)),
                cost_per_hour=float(x.get("cost_per_hour", 35)),
                loading_method=x.get("loading_method", "bulk_dump"),
            )
            for x in data.get("trucks", [])
        )

        sites = tuple(
            ProcessingSite(
                id=str(x["id"]),
                name=str(x.get("name", x["id"])),
                storage_capacity_lbs=float(
                    x.get("storage_capacity_lbs", 5000)
                ),
                processing_lbs_per_day=float(
                    x.get("processing_lbs_per_day", 500)
                ),
                address=str(x.get("address", "")),
                latitude=cls._optional_float(x.get("latitude")),
                longitude=cls._optional_float(x.get("longitude")),
                unload_minutes=float(x.get("unload_minutes", 12)),
            )
            for x in data.get("processing_sites", [])
        )

        p = data.get("policy", {})
        policy = PolicyConfig(
            type=p.get("type", "fixed"),
            weekdays=tuple(int(v) for v in p.get("weekdays", [0, 3])),
            threshold=float(p.get("threshold", 0.8)),
        )

        if not locations:
            raise ValueError("Scenario requires at least one collection location.")
        if not trucks:
            raise ValueError("Scenario requires at least one truck.")
        if not sites:
            raise ValueError("Scenario requires at least one processing site.")

        for loc in locations:
            if loc.capacity_lbs <= 0:
                raise ValueError(
                    f"Collection location {loc.id} has nonpositive capacity."
                )
            if not loc.address and (
                loc.latitude is None or loc.longitude is None
            ):
                raise ValueError(
                    f"Collection location {loc.id} requires an address or coordinates."
                )

        for site in sites:
            if site.storage_capacity_lbs <= 0:
                raise ValueError(
                    f"Processing site {site.id} has nonpositive storage capacity."
                )
            if not site.address and (
                site.latitude is None or site.longitude is None
            ):
                raise ValueError(
                    f"Processing site {site.id} requires an address or coordinates."
                )

        for truck in trucks:
            if truck.max_weight_lbs <= 0:
                raise ValueError(
                    f"Truck {truck.id} has nonpositive payload capacity."
                )

        return cls(
            schema_version=int(data.get("schema_version", 1)),
            name=str(data.get("name", "Untitled scenario")),
            simulation=settings,
            depot=depot,
            locations=locations,
            trucks=trucks,
            processing_sites=sites,
            policy=policy,
        )
