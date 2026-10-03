"""Serve the existing interface and the challenge's project/risk data."""

import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from openpyxl import load_workbook
from pydantic import BaseModel, Field

from simulation import simulate_portfolio, stress_once

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "carbon_credits_challenge.xlsx"
TARGET = 100000
MAX_BUDGET = 1000000
RISK = {"AAA": .01, "AA": .02, "A": .04, "BBB": .07,
        "BB": .12, "B": .20, "CCC": .35, "Unrated": .15}
app = FastAPI(title="CarbonShield")


@lru_cache(maxsize=1)
def load_projects():
    """Read supplied synthetic price/risk fields, never invent missing values."""
    if not DATA_FILE.is_file():
        raise ValueError("Missing carbon_credits_challenge.xlsx. Use the challenge workbook, not the raw Berkeley database.")
    workbook = load_workbook(DATA_FILE, read_only=True, data_only=True)
    try:
        if "CREDITS" not in workbook.sheetnames:
            raise ValueError("The challenge workbook must contain a CREDITS sheet.")
        rows = workbook["CREDITS"].iter_rows(values_only=True)
        headers = next(rows)
        required = {"credit_id", "project_name", "price_usd_per_t", "available_tonnes",
                    "risk_rating", "has_buffer_pool", "had_reversal"}
        if not required.issubset(headers):
            raise ValueError("The challenge workbook is missing required price/risk columns.")
        projects = []
        seen = set()
        for row in rows:
            data = dict(zip(headers, row))
            if data.get("credit_id") is None:
                continue
            project_id = str(data["credit_id"])
            if project_id in seen:
                raise ValueError(f"Duplicate credit id: {project_id}.")
            seen.add(project_id)
            price = float(data["price_usd_per_t"])
            available = float(data["available_tonnes"])
            if not all(math.isfinite(v) and v >= 0 for v in (price, available)):
                raise ValueError(f"Invalid price or available quantity for {project_id}.")
            rating = str(data["risk_rating"] or "Unrated").strip()
            if rating.lower() in {"nan", "unrated"}:
                rating = "Unrated"
            if rating not in RISK:
                raise ValueError(f"Unknown risk rating for {project_id}: {rating}.")
            reversed_before = str(data["had_reversal"]).strip().lower() == "yes"
            buffered = str(data["has_buffer_pool"]).strip().lower() == "yes"
            name = str(data["project_name"] or "").strip()
            if not name:
                raise ValueError(f"Missing project name for {project_id}.")
            projects.append({
                "id": project_id, "project_name": name,
                "country": data.get("country") or "Not provided",
                "project_type": data.get("project_type") or "Not provided",
                "registry": data.get("registry") or "Not provided",
                "available_tonnes": available, "price_per_credit": price,
                "currency": "USD", "risk_rating": rating,
                "failure_probability": min(1, RISK[rating] * (1.5 if reversed_before else 1)),
                "loss_recovery_fraction": .5 if buffered else 0,
                "has_buffer_pool": buffered, "had_reversal": reversed_before,
            })
        return projects
    except (TypeError, KeyError, StopIteration) as error:
        raise ValueError("Invalid challenge workbook. Check its columns and values.") from error
    finally:
        workbook.close()


class Purchase(BaseModel):
    id: str
    co2: float = Field(gt=0, allow_inf_nan=False)


class PortfolioRequest(BaseModel):
    projects: list[Purchase] = Field(min_length=1, max_length=100)
    budget: float = Field(default=MAX_BUDGET, gt=0, le=MAX_BUDGET, allow_inf_nan=False)
    target: int = Field(default=TARGET, ge=TARGET, le=TARGET)
    n_simulations: int = Field(default=5000, ge=1, le=20000)


def catalogue():
    try:
        return load_projects()
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def checked_portfolio(request):
    """Use workbook prices/risk, not values supplied by the browser."""
    lookup = {project["id"]: project for project in catalogue()}
    selected = []
    seen = set()
    cost = Decimal("0")
    for purchase in request.projects:
        if purchase.id in seen:
            raise HTTPException(422, "A project can only appear once in your portfolio.")
        seen.add(purchase.id)
        project = lookup.get(purchase.id)
        if project is None:
            raise HTTPException(422, "An unknown project was selected. Reload the page.")
        if purchase.co2 > project["available_tonnes"]:
            raise HTTPException(422, f"{project['project_name']}: quantity exceeds available credits.")
        cost += Decimal(str(purchase.co2)) * Decimal(str(project["price_per_credit"]))
        selected.append({**project, "co2": purchase.co2})
    if cost > Decimal(str(request.budget)):
        raise HTTPException(422, "Portfolio exceeds your budget. Reduce quantities or remove a project.")
    return selected


@app.get("/api/projects")
def get_projects():
    return {"projects": catalogue(), "target": TARGET, "maximum_budget": MAX_BUDGET,
            "source": "Optiver challenge workbook: prices and risk ratings are synthetic challenge inputs."}


@app.post("/api/risk")
def run_risk(request: PortfolioRequest):
    return simulate_portfolio(checked_portfolio(request), request.n_simulations, request.target)


@app.post("/api/stress")
def run_stress(request: PortfolioRequest):
    return stress_once(checked_portfolio(request), request.target)


@app.get("/")
@app.get("/index.html")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/app.js")
def javascript():
    return FileResponse(ROOT / "app.js", media_type="text/javascript")


@app.get("/style.css")
def stylesheet():
    return FileResponse(ROOT / "style.css", media_type="text/css")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
