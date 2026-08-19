from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import httpx

from .models import CollectionLocation, ProcessingSite, Scenario
from .state import Failure, SystemState


OSRM_BASE_URL = os.getenv(
    "OSRM_BASE_URL",
    "https://router.project-osrm.org",
).rstrip("/")

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN")

MAPBOX_GEOCODING_URL = (
    "https://api.mapbox.com/search/geocode/v6/forward"
)

MILES_PER_METER = 1.0 / 1609.344


@lru_cache(maxsize=512)
def _geocode(address: str) -> tuple[float, float]:
    """
    Convert an arbitrary address to latitude/longitude.

    Results are cached for the lifetime of the application process so
    repeated simulations do not repeatedly geocode the same address.
    """

    address = address.strip()

    if not address:
        raise ValueError("Cannot geocode an empty address.")

    if not MAPBOX_TOKEN:
        raise RuntimeError(
            "MAPBOX_TOKEN environment variable is not configured."
        )

    params = {
        "q": address,
        "access_token": MAPBOX_TOKEN,
        "limit": 1,
        "country": "US",
        "autocomplete": "false",
    }

    with httpx.Client(timeout=20.0) as client:
        response = client.get(
            MAPBOX_GEOCODING_URL,
            params=params,
        )

        response.raise_for_status()
        data = response.json()

    features = data.get("features", [])

    if not features:
        raise RuntimeError(
            f"Could not geocode address: {address}"
        )

    coordinates = features[0].get("geometry", {}).get(
        "coordinates"
    )

    if not coordinates or len(coordinates) < 2:
        raise RuntimeError(
            f"Geocoder returned no coordinates for: {address}"
        )

    longitude = float(coordinates[0])
    latitude = float(coordinates[1])

    return latitude, longitude


def _coordinates(obj: Any) -> tuple[float, float]:
    """
    Use supplied coordinates when present; otherwise dynamically
    geocode the object's address.
    """

    if (
        getattr(obj, "latitude", None) is not None
        and getattr(obj, "longitude", None) is not None
    ):
        return (
            float(obj.latitude),
            float(obj.longitude),
        )

    return _geocode(obj.address)


def _point(
    obj: CollectionLocation | ProcessingSite,
    point_type: str,
) -> dict[str, Any]:

    latitude, longitude = _coordinates(obj)

    return {
        "id": obj.id,
        "name": obj.name,
        "type": point_type,
        "address": obj.address,
        "latitude": latitude,
        "longitude": longitude,
    }


def _osrm_trip(
    origin: dict[str, Any],
    collection_points: list[dict[str, Any]],
    destination: dict[str, Any],
) -> dict[str, Any]:
    """
    Optimize the ordering of collection stops between a fixed origin
    and fixed processing destination.
    """

    points = [
        origin,
        *collection_points,
        destination,
    ]

    coordinates = ";".join(
        f'{point["longitude"]},{point["latitude"]}'
        for point in points
    )

    url = (
        f"{OSRM_BASE_URL}/trip/v1/driving/"
        f"{coordinates}"
    )

    params = {
        "roundtrip": "false",
        "source": "first",
        "destination": "last",
        "geometries": "geojson",
        "overview": "full",
        "steps": "false",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            url,
            params=params,
        )

        response.raise_for_status()
        data = response.json()

    if (
        data.get("code") != "Ok"
        or not data.get("trips")
    ):
        raise RuntimeError(
            "OSRM trip routing failed: "
            f'{data.get("code", "unknown")}'
        )

    trip = data["trips"][0]
    waypoints = data.get("waypoints", [])

    if len(waypoints) != len(points):
        raise RuntimeError(
            "OSRM returned an unexpected waypoint count."
        )

    ordered_pairs = sorted(
        enumerate(waypoints),
        key=lambda item: item[1]["waypoint_index"],
    )

    ordered_points = [
        points[input_index]
        for input_index, _ in ordered_pairs
    ]

    return {
        "distance_miles": (
            float(trip["distance"])
            * MILES_PER_METER
        ),
        "drive_minutes": (
            float(trip["duration"])
            / 60.0
        ),
        "geometry": trip["geometry"],
        "stops": ordered_points,
    }


def _osrm_route(
    origin: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute an ordinary road route between two points.
    """

    coordinates = (
        f'{origin["longitude"]},{origin["latitude"]};'
        f'{destination["longitude"]},{destination["latitude"]}'
    )

    url = (
        f"{OSRM_BASE_URL}/route/v1/driving/"
        f"{coordinates}"
    )

    params = {
        "geometries": "geojson",
        "overview": "full",
        "steps": "false",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            url,
            params=params,
        )

        response.raise_for_status()
        data = response.json()

    if (
        data.get("code") != "Ok"
        or not data.get("routes")
    ):
        raise RuntimeError(
            "OSRM route lookup failed: "
            f'{data.get("code", "unknown")}'
        )

    route = data["routes"][0]

    return {
        "distance_miles": (
            float(route["distance"])
            * MILES_PER_METER
        ),
        "drive_minutes": (
            float(route["duration"])
            / 60.0
        ),
        "geometry": route["geometry"],
    }


def _split_by_payload(
    requested: list[str],
    scenario: Scenario,
    state: SystemState,
    timestamp_hours: float,
) -> list[list[str]]:
    """
    Split requested pickups into payload-feasible batches.
    """

    locations = {
        loc.id: loc
        for loc in scenario.locations
    }

    truck = scenario.trucks[0]

    batches: list[list[str]] = []

    current_batch: list[str] = []
    current_weight = 0.0

    for location_id in requested:

        location = locations[location_id]

        quantity = (
            state.bins[location_id].inventory_lbs
        )

        if quantity <= 1e-12:
            continue

        if (
            quantity
            > truck.max_weight_lbs + 1e-9
        ):
            state.failures.append(
                Failure(
                    timestamp_hours=timestamp_hours,
                    type="truck_weight_capacity",
                    message=(
                        f"{location.name} contains "
                        f"{quantity:.2f} lbs, exceeding "
                        f"truck capacity "
                        f"{truck.max_weight_lbs:.2f} lbs."
                    ),
                    location_id=location_id,
                    truck_id=truck.id,
                )
            )

            continue

        if (
            current_batch
            and current_weight + quantity
            > truck.max_weight_lbs + 1e-9
        ):
            batches.append(current_batch)

            current_batch = []
            current_weight = 0.0

        current_batch.append(location_id)
        current_weight += quantity

    if current_batch:
        batches.append(current_batch)

    return batches


def _best_processing_trip(
    origin: dict[str, Any],
    batch: list[str],
    scenario: Scenario,
    state: SystemState,
) -> tuple[ProcessingSite, dict[str, Any]]:
    """
    Evaluate every processing site with enough available storage and
    select the route with minimum road distance.
    """

    locations = {
        loc.id: loc
        for loc in scenario.locations
    }

    batch_weight = sum(
        state.bins[location_id].inventory_lbs
        for location_id in batch
    )

    collection_points = [
        _point(
            locations[location_id],
            "collection",
        )
        for location_id in batch
    ]

    candidates: list[
        tuple[ProcessingSite, dict[str, Any]]
    ] = []

    for site in scenario.processing_sites:

        site_state = state.sites[site.id]

        available_storage = (
            site.storage_capacity_lbs
            - site_state.inventory_lbs
        )

        if (
            batch_weight
            > available_storage + 1e-9
        ):
            continue

        destination = _point(
            site,
            "processing_site",
        )

        trip = _osrm_trip(
            origin,
            collection_points,
            destination,
        )

        candidates.append(
            (
                site,
                trip,
            )
        )

    if not candidates:
        raise RuntimeError(
            "No processing site has enough available "
            f"storage for {batch_weight:.2f} lbs."
        )

    return min(
        candidates,
        key=lambda item: (
            item[1]["distance_miles"]
        ),
    )


def execute_greedy_route(
    scenario: Scenario,
    state: SystemState,
    requested: list[str],
    timestamp_hours: float,
) -> None:
    """
    Construct and execute one route decision.

    Current assumptions:
    - first truck is used
    - first processing site is used as the route origin/depot
    - requested pickups are split only when truck payload requires it
    - processing destination is selected dynamically by shortest
      feasible road route
    """

    if not requested:
        return

    truck = scenario.trucks[0]
    truck_state = state.trucks[truck.id]

    locations = {
        loc.id: loc
        for loc in scenario.locations
    }

    try:
        origin_site = (
            scenario.processing_sites[0]
        )

        route_origin = _point(
            origin_site,
            "route_origin",
        )

    except Exception as exc:

        state.failures.append(
            Failure(
                timestamp_hours=timestamp_hours,
                type="geocoding_failure",
                message=str(exc),
                truck_id=truck.id,
            )
        )

        return

    batches = _split_by_payload(
        requested,
        scenario,
        state,
        timestamp_hours,
    )

    if not batches:
        return

    route_segments: list[
        dict[str, Any]
    ] = []

    ordered_stops: list[
        dict[str, Any]
    ] = [
        route_origin
    ]

    total_miles = 0.0
    total_drive_minutes = 0.0
    total_service_minutes = 0.0
    total_collected = 0.0

    processing_site_ids: list[str] = []

    current_origin = route_origin

    for batch in batches:

        try:

            site, trip = _best_processing_trip(
                current_origin,
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

        collection_stops = [
            stop
            for stop in trip["stops"]
            if stop["type"] == "collection"
        ]

        batch_collected = 0.0

        for stop in collection_stops:

            location_id = stop["id"]

            location = locations[
                location_id
            ]

            bin_state = state.bins[
                location_id
            ]

            quantity = (
                bin_state.inventory_lbs
            )

            if quantity <= 1e-12:
                continue

            if (
                truck_state.load_lbs
                + quantity
                > truck.max_weight_lbs
                + 1e-9
            ):

                state.failures.append(
                    Failure(
                        timestamp_hours=(
                            timestamp_hours
                        ),
                        type=(
                            "truck_weight_capacity"
                        ),
                        message=(
                            "Route would exceed "
                            "truck capacity at "
                            f"{location.name}."
                        ),
                        location_id=(
                            location_id
                        ),
                        truck_id=truck.id,
                    )
                )

                return

            #
            # Atomic pickup transfer
            #

            bin_state.inventory_lbs = 0.0

            bin_state.collected_lbs += (
                quantity
            )

            bin_state.pickups += 1

            state.total_collected_lbs += (
                quantity
            )

            truck_state.load_lbs += (
                quantity
            )

            truck_state.max_load_lbs = max(
                truck_state.max_load_lbs,
                truck_state.load_lbs,
            )

            batch_collected += quantity
            total_collected += quantity

            total_service_minutes += (
                location.service_minutes
            )

        if batch_collected <= 1e-12:
            continue

        available_storage = (
            site.storage_capacity_lbs
            - site_state.inventory_lbs
        )

        if (
            truck_state.load_lbs
            > available_storage + 1e-9
        ):

            raise RuntimeError(
                "Processing storage became "
                "insufficient after route planning."
            )

        #
        # Atomic unload transfer
        #

        unload_quantity = (
            truck_state.load_lbs
        )

        site_state.inventory_lbs += (
            unload_quantity
        )

        site_state.received_lbs += (
            unload_quantity
        )

        site_state.max_inventory_lbs = max(
            site_state.max_inventory_lbs,
            site_state.inventory_lbs,
        )

        truck_state.load_lbs = 0.0

        total_service_minutes += (
            site.unload_minutes
        )

        total_miles += (
            trip["distance_miles"]
        )

        total_drive_minutes += (
            trip["drive_minutes"]
        )

        route_segments.append(
            {
                "type": (
                    "collection_to_processing"
                ),
                "distance_miles": (
                    trip["distance_miles"]
                ),
                "drive_minutes": (
                    trip["drive_minutes"]
                ),
                "geometry": (
                    trip["geometry"]
                ),
                "stops": (
                    trip["stops"]
                ),
            }
        )

        ordered_stops.extend(
            trip["stops"][1:]
        )

        processing_site_ids.append(
            site.id
        )

        current_origin = _point(
            site,
            "processing_site",
        )

    if total_collected <= 1e-12:
        return

    #
    # Return to route origin.
    #

    if current_origin["id"] != route_origin["id"]:

        try:

            return_leg = _osrm_route(
                current_origin,
                route_origin,
            )

        except Exception as exc:

            state.failures.append(
                Failure(
                    timestamp_hours=(
                        timestamp_hours
                    ),
                    type="routing_failure",
                    message=(
                        "Return-leg routing failed: "
                        f"{exc}"
                    ),
                    truck_id=truck.id,
                )
            )

            return

        total_miles += (
            return_leg["distance_miles"]
        )

        total_drive_minutes += (
            return_leg["drive_minutes"]
        )

        route_segments.append(
            {
                "type": "return",
                "distance_miles": (
                    return_leg[
                        "distance_miles"
                    ]
                ),
                "drive_minutes": (
                    return_leg[
                        "drive_minutes"
                    ]
                ),
                "geometry": (
                    return_leg["geometry"]
                ),
                "stops": [
                    current_origin,
                    route_origin,
                ],
            }
        )

        ordered_stops.append(
            route_origin
        )

    labor_hours = (
        total_drive_minutes
        + total_service_minutes
    ) / 60.0

    truck_state.miles += total_miles

    truck_state.labor_hours += (
        labor_hours
    )

    truck_state.routes += 1

    state.operating_cost += (
        total_miles
        * truck.cost_per_mile
        + labor_hours
        * truck.cost_per_hour
    )

    geometries = [
        segment["geometry"]["coordinates"]
        for segment in route_segments
        if (
            segment.get(
                "geometry",
                {},
            ).get("type")
            == "LineString"
        )
    ]

    state.routes.append(
        {
            "route_id": (
                f"route_{len(state.routes) + 1}"
            ),
            "timestamp_hours": (
                timestamp_hours
            ),
            "truck_id": truck.id,
            "origin": route_origin,
            "processing_site_ids": (
                processing_site_ids
            ),
            "distance_miles": (
                total_miles
            ),
            "drive_minutes": (
                total_drive_minutes
            ),
            "labor_hours": (
                labor_hours
            ),
            "collected_lbs": (
                total_collected
            ),
            "stops": (
                ordered_stops
            ),
            "geometry": {
                "type": (
                    "MultiLineString"
                ),
                "coordinates": (
                    geometries
                ),
            },
            "segments": (
                route_segments
            ),
        }
    )
