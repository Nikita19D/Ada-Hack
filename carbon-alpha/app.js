(() => {
    "use strict";

    const TARGET = 100000;
    const SIMULATION_COUNT = 5000;
    const SVG_NS = "http://www.w3.org/2000/svg";
    const PALETTE = ["#315c49", "#758d72", "#b48743", "#9a725f", "#536d7a", "#9b9b70", "#765f79", "#af866b"];
    const runButton = document.getElementById("run-risk-test");
    const stressButton = document.getElementById("break-portfolio");
    const selectionMessage = document.getElementById("risk-selection-message");
    const runMessage = document.getElementById("risk-run-message");
    const errorMessage = document.getElementById("risk-error");
    const integrationNote = document.getElementById("risk-integration-note");
    const chartSection = document.getElementById("risk-chart-section");
    const stressSection = document.getElementById("stress-section");
    const stressResults = document.getElementById("stress-results");

    let selectedProjects = [];
    let portfolioSignature = "[]";
    let portfolioRevision = 0;
    let integration = null;
    let riskRequestRunning = false;
    let stressRequestRunning = false;
    let hasSimulation = false;

    function projectColor(index) {
        if (index < PALETTE.length) {
            return PALETTE[index];
        }
        const hue = (index * 137.508) % 360;
        const lightness = index % 2 === 0 ? 41 : 51;
        return `hsl(${hue.toFixed(1)} 24% ${lightness}%)`;
    }

    function formatNumber(value, digits = 0) {
        return Number(value).toLocaleString(undefined, {
            maximumFractionDigits: digits,
            minimumFractionDigits: digits,
        });
    }

    function createSvgElement(name, attributes = {}) {
        const element = document.createElementNS(SVG_NS, name);
        for (const [key, value] of Object.entries(attributes)) {
            element.setAttribute(key, String(value));
        }
        return element;
    }

    function setSvgText(svg, text, attributes = {}) {
        const node = createSvgElement("text", attributes);
        node.textContent = text;
        svg.append(node);
        return node;
    }

    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.hidden = false;
    }

    function clearError() {
        errorMessage.textContent = "";
        errorMessage.hidden = true;
    }

    function validateProjects(projects) {
        if (!Array.isArray(projects) || projects.length === 0) {
            throw new Error("No projects selected. Choose projects before running a risk test.");
        }
        for (const project of projects) {
            if (
                !project ||
                project.id === undefined ||
                typeof project.project_name !== "string" ||
                !project.project_name.trim() ||
                typeof project.co2 !== "number" ||
                !Number.isFinite(project.co2) ||
                project.co2 < 0 ||
                typeof project.failure_probability !== "number" ||
                !Number.isFinite(project.failure_probability) ||
                project.failure_probability < 0 ||
                project.failure_probability > 1
            ) {
                throw new Error("A project has invalid risk data and cannot be simulated.");
            }
        }
    }

    function projectSignature(projects) {
        try {
            return JSON.stringify(projects);
        } catch {
            return `unserializable-${Date.now()}-${Math.random()}`;
        }
    }

    function totalPurchasedCredits(projects) {
        if (projects.some((project) =>
            typeof project.co2 !== "number" || !Number.isFinite(project.co2) || project.co2 < 0
        )) {
            return null;
        }
        return projects.reduce((total, project) => total + project.co2, 0);
    }

    function updateOverview() {
        document.getElementById("overview-project-count").textContent =
            formatNumber(selectedProjects.length);

        const purchased = totalPurchasedCredits(selectedProjects);
        document.getElementById("overview-purchased-credits").textContent =
            purchased === null ? "—" : `${formatNumber(purchased)} tCO2e`;

        const hasPrices = selectedProjects.length > 0 && selectedProjects.every((project) =>
            typeof project.price_per_credit === "number" &&
            Number.isFinite(project.price_per_credit) &&
            project.price_per_credit >= 0
        );
        const currencyCodes = new Set(selectedProjects.map((project) => project.currency));
        const currency = currencyCodes.size === 1 ? [...currencyCodes][0] : null;
        const costElement = document.getElementById("overview-total-cost");
        if (purchased !== null && hasPrices) {
            const totalCost = selectedProjects.reduce(
                (total, project) => total + project.co2 * project.price_per_credit,
                0,
            );
            costElement.textContent = currency && /^[A-Z]{3}$/.test(currency)
                ? new Intl.NumberFormat(undefined, {
                    style: "currency",
                    currency,
                    maximumFractionDigits: 2,
                }).format(totalCost)
                : `${formatNumber(totalCost, 2)} (currency not specified)`;
        } else {
            costElement.textContent = "—";
        }
    }

    function renderAllocation() {
        const empty = document.getElementById("allocation-empty");
        const zero = document.getElementById("allocation-zero");
        const content = document.getElementById("allocation-content");
        const donut = document.getElementById("allocation-donut");
        const legend = document.getElementById("allocation-legend");

        donut.replaceChildren();
        legend.replaceChildren();
        empty.hidden = selectedProjects.length > 0;
        zero.hidden = true;
        content.hidden = true;

        if (selectedProjects.length === 0) {
            return;
        }
        const total = totalPurchasedCredits(selectedProjects);
        if (total === null) {
            return;
        }
        if (total === 0) {
            zero.hidden = false;
            return;
        }

        const size = 210;
        const center = size / 2;
        const radius = 78;
        const strokeWidth = 28;
        let angle = -Math.PI / 2;
        const svg = createSvgElement("svg", {
            viewBox: `0 0 ${size} ${size}`,
            role: "img",
            "aria-label": `Purchased-credit allocation across ${selectedProjects.length} selected projects.`,
        });
        const title = createSvgElement("title");
        title.textContent = "Portfolio allocation by project";
        svg.append(title);

        selectedProjects.forEach((project, index) => {
            const share = project.co2 / total;
            const nextAngle = angle + share * Math.PI * 2;
            const startX = center + radius * Math.cos(angle);
            const startY = center + radius * Math.sin(angle);
            const endX = center + radius * Math.cos(nextAngle);
            const endY = center + radius * Math.sin(nextAngle);
            const largeArc = nextAngle - angle > Math.PI ? 1 : 0;
            if (share > 0) {
                const sector = share === 1
                    ? createSvgElement("circle", {
                        cx: center,
                        cy: center,
                        r: radius,
                        fill: "none",
                        stroke: projectColor(index),
                        "stroke-width": strokeWidth,
                    })
                    : createSvgElement("path", {
                        d: `M ${startX} ${startY} A ${radius} ${radius} 0 ${largeArc} 1 ${endX} ${endY}`,
                        fill: "none",
                        stroke: projectColor(index),
                        "stroke-width": strokeWidth,
                        "stroke-linecap": "butt",
                    });
                const hover = createSvgElement("title");
                hover.textContent = `${project.project_name}: ${formatNumber(project.co2)} tCO2e (${formatNumber(share * 100, 1)}%)`;
                sector.append(hover);
                svg.append(sector);
            }
            angle = nextAngle;

            const item = document.createElement("li");
            const swatch = document.createElement("span");
            swatch.className = "legend-swatch";
            swatch.style.backgroundColor = projectColor(index);
            swatch.setAttribute("aria-hidden", "true");
            const name = document.createElement("span");
            name.className = "legend-name";
            name.textContent = project.project_name;
            const value = document.createElement("span");
            value.className = "legend-value";
            value.textContent = `${formatNumber(project.co2)} tCO2e · ${formatNumber(share * 100, 1)}%`;
            item.append(swatch, name, value);
            legend.append(item);
        });

        const innerLabel = createSvgElement("text", {
            x: center,
            y: center - 3,
            "text-anchor": "middle",
            fill: "#26352c",
            "font-size": 13,
            "font-weight": 650,
        });
        innerLabel.textContent = formatNumber(total);
        svg.append(innerLabel);
        setSvgText(svg, "tCO2e", {
            x: center,
            y: center + 15,
            "text-anchor": "middle",
            fill: "#68716a",
            "font-size": 10,
        });
        donut.append(svg);
        content.hidden = false;
    }

    function setMetricValues(result) {
        document.getElementById("target-success").textContent = result
            ? `${(result.success_probability * 100).toFixed(1)}%`
            : "—";
        document.getElementById("expected-delivery").textContent = result
            ? `${formatNumber(result.expected_co2)} tCO2e`
            : "—";
        document.getElementById("shortfall-risk").textContent = result
            ? `${(result.shortfall_probability * 100).toFixed(1)}%`
            : "—";
    }

    function renderHistogram(values, target) {
        const container = document.getElementById("risk-histogram");
        container.replaceChildren();
        if (
            !Array.isArray(values) ||
            values.length === 0 ||
            values.some((value) => typeof value !== "number" || !Number.isFinite(value))
        ) {
            throw new Error("Unable to calculate risk. Check the selected project data.");
        }

        const width = 760;
        const height = 300;
        const margin = { top: 24, right: 27, bottom: 57, left: 66 };
        const plotWidth = width - margin.left - margin.right;
        const plotHeight = height - margin.top - margin.bottom;
        let minValue = Math.min(...values, target);
        let maxValue = Math.max(...values, target);
        if (minValue === maxValue) {
            minValue -= 1;
            maxValue += 1;
        }
        const padding = (maxValue - minValue) * 0.04;
        minValue = Math.max(0, minValue - padding);
        maxValue += padding;
        const binCount = Math.min(30, Math.max(5, Math.ceil(Math.sqrt(values.length))));
        const binWidth = (maxValue - minValue) / binCount;
        const bins = Array(binCount).fill(0);
        values.forEach((value) => {
            const index = Math.min(
                binCount - 1,
                Math.floor((value - minValue) / binWidth),
            );
            bins[index] += 1;
        });

        const maxFrequency = Math.max(...bins, 1);
        const x = (value) => margin.left + ((value - minValue) / (maxValue - minValue)) * plotWidth;
        const y = (frequency) => margin.top + plotHeight - (frequency / maxFrequency) * plotHeight;
        const svg = createSvgElement("svg", {
            viewBox: `0 0 ${width} ${height}`,
            role: "img",
            "aria-label": `Histogram of ${values.length.toLocaleString()} simulated deliveries. Each bar reports a delivery range and number of simulations; the ${formatNumber(target)} tCO2e target is marked.`,
        });
        const title = createSvgElement("title");
        title.textContent = "Simulated delivery distribution";
        svg.append(title);

        for (let tick = 0; tick <= 4; tick += 1) {
            const frequency = maxFrequency * tick / 4;
            const tickY = y(frequency);
            svg.append(createSvgElement("line", {
                x1: margin.left,
                y1: tickY,
                x2: width - margin.right,
                y2: tickY,
                stroke: "#e8e8e1",
            }));
            setSvgText(svg, formatNumber(Math.round(frequency)), {
                x: margin.left - 9,
                y: tickY + 4,
                "text-anchor": "end",
                fill: "#68716a",
                "font-size": 11,
            });
        }

        const barWidth = plotWidth / binCount;
        bins.forEach((frequency, index) => {
            const lower = minValue + index * binWidth;
            const upper = lower + binWidth;
            const barHeight = (frequency / maxFrequency) * plotHeight;
            const rect = createSvgElement("rect", {
                x: margin.left + index * barWidth + 1,
                y: margin.top + plotHeight - barHeight,
                width: Math.max(1, barWidth - 2),
                height: barHeight,
                fill: "#65836d",
            });
            const tooltip = createSvgElement("title");
            tooltip.textContent = `${formatNumber(lower)}–${formatNumber(upper)} tCO2e · ${formatNumber(frequency)} simulations`;
            rect.append(tooltip);
            svg.append(rect);
        });

        const targetX = x(target);
        svg.append(createSvgElement("line", {
            x1: targetX,
            y1: margin.top,
            x2: targetX,
            y2: margin.top + plotHeight,
            stroke: "#a66b16",
            "stroke-width": 2,
            "stroke-dasharray": "5 4",
        }));
        setSvgText(svg, "Target 100,000", {
            x: Math.min(targetX + 5, width - margin.right - 80),
            y: margin.top + 13,
            fill: "#815411",
            "font-size": 11,
            "font-weight": 600,
        });

        for (let tick = 0; tick <= 4; tick += 1) {
            const tickValue = minValue + (maxValue - minValue) * tick / 4;
            const tickX = x(tickValue);
            setSvgText(svg, formatNumber(Math.round(tickValue)), {
                x: tickX,
                y: margin.top + plotHeight + 18,
                "text-anchor": tick === 0 ? "start" : tick === 4 ? "end" : "middle",
                fill: "#68716a",
                "font-size": 10,
            });
        }

        svg.append(createSvgElement("line", {
            x1: margin.left,
            y1: margin.top + plotHeight,
            x2: width - margin.right,
            y2: margin.top + plotHeight,
            stroke: "#7a827b",
        }));
        svg.append(createSvgElement("line", {
            x1: margin.left,
            y1: margin.top,
            x2: margin.left,
            y2: margin.top + plotHeight,
            stroke: "#7a827b",
        }));
        setSvgText(svg, "Delivered tCO2e", {
            x: margin.left + plotWidth / 2,
            y: height - 7,
            "text-anchor": "middle",
            fill: "#465149",
            "font-size": 12,
        });
        const yLabel = setSvgText(svg, "Number of simulations", {
            x: 16,
            y: margin.top + plotHeight / 2,
            "text-anchor": "middle",
            fill: "#465149",
            "font-size": 12,
        });
        yLabel.setAttribute("transform", `rotate(-90 16 ${margin.top + plotHeight / 2})`);
        container.append(svg);
    }

    function renderConfidenceCurve(values, target, successProbability) {
        const container = document.getElementById("confidence-chart");
        container.replaceChildren();
        const minimum = Math.min(0, ...values, target);
        const maximum = Math.max(...values, target);
        let low = minimum;
        let high = maximum;
        if (low === high) {
            low -= 1;
            high += 1;
        }

        const targets = new Set();
        for (let index = 0; index <= 30; index += 1) {
            targets.add(low + (high - low) * index / 30);
        }
        targets.add(target);
        const points = [...targets].sort((left, right) => left - right).map((value) => ({
            target: value,
            probability: values.filter((delivered) => delivered >= value).length / values.length,
        }));
        const exactTargetPoint = points.find((point) => point.target === target);
        if (exactTargetPoint) {
            exactTargetPoint.probability = successProbability;
        }

        const width = 760;
        const height = 255;
        const margin = { top: 20, right: 27, bottom: 48, left: 66 };
        const plotWidth = width - margin.left - margin.right;
        const plotHeight = height - margin.top - margin.bottom;
        const x = (value) => margin.left + ((value - low) / (high - low)) * plotWidth;
        const y = (probability) => margin.top + (1 - probability) * plotHeight;
        const svg = createSvgElement("svg", {
            viewBox: `0 0 ${width} ${height}`,
            role: "img",
            "aria-label": `Estimated delivery confidence from ${values.length.toLocaleString()} simulated outcomes. Chance of reaching 100,000 tCO2e is ${(successProbability * 100).toFixed(1)} percent.`,
        });
        const title = createSvgElement("title");
        title.textContent = "Chance of delivering at least each target";
        svg.append(title);

        [0, 0.25, 0.5, 0.75, 1].forEach((probability) => {
            const tickY = y(probability);
            svg.append(createSvgElement("line", {
                x1: margin.left,
                y1: tickY,
                x2: width - margin.right,
                y2: tickY,
                stroke: "#e8e8e1",
            }));
            setSvgText(svg, `${Math.round(probability * 100)}%`, {
                x: margin.left - 9,
                y: tickY + 4,
                "text-anchor": "end",
                fill: "#68716a",
                "font-size": 11,
            });
        });

        // Exact empirical step curve: no invented interpolation between outcomes.
        const frequencies = new Map();
        values.forEach(value => frequencies.set(value, (frequencies.get(value) || 0) + 1));
        let remaining = values.length;
        let path = `M ${x(low)} ${y(1)}`;
        [...frequencies.keys()].sort((a, b) => a - b).forEach(value => {
            if (value >= high) return;
            path += ` H ${x(value)}`;
            remaining -= frequencies.get(value);
            path += ` V ${y(remaining / values.length)}`;
        });
        path += ` H ${x(high)}`;
        svg.append(createSvgElement("path", {
            d: path,
            fill: "none",
            stroke: "#315c49",
            "stroke-width": 2.5,
            "stroke-linejoin": "round",
            "stroke-linecap": "round",
        }));

        const targetPoint = points.find((point) => point.target === target);
        if (targetPoint) {
            const targetX = x(target);
            svg.append(createSvgElement("line", {
                x1: targetX,
                y1: margin.top,
                x2: targetX,
                y2: margin.top + plotHeight,
                stroke: "#a66b16",
                "stroke-width": 1.5,
                "stroke-dasharray": "4 4",
            }));
            const marker = createSvgElement("circle", {
                cx: targetX,
                cy: y(targetPoint.probability),
                r: 5,
                fill: "#a66b16",
                stroke: "#fffefa",
                "stroke-width": 2,
            });
            const markerTitle = createSvgElement("title");
            markerTitle.textContent = `100,000 tCO2e target: ${(targetPoint.probability * 100).toFixed(1)}% estimated chance`;
            marker.append(markerTitle);
            svg.append(marker);
            setSvgText(svg, "100,000 target", {
                x: Math.min(targetX + 5, width - margin.right - 82),
                y: margin.top + 13,
                fill: "#815411",
                "font-size": 11,
                "font-weight": 600,
            });
        }

        [0, 0.25, 0.5, 0.75, 1].forEach((portion) => {
            const tickX = margin.left + portion * plotWidth;
            const tickTarget = low + portion * (high - low);
            setSvgText(svg, formatNumber(Math.round(tickTarget)), {
                x: tickX,
                y: margin.top + plotHeight + 18,
                "text-anchor": portion === 0 ? "start" : portion === 1 ? "end" : "middle",
                fill: "#68716a",
                "font-size": 10,
            });
        });
        svg.append(createSvgElement("line", {
            x1: margin.left,
            y1: margin.top + plotHeight,
            x2: width - margin.right,
            y2: margin.top + plotHeight,
            stroke: "#7a827b",
        }));
        svg.append(createSvgElement("line", {
            x1: margin.left,
            y1: margin.top,
            x2: margin.left,
            y2: margin.top + plotHeight,
            stroke: "#7a827b",
        }));
        setSvgText(svg, "Delivery target in tCO2e", {
            x: margin.left + plotWidth / 2,
            y: height - 7,
            "text-anchor": "middle",
            fill: "#465149",
            "font-size": 12,
        });
        const yLabel = setSvgText(svg, "Estimated chance", {
            x: 16,
            y: margin.top + plotHeight / 2,
            "text-anchor": "middle",
            fill: "#465149",
            "font-size": 12,
        });
        yLabel.setAttribute("transform", `rotate(-90 16 ${margin.top + plotHeight / 2})`);
        container.append(svg);
    }

    function renderStressChart(result) {
        const stressById = new Map(result.projects.map((project) => [String(project.id), project]));
        if (
            stressById.size !== selectedProjects.length ||
            selectedProjects.some((project) => !stressById.has(String(project.id)))
        ) {
            throw new Error("Unable to calculate risk. Check the selected project data.");
        }

        const chartContainer = document.createElement("div");
        chartContainer.className = "stress-chart";
        chartContainer.setAttribute("role", "img");
        chartContainer.setAttribute(
            "aria-label",
            "Horizontal comparison of purchased credits and delivered credits for each project in this stress scenario.",
        );
        const width = 760;
        const rowHeight = 58;
        const top = 24;
        const left = 180;
        const right = 70;
        const barWidth = width - left - right;
        const height = top + selectedProjects.length * rowHeight + 38;
        const maximum = Math.max(
            1,
            ...selectedProjects.map((project) => project.co2),
            ...result.projects.map((project) => project.delivered_co2),
        );
        const scale = barWidth / maximum;
        const svg = createSvgElement("svg", {
            viewBox: `0 0 ${width} ${height}`,
            role: "img",
            "aria-label": chartContainer.getAttribute("aria-label"),
        });
        const title = createSvgElement("title");
        title.textContent = "Purchased and delivered credits by project";
        svg.append(title);

        selectedProjects.forEach((project, index) => {
            const scenario = stressById.get(String(project.id));
            if (
                typeof scenario.delivered_co2 !== "number" ||
                !Number.isFinite(scenario.delivered_co2) ||
                scenario.delivered_co2 < 0 ||
                scenario.delivered_co2 > project.co2
            ) {
                throw new Error("Unable to calculate risk. Check the selected project data.");
            }
            const rowTop = top + index * rowHeight;
            const shortName = project.project_name.length > 26 ? project.project_name.slice(0, 25) + "…" : project.project_name;
            const nameLabel = setSvgText(svg, shortName, {
                x: left - 12,
                y: rowTop + 19,
                "text-anchor": "end",
                fill: "#465149",
                "font-size": 11,
            });
            const nameTitle = createSvgElement("title");
            nameTitle.textContent = project.project_name;
            nameLabel.append(nameTitle);

            [
                { label: "Purchased", value: project.co2, y: rowTop + 4, color: "#b7c7b6" },
                { label: "Delivered", value: scenario.delivered_co2, y: rowTop + 27, color: "#315c49" },
            ].forEach((bar) => {
                setSvgText(svg, bar.label, {
                    x: left,
                    y: bar.y + 10,
                    fill: "#68716a",
                    "font-size": 9,
                });
                const rect = createSvgElement("rect", {
                    x: left + 57,
                    y: bar.y,
                    width: Math.max(0, (barWidth - 57) * bar.value / maximum),
                    height: 13,
                    fill: bar.color,
                });
                const tooltip = createSvgElement("title");
                tooltip.textContent = `${project.project_name}: ${bar.label.toLowerCase()} ${formatNumber(bar.value)} tCO2e`;
                rect.append(tooltip);
                svg.append(rect);
                setSvgText(svg, formatNumber(bar.value), {
                    x: Math.min(left + 62 + (barWidth - 57) * bar.value / maximum, width - right),
                    y: bar.y + 11,
                    fill: "#465149",
                    "font-size": 9,
                });
            });
        });

        chartContainer.append(svg);
        return chartContainer;
    }

    function renderStressResult(result) {
        if (
            !result ||
            !Array.isArray(result.projects) ||
            typeof result.total_delivered !== "number" ||
            !Number.isFinite(result.total_delivered) ||
            typeof result.target_reached !== "boolean" ||
            result.projects.some((project) =>
                !project ||
                project.id === undefined ||
                typeof project.project_name !== "string" ||
                typeof project.survived !== "boolean" ||
                typeof project.delivered_co2 !== "number" ||
                !Number.isFinite(project.delivered_co2)
            )
        ) {
            throw new Error("Unable to calculate risk. Check the selected project data.");
        }

        const table = document.createElement("table");
        const head = document.createElement("thead");
        const headerRow = document.createElement("tr");
        ["Project", "Outcome", "Delivered tCO2e"].forEach((label) => {
            const header = document.createElement("th");
            header.textContent = label;
            headerRow.append(header);
        });
        head.append(headerRow);
        table.append(head);

        const body = document.createElement("tbody");
        result.projects.forEach((project) => {
            const row = document.createElement("tr");
            const projectName = document.createElement("td");
            const status = document.createElement("td");
            const delivered = document.createElement("td");
            projectName.textContent = project.project_name;
            status.textContent = project.survived ? "Survived" :
                project.delivered_co2 > 0 ? "Failed · half recovered" : "Failed";
            delivered.textContent = `${formatNumber(project.delivered_co2)} tCO2e`;
            row.append(projectName, status, delivered);
            body.append(row);
        });
        table.append(body);

        const message = document.createElement("p");
        message.className = "stress-message";
        message.textContent = result.target_reached
            ? "Target reached in this scenario."
            : `Target missed in this scenario by ${formatNumber(Math.max(0, TARGET - result.total_delivered))} tCO2e.`;

        stressResults.replaceChildren(
            renderStressChart(result),
            table,
            message,
        );
        stressResults.classList.add("stress-results");
        stressResults.hidden = false;
    }

    function updateButtonStates() {
        const busy = riskRequestRunning || stressRequestRunning;
        runButton.disabled = selectedProjects.length === 0 || busy || !budgetIsValid();
        stressButton.disabled = busy || !budgetIsValid();
        if (riskRequestRunning) {
            runMessage.textContent = "Testing 5,000 scenarios…";
            runMessage.hidden = false;
        } else if (!hasSimulation && selectedProjects.length > 0) {
            runMessage.textContent = "Run risk test.";
            runMessage.hidden = false;
        } else {
            runMessage.hidden = true;
        }
    }

    function clearSimulationResults() {
        hasSimulation = false;
        setMetricValues(null);
        document.getElementById("risk-histogram").replaceChildren();
        document.getElementById("confidence-chart").replaceChildren();
        chartSection.hidden = true;
        stressSection.hidden = true;
        stressResults.replaceChildren();
        stressResults.hidden = true;
    }

    function setSelectedProjects(projects) {
        const nextProjects = Array.isArray(projects)
            ? projects.map((project) => project && typeof project === "object" ? { ...project } : project)
            : [];
        const nextSignature = projectSignature(nextProjects);
        if (nextSignature !== portfolioSignature) {
            portfolioSignature = nextSignature;
            portfolioRevision += 1;
            selectedProjects = nextProjects;
            clearSimulationResults();
            clearError();
        } else {
            selectedProjects = nextProjects;
        }
        updateOverview();
        renderAllocation();
        renderPickedProjects();

        const hasProjects = selectedProjects.length > 0;
        selectionMessage.hidden = hasProjects;
        selectionMessage.textContent = hasProjects
            ? ""
            : "Select projects to calculate portfolio risk.";
        updateButtonStates();
    }

    function validateSimulationResult(result) {
        if (
            !result ||
            !Array.isArray(result.simulation_results) ||
            result.simulation_results.length === 0 ||
            result.simulation_results.some((value) =>
                typeof value !== "number" || !Number.isFinite(value) || value < 0
            ) ||
            typeof result.success_probability !== "number" ||
            !Number.isFinite(result.success_probability) ||
            result.success_probability < 0 ||
            result.success_probability > 1 ||
            typeof result.shortfall_probability !== "number" ||
            !Number.isFinite(result.shortfall_probability) ||
            result.shortfall_probability < 0 ||
            result.shortfall_probability > 1 ||
            typeof result.expected_co2 !== "number" ||
            !Number.isFinite(result.expected_co2) ||
            result.target !== TARGET
        ) {
            throw new Error("Unable to calculate risk. Check the selected project data.");
        }
    }

    async function runRiskTest() {
        if (riskRequestRunning || stressRequestRunning) {
            return;
        }
        let requestedRevision = portfolioRevision;
        clearError();
        try {
            validateProjects(selectedProjects);
            if (!integration || typeof integration.simulatePortfolio !== "function") {
                showError("Unable to calculate risk. Check the selected project data. Risk API integration is not connected.");
                return;
            }

            riskRequestRunning = true;
            requestedRevision = portfolioRevision;
            const requestProjects = selectedProjects.map((project) => ({ ...project }));
            updateButtonStates();
            const result = await integration.simulatePortfolio(
                requestProjects,
                SIMULATION_COUNT,
                TARGET,
            );
            if (requestedRevision !== portfolioRevision) {
                return;
            }

            validateSimulationResult(result);
            const actualSuccessProbability =
                result.simulation_results.filter((delivery) => delivery >= TARGET).length /
                result.simulation_results.length;
            setMetricValues({
                ...result,
                success_probability: actualSuccessProbability,
                shortfall_probability: 1 - actualSuccessProbability,
            });
            renderHistogram(result.simulation_results, TARGET);
            renderConfidenceCurve(
                result.simulation_results,
                TARGET,
                actualSuccessProbability,
            );
            hasSimulation = true;
            chartSection.hidden = false;
            stressSection.hidden = false;
            integrationNote.hidden = Boolean(
                integration &&
                typeof integration.simulatePortfolio === "function" &&
                typeof integration.stressOnce === "function"
            );
        } catch (error) {
            if (requestedRevision === portfolioRevision) {
                if (error instanceof Error) {
                    showError(error.message || "Unable to calculate risk. Check the selected project data.");
                } else {
                    showError("Unable to calculate risk. Check the selected project data.");
                }
            }
        } finally {
            riskRequestRunning = false;
            updateButtonStates();
        }
    }

    async function runStressTest() {
        if (riskRequestRunning || stressRequestRunning) {
            return;
        }
        let requestedRevision = portfolioRevision;
        clearError();
        try {
            validateProjects(selectedProjects);
            if (!integration || typeof integration.stressOnce !== "function") {
                showError("Unable to calculate risk. Check the selected project data. Stress-test API integration is not connected.");
                return;
            }

            stressRequestRunning = true;
            requestedRevision = portfolioRevision;
            const requestProjects = selectedProjects.map((project) => ({ ...project }));
            updateButtonStates();
            const result = await integration.stressOnce(requestProjects, TARGET);
            if (requestedRevision !== portfolioRevision) {
                return;
            }
            renderStressResult(result);
        } catch (error) {
            if (requestedRevision === portfolioRevision) {
                if (error instanceof Error) {
                    showError(error.message || "Unable to calculate risk. Check the selected project data.");
                } else {
                    showError("Unable to calculate risk. Check the selected project data.");
                }
            }
        } finally {
            stressRequestRunning = false;
            updateButtonStates();
        }
    }

    runButton.addEventListener("click", runRiskTest);
    stressButton.addEventListener("click", runStressTest);

    window.CarbonShieldPortfolioRisk = {
        setSelectedProjects,
        connect: (callbacks) => {
            integration = callbacks;
            integrationNote.hidden = Boolean(
                integration &&
                typeof integration.simulatePortfolio === "function" &&
                typeof integration.stressOnce === "function"
            );
        },
        renderStressResult,
    };

    // Same-origin bridge: main.py serves this page and both calculation endpoints.
    let catalogueProjects = [];
    const picker = document.getElementById("project-picker");
    const budgetInput = document.getElementById("portfolio-budget");
    const builderMessage = document.getElementById("builder-message");
    const money = (value) => new Intl.NumberFormat("en-US", {
        style: "currency", currency: "USD", maximumFractionDigits: 2,
    }).format(value);
    const portfolioCost = () => selectedProjects.reduce((sum, p) => sum + p.co2 * p.price_per_credit, 0);

    function budgetIsValid() {
        if (!budgetInput) return true; // Preserve the existing hook for other pages.
        const budget = Number(budgetInput.value);
        return Number.isFinite(budget) && budget > 0 && budget <= 1000000 &&
            portfolioCost() <= budget + 1e-7;
    }

    function renderPickedProjects() {
        const body = document.getElementById("selected-projects-body");
        if (!body) return;
        body.replaceChildren();
        selectedProjects.forEach((project) => {
            const row = document.createElement("tr");
            const name = document.createElement("td");
            name.textContent = project.project_name;
            const country = document.createElement("small");
            country.textContent = project.country || "Country not provided";
            name.append(country);
            row.append(name);
            [project.risk_rating || "Not provided", formatNumber(project.co2),
                Number.isFinite(project.price_per_credit) ? money(project.co2 * project.price_per_credit) : "—"
            ].forEach((value) => {
                const cell = document.createElement("td");
                cell.textContent = value;
                row.append(cell);
            });
            const action = document.createElement("td");
            const remove = document.createElement("button");
            remove.className = "secondary-button";
            remove.textContent = "Remove";
            remove.setAttribute("aria-label", `Remove ${project.project_name}`);
            remove.addEventListener("click", () => setSelectedProjects(selectedProjects.filter(p => p.id !== project.id)));
            action.append(remove);
            row.append(action);
            body.append(row);
        });
        document.getElementById("selected-projects-wrap").hidden = selectedProjects.length === 0;
        document.getElementById("clear-portfolio").disabled = selectedProjects.length === 0;
        if (!budgetIsValid()) {
            builderMessage.textContent = "Use a budget above $0 and at most $1,000,000. Your portfolio must fit within it.";
        } else if (selectedProjects.length) {
            const nominal = selectedProjects.reduce((sum, p) => sum + p.co2, 0);
            builderMessage.textContent = `${money(Number(budgetInput.value) - portfolioCost())} budget remaining. ` +
                (nominal < TARGET ? "Not enough credits yet: even full delivery misses the target." :
                 nominal === TARGET ? "Exactly at target: any lost credits could cause a shortfall." :
                 "Ready to test. Extra credits provide a cushion against failures.");
        } else {
            builderMessage.textContent = "Add projects, then run 5,000 possible futures below.";
        }
    }

    function updateProjectDetails() {
        const project = catalogueProjects.find(p => p.id === picker.value);
        const details = document.getElementById("project-details");
        const add = document.getElementById("add-project");
        add.disabled = !project;
        if (!project) {
            details.textContent = "No matching project. Try a different search.";
            return;
        }
        details.textContent = `${money(project.price_per_credit)} per credit · ${formatNumber(project.available_tonnes)} available · ` +
            `${project.risk_rating} rating · ${(project.failure_probability * 100).toFixed(1)}% model failure chance · ` +
            (project.has_buffer_pool ? "Half recovered if it fails" : "No buffer protection");
        document.getElementById("project-quantity").max = project.available_tonnes;
    }

    function filterProjects() {
        const query = document.getElementById("project-search").value.trim().toLowerCase();
        const previous = picker.value;
        const matching = catalogueProjects.filter(p => p.available_tonnes > 0 &&
            `${p.id} ${p.project_name} ${p.country} ${p.project_type}`.toLowerCase().includes(query));
        picker.replaceChildren();
        matching.forEach(p => {
            const option = document.createElement("option");
            option.value = p.id;
            option.textContent = `${p.project_name} · ${p.country} · ${p.id}`;
            picker.append(option);
        });
        if (matching.some(p => p.id === previous)) picker.value = previous;
        updateProjectDetails();
    }

    async function apiRequest(path, payload) {
        const response = await fetch(path, payload ? {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        } : {});
        let result;
        try { result = await response.json(); }
        catch { throw new Error("Calculation service not found. Run python main.py and open http://127.0.0.1:8000."); }
        if (!response.ok) {
            throw new Error(typeof result.detail === "string" ? result.detail : "Check project quantities and budget, then try again.");
        }
        return result;
    }

    function requestPayload(projects, target, simulations = SIMULATION_COUNT) {
        if (!budgetIsValid()) throw new Error("Your selected projects exceed your budget, or the budget is invalid.");
        return { projects: projects.map(p => ({ id: String(p.id), co2: p.co2 })),
            budget: Number(budgetInput.value), target, n_simulations: simulations };
    }

    async function connectChallengeData() {
        try {
            const data = await apiRequest("/api/projects");
            if (!Array.isArray(data.projects) || !data.projects.length) throw new Error("No projects found in the challenge workbook.");
            catalogueProjects = data.projects;
            document.getElementById("catalogue-status").textContent =
                `${formatNumber(catalogueProjects.length)} projects loaded from the supplied challenge sheet. Prices and risk ratings are synthetic challenge inputs.`;
            ["project-search", "project-picker", "project-quantity", "example-portfolio"].forEach(id => {
                document.getElementById(id).disabled = false;
            });
            filterProjects();
            window.CarbonShieldPortfolioRisk.connect({
                simulatePortfolio: (projects, count, target) => apiRequest("/api/risk", requestPayload(projects, target, count)),
                stressOnce: (projects, target) => apiRequest("/api/stress", requestPayload(projects, target)),
            });
        } catch (error) {
            document.getElementById("catalogue-status").textContent = "Projects could not be loaded.";
            integrationNote.hidden = false;
            showError(error.message || "Cannot connect to the calculation service. Start python main.py.");
        }
    }

    document.getElementById("project-search").addEventListener("input", filterProjects);
    picker.addEventListener("change", updateProjectDetails);
    document.getElementById("add-project").addEventListener("click", () => {
        const project = catalogueProjects.find(p => p.id === picker.value);
        const quantity = Number(document.getElementById("project-quantity").value);
        const previous = selectedProjects.find(p => p.id === project?.id);
        const combined = quantity + (previous?.co2 || 0);
        if (!project || !Number.isFinite(quantity) || quantity <= 0) {
            showError("Choose a project and enter a quantity above zero."); return;
        }
        if (combined > project.available_tonnes) {
            showError(`Only ${formatNumber(project.available_tonnes)} credits are available for this project, including any already selected.`); return;
        }
        if (!previous && selectedProjects.length >= 100) { showError("Use at most 100 projects per portfolio."); return; }
        const nextCost = portfolioCost() + quantity * project.price_per_credit;
        if (!budgetIsValid() || nextCost > Number(budgetInput.value) + 1e-7) {
            showError("This purchase exceeds your budget. Reduce the quantity or remove a project."); return;
        }
        setSelectedProjects([...selectedProjects.filter(p => p.id !== project.id), { ...project, co2: combined }]);
    });
    document.getElementById("clear-portfolio").addEventListener("click", () => setSelectedProjects([]));
    budgetInput.addEventListener("input", () => {
        portfolioRevision += 1;
        clearSimulationResults();
        renderPickedProjects();
        updateButtonStates();
    });
    document.getElementById("example-portfolio").addEventListener("click", () => {
        // A convenience sample from real rows, not an optimizer or invented demo dataset.
        if (!Number.isFinite(Number(budgetInput.value)) || Number(budgetInput.value) <= 0 || Number(budgetInput.value) > 1000000) {
            showError("Enter a valid budget first."); return;
        }
        const example = [];
        let cost = 0;
        for (const project of catalogueProjects) {
            if (project.available_tonnes < 50000 || example.some(p => p.country === project.country)) continue;
            const purchaseCost = project.price_per_credit * 50000;
            if (cost + purchaseCost > Number(budgetInput.value)) continue;
            example.push({ ...project, co2: 50000 });
            cost += purchaseCost;
            if (example.length === 3) break;
        }
        if (example.length !== 3) { showError("Could not fit the example within this budget. Add projects manually or increase your budget."); return; }
        setSelectedProjects(example);
        builderMessage.textContent += " Example uses three actual challenge rows; it is not an optimized portfolio.";
    });

    setSelectedProjects([]);
    connectChallengeData();
})();
