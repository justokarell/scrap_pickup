
from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Any

import httpx

from .models import CollectionLocation, ProcessingSite, Scenario
from .state import Failure, SystemState

OSRM_BASE_URL = os.getenv(
    "OSRM_BASE_URL",
    "https://router.project-osrm.org",
).rstrip("/")

NOMINATIM_BASE_URL = os.getenv(
    "NOMINATIM_BASE_URL",
    "https://nominatim.openstreetmap.org",
).rstrip("/")

ROUTING_USER_AGENT = os.getenv(
    "ROUTING_USER_AGENT",
    "stamford-food-scraps-simulator/0.1",
)

_MILES_PER_METER = 1.0 / 1609.344


def _has_coordinates(obj: Any) -> bool:
    return obj.latitude is not None and obj.longitude is not None


@lru_cache(maxsize=128)
def _geocode(address: str) -> tuple[float, float]:
    if not address.strip():
        raise ValueError("Cannot geocode an empty address.")

    headers = {"User-Agent": ROUTING_USER_AGENT}
    params = {
        "q": address,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "us",
    }

    with httpx.Client(timeout=20.0, headers=headers) as client:
        response = client.get(
            f"{NOMINATIM_BASE_URL}/search",
            params=params,
        )
        response.raise_for_status()
        items = response.json()

    if not items:
        raise RuntimeError(f"Geocoding failed for address: {address}")

    # Public Nominatim asks clients to avoid burst traffic.
    time.sleep(1.05)

    return float(items[0]["lat"]), float(items[0]["lon"])


def _coordinates(obj: Any) -> tuple[float, float]:
    if _has_coordinates(obj):
        return float(obj.latitude), float(obj.longitude)
    return _geocode(obj.address)


def _point(
    obj: CollectionLocation | ProcessingSite,
    point_type: str,
) -> dict[str, Any]:
    lat, lon = _coordinates(obj)
    return {
        "id": obj.id,
        "name": obj.name,
        "type": point_type,
        "address": obj.address,
        "latitude": lat,
        "longitude": lon,
    }


def _osrm_trip(points: list[dict[str, Any]]) -> dict[str, Any]:
    if len(points) < 2:
        raise ValueError("A road route requires at least two points.")

    coordinates = ";".join(
        f'{p["longitude"]},{p["latitude"]}' for p in points
    )

    url = f"{OSRM_BASE_URL}/trip/v1/driving/{coordinates}"
    params = {
        "roundtrip": "false",
        "source": "first",
        "destination": "last",
        "geometries": "geojson",
        "overview": "full",
        "steps": "false",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    if data.get("code") != "Ok" or not data.get("trips"):
        raise RuntimeError(
            f'OSRM trip routing failed: {data.get("code", "unknown")}'
        )

    trip = data["trips"][0]
    waypoint_metadata = data.get("waypoints", [])

    if len(waypoint_metadata) != len(points):
        raise RuntimeError("OSRM returned an unexpected waypoint count.")

    ordered_pairs = sorted(
        enumerate(waypoint_metadata),
        key=lambda pair: pair[1]["waypoint_index"],
    )
    ordered_points = [points[input_index] for input_index, _ in ordered_pairs]

    return {
        "distance_miles": float(trip["distance"]) * _MILES_PER_METER,
        "drive_minutes": float(trip["duration"]) / 60.0,
        "geometry": trip["geometry"],
        "stops": ordered_points,
    }


def _osrm_route(
    origin: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, Any]:
    coordinates = (
        f'{origin["longitude"]},{origin["latitude"]};'
        f'{destination["longitude"]},{destination["latitude"]}'
    )

    url = f"{OSRM_BASE_URL}/route/v1/driving/{coordinates}"
    params = {
        "geometries": "geojson",
        "overview": "full",
        "steps": "false",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(
            f'OSRM route lookup failed: {data.get("code", "unknown")}'
        )

    route = data["routes"][0]
    return {
        "distance_miles": float(route["distance"]) * _MILES_PER_METER,
        "drive_minutes": float(route["duration"]) / 60.0,
        "geometry": route["geometry"],
    }


def _split_by_payload(
    requested: list[str],
    scenario: Scenario,
    state: SystemState,
) -> list[list[str]]:
    locs = {loc.id: loc for loc in scenario.locations}
    truck = scenario.trucks[0]

    batches: list[list[str]] = []
    current: list[str] = []
    current_weight = 0.0

    for location_id in requested:
        loc = locs[location_id]
        quantity = state.bins[location_id].inventory_lbs

        if quantity <= 1e-12:
            continue

        if quantity > truck.max_weight_lbs + 1e-9:
            state.failures.append(
                Failure(
                    timestamp_hours=0.0,
                    type="truck_weight_capacity",
                    message=(
                        f"{loc.name} contains {quantity:.2f} lbs, "
                        f"exceeding truck capacity "
                        f"{truck.max_weight_lbs:.2f} lbs."
                    ),
                    location_id=location_id,
                    truck_id=truck.id,
                )
            )
            continue

        if (
            current
            and current_weight + quantity
            > truck.max_weight_lbs + 1e-9
        ):
            batches.append(current)
            current = []
            current_weight = 0.0

        current.append(location_id)
        current_weight += quantity

    if current:
        batches.append(current)

    return batches


def _best_processing_trip(
    origin: dict[str, Any],
    batch: list[str],
    scenario: Scenario,
    state: SystemState,
) -> tuple[ProcessingSite, dict[str, Any]]:
    locs = {loc.id: loc for loc in scenario.locations}
    batch_weight = sum(state.bins[lid].inventory_lbs for lid in batch)

    candidates: list[tuple[ProcessingSite, dict[str, Any]]] = []

    for site in scenario.processing_sites:
        site_state = state.sites[site.id]
        available = site.storage_capacity_lbs - site_state.inventory_lbs

        if batch_weight > available + 1e-9:
            continue

        destination = _point(site, "processing_site")
        pickup_points = [
            _point(locs[lid], "collection") for lid in batch
        ]
        trip = _osrm_trip([origin, *pickup_points, destination])
        candidates.append((site, trip))

    if not candidates:
        raise RuntimeError(
            "No processing site has enough available storage for "
            f"{batch_weight:.2f} lbs."
        )

    return min(candidates, key=lambda item: item[1]["distance_miles"])


def execute_greedy_route(
    scenario: Scenario,
    state: SystemState,
    requested: list[str],
    timestamp_hours: float,
) -> None:
    if not requested:
        return

    truck = scenario.trucks[0]
    truck_state = state.trucks[truck.id]
    locs = {loc.id: loc for loc in scenario.locations}

    batches = _split_by_payload(requested, scenario, state)
    if not batches:
        return

    # The current model has no separate depot object. Until one is added,
    # the first processing site is the explicit route origin/return point.
    origin_site = scenario.processing_sites[0]
    origin = _point(origin_site, "route_origin")

    route_segments: list[dict[str, Any]] = []
    ordered_stops: list[dict[str, Any]] = [origin]
    total_miles = 0.0
    total_drive_minutes = 0.0
    total_service_minutes = 0.0
    collected_on_route = 0.0
    processing_site_ids: list[str] = []

    for batch in batches:
        try:
            site, trip = _best_processing_trip(
                origin,
                batch,
                scenario,
                state,
            )
        except Exception as exc:
            state.failures.append(
                Failure(
                    timestamp_hours=timestamp_hours,
                    type="routing_failure",
                    message=str(exc),
                    truck_id=truck.id,
                )
            )
            return

        site_state = state.sites[site.id]

        # OSRM returns the optimized order, including origin and destination.
        visit_stops = [
            stop
            for stop in trip["stops"]
            if stop["type"] == "collection"
        ]

        batch_collected = 0.0

        for stop in visit_stops:
            location_id = stop["id"]
            loc = locs[location_id]
            bin_state = state.bins[location_id]
            quantity = bin_state.inventory_lbs

            if quantity <= 1e-12:
                continue

            if (
                truck_state.load_lbs + quantity
                > truck.max_weight_lbs + 1e-9
            ):
                state.failures.append(
                    Failure(
                        timestamp_hours=timestamp_hours,
                        type="truck_weight_capacity",
                        message=(
                            f"Route would exceed truck capacity at "
                            f"{loc.name}."
                        ),
                        location_id=location_id,
                        truck_id=truck.id,
                    )
                )
                return

            bin_state.inventory_lbs = 0.0
            bin_state.collected_lbs += quantity
            bin_state.pickups += 1
            state.total_collected_lbs += quantity

            truck_state.load_lbs += quantity
            truck_state.max_load_lbs = max(
                truck_state.max_load_lbs,
                truck_state.load_lbs,
            )

            batch_collected += quantity
            collected_on_route += quantity
            total_service_minutes += loc.service_minutes

        if batch_collected <= 1e-12:
            continue

        available = site.storage_capacity_lbs - site_state.inventory_lbs
        if batch_collected > available + 1e-9:
            raise RuntimeError(
                "Processing capacity changed between route planning "
                "and unload."
            )

        # Atomic unload.
        site_state.inventory_lbs += truck_state.load_lbs
        site_state.received_lbs += truck_state.load_lbs
        site_state.max_inventory_lbs = max(
            site_state.max_inventory_lbs,
            site_state.inventory_lbs,
        )
        truck_state.load_lbs = 0.0

        total_service_minutes += site.unload_minutes
        total_miles += trip["distance_miles"]
        total_drive_minutes += trip["drive_minutes"]

        route_segments.append(
            {
                "type": "collection_to_processing",
                "distance_miles": trip["distance_miles"],
                "drive_minutes": trip["drive_minutes"],
                "geometry": trip["geometry"],
                "stops": trip["stops"],
            }
        )

        # Avoid duplicating the segment origin in the flattened stop list.
        ordered_stops.extend(trip["stops"][1:])
        processing_site_ids.append(site.id)
        origin = _point(site, "processing_site")

    if collected_on_route <= 1e-12:
        return

    # Return to the route origin after the last unload.
    if origin["id"] != origin_site.id:
        destination = _point(origin_site, "route_origin")
        try:
            return_leg = _osrm_route(origin, destination)
        except Exception as exc:
            state.failures.append(
                Failure(
                    timestamp_hours=timestamp_hours,
                    type="routing_failure",
                    message=f"Return-leg routing failed: {exc}",
                    truck_id=truck.id,
                )
            )
            return

        total_miles += return_leg["distance_miles"]
        total_drive_minutes += return_leg["drive_minutes"]
        route_segments.append(
            {
                "type": "return",
                "distance_miles": return_leg["distance_miles"],
                "drive_minutes": return_leg["drive_minutes"],
                "geometry": return_leg["geometry"],
                "stops": [origin, destination],
            }
        )
        ordered_stops.append(destination)

    labor_hours = (
        total_drive_minutes + total_service_minutes
    ) / 60.0

    truck_state.miles += total_miles
    truck_state.labor_hours += labor_hours
    truck_state.routes += 1

    state.operating_cost += (
        total_miles * truck.cost_per_mile
        + labor_hours * truck.cost_per_hour
    )

    geometries = [
        segment["geometry"]["coordinates"]
        for segment in route_segments
        if segment.get("geometry", {}).get("type") == "LineString"
    ]

    state.routes.append(
        {
            "route_id": f"route_{len(state.routes) + 1}",
            "timestamp_hours": timestamp_hours,
            "truck_id": truck.id,
            "origin_assumption": (
                "first configured processing site is used as "
                "route origin and return point"
            ),
            "processing_site_ids": processing_site_ids,
            "distance_miles": total_miles,
            "drive_minutes": total_drive_minutes,
            "labor_hours": labor_hours,
            "collected_lbs": collected_on_route,
            "stops": ordered_stops,
            "geometry": {
                "type": "MultiLineString",
                "coordinates": geometries,
            },
            "segments": route_segments,
        }
    )
