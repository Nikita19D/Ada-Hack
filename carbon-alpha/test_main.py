"""
Tests for Carbon Alpha's main.py.

How to run (from inside the carbon-alpha folder):

    python -m pytest test_main.py -v

Why these tests exist:
    They check that the REAL Excel data is loaded correctly and that the two
    API endpoints behave as we expect - including the fact that price and
    failure_probability are deliberately left empty (None), because they are
    genuinely not in optiver.xlsx.

Note: importing main reads the 16 MB workbook once (~10-15 s), so the
TestClient is created a single time and shared by every test.
"""

import math
import os
import sys

# Make sure we can import main.py no matter which folder pytest is started from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from fastapi.testclient import TestClient

import main


# ---------------------------------------------------------------------------
# Shared test client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """One TestClient for all tests (creating it loads the Excel file once)."""
    with TestClient(main.app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Facts about the real data, taken from inspecting optiver.xlsx.
# These act as a "smoke test" that we are reading the right columns.
# ---------------------------------------------------------------------------

KNOWN_PROJECT = {
    "id": "ACR0102",
    "name": "Air Bag Gas Substitution",
    "co2": 7966340,
    "co2_issued": 7984006,
    "type": "SF6 Replacement",
    "country": "United States",
}

BIGGEST_PROJECT_ID = "ART0102"  # the Guyana project, biggest by credits


# ===========================================================================
# Tests for load_projects()
# ===========================================================================

def test_load_projects_returns_a_list():
    """load_projects() should hand back a plain Python list."""
    assert isinstance(main.PROJECTS, list)


def test_load_projects_count():
    """The real workbook has 11,468 projects."""
    assert len(main.PROJECTS) == 11468


def test_every_project_has_the_same_keys():
    """Each record must have exactly the fields the rest of the app expects."""
    expected = {"id", "name", "co2", "co2_issued", "price",
                "failure_probability", "type", "country"}
    for project in main.PROJECTS:
        assert set(project.keys()) == expected


def test_ids_are_unique_and_non_empty():
    """Every project id must be unique and a non-empty string."""
    ids = [p["id"] for p in main.PROJECTS]
    assert len(ids) == len(set(ids))          # no duplicates
    assert all(isinstance(i, str) and i for i in ids)


def test_known_project_values():
    """A project we looked up by hand must match the spreadsheet exactly."""
    project = main.PROJECTS_BY_ID["ACR0102"]
    assert project["name"] == KNOWN_PROJECT["name"]
    assert project["co2"] == KNOWN_PROJECT["co2"]
    assert project["co2_issued"] == KNOWN_PROJECT["co2_issued"]
    assert project["type"] == KNOWN_PROJECT["type"]
    assert project["country"] == KNOWN_PROJECT["country"]


def test_biggest_project():
    """The biggest project by available credits is still ART0102 (Guyana)."""
    biggest = max(main.PROJECTS, key=lambda p: p["co2"])
    assert biggest["id"] == BIGGEST_PROJECT_ID
    assert biggest["name"] == "Guyana"


def test_price_and_failure_are_none_for_every_project():
    """IMPORTANT honesty check.

    optiver.xlsx has no price or failure-probability data, so both fields must
    stay None. If this test ever fails, someone has invented fake numbers.
    """
    assert all(p["price"] is None for p in main.PROJECTS)
    assert all(p["failure_probability"] is None for p in main.PROJECTS)


def test_no_nan_values_leak_through():
    """Missing Excel cells must become None, never the float value NaN."""
    for p in main.PROJECTS:
        # Integer fields
        assert isinstance(p["co2"], int)
        assert isinstance(p["co2_issued"], int)
        # Text fields: a string or None, never NaN
        for field in ("name", "type", "country"):
            value = p[field]
            assert value is None or isinstance(value, str)
            if isinstance(value, float):
                assert not math.isnan(value)


def test_text_fields_are_trimmed():
    """Text should not have leading/trailing spaces (e.g. 'ACR ' )."""
    for p in main.PROJECTS[:2000]:          # a sample keeps the test quick
        for field in ("name", "type", "country"):
            value = p[field]
            if value is not None:
                assert value == value.strip()


def test_lookup_table_agrees_with_the_list():
    """PROJECTS_BY_ID must contain every project and point at the right one."""
    assert len(main.PROJECTS_BY_ID) == len(main.PROJECTS)
    for p in main.PROJECTS:
        assert main.PROJECTS_BY_ID[p["id"]] is p


# ===========================================================================
# Tests for GET /api/projects
# ===========================================================================

def test_list_projects_status_and_default_limit(client):
    """No limit given -> default of 50 projects, with a total count."""
    response = client.get("/api/projects")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 11468
    assert body["count"] == 50
    assert len(body["projects"]) == 50


def test_list_projects_custom_limit(client):
    """?limit=5 should return exactly 5 projects."""
    body = client.get("/api/projects?limit=5").json()
    assert body["count"] == 5
    assert len(body["projects"]) == 5


def test_list_projects_limit_zero(client):
    """?limit=0 is allowed and returns an empty list."""
    body = client.get("/api/projects?limit=0").json()
    assert body["count"] == 0
    assert body["projects"] == []


def test_list_projects_limit_larger_than_total(client):
    """Asking for more rows than exist just returns everything."""
    body = client.get("/api/projects?limit=999999").json()
    assert body["total"] == 11468
    assert body["count"] == 11468
    assert len(body["projects"]) == 11468


def test_list_projects_negative_limit_is_safe(client):
    """A negative limit must not crash or slice from the end."""
    response = client.get("/api/projects?limit=-5")
    assert response.status_code == 200
    assert response.json()["projects"] == []


def test_list_projects_limit_must_be_a_number(client):
    """A non-number limit is rejected by FastAPI with status 422."""
    response = client.get("/api/projects?limit=abc")
    assert response.status_code == 422


def test_list_projects_contains_no_invalid_json(client):
    """The JSON must be valid - no NaN littered inside it."""
    response = client.get("/api/projects?limit=50")
    assert "NaN" not in response.text
    assert "Infinity" not in response.text


def test_list_projects_first_record_shape(client):
    """The first project returned matches our loader output exactly."""
    first = client.get("/api/projects?limit=1").json()["projects"][0]
    assert first["id"] == KNOWN_PROJECT["id"]
    assert first["price"] is None
    assert first["failure_probability"] is None


# ===========================================================================
# Tests for GET /api/projects/{project_id}
# ===========================================================================

def test_get_one_project(client):
    """Fetching a real id returns that project's details."""
    response = client.get("/api/projects/ACR0102")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "ACR0102"
    assert body["name"] == KNOWN_PROJECT["name"]
    assert body["co2"] == KNOWN_PROJECT["co2"]


def test_get_one_project_matches_the_list(client):
    """The single-project endpoint and the list must agree."""
    from_list = client.get("/api/projects?limit=1").json()["projects"][0]
    from_single = client.get("/api/projects/ACR0102").json()
    assert from_single == from_list


def test_get_unknown_project_returns_404(client):
    """An id that does not exist returns a clear 404 error."""
    response = client.get("/api/projects/DOES-NOT-EXIST")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_biggest_project(client):
    """We can fetch the biggest project through the API too."""
    body = client.get(f"/api/projects/{BIGGEST_PROJECT_ID}").json()
    assert body["name"] == "Guyana"
    assert body["co2"] == 45762713


# ===========================================================================
# Tests for calculate_portfolio() and POST /api/portfolio
# ===========================================================================

def test_calculate_portfolio_empty():
    """No projects chosen -> zero credits and the target is not reached."""
    result = main.calculate_portfolio([])
    assert result["project_count"] == 0
    assert result["nominal_co2"] == 0
    assert result["nominal_target_reached"] is False


def test_calculate_portfolio_single_project():
    """One real project carries its exact credits into the summary."""
    result = main.calculate_portfolio(["ACR0102"])
    assert result["project_count"] == 1
    assert result["nominal_co2"] == KNOWN_PROJECT["co2"]
    assert result["target"] == 100000
    assert result["nominal_target_reached"] is True


def test_calculate_portfolio_adds_credits_up():
    """Credits from several projects are summed correctly."""
    result = main.calculate_portfolio(["ACR0102", BIGGEST_PROJECT_ID])
    assert result["project_count"] == 2
    assert result["nominal_co2"] == 7966340 + 45762713


def test_calculate_portfolio_reports_unknown_ids():
    """Ids that are not in the data are reported, not silently dropped."""
    result = main.calculate_portfolio(["ACR0102", "NOPE-1", "NOPE-2"])
    assert result["project_count"] == 1
    assert result["missing_project_ids"] == ["NOPE-1", "NOPE-2"]


def test_calculate_portfolio_cost_is_none_without_prices():
    """Honesty check: no price data -> total_cost stays None, never guessed."""
    result = main.calculate_portfolio(["ACR0102", BIGGEST_PROJECT_ID])
    assert result["total_cost"] is None


def test_calculate_portfolio_zero_credit_project_is_below_target():
    """A project with no credits left cannot reach the target."""
    zero = next(p for p in main.PROJECTS if p["co2"] == 0)
    result = main.calculate_portfolio([zero["id"]])
    assert result["nominal_co2"] == 0
    assert result["nominal_target_reached"] is False


def test_post_portfolio_endpoint(client):
    """POSTing ids returns the expected summary."""
    body = client.post("/api/portfolio", json={"project_ids": ["ACR0102"]}).json()
    assert body["project_count"] == 1
    assert body["nominal_co2"] == KNOWN_PROJECT["co2"]
    assert body["nominal_target_reached"] is True


def test_post_portfolio_matches_helper(client):
    """The HTTP endpoint must agree with calculate_portfolio()."""
    ids = ["ACR0102", BIGGEST_PROJECT_ID]
    body = client.post("/api/portfolio", json={"project_ids": ids}).json()
    assert body == main.calculate_portfolio(ids)


def test_post_portfolio_empty_list(client):
    """An empty selection is valid and returns a zero summary."""
    response = client.post("/api/portfolio", json={"project_ids": []})
    assert response.status_code == 200
    assert response.json()["nominal_co2"] == 0


def test_post_portfolio_bad_body_is_rejected(client):
    """A body without project_ids is rejected with 422."""
    response = client.post("/api/portfolio", json={"wrong": "shape"})
    assert response.status_code == 422


def test_post_portfolio_valid_json(client):
    """The POST response is valid JSON with no NaN values."""
    response = client.post("/api/portfolio", json={"project_ids": ["ACR0102"]})
    assert "NaN" not in response.text


# ===========================================================================
# Tests for the frontend files
# ===========================================================================

def test_index_page_is_served(client):
    """GET / returns the HTML page."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Carbon Alpha" in response.text


def test_stylesheet_is_served(client):
    """GET /style.css returns the stylesheet."""
    response = client.get("/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_javascript_is_served(client):
    """GET /app.js returns the browser script."""
    response = client.get("/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_spreadsheet_and_source_are_not_exposed(client):
    """Safety check: we must NOT serve the workbook or our Python files."""
    assert client.get("/optiver.xlsx").status_code == 404
    assert client.get("/main.py").status_code == 404
