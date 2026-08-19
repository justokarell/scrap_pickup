
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
import json
from pathlib import Path

client = TestClient(app)


def payload():
    return json.loads(
        (
            Path(__file__).parents[1]
            / "reference_request.json"
        ).read_text()
    )


def fake_trip(points):
    # Preserve the supplied order and return simple GeoJSON solely for tests.
    coords = [
        [p["longitude"], p["latitude"]]
        for p in points
    ]
    return {
        "distance_miles": 10.0,
        "drive_minutes": 20.0,
        "geometry": {
            "type": "LineString",
            "coordinates": coords,
        },
        "stops": points,
    }


def fake_route(origin, destination):
    return {
        "distance_miles": 2.0,
        "drive_minutes": 5.0,
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [origin["longitude"], origin["latitude"]],
                [destination["longitude"], destination["latitude"]],
            ],
        },
    }


def fake_geocode(address):
    # Used only for the Scofieldtown address in tests.
    return (41.1300, -73.5550)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@patch("simulation.routing._geocode", side_effect=fake_geocode)
@patch("simulation.routing._osrm_route", side_effect=fake_route)
@patch("simulation.routing._osrm_trip", side_effect=fake_trip)
def test_reference(mock_trip, mock_route, mock_geocode):
    response = client.post("/simulate", json=payload())
    assert response.status_code == 200, response.text

    result = response.json()
    assert result["valid"] is True
    assert result["validation"]["mass_balance_passed"] is True
    assert abs(
        result["validation"]["mass_balance_residual_lbs"]
    ) < 1e-6
    assert result["summary"]["routes_executed"] == 2
    assert result["summary"]["total_arrivals_lbs"] > 0
    assert result["summary"]["total_collected_lbs"] > 0
    assert len(result["routes"]) == 2
    assert result["routes"][0]["geometry"]["type"] == "MultiLineString"


@patch("simulation.routing._geocode", side_effect=fake_geocode)
@patch("simulation.routing._osrm_route", side_effect=fake_route)
@patch("simulation.routing._osrm_trip", side_effect=fake_trip)
def test_reproducible_except_run_id(mock_trip, mock_route, mock_geocode):
    p = payload()
    first = client.post("/simulate", json=p).json()
    second = client.post("/simulate", json=p).json()

    for key in (
        "summary",
        "locations",
        "trucks",
        "processing_sites",
        "failures",
        "time_series",
        "routes",
    ):
        assert first[key] == second[key]


@patch("simulation.routing._geocode", side_effect=fake_geocode)
@patch("simulation.routing._osrm_route", side_effect=fake_route)
@patch("simulation.routing._osrm_trip", side_effect=fake_trip)
def test_threshold_policy(mock_trip, mock_route, mock_geocode):
    p = payload()
    p["scenario"]["policy"] = {
        "type": "threshold",
        "threshold": 0.20,
        "weekdays": [],
    }
    response = client.post("/simulate", json=p)
    assert response.status_code == 200
    assert response.json()["valid"] is True
