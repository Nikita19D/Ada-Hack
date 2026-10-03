// carbon-alpha/app.js
//
// This file talks to the FastAPI server using three requests:
//   GET  /api/projects        -> load the list of projects
//   GET  /api/projects/{id}   -> load one project's details
//   POST /api/portfolio       -> send the ticked ids and get the summary back
//
// All requests go to the same server that served this page, so no extra setup.

const projectsBody = document.getElementById("projects-body");
const statusEl = document.getElementById("projects-status");
const limitInput = document.getElementById("limit-input");
const loadBtn = document.getElementById("load-btn");
const clearBtn = document.getElementById("clear-btn");
const calcBtn = document.getElementById("calc-btn");
const resultEl = document.getElementById("portfolio-result");
const detailPanel = document.getElementById("detail-panel");
const detailBody = document.getElementById("detail-body");

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function formatNumber(value) {
    return Number(value).toLocaleString("en-US");
}

// Missing values in the spreadsheet arrive as null, so show a dash instead.
function show(value) {
    return value === null || value === undefined || value === "" ? "-" : value;
}

function makeCell(text) {
    const td = document.createElement("td");
    td.textContent = text;
    return td;
}

// ---------------------------------------------------------------------------
// GET /api/projects - load the list
// ---------------------------------------------------------------------------

async function loadProjects() {
    const limit = limitInput.value || 50;
    statusEl.textContent = "Loading projects...";

    try {
        const response = await fetch("/api/projects?limit=" + limit);
        if (!response.ok) {
            throw new Error("server replied " + response.status);
        }
        const data = await response.json();
        renderProjects(data.projects);
        statusEl.textContent = "Showing " + data.count + " of " + data.total + " projects.";
    } catch (error) {
        statusEl.textContent = "Could not load projects: " + error.message;
    }
}

function renderProjects(projects) {
    projectsBody.innerHTML = "";

    for (const project of projects) {
        const row = document.createElement("tr");

        // 1. the tick box used to build the portfolio
        const checkCell = document.createElement("td");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "project-check";
        checkbox.value = project.id;
        checkCell.appendChild(checkbox);
        row.appendChild(checkCell);

        // 2. the project id
        row.appendChild(makeCell(project.id));

        // 3. the name, clickable to load details with another GET request
        const nameCell = document.createElement("td");
        const link = document.createElement("a");
        link.href = "#";
        link.textContent = show(project.name);
        link.addEventListener("click", function (event) {
            event.preventDefault();
            showDetails(project.id);
        });
        nameCell.appendChild(link);
        row.appendChild(nameCell);

        // 4. credits still available
        row.appendChild(makeCell(formatNumber(project.co2)));

        // 5. type and country
        row.appendChild(makeCell(show(project.type)));
        row.appendChild(makeCell(show(project.country)));

        projectsBody.appendChild(row);
    }
}

// ---------------------------------------------------------------------------
// GET /api/projects/{id} - one project's details
// ---------------------------------------------------------------------------

async function showDetails(projectId) {
    detailPanel.classList.remove("hidden");
    detailBody.textContent = "Loading " + projectId + "...";

    try {
        const response = await fetch("/api/projects/" + encodeURIComponent(projectId));
        if (!response.ok) {
            throw new Error("server replied " + response.status);
        }
        const project = await response.json();
        renderDetails(project);
    } catch (error) {
        detailBody.textContent = "Could not load details: " + error.message;
    }
}

function renderDetails(project) {
    const rows = [
        ["ID", project.id],
        ["Name", show(project.name)],
        ["Type", show(project.type)],
        ["Country", show(project.country)],
        ["Credits remaining", formatNumber(project.co2) + " tCO2e"],
        ["Credits issued", formatNumber(project.co2_issued) + " tCO2e"],
        ["Price", show(project.price)],
        ["Failure probability", show(project.failure_probability)],
    ];

    detailBody.innerHTML = "";
    const list = document.createElement("dl");
    for (const row of rows) {
        const dt = document.createElement("dt");
        dt.textContent = row[0];
        const dd = document.createElement("dd");
        dd.textContent = row[1];
        list.appendChild(dt);
        list.appendChild(dd);
    }
    detailBody.appendChild(list);
}

// ---------------------------------------------------------------------------
// POST /api/portfolio - send the ticked ids and show the summary
// ---------------------------------------------------------------------------

async function calculatePortfolio() {
    const ticked = document.querySelectorAll(".project-check:checked");
    const ids = Array.from(ticked).map(function (box) { return box.value; });

    if (ids.length === 0) {
        resultEl.textContent = "Tick some projects first.";
        return;
    }

    resultEl.textContent = "Calculating...";

    try {
        const response = await fetch("/api/portfolio", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_ids: ids }),
        });
        if (!response.ok) {
            throw new Error("server replied " + response.status);
        }
        const result = await response.json();
        renderResult(result);
    } catch (error) {
        resultEl.textContent = "Could not calculate: " + error.message;
    }
}

function renderResult(result) {
    const cost = result.total_cost === null
        ? "unknown (optiver.xlsx has no price data)"
        : "$" + formatNumber(result.total_cost);

    resultEl.innerHTML = "";

    const list = document.createElement("ul");
    const lines = [
        ["Projects selected", result.project_count],
        ["Nominal CO2", formatNumber(result.nominal_co2) + " tCO2e"],
        ["Target", formatNumber(result.target) + " tCO2e"],
        ["Total cost", cost],
    ];
    for (const line of lines) {
        const li = document.createElement("li");
        li.textContent = line[0] + ": " + line[1];
        list.appendChild(li);
    }

    const verdict = document.createElement("li");
    verdict.className = result.nominal_target_reached ? "good" : "bad";
    verdict.textContent = result.nominal_target_reached ? "Target reached" : "Below target";
    list.appendChild(verdict);

    resultEl.appendChild(list);

    if (result.missing_project_ids.length > 0) {
        const warning = document.createElement("p");
        warning.className = "warn";
        warning.textContent = "Unknown project ids: " + result.missing_project_ids.join(", ");
        resultEl.appendChild(warning);
    }
}

// ---------------------------------------------------------------------------
// Wire up the buttons and load the first page of projects
// ---------------------------------------------------------------------------

loadBtn.addEventListener("click", loadProjects);
calcBtn.addEventListener("click", calculatePortfolio);
clearBtn.addEventListener("click", function () {
    document.querySelectorAll(".project-check:checked").forEach(function (box) {
        box.checked = false;
    });
});

loadProjects();

