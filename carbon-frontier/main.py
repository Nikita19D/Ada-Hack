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
from advise import advise_rules
import hashlib as _hashlib
import json as _json

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "carbon_credits_challenge.xlsx"


def _load_dotenv():
    """Simplest .env loader: KEY=value lines next to main.py, no new dependency."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()
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


_ADVISE_CACHE = {}
_ADVISE_SYSTEM = ("You are Carbon Frontier advisor. Synthetic challenge data only, "
                  "not investment advice, not verified impact. Reword the given rules "
                  "in plain language. Use ONLY the numbers given; never invent projects, "
                  "prices, or probabilities. Always return valid JSON with exactly "
                  "these keys: summary (string), risks (array of 1-2 strings), "
                  "suggestions (array of 1-3 objects with action, why, tradeoff), "
                  "what_if (string). Example: {\"summary\": \"...\", \"risks\": [\"...\"], "
                  "\"suggestions\": [{\"action\": \"...\", \"why\": \"...\", \"tradeoff\": \"...\"}], "
                  "\"what_if\": \"...\"}")


def _advise_key(projects, risk, budget, target):
    payload = _json.dumps({"p": [(p["id"], p["co2"]) for p in projects],
                           "s": round(float(risk.get("success_probability", 0)), 4),
                           "e": round(float(risk.get("expected_co2", 0)), 1),
                           "b": budget, "t": target}, sort_keys=True)
    return _hashlib.sha256(payload.encode()).hexdigest()


async def _call_openai(client, compact):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None, None
    body = {"model": os.getenv("ADVISE_MODEL", "gpt-4o-mini"), "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": _ADVISE_SYSTEM},
                         {"role": "user", "content": _json.dumps(compact)[:6000]}]}
    for attempt in range(3):
        try:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": "Bearer " + key}, json=body)
            status = getattr(resp, "status_code", 200)
            if status in _RETRY_STATUS:
                print(f"OpenAI retryable status {status} (attempt {attempt + 1}).")
                if attempt == 2:
                    return None, None
                await _sleep_backoff(attempt)
                continue
            if status >= 400:
                print(f"OpenAI error {_error_message(resp)}; falling back.")
                return None, None
            text = resp.json()["choices"][0]["message"]["content"]
            return text, "openai"
        except Exception:
            print("OpenAI call failed; falling back.")
            return None, None
    return None, None


_GEMINI_DEFAULT = "gemini-3.8-flash"
_GEMINI_FALLBACKS = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash")
# Google's docs call for exponential backoff on 429 RESOURCE_EXHAUSTED and
# 503 UNAVAILABLE. Short and bounded so the /api/advise timeout still holds.
_RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})


async def _call_gemini(client, compact):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None, None
    requested = os.getenv("GEMINI_MODEL", os.getenv("ADVISE_MODEL") or _GEMINI_DEFAULT)
    candidates = []
    for m in [requested, *_GEMINI_FALLBACKS]:
        if m and m not in candidates and "/" not in m and not m.startswith("gpt-"):
            candidates.append(m)
    prompt = (_ADVISE_SYSTEM + " Data: " + _json.dumps(compact)[:6000])
    for model in candidates:
        for attempt in range(3):
            try:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key},
                    json={"generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
                          "contents": [{"parts": [{"text": prompt}]}]})
            except Exception as error:
                # Transport hiccup: retry briefly, then move to the next model.
                print(f"Gemini call to {model} failed ({type(error).__name__}).")
                if attempt == 2:
                    break
                await _sleep_backoff(attempt)
                continue
            status = getattr(resp, "status_code", 200)
            if status in _RETRY_STATUS:
                msg = _error_message(resp)
                print(f"Gemini model {model}: {msg} (retrying, attempt {attempt + 1}).")
                if attempt == 2:
                    break
                await _sleep_backoff(attempt)
                continue
            if status >= 400:
                print(f"Gemini model {model}: {_error_message(resp)}; skipping model.")
                break
            try:
                data = resp.json()
            except Exception:
                print(f"Gemini model {model} returned unparseable JSON; skipping.")
                break
            if isinstance(data, dict) and data.get("error"):
                print(f"Gemini model {model}: {data['error'].get('message', data['error'])}; skipping.")
                break
            text = _extract_text(data)
            if not text:
                print(f"Gemini model {model} returned no text; falling back.")
                return None, None
            print(f"Gemini OK with model {model}.")
            return text, "gemini"
    return None, None


async def _sleep_backoff(attempt):
    """Full-jitter exponential backoff, capped so the request stays responsive."""
    import asyncio
    import random as _random
    cap = 0.5 * (2 ** attempt)
    await asyncio.sleep(_random.uniform(0, cap))


def _error_message(resp):
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"].get("message", data["error"]))[:200]
    except Exception:
        pass
    return f"HTTP {getattr(resp, 'status_code', '?')}"


def _extract_text(data):
    """Pull text out of a Gemini generateContent response, tolerating wrappers."""
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    except Exception:
        return None
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):  # strip ```json fences some models add
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return text


def _clean_llm(parsed, valid_ids=None):
    if not isinstance(parsed, dict):
        return None
    if not all(k in parsed for k in ("summary", "risks", "suggestions", "what_if")):
        return None
    try:
        return {"summary": str(parsed["summary"])[:600],
                "risks": [str(r)[:300] for r in parsed["risks"]][:2],
                "suggestions": [{"action": str(s.get("action", ""))[:300],
                                 "why": str(s.get("why", ""))[:300],
                                 "tradeoff": str(s.get("tradeoff", ""))[:300]}
                                for s in parsed["suggestions"] if isinstance(s, dict)][:3],
                "what_if": str(parsed["what_if"])[:400]}
    except Exception:
        return None


async def _llm_rewrite(rules, risk, projects, cost, target):
    import httpx
    compact = {"rules": {"summary": rules["summary"], "risks": rules["risks"],
                         "suggestions": rules["suggestions"], "what_if": rules["what_if"]},
               "risk": {"success": risk.get("success_probability"),
                        "expected": risk.get("expected_co2"),
                        "target": target, "cost": cost},
               "projects": [{"id": p["id"], "name": p.get("project_name"),
                             "co2": p["co2"], "country": p.get("country")} for p in projects]}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for caller in (_call_gemini, _call_openai):
                text, source = await caller(client, compact)
                if not text:
                    continue
                try:
                    cleaned = _clean_llm(_json.loads(text))
                except Exception:
                    continue
                if cleaned is not None:
                    cleaned["source"] = source
                    return cleaned
    except Exception:
        pass
    return None


@app.post("/api/advise")
async def run_advise(request: PortfolioRequest):
    projects = checked_portfolio(request)
    cost = sum(float(p["co2"]) * float(p["price_per_credit"]) for p in projects)
    risk = await run_in_threadpool(
        simulate_portfolio, projects, request.n_simulations, request.target)
    rules = advise_rules(projects, risk, cost, request.target)
    key = _advise_key(projects, risk, request.budget, request.target)
    if key in _ADVISE_CACHE:
        cached = dict(_ADVISE_CACHE[key])
        cached["metrics"] = rules["metrics"]
        return cached
    pretty = await _llm_rewrite(rules, risk, projects, cost, request.target)
    if pretty is None:
        return {**rules, "source": "rules",
                "disclaimer": "Rule-based advice from your simulation; no AI used."}
    source = pretty.pop("source", "llm")
    out = {**pretty, "metrics": rules["metrics"],
           "project_ids": rules["project_ids"], "source": source,
           "disclaimer": "AI explains your simulation; Monte Carlo numbers decide."}
    if len(_ADVISE_CACHE) > 200:
        _ADVISE_CACHE.clear()
    _ADVISE_CACHE[key] = out
    return out


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
