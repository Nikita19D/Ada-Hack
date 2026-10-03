"""Serve the existing interface and the challenge's project/risk data.

Optimised for ngrok hosting: binds 0.0.0.0, honours $PORT, allows the
ngrok domain via CORS, compresses the 4k-row catalogue, and runs the
Monte Carlo math in a worker thread so the tunnel stays responsive.
"""

import math
import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
app = FastAPI(title="Carbon Frontier", docs_url="/docs", redoc_url=None)

# --- ngrok-friendly middleware -------------------------------------------
# Wildcard CORS: ngrok gives you a random *.ngrok-free.app origin, so a
# fixed allow-list would break the UI on every restart.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*", "ngrok-skip-browser-warning"],
)
# GZip the big /api/projects payload (4355 rows) -> much faster over tunnel.
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def _ngrok_no_interstitial(request, call_next):
    """Tell ngrok this is an API call; also stop click-jacking blocks."""
    response = await call_next(request)
    # Lets fetch() pass through without the ngrok warning page.
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response


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


@app.get("/health")
def health():
    """Cheap ngrok/uptime check — avoids loading the workbook."""
    return {"ok": True, "target": TARGET, "maximum_budget": MAX_BUDGET}


@app.post("/api/risk")
async def run_risk(request: PortfolioRequest):
    projects = checked_portfolio(request)  # fast validation on event loop
    return await run_in_threadpool(
        simulate_portfolio, projects, request.n_simulations, request.target)


@app.post("/api/stress")
async def run_stress(request: PortfolioRequest):
    projects = checked_portfolio(request)
    return await run_in_threadpool(stress_once, projects, request.target)


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
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Run Carbon Frontier (ngrok-ready).")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"),
                        help="Bind address (default 0.0.0.0 so ngrok can reach it).")
    parser.add_argument("--port", type=int,
                        default=int(os.getenv("PORT", "8000")),
                        help="Port (honours $PORT for hosts that assign one).")
    parser.add_argument("--ngrok", action="store_true",
                        help="Open an ngrok tunnel via pyngrok (needs NGROK_AUTHTOKEN).")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload.")
    args = parser.parse_args()

    try:
        load_projects()  # warm the lru_cache so first tunnel hit is fast
        print(f"Catalogue ready.")
    except Exception as error:
        print(f"WARNING: catalogue not preloaded: {error}")

    if args.ngrok:
        try:
            from pyngrok import ngrok
        except ImportError:
            raise SystemExit("pyngrok not installed. Run: pip install pyngrok")
        token = os.getenv("NGROK_AUTHTOKEN")
        if token:
            ngrok.set_auth_token(token)
        tunnel = ngrok.connect(args.port, "http")
        print(f"ngrok tunnel -> {tunnel.public_url}  (share this URL)")

    print(f"Serving Carbon Frontier on {args.host}:{args.port} "
          f"-> open http://127.0.0.1:{args.port} in your browser "
          f"(0.0.0.0 is the bind address, not a browsable URL).")

    uvicorn.run(app, host=args.host, port=args.port,
                reload=bool(os.getenv("RELOAD")) and not args.no_reload,
                workers=int(os.getenv("WORKERS", "1")))
