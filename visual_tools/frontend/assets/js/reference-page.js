import { fetchJson } from "./api.js";
import {
  ForceGraphRenderer,
  createAsyncAction,
  createStatusSetter,
  createOption,
  escapeHtml,
  setupColumnResize,
  setupVerticalResize,
} from "./viewer-common.js";

const state = {
  referenceId: null,
  graph: null,
  guidanceItems: [],
  selectedRuleId: null,
};

const els = {
  referenceSelect: document.getElementById("referenceSelect"),
  openButton: document.getElementById("openButton"),
  fileChip: document.getElementById("fileChip"),
  loadDot: document.getElementById("loadDot"),
  loadText: document.getElementById("loadText"),
  btnResetGraph: document.getElementById("btnResetGraph"),
  btnExportGraph: document.getElementById("btnExportGraph"),
  rulesBox: document.getElementById("rulesBox"),
  guidanceMeta: document.getElementById("guidanceMeta"),
  guidanceBox: document.getElementById("guidanceBox"),
  nodeInfoCard: document.getElementById("nodeInfoCard"),
};

let activeNodeId = null;
const setStatus = createStatusSetter(els.loadDot, els.loadText);
const handleAsync = (fn) => createAsyncAction(fn, {
  onError: () => setStatus("bad", "Error"),
});

function formatNodeKeyLabel(value) {
  return String(value || "").replaceAll("_", " ");
}

function createReferenceGraphExportCss() {
  return `
    svg {
      background: #ffffff;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .link {
      stroke: #94a3b8;
      stroke-width: 1.4px;
      fill: none;
      opacity: 0.72;
    }
    .link.active {
      stroke: #2f6fed;
      stroke-width: 2.4px;
      opacity: 1;
    }
    .link.dim {
      opacity: 0.14;
    }
    .node-circle {
      fill: #ffffff;
      stroke: #0f172a;
      stroke-width: 1.4px;
    }
    .node-circle.target {
      stroke: #0ea5e9;
      stroke-width: 2px;
      fill: #e0f2fe;
    }
    .node-circle.active {
      stroke: #2f6fed;
      stroke-width: 2.8px;
      fill: #eef4ff;
    }
    .node-circle.matched {
      stroke: #1b9b61;
      stroke-width: 2.2px;
      fill: #e9fbf2;
    }
    .node-circle.target.matched {
      stroke: #1b9b61;
      fill: #dcfce7;
    }
    .node-circle.dim,
    .node-label.dim {
      opacity: 0.22;
    }
    .node-label {
      font-size: 12px;
      text-anchor: middle;
      fill: #0f172a;
      pointer-events: none;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
    .node-label tspan.key {
      font-size: 12px;
      fill: #6b7280;
    }
    .node-label tspan.value {
      font-size: 11px;
      fill: #4b5563;
    }
  `;
}

function downloadBlob(filename, blob) {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

function exportCurrentGraphSvg() {
  const svgEl = document.getElementById("graphSvg");
  if (!svgEl || !state.graph?.nodes?.length) {
    throw new Error("There is no graph to export.");
  }

  const clone = svgEl.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");

  const wrapRect = document.getElementById("graphWrap")?.getBoundingClientRect();
  const width = Math.max(1, Math.round(wrapRect?.width || svgEl.clientWidth || 1200));
  const height = Math.max(1, Math.round(wrapRect?.height || svgEl.clientHeight || 800));
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));

  const defs = clone.querySelector("defs") || clone.insertBefore(document.createElementNS("http://www.w3.org/2000/svg", "defs"), clone.firstChild);
  const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = createReferenceGraphExportCss();
  defs.append(style);

  const serializer = new XMLSerializer();
  const source = `<?xml version="1.0" encoding="UTF-8"?>\n${serializer.serializeToString(clone)}`;
  const safeReferenceId = (state.referenceId || "reference").replaceAll(/[^a-zA-Z0-9_-]+/g, "_");
  downloadBlob(`${safeReferenceId}_graph.svg`, new Blob([source], { type: "image/svg+xml;charset=utf-8" }));
}

function estimateLabelUnits(value) {
  return [...String(value || "")].reduce((sum, char) => {
    if (char === " ") return sum + 0.45;
    if (/[\u4e00-\u9fff]/.test(char)) return sum + 1.7;
    return sum + 0.95;
  }, 0);
}

function computeReferenceNodeMetrics(node) {
  const keyLabel = formatNodeKeyLabel(node.key);
  const valueLabel = `(${node.valuePreview})`;
  const maxUnits = Math.max(estimateLabelUnits(keyLabel), estimateLabelUnits(valueLabel));
  const rx = Math.max(62, Math.min(132, 26 + maxUnits * 4.6));
  const ry = 42;
  return {
    rx,
    ry,
    collisionRadius: Math.max(rx, ry) + 12,
  };
}

function extractExprKeys(expr) {
  const matches = String(expr || "").match(/[A-Za-z_][A-Za-z0-9_]*/g) || [];
  const ignored = new Set(["and", "or", "not", "in", "True", "False"]);
  return [...new Set(matches.filter((token) => !ignored.has(token)))];
}

function buildReferenceGraph(graph) {
  const nodes = (graph?.nodes || []).map((node) => ({
    id: node.key_id,
    key: node.key,
    raw: node,
    valuePreview: node.values?.length ? `values:${node.values.length}` : node.type,
    type: node.key === "treatment" || node.key === "staging" ? "target" : "normal",
  }));

  const keyToId = new Map(nodes.map((node) => [node.key, node.id]));
  const links = [];
  const seen = new Set();

  (graph?.rules || []).forEach((rule) => {
    const targetKey = rule.target?.key;
    const targetId = keyToId.get(targetKey);
    if (!targetId) return;

    const involvedKeys = new Set([...(rule.required_keys || []), ...extractExprKeys(rule.expr || "")]);
    involvedKeys.delete(targetKey);

    involvedKeys.forEach((key) => {
      const sourceId = keyToId.get(key);
      if (!sourceId) return;
      const edgeKey = `${sourceId}-${targetId}`;
      if (seen.has(edgeKey)) return;
      seen.add(edgeKey);
      links.push({ source: sourceId, target: targetId });
    });
  });

  return { nodes, links };
}

function getActiveRule() {
  if (!state.graph?.rules || state.selectedRuleId == null) return null;
  return state.graph.rules.find((rule) => rule.id === state.selectedRuleId) || null;
}

function getRuleHighlightInfo() {
  const activeRule = getActiveRule();
  if (!activeRule) {
    return { nodeKeys: new Set(), edgeKeys: new Set() };
  }
  const targetKey = activeRule.target?.key;
  const nodeKeys = new Set([targetKey, ...(activeRule.required_keys || []), ...extractExprKeys(activeRule.expr || "")]);
  const edgeKeys = new Set();
  nodeKeys.forEach((key) => {
    if (key !== targetKey) edgeKeys.add(`${key}->${targetKey}`);
  });
  return { nodeKeys, edgeKeys };
}

const graphRenderer = new ForceGraphRenderer({
  svgId: "graphSvg",
  wrapId: "graphWrap",
  placeholderId: "graphPlaceholder",
  metaId: "graphMeta",
  zoomScaleExtent: [0.08, 4],
  widthMin: 360,
  heightMin: 280,
  nodeRadius: 44,
  nodeShape: () => "ellipse",
  nodeMetrics: (node) => computeReferenceNodeMetrics(node),
  linkDistance: 150,
  chargeStrength: -320,
  collisionRadius: 86,
  fitPadding: 55,
  fitScaleMax: 1.45,
  circleClass: (node) => {
    const highlight = getRuleHighlightInfo();
    const classes = ["node-circle"];
    if (node.type === "target") classes.push("target");
    if (highlight.nodeKeys.size) {
      if (highlight.nodeKeys.has(node.key)) classes.push("active");
      else classes.push("dim");
    }
    return classes.join(" ");
  },
  labelClass: (node) => {
    const highlight = getRuleHighlightInfo();
    const classes = ["node-label"];
    if (highlight.nodeKeys.size && !highlight.nodeKeys.has(node.key)) classes.push("dim");
    return classes.join(" ");
  },
  linkClass: (edge, nodes) => {
    const highlight = getRuleHighlightInfo();
    const sourceKey = nodes.find((node) => node.id === edge.source)?.key;
    const targetKey = nodes.find((node) => node.id === edge.target)?.key;
    const classes = ["link"];
    if (highlight.edgeKeys.size) {
      if (highlight.edgeKeys.has(`${sourceKey}->${targetKey}`)) classes.push("active");
      else classes.push("dim");
    }
    return classes.join(" ");
  },
  formatNodeLabel: (text, node) => {
    text.selectAll("*").remove();
    text.append("tspan").attr("class", "key").attr("x", 0).attr("dy", "-0.2em").text(formatNodeKeyLabel(node.key));
    text.append("tspan").attr("class", "value").attr("x", 0).attr("dy", "1.1em").text(`(${node.valuePreview})`);
  },
  onNodeClick: (node) => openNodeModal(node.raw),
  onNodeDrag: (node) => {
    if (activeNodeId === node.id) openNodeModal(node.raw);
  },
});

function renderGraph({ relayout = false } = {}) {
  graphRenderer.render(buildReferenceGraph(state.graph || {}), { relayout });
}

function renderRules() {
  const rules = state.graph?.rules || [];
  els.rulesBox.innerHTML = "";
  if (!rules.length) {
    els.rulesBox.innerHTML = '<div class="muted small">No rules</div>';
    return;
  }

  rules.forEach((rule) => {
    const card = document.createElement("div");
    card.className = `ruleCard${state.selectedRuleId === rule.id ? " active" : ""}`;
    card.innerHTML = `
      <div class="ruleTitle">#${escapeHtml(String(rule.id))} · ${escapeHtml(rule.kind || "rule")}</div>
      <div class="ruleMeta">target: ${escapeHtml(rule.target?.key || "-")} = ${escapeHtml(rule.target?.value || "-")}</div>
      <div class="ruleMeta">required_keys: ${escapeHtml((rule.required_keys || []).join(", ") || "-")}</div>
      <div class="guidanceValue">${escapeHtml(rule.describe || "")}</div>
      <div class="ruleExpr">${escapeHtml(rule.expr || "")}</div>
    `;
    card.addEventListener("click", () => {
      state.selectedRuleId = state.selectedRuleId === rule.id ? null : rule.id;
      renderRules();
      renderGraph({ relayout: false });
    });
    els.rulesBox.append(card);
  });
}

function renderGuidance() {
  els.guidanceBox.innerHTML = "";
  els.guidanceMeta.textContent = `${state.guidanceItems.length} items`;
  if (!state.guidanceItems.length) {
    els.guidanceBox.innerHTML = '<div class="muted small">No guidance entries</div>';
    return;
  }

  state.guidanceItems.forEach((item) => {
    const card = document.createElement("div");
    card.className = "guidanceCard";
    card.innerHTML = `
      <div class="guidanceHead">
        <span class="guidanceId">${escapeHtml(item.id || "-")}</span>
        <span class="guidanceTag">${escapeHtml(item.category || "-")}</span>
        <span class="guidanceTag">${escapeHtml(item.source || "-")}</span>
      </div>
      <div class="guidanceSection">
        <div class="guidanceLabel">Condition</div>
        <div class="guidanceValue">${escapeHtml(item.condition || "-")}</div>
      </div>
      <div class="guidanceSection">
        <div class="guidanceLabel">Recommendation</div>
        <div class="guidanceValue">${escapeHtml(item.recommendation || "-")}</div>
      </div>
      <div class="guidanceSection">
        <div class="guidanceLabel">Hint</div>
        <div class="guidanceValue">${escapeHtml(item.hint || "-")}</div>
      </div>
      <div class="guidanceSection">
        <div class="guidanceLabel">Original Text</div>
        <div class="guidanceValue">${escapeHtml(item.original_text || "-")}</div>
      </div>
    `;
    els.guidanceBox.append(card);
  });
}

function closeNodeModal() {
  activeNodeId = null;
  els.nodeInfoCard.hidden = true;
}

function openNodeModal(node) {
  const pos = graphRenderer.getNodePosition(node.key_id);
  activeNodeId = node.key_id;
  const values = Array.isArray(node.values) ? node.values.join(", ") : node.values?.length ? String(node.values) : "None";

  els.nodeInfoCard.innerHTML = `
    <div class="nodeInfoHead">
      <div>
        <div class="nodeInfoTitle">${escapeHtml(formatNodeKeyLabel(node.key || "-"))}</div>
      </div>
      <button class="nodeInfoClose" id="btnHideNodeCard">×</button>
    </div>
    <div class="nodeInfoMeta">
      <div class="nodeInfoMetaLabel">key_id</div><div class="nodeInfoMetaValue">${escapeHtml(String(node.key_id ?? "-"))}</div>
      <div class="nodeInfoMetaLabel">type</div><div class="nodeInfoMetaValue">${escapeHtml(node.type || "-")}</div>
      <div class="nodeInfoMetaLabel">unit</div><div class="nodeInfoMetaValue">${escapeHtml(node.unit || "-")}</div>
      <div class="nodeInfoMetaLabel">values</div><div class="nodeInfoMetaValue">${escapeHtml(values)}</div>
    </div>
  `;
  els.nodeInfoCard.hidden = false;

  const wrap = document.getElementById("graphWrap");
  const wrapRect = wrap.getBoundingClientRect();
  const cardWidth = 280;
  const cardHeight = 170;
  let left = (pos?.x ?? 20) + 56;
  let top = (pos?.y ?? 20) - 20;
  if (left + cardWidth > wrapRect.width - 8) {
    left = Math.max(8, (pos?.x ?? 20) - cardWidth - 56);
  }
  if (top + cardHeight > wrapRect.height - 8) {
    top = Math.max(8, wrapRect.height - cardHeight - 8);
  }
  if (top < 8) top = 8;
  els.nodeInfoCard.style.left = `${left}px`;
  els.nodeInfoCard.style.top = `${top}px`;
  document.getElementById("btnHideNodeCard")?.addEventListener("click", closeNodeModal);
}

async function loadInitialOptions() {
  const references = await fetchJson("/api/reference/options");
  els.referenceSelect.innerHTML = "";
  references.items.forEach((item) => {
    els.referenceSelect.append(createOption(item.reference_id, item.reference_id));
  });
}

async function openReference() {
  const referenceId = els.referenceSelect.value;
  if (!referenceId) {
    throw new Error("Please select a reference first");
  }

  setStatus("warn", "Loading");
  const payload = await fetchJson(`/api/reference/${referenceId}/bundle`);
  state.referenceId = referenceId;
  state.graph = payload.graph || { nodes: [], rules: [] };
  state.guidanceItems = payload.guidance_items || [];
  state.selectedRuleId = null;
  graphRenderer.clearLayout();
  closeNodeModal();

  els.fileChip.textContent = `${payload.reference_id} · ${payload.graph_file}`;
  renderRules();
  renderGuidance();
  renderGraph({ relayout: true });
  setStatus("ok", "Ready");
}

function bindEvents() {
  els.openButton.addEventListener("click", handleAsync(openReference));
  els.btnResetGraph.addEventListener("click", () => graphRenderer.resetLayout());
  els.btnExportGraph.addEventListener("click", handleAsync(async () => exportCurrentGraphSvg()));
  setupColumnResize("resVMain", "colLeft", "colRight", { minWidth: 260 });
  setupVerticalResize("resHLeft", { minHeight: 80 });
  graphRenderer.bindResizeObserver({ relayout: false });
}

async function init() {
  graphRenderer.init();
  bindEvents();
  await loadInitialOptions();
}

init().catch((error) => {
  console.error(error);
  setStatus("bad", "Init Error");
  window.alert(error.message || "Initialization failed");
});
