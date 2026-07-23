// Static leaderboard: reads the pre-rendered ./dashboard.json (no backend).
// Regenerate that file with build_dashboard.py whenever the results change.

const state = {
  payload: null,
  selectedMetricKey: "reasoning_score",
};

const els = {
  metricSelect: document.getElementById("metricSelect"),
  metricMeta: document.getElementById("metricMeta"),
  smallMultiples: document.getElementById("smallMultiples"),
  metricTables: document.getElementById("metricTables"),
};

const MODEL_COLORS = new Map([
  ["GPT-5.2", "#2254f4"],
  ["Claude 4.5 sonnet", "#00a28a"],
  ["Gemini 3 pro preview", "#ff8a00"],
  ["Baichuan-M3 (plus)", "#845ef7"],
  ["medgemma", "#d94878"],
  ["GLM-4.7", "#14866d"],
  ["kimi-k2.5", "#2b59c3"],
  ["Deepseek-v3.2", "#0d9488"],
  ["Qwen-Max", "#dc6b1f"],
  ["Qwen3.5-Plus", "#6d55ff"],
]);

async function loadDashboard() {
  const response = await fetch("./dashboard.json", { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`Failed to load dashboard.json: ${response.status}`);
  }
  return response.json();
}

function formatValue(value, digits = 3) {
  if (value == null || Number.isNaN(value)) return "-";
  return Number(value).toFixed(digits);
}

function displayDatasetLabel(dataset) {
  return dataset.label;
}

function displayTaskFamily(value) {
  const map = {
    oncology: "Oncology",
    acute: "Acute",
  };
  return map[value] || value;
}

function displayMetricLabel(metric) {
  return metric.label || metric.raw_label || metric.key;
}

function metricByKey(key) {
  return state.payload.metric_catalog.find((item) => item.key === key) || null;
}

function visibleMetrics() {
  return state.payload.metric_catalog.filter((metric) => metric.group !== "other");
}

function datasetMetric(dataset, metricKey) {
  return dataset.metrics.find((metric) => metric.key === metricKey) || null;
}

function buildMetricSelect() {
  const metrics = visibleMetrics();
  const options = metrics
    .map((metric) => `<option value="${metric.key}">${escapeHtml(displayMetricLabel(metric))}</option>`)
    .join("");
  els.metricSelect.innerHTML = options;

  if (!metrics.length) {
    state.selectedMetricKey = "";
    return;
  }

  if (!metrics.some((metric) => metric.key === state.selectedMetricKey)) {
    state.selectedMetricKey = metrics[0].key;
  }
  els.metricSelect.value = state.selectedMetricKey;
}

function directionNote(metric) {
  return metric.direction === "lower" ? "↓ lower is better" : "↑ higher is better";
}

function bestOf(nums, direction) {
  const clean = nums.filter((v) => v != null && !Number.isNaN(v));
  if (!clean.length) return null;
  return direction === "lower" ? Math.min(...clean) : Math.max(...clean);
}

function isBest(value, best) {
  return value != null && best != null && Math.abs(value - best) < 1e-9;
}

function renderMetricMeta() {
  const metric = metricByKey(state.selectedMetricKey);
  if (!metric) {
    els.metricMeta.innerHTML = "";
    return;
  }
  els.metricMeta.innerHTML =
    `<strong>${escapeHtml(displayMetricLabel(metric))}</strong>` +
    ` <span class="dir">${directionNote(metric)}</span>`;
}

function renderSmallMultiples() {
  const metric = metricByKey(state.selectedMetricKey);
  els.smallMultiples.innerHTML = "";
  if (!metric) return;

  state.payload.datasets.forEach((dataset) => {
    const metricEntry = datasetMetric(dataset, metric.key);
    const card = document.createElement("article");
    card.className = "dataset-card";

    const title = `
      <div class="dataset-card__head">
        <h3>${escapeHtml(displayDatasetLabel(dataset))}</h3>
        <div class="dataset-card__meta">n=${dataset.sample_size ?? "-"} · ${escapeHtml(displayTaskFamily(dataset.task_family))}</div>
      </div>
    `;

    if (!metricEntry) {
      card.innerHTML = `${title}<div class="dataset-card__empty">This metric does not apply to this dataset.</div>`;
      els.smallMultiples.append(card);
      return;
    }

    card.innerHTML = title;
    const values = state.payload.models
      .map((item) => ({ model: item.name, value: metricEntry.values[item.name] }))
      .filter((item) => item.value != null);

    // Rank so the best model is always on top (direction-aware).
    const lower = metric.direction === "lower";
    values.sort((a, b) => (lower ? a.value - b.value : b.value - a.value));
    const bestModel = values.length ? values[0].model : null;

    const width = 340;
    const margin = { top: 6, right: 46, bottom: 20, left: 124 };
    const height = Math.max(110, values.length * 22 + margin.top + margin.bottom);

    const svg = d3.select(card)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("preserveAspectRatio", "xMinYMin meet");

    const x = d3.scaleLinear()
      .domain([0, d3.max(values, (item) => item.value) || 1])
      .nice()
      .range([margin.left, width - margin.right]);

    const y = d3.scaleBand()
      .domain(values.map((item) => item.model))
      .range([margin.top, height - margin.bottom])
      .padding(0.3);

    svg.append("g")
      .attr("transform", `translate(0, ${height - margin.bottom})`)
      .call(d3.axisBottom(x).ticks(4).tickSizeOuter(0))
      .call((g) => g.selectAll("text").attr("fill", "#898781").attr("font-size", 9))
      .call((g) => g.selectAll("line,path").attr("stroke", "#e1e0d9"));

    svg.append("g")
      .attr("transform", `translate(${margin.left}, 0)`)
      .call(d3.axisLeft(y).tickSizeOuter(0))
      .call((g) => g.selectAll("text")
        .attr("fill", (d) => (d === bestModel ? "#0b0b0b" : "#52514e"))
        .attr("font-size", 11)
        .attr("font-weight", (d) => (d === bestModel ? 700 : 400)))
      .call((g) => g.selectAll("line,path").remove());

    const bars = svg.append("g")
      .selectAll("rect")
      .data(values)
      .join("rect")
      .attr("x", margin.left)
      .attr("y", (item) => y(item.model))
      .attr("height", y.bandwidth())
      .attr("rx", 4)
      .attr("ry", 4)
      .attr("width", (item) => Math.max(2, x(item.value) - margin.left))
      .attr("fill", (item) => MODEL_COLORS.get(item.model) || "#2254f4")
      .attr("opacity", (item) => (item.model === bestModel ? 1 : 0.82));
    bars.append("title").text((item) => `${item.model}: ${formatValue(item.value)}`);

    svg.append("g")
      .selectAll("text.value")
      .data(values)
      .join("text")
      .attr("class", "value")
      .attr("x", (item) => x(item.value) + 6)
      .attr("y", (item) => y(item.model) + y.bandwidth() / 2 + 3.5)
      .attr("fill", (item) => (item.model === bestModel ? "#0b0b0b" : "#52514e"))
      .attr("font-size", 10)
      .attr("font-weight", (item) => (item.model === bestModel ? 700 : 400))
      .style("font-variant-numeric", "tabular-nums")
      .text((item) => (item.model === bestModel ? `▸ ${formatValue(item.value)}` : formatValue(item.value)));

    els.smallMultiples.append(card);
  });
}

function renderTables() {
  const sections = state.payload.datasets.map((dataset) => {
    const modelNames = state.payload.models.map((item) => item.name);
    const header = modelNames.map((name) => `<th class="model-col">${escapeHtml(name)}</th>`).join("");
    const rows = dataset.metrics.map((metric) => {
      const rowValues = modelNames.map((name) => metric.values[name]);
      const best = bestOf(rowValues, metric.direction);
      const valueCells = modelNames.map((name) => {
        const value = metric.values[name];
        const best_ = isBest(value, best);
        return `<td class="num${best_ ? " is-best" : ""}"${best_ ? ' title="Best"' : ""}>${formatValue(value)}</td>`;
      }).join("");
      return `
        <tr>
          <td class="metric-name" title="${escapeHtml(directionNote(metric))}">${escapeHtml(displayMetricLabel(metric))}</td>
          ${valueCells}
        </tr>
      `;
    }).join("");

    return `
      <section class="metric-table__section">
        <h3 class="metric-table__title">${escapeHtml(displayDatasetLabel(dataset))} <span class="metric-table__n">n=${dataset.sample_size ?? "-"}</span></h3>
        <table class="metric-table">
          <thead>
            <tr>
              <th class="metric-col">Metric</th>
              ${header}
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </section>
    `;
  }).join("");

  els.metricTables.innerHTML = sections;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderAll() {
  renderMetricMeta();
  renderSmallMultiples();
  renderTables();
}

function bindEvents() {
  els.metricSelect.addEventListener("change", () => {
    state.selectedMetricKey = els.metricSelect.value;
    renderMetricMeta();
    renderSmallMultiples();
  });
}

async function init() {
  try {
    state.payload = await loadDashboard();
    buildMetricSelect();
    bindEvents();
    renderAll();
  } catch (error) {
    els.metricMeta.textContent = error.message || "Failed to load the results page.";
  }
}

init();
