"""Tests for portfolio-risk calculations using test-only dummy projects."""

import random

import pytest

from simulation import simulate_portfolio, stress_once


def test_buffer_recovers_half_test_only_project():
    project = {"id": "test-buffer", "project_name": "Test buffer", "co2": 200000,
               "failure_probability": 1, "loss_recovery_fraction": .5}
    result = simulate_portfolio([project], n_simulations=10)
    assert result["success_probability"] == 1  # Exactly 100k counts as success.
    assert result["simulation_results"] == [100000] * 10
    scenario = stress_once([project])
    assert scenario["projects"][0]["survived"] is False
    assert scenario["total_delivered"] == 100000
    assert scenario["target_reached"] is True


@pytest.mark.parametrize("recovery", [-1, 1.1, float("nan"), True, "0.5"])
def test_invalid_recovery_is_rejected(recovery):
    project = {"id": "test", "project_name": "Test", "co2": 1,
               "failure_probability": 0, "loss_recovery_fraction": recovery}
    with pytest.raises(ValueError):
        simulate_portfolio([project])


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def test_catalogue_and_page_are_served(client):
    response = client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert len(data["projects"]) == 4355
    assert data["maximum_budget"] == 1000000
    assert all(0 <= p["failure_probability"] <= 1 for p in data["projects"])
    for path in ("/", "/app.js", "/style.css"):
        assert client.get(path).status_code == 200
    assert client.get("/carbon_credits_challenge.xlsx").status_code == 404


def test_api_uses_authoritative_risk_not_browser_values(client, monkeypatch):
    import main
    project = main.load_projects()[0]
    captured = {}
    def capture(projects, count, target):
        captured.update(projects=projects, count=count, target=target)
        return {"checked": True}
    monkeypatch.setattr(main, "simulate_portfolio", capture)
    response = client.post("/api/risk", json={"projects": [{"id": project["id"], "co2": 10,
        "failure_probability": 0.99, "price_per_credit": 0}], "n_simulations": 50})
    assert response.status_code == 200
    assert captured["projects"][0]["failure_probability"] == project["failure_probability"]
    assert captured["projects"][0]["price_per_credit"] == project["price_per_credit"]
    assert captured["count"] == 50
    assert captured["target"] == 100000


@pytest.mark.parametrize("kind", ["empty", "unknown", "duplicate", "too_many", "over_budget", "negative", "wrong_target"])
def test_api_rejects_invalid_portfolios(client, kind):
    from main import load_projects
    project = load_projects()[0]
    purchase = {"id": project["id"], "co2": 10}
    payload = {"projects": [purchase]}
    if kind == "empty": payload["projects"] = []
    elif kind == "unknown": payload["projects"] = [{"id": "missing", "co2": 10}]
    elif kind == "duplicate": payload["projects"] = [purchase, purchase]
    elif kind == "too_many": purchase["co2"] = project["available_tonnes"] + 1
    elif kind == "over_budget": payload["budget"] = 1
    elif kind == "negative": purchase["co2"] = -1
    elif kind == "wrong_target": payload["target"] = 1
    for path in ("/api/risk", "/api/stress"):
        assert client.post(path, json=payload).status_code == 422


def test_end_to_end_real_challenge_portfolio(client):
    from main import load_projects
    projects = []
    cost = 0
    countries = set()
    for project in load_projects():
        if project["available_tonnes"] < 50000 or project["country"] in countries:
            continue
        added_cost = 50000 * project["price_per_credit"]
        if cost + added_cost > 1000000:
            continue
        projects.append({"id": project["id"], "co2": 50000})
        countries.add(project["country"])
        cost += added_cost
        if len(projects) == 3: break
    assert len(projects) == 3
    response = client.post("/api/risk", json={"projects": projects})
    assert response.status_code == 200
    result = response.json()
    assert len(result["simulation_results"]) == 5000
    assert result["success_probability"] == sum(v >= 100000 for v in result["simulation_results"]) / 5000
    assert result["expected_co2"] == sum(result["simulation_results"]) / 5000
    stress = client.post("/api/stress", json={"projects": projects})
    assert stress.status_code == 200
    scenario = stress.json()
    assert scenario["total_delivered"] == sum(p["delivered_co2"] for p in scenario["projects"])
    assert scenario["target_reached"] == (scenario["total_delivered"] >= 100000)


def test_guaranteed_success_test_only_projects():
    """Test-only dummy projects: all credits are delivered above the target."""
    projects = [
        {"id": "test-a", "project_name": "Test A", "co2": 70000, "failure_probability": 0},
        {"id": "test-b", "project_name": "Test B", "co2": 50000, "failure_probability": 0},
    ]

    result = simulate_portfolio(projects)

    assert result["success_probability"] == 1
    assert result["shortfall_probability"] == 0
    assert result["expected_co2"] == 120000
    assert result["median_co2"] == 120000
    assert len(result["simulation_results"]) == 5000


def test_impossible_portfolio_test_only_projects():
    """Test-only dummy project: total credits cannot reach the target."""
    projects = [
        {"id": "test-small", "project_name": "Test small", "co2": 25000, "failure_probability": 0},
    ]

    result = simulate_portfolio(projects)

    assert result["success_probability"] == 0
    assert result["shortfall_probability"] == 1
    assert all(delivered < result["target"] for delivered in result["simulation_results"])


def test_risky_portfolio_test_only_projects():
    """Test-only dummy projects produce both successful and missed scenarios."""
    projects = [
        {"id": "test-a", "project_name": "Test A", "co2": 70000, "failure_probability": 0.2},
        {"id": "test-b", "project_name": "Test B", "co2": 50000, "failure_probability": 0.2},
    ]
    random.seed(31415)

    result = simulate_portfolio(projects)

    assert 0 < result["success_probability"] < 1
    assert result["success_probability"] + result["shortfall_probability"] == 1


def test_higher_failure_probability_lowers_success_test_only_projects():
    """Test-only matched portfolios: higher project risk lowers success."""
    low_risk = [
        {"id": "test-a", "project_name": "Test A", "co2": 70000, "failure_probability": 0.05},
        {"id": "test-b", "project_name": "Test B", "co2": 50000, "failure_probability": 0.05},
    ]
    high_risk = [
        {"id": "test-a", "project_name": "Test A", "co2": 70000, "failure_probability": 0.35},
        {"id": "test-b", "project_name": "Test B", "co2": 50000, "failure_probability": 0.35},
    ]

    random.seed(27182)
    low_risk_result = simulate_portfolio(low_risk, n_simulations=20000)
    random.seed(27182)
    high_risk_result = simulate_portfolio(high_risk, n_simulations=20000)

    assert high_risk_result["success_probability"] < low_risk_result["success_probability"]


def test_stress_once_reports_project_outcomes_and_total_test_only_projects():
    """Test-only dummy projects verify project outcomes and summed delivery."""
    projects = [
        {
            "id": "test-survivor",
            "project_name": "Test survivor",
            "co2": 40000,
            "failure_probability": 0,
        },
        {
            "id": "test-failure",
            "project_name": "Test failure",
            "co2": 30000,
            "failure_probability": 1,
        },
    ]

    result = stress_once(projects, target=35000)

    assert result == {
        "projects": [
            {
                "id": "test-survivor",
                "project_name": "Test survivor",
                "survived": True,
                "delivered_co2": 40000,
            },
            {
                "id": "test-failure",
                "project_name": "Test failure",
                "survived": False,
                "delivered_co2": 0,
            },
        ],
        "total_delivered": 40000,
        "target_reached": True,
    }


@pytest.mark.parametrize(
    ("projects", "n_simulations", "target", "message"),
    [
        ([], 5000, 100000, "non-empty"),
        ([{"id": "test-a", "project_name": "Test A", "co2": 1, "failure_probability": 0}], 0, 100000, "positive"),
        ([{"id": "test-a", "project_name": "Test A", "co2": 1, "failure_probability": 0}], 5000, -1, "target"),
        ([{"project_name": "Test A", "co2": 1, "failure_probability": 0}], 5000, 100000, "id"),
        ([{"id": "test-a", "project_name": "Test A", "failure_probability": 0}], 5000, 100000, "co2"),
        ([{"id": "test-a", "project_name": "Test A", "co2": 1}], 5000, 100000, "failure_probability"),
        ([{"id": "test-a", "project_name": "Test A", "co2": -1, "failure_probability": 0}], 5000, 100000, "co2"),
        (
            [{"id": "test-a", "project_name": "Test A", "co2": 1, "failure_probability": 1.1}],
            5000,
            100000,
            "failure_probability",
        ),
        ([{"id": "test-a", "co2": 1, "failure_probability": 0}], 5000, 100000, "project_name"),
    ],
)
def test_invalid_inputs_raise_value_error(projects, n_simulations, target, message):
    with pytest.raises(ValueError, match=message):
        simulate_portfolio(projects, n_simulations=n_simulations, target=target)
