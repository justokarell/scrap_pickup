
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


def fake_geocode(address):
    # Stable deterministic coordinates keyed only by address for unit tests.
    seed = sum(ord(ch) for ch in address)
    return (
        41.0 + (seed % 1000) / 100000.0,
        -73.6 + (seed % 1200) / 100000.0,
    )


def fake_trip(origin, collection_points, destination):
    points = [origin, *collection_points, destination]
    coords = [[p["longitude"], p["latitude"]] for p in points]
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
    assert abs(result["validation"]["mass_balance_residual_lbs"]) < 1e-6
    assert result["summary"]["routes_executed"] == 2
    assert len(result["routes"]) == 2
    assert result["routes"][0]["depot"]["id"] == "stamford_collection_depot"
    assert result["routes"][0]["geometry"]["type"] == "MultiLineString"


def test_depot_required():
    p = payload()
    del p["scenario"]["depot"]
    response = client.post("/simulate", json=p)
    assert response.status_code in (400, 422, 500)


@patch("simulation.routing._geocode", side_effect=fake_geocode)
@patch("simulation.routing._osrm_route", side_effect=fake_route)
@patch("simulation.routing._osrm_trip", side_effect=fake_trip)
def test_reference_has_no_coordinates(mock_trip, mock_route, mock_geocode):
    p = payload()
    assert "latitude" not in p["scenario"]["depot"]
    assert "longitude" not in p["scenario"]["depot"]
    for obj in p["scenario"]["locations"] + p["scenario"]["processing_sites"]:
        assert "latitude" not in obj
        assert "longitude" not in obj

    response = client.post("/simulate", json=p)
    assert response.status_code == 200
    assert response.json()["summary"]["routes_executed"] == 2
