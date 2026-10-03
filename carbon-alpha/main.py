"""
Carbon Alpha - main.py

Loads the REAL carbon-project data from optiver.xlsx and serves it as JSON
through a small FastAPI app.

Data flow we are building:
    optiver.xlsx  ->  load_projects()  ->  FastAPI  ->  GET /api/projects

IMPORTANT FACT ABOUT OUR DATA (found by inspecting the file):
    optiver.xlsx contains NO price and NO failure_probability columns
    (checked every sheet). Those numbers must come from the separate
    Optiver synthetic dataset, which we have not added yet.
    So 'price' and 'failure_probability' are set to None for now.
    We DO NOT invent numbers to fill the gaps.
"""

from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration - the names and numbers we rely on
# ---------------------------------------------------------------------------

# Path to the real challenge data, next to this file.
EXCEL_FILE = Path(__file__).parent / "optiver.xlsx"

SHEET_NAME = "PROJECTS"
# The real column names live on the 4th Excel row, so pandas needs header=3
# (pandas counts rows starting from 0).
HEADER_ROW = 3

# Real column names in the workbook. We copy them EXACTLY as pandas reads them.
COL_ID = "Project ID"
COL_NAME = "Project Name"
COL_TYPE = "Type"
COL_COUNTRY = "Country"
# 'Total Credits Remaining' = carbon credits still available to buy for a project.
COL_CO2 = "Total Credits Remaining"
# 'Total Credits Issued' = every credit the project has ever issued (its size).
# NOTE: this header really contains a newline inside it, which is why we write \n.
COL_CO2_ISSUED = "Total Credits \nIssued"

# The challenge target: a portfolio should deliver at least this many tonnes CO2e.
TARGET_CO2 = 100_000


# ---------------------------------------------------------------------------
# Loading the data
# ---------------------------------------------------------------------------

def clean_text(value):
    """Turn one Excel cell into a tidy string, or None if it is empty.

    In : a single cell value (could be text, number, or pandas NaN)
    Do : if the cell is missing (NaN) return None, otherwise trim spaces
    Out: a clean string, or None
    Why: keeps the JSON clean - no "nan" text and no trailing spaces.
    """
    if pd.isna(value):
        return None
    return str(value).strip()


def load_projects():
    """Read optiver.xlsx ONCE and return a simple list of project dictionaries.

    In : nothing (it reads the Excel file from disk)
    Do : opens the PROJECTS sheet, keeps only the columns we need,
         and converts NaN values to None
    Out: a list of dicts, each shaped like
         {
             "id": "...",
             "name": "...",
             "co2": 25000,                 # credits still available (tCO2e)
             "co2_issued": 40000,          # credits ever issued (project size)
             "price": None,                # not in this file yet
             "failure_probability": None,  # not in this file yet
             "type": "...",
             "country": "..."
         }
    Why: the rest of the app works with plain Python data, not DataFrames.
    """
    df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME, header=HEADER_ROW)

    projects = []
    for _, row in df.iterrows():
        project_id = row[COL_ID]

        # Skip rows where there is no project id - they are not real projects.
        if pd.isna(project_id):
            continue

        # Some rows have a missing credit number; treat that as 0 credits.
        co2 = row[COL_CO2]
        if pd.isna(co2):
            co2 = 0

        # Same idea for the "issued" figure - missing means 0.
        co2_issued = row[COL_CO2_ISSUED]
        if pd.isna(co2_issued):
            co2_issued = 0

        projects.append({
            "id": str(project_id).strip(),
            "name": clean_text(row[COL_NAME]),
            "co2": int(co2),
            "co2_issued": int(co2_issued),
            "price": None,                 # real price data is not in this file
            "failure_probability": None,   # real risk data is not in this file
            "type": clean_text(row[COL_TYPE]),
            "country": clean_text(row[COL_COUNTRY]),
        })

    return projects


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Carbon Alpha API")

# Load the data one time when the server starts, then reuse it for every request.
PROJECTS = load_projects()

# A quick lookup table {project_id: project} so we can find one project fast.
PROJECTS_BY_ID = {project["id"]: project for project in PROJECTS}


@app.get("/api/projects")
def list_projects(limit: int = 50):
    """Return a limited slice of the project list as JSON.

    In : an optional ?limit=N query parameter (default 50)
    Do : takes the first N projects from the in-memory list
    Out: {"total": <all projects>, "count": <returned>, "projects": [...]}
    Why: the frontend only needs a small number of rows, not all 11,000+.
    """
    # Guard against a negative limit, which would slice weirdly.
    safe_limit = max(0, limit)
    return {
        "total": len(PROJECTS),
        "count": min(safe_limit, len(PROJECTS)),
        "projects": PROJECTS[:safe_limit],
    }


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    """Return ONE project by its id.

    In : the project id from the URL, e.g. /api/projects/ACR0102
    Do : looks the id up in the lookup table
    Out: the project dictionary, or a 404 error if it does not exist
    Why: the frontend will open a single project's details.
    """
    project = PROJECTS_BY_ID.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return project


# ---------------------------------------------------------------------------
# Portfolio calculation (POST /api/portfolio)
# ---------------------------------------------------------------------------

class PortfolioRequest(BaseModel):
    """The JSON body the frontend sends us: a list of chosen project ids.

    Example body: {"project_ids": ["ACR0102", "ART0102"]}
    """
    project_ids: list[str]


def calculate_portfolio(project_ids):
    """Work out the totals for a chosen set of projects.

    In : a list of project ids (the ones the user ticked)
    Do : sums up the credits, and the cost IF real price data exists
    Out: a summary dictionary (see the keys below)
    Why: the whole point of the app - "does this portfolio reach the target?"
    """
    chosen = []
    missing = []
    for project_id in project_ids:
        project = PROJECTS_BY_ID.get(project_id)
        if project is None:
            missing.append(project_id)   # unknown id -> tell the user, don't guess
        else:
            chosen.append(project)

    # 'co2' is the credits still available, so adding them up is safe.
    nominal_co2 = sum(project["co2"] for project in chosen)

    # We can only add up a cost when EVERY chosen project has a real price.
    # optiver.xlsx has no price column yet, so this stays None for now.
    if chosen and all(project["price"] is not None for project in chosen):
        total_cost = sum(project["price"] for project in chosen)
    else:
        total_cost = None

    return {
        "project_count": len(chosen),
        "nominal_co2": nominal_co2,
        "total_cost": total_cost,
        "target": TARGET_CO2,
        "nominal_target_reached": nominal_co2 >= TARGET_CO2,
        "missing_project_ids": missing,
    }


@app.post("/api/portfolio")
def portfolio(request: PortfolioRequest):
    """Return the summary for the portfolio the frontend sent us.

    In : a JSON body {"project_ids": [...]}
    Do : hands the ids to calculate_portfolio()
    Out: the summary dictionary as JSON
    Why: the frontend POSTs the ticked projects and shows the result.
    """
    return calculate_portfolio(request.project_ids)


# ---------------------------------------------------------------------------
# Frontend files (index.html, style.css, app.js)
# ---------------------------------------------------------------------------
# We serve these three files explicitly, on purpose. Mounting the whole folder
# would also expose optiver.xlsx (16 MB) and main.py, which we do not want.

BASE_DIR = Path(__file__).parent


@app.get("/", include_in_schema=False)
def serve_index():
    """Serve the single-page UI."""
    return FileResponse(BASE_DIR / "index.html")


@app.get("/style.css", include_in_schema=False)
def serve_css():
    """Serve the stylesheet."""
    return FileResponse(BASE_DIR / "style.css")


@app.get("/app.js", include_in_schema=False)
def serve_js():
    """Serve the browser JavaScript."""
    return FileResponse(BASE_DIR / "app.js")
