# Ada-Hack

## Run CarbonShield (Windows / VS Code terminal)

From the repository root:

```powershell
cd carbon-alpha
python -m pip install -r requirements.txt
python main.py
```

Open http://127.0.0.1:8000 in your browser. Keep the terminal running;
Ctrl+C stops the app. Do not use Live Server or open index.html directly:
the Python service serves both the page and its calculation endpoints.

Choose projects and quantities, or click **Load example portfolio** for three
actual challenge rows (not an optimizer). Run the risk test to draw the allocation
donut, delivery histogram, target-probability curve and single-scenario bars.
Changing a project or budget clears outdated results.

The supplied `carbon_credits_challenge.xlsx` has 4,355 projects with the
challenge's synthetic prices and ratings. The original `optiver.xlsx` is the raw
Berkeley database and is preserved unchanged. These are simulation estimates,
not market forecasts or verified environmental outcomes.

The simplified model assumes independent failures, despite the challenge's
correlated-risk warning. It uses the supplied rating probabilities, multiplies
them by 1.5 for past reversals and recovers half the credits for buffer pools.
Do not claim this implements the full correlated-risk model.

## Integration contract

- `GET /api/projects`: `{projects, target, maximum_budget, source}`.
- `POST /api/risk`: `{projects: [{id, co2}], budget, target, n_simulations}`.
- `POST /api/stress`: the same request shape (simulation count is unused).
- The service validates budget and available quantity, and reads price/risk
  directly from the workbook; browser-supplied price/risk overrides are ignored.
- `simulate_portfolio(projects, n_simulations=5000, target=100000)` returns
  `{target, simulations, success_probability, shortfall_probability,
  expected_co2, median_co2, simulation_results}`.
- `stress_once(projects, target=100000)` returns `{projects:
  [{id, project_name, survived, delivered_co2}], total_delivered, target_reached}`.
- Simulation projects require `{id, project_name, co2, failure_probability}`;
  optional `loss_recovery_fraction` defaults to zero. Workbook-backed projects
  use 0.5 for buffer pools. Probabilities are 0–1, not percentages.
- The existing `window.CarbonShieldPortfolioRisk` interface is preserved.

Dataset source: [Optiver challenge sheet](https://docs.google.com/spreadsheets/d/1d3YKqXgVyYUkYA9aYVlmE6ryc5MrrasY/edit).
Check Berkeley's licence before redistributing underlying data outside the event.

Portfolio-risk simulation functions are in `carbon-alpha/simulation.py`.
Tests cover labelled dummy projects and workbook-backed API integration.
After installing the requirements, run from the repository root:

```powershell
python -m pytest -q carbon-alpha/test_simulation.py
```
