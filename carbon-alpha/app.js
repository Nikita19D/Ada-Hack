const chartData = {
  "1M": { labels: ["Sep 8", "Sep 12", "Sep 16", "Sep 20", "Sep 24", "Sep 28", "Oct 2", "Oct 6"], values: [52, 55, 54, 63, 67, 69, 76, 82] },
  "3M": { labels: ["Jul", "Jul 15", "Aug", "Aug 15", "Sep", "Sep 15", "Oct", "Oct 6"], values: [37, 42, 40, 53, 57, 65, 69, 82] },
  "6M": { labels: ["May", "Jun", "Jul", "Aug", "Sep", "Oct"], values: [31, 38, 46, 54, 68, 82, 78, 91, 86, 100] },
  "1Y": { labels: ["Nov", "Jan", "Mar", "May", "Jul", "Sep", "Oct"], values: [20, 29, 34, 43, 52, 67, 73, 82, 100] },
  ALL: { labels: ["2022", "2023", "Q1 '24", "Q2 '24", "Q3 '24", "Q4 '24", "2025"], values: [14, 23, 28, 37, 48, 53, 65, 79, 100] }
};

function renderChart(period) {
  const { labels, values } = chartData[period];
  const lineChart = document.getElementById("line-chart");
  const bars = document.getElementById("bar-series");
  const months = document.getElementById("chart-months");
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 300 : 16 + index * (568 / (values.length - 1));
    const y = 194 - value * 1.72;
    return { x, y };
  });

  lineChart.replaceChildren();
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", points.map(({ x, y }) => `${x},${y}`).join(" "));
  lineChart.append(line);
  points.forEach(({ x, y }) => {
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.setAttribute("cx", String(x));
    dot.setAttribute("cy", String(y));
    dot.setAttribute("r", "3.2");
    lineChart.append(dot);
  });

  bars.replaceChildren();
  values.forEach((value) => {
    const bar = document.createElement("span");
    bar.style.height = `${Math.max(12, value * 0.83)}%`;
    bars.append(bar);
  });

  months.replaceChildren();
  labels.forEach((label) => {
    const tick = document.createElement("span");
    tick.textContent = label;
    months.append(tick);
  });
}

document.querySelectorAll(".period-tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector(".period-tabs .selected")?.classList.remove("selected");
    button.classList.add("selected");
    renderChart(button.dataset.period);
  });
});

document.getElementById("search-input").addEventListener("input", (event) => {
  const query = event.target.value.trim().toLowerCase();
  const rows = [...document.querySelectorAll("#credits-body tr:not(.no-results)")];
  let visibleRows = 0;
  rows.forEach((row) => {
    const matches = row.textContent.toLowerCase().includes(query);
    row.hidden = !matches;
    if (matches) visibleRows += 1;
  });
  document.querySelector("#credits-body .no-results").hidden = visibleRows !== 0;

  document.querySelectorAll(".transaction-item").forEach((item) => {
    item.hidden = query !== "" && !item.textContent.toLowerCase().includes(query);
  });
});

document.querySelector(".view-all-button").addEventListener("click", () => {
  document.querySelectorAll("#credits-body tr:not(.no-results)").forEach((row) => {
    row.hidden = false;
  });
  document.getElementById("search-input").value = "";
  document.querySelector("#credits-body .no-results").hidden = true;
  document.querySelectorAll(".transaction-item").forEach((item) => {
    item.hidden = false;
  });
});

renderChart("6M");
