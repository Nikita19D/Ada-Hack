# Carbon Frontier

Carbon Frontier is a small browser-based portfolio workspace for exploring
carbon-credit project purchases and estimating delivery risk. The page is
served by a local FastAPI service. It reads the supplied challenge workbook,
lets you choose projects and purchase quantities within a budget, and displays
portfolio risk from Monte Carlo simulations.

The estimates are for the challenge exercise. Workbook prices and ratings are
synthetic challenge inputs, not market forecasts or verified environmental
impact.

## Run the project

From the repository root in PowerShell:

```powershell
cd carbon-alpha
python -m pip install -r requirements.txt
python main.py
```

Open <http://127.0.0.1:8000> and leave the server running while you use the
page. Stop it with Ctrl+C. Open the app through this address; opening
`index.html` directly or using a static Live Server preview will not connect to
the API.

## Use the portfolio workspace

1. Set the portfolio budget in USD.
2. Search projects by name, country, or type, then choose a project and enter
   the amount of credits to purchase.
3. Select **Add project**. Repeat as needed. The page checks the available
   quantity and budget.
4. Review the selected projects, portfolio allocation, purchased-credit total,
   and total cost.
5. Select **Run risk test** to simulate 5,000 possible outcomes. Review target
   success, expected delivery, shortfall risk, the delivery histogram, and the
   delivery-confidence curve.
6. Select **Break my portfolio** to view one independently drawn scenario,
   including each project's outcome and its delivered credits.
7. Remove projects or select **Clear** to change the portfolio. Old simulation
   and stress results are cleared when the portfolio or budget changes.

**Load example portfolio** selects three real rows from the supplied challenge
workbook that fit the current budget. It is a convenience example, not an
optimizer. No project or risk values are made up for the interface.

## Risk model

The default target is 100,000 tCO2e. The simulator runs 5,000 scenarios by
default, checks every selected project in each scenario, and reports success
probability, shortfall probability, expected delivery, median delivery, and
the individual scenario totals.

Each project has a failure probability derived from its challenge risk rating.
The model multiplies that probability by 1.5 for projects marked as having a
past reversal, capped at 1. A project with a buffer pool returns half of its
selected credits in a failure scenario; otherwise a failed project returns
zero. Project failures are modelled as independent events. The supplied
challenge warns about correlated risk, which this simplified model does not
capture; results should not be described as guaranteed safety or verified
environmental impact.

## Project data and API

The browser loads the project catalogue from `GET /api/projects`. The API
returns project names, available quantities, synthetic challenge prices, risk
ratings, and the corresponding failure probabilities.

Each selected project held by the browser includes its catalogue fields and a
`co2` value for the quantity selected to purchase. The simulation functions
accept project dictionaries with these required fields:

```python
{
    "id": "catalogue project ID",
    "project_name": "catalogue project name",
    "co2": 25000,  # selected purchase quantity, not total availability
    "failure_probability": 0.12,  # probability from 0 to 1
}
```

`loss_recovery_fraction` is optional and defaults to zero. The API sets it to
0.5 for projects with a buffer pool. The browser sends only project IDs and
purchase quantities to the risk endpoints; the backend resolves prices and
risk values from the workbook rather than trusting browser-supplied values.

- `GET /api/projects` returns the catalogue, target, maximum budget, and source.
- `POST /api/risk` runs the portfolio simulation.
- `POST /api/stress` generates one stress scenario.

The existing browser integration is exposed as
`window.CarbonFrontierPortfolioRisk`. It includes `setSelectedProjects(projects)`,
`connect({ simulatePortfolio, stressOnce })`, and `renderStressResult(result)`.
The page's built-in connection calls the same-origin API endpoints above.

## Test

From the repository root, install dependencies as shown above, then run:

```powershell
python -m pytest -q carbon-alpha\test_simulation.py
```

The tests cover simulation outcomes, input validation, buffer recovery, and
the HTTP project/risk integration.

## Reusable prompt

Use this prompt when asking someone or an AI assistant to help operate or
review the workspace. Open Carbon Frontier at <http://127.0.0.1:8000> first.

> Help me use Carbon Frontier to review my selected carbon-credit portfolio.
> Use only the projects and prices loaded from the supplied challenge workbook
> and the results returned by the running application. Do not invent project
> data, probabilities, simulation results, or environmental claims. Help me
> check that my selected quantities fit the budget, interpret the estimated
> chance of delivering at least 100,000 tCO2e, explain the delivery histogram
> and confidence curve, and describe the single stress scenario if I run it.
> Make clear that the challenge inputs are synthetic and the simplified model
> assumes independent failures; these estimates are neither guarantees nor
> verified environmental impact. If the app or API is unavailable, tell me
> what could not be calculated instead of estimating it yourself.

## Data source note

The challenge workbook is included for the event exercise. Review Berkeley's
licence and the challenge terms before redistributing the underlying data.
