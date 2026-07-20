export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function createOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

export function createLeaf(keyName, value, type = "") {
  const wrapper = document.createElement("div");
  wrapper.className = "jsonLeaf";
  wrapper.innerHTML = `<span class="jsonKey">${escapeHtml(keyName)}</span>: <span class="jsonVal">${escapeHtml(value)}</span>${
    type ? `<span class="jsonType">(${escapeHtml(type)})</span>` : ""
  }`;
  return wrapper;
}

export function jsonTree(value, keyName = "root", path = "root", stateSet = null) {
  const valueType = typeof value;
  if (value === null || value === undefined) {
    return createLeaf(keyName, String(value));
  }
  if (valueType !== "object") {
    return createLeaf(keyName, String(value), valueType);
  }

  const isArray = Array.isArray(value);
  const keys = isArray ? value.map((_, index) => String(index)) : Object.keys(value);
  const details = document.createElement("details");
  details.className = "jsonNode";
  if (stateSet?.has(path)) {
    details.open = true;
  }
  details.addEventListener("toggle", () => {
    if (!stateSet) return;
    if (details.open) stateSet.add(path);
    else stateSet.delete(path);
  });

  const summary = document.createElement("summary");
  summary.className = "jsonSummary";
  summary.textContent = isArray ? `${keyName} [${keys.length}]` : `${keyName} {${keys.length}}`;
  details.append(summary);

  const body = document.createElement("div");
  keys.forEach((key) => {
    const child = isArray ? value[Number(key)] : value[key];
    body.append(jsonTree(child, key, `${path}.${key}`, stateSet));
  });
  details.append(body);
  return details;
}

export function renderJsonPanel(target, value, mode, expandedSet) {
  target.innerHTML = "";
  if (mode === "raw") {
    const pre = document.createElement("pre");
    pre.className = "textContent";
    pre.textContent = JSON.stringify(value ?? {}, null, 2);
    target.append(pre);
    return;
  }
  target.append(jsonTree(value ?? {}, "root", "root", expandedSet));
}

export function bindToggleGroup(rootId, onChange, rerender) {
  const root = document.getElementById(rootId);
  if (!root) return;

  root.querySelectorAll(".toggle").forEach((toggle) => {
    toggle.addEventListener("click", () => {
      root.querySelectorAll(".toggle").forEach((node) => node.classList.remove("active"));
      toggle.classList.add("active");
      onChange(toggle.dataset.mode);
      if (rerender) rerender();
    });
  });
}

export function setupColumnResize(resizerId, leftId, rightId, { minWidth = 200 } = {}) {
  const resizer = document.getElementById(resizerId);
  const left = document.getElementById(leftId);
  const right = document.getElementById(rightId);
  if (!resizer || !left || !right) return;

  let dragging = false;
  let startX = 0;
  let startLeftW = 0;
  let startRightW = 0;

  resizer.addEventListener("mousedown", (event) => {
    dragging = true;
    document.body.style.cursor = "col-resize";
    startX = event.clientX;
    startLeftW = left.getBoundingClientRect().width;
    startRightW = right.getBoundingClientRect().width;
    event.preventDefault();
  });

  window.addEventListener("mouseup", () => {
    dragging = false;
    document.body.style.cursor = "default";
  });

  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const dx = event.clientX - startX;
    const newLeft = startLeftW + dx;
    const newRight = startRightW - dx;
    if (newLeft < minWidth || newRight < minWidth) return;
    left.style.width = `${newLeft}px`;
    right.style.width = `${newRight}px`;
  });
}

export function setupVerticalResize(resizerId, { minHeight = 60 } = {}) {
  const resizer = document.getElementById(resizerId);
  const previousPanel = resizer?.previousElementSibling;
  const nextPanel = resizer?.nextElementSibling;
  if (!resizer || !previousPanel || !nextPanel) return;

  let dragging = false;
  let startY = 0;
  let startPrevH = 0;
  let startNextH = 0;

  resizer.addEventListener("mousedown", (event) => {
    dragging = true;
    document.body.style.cursor = "row-resize";
    startY = event.clientY;
    startPrevH = previousPanel.getBoundingClientRect().height;
    startNextH = nextPanel.getBoundingClientRect().height;
    event.preventDefault();
  });

  window.addEventListener("mouseup", () => {
    dragging = false;
    document.body.style.cursor = "default";
  });

  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const dy = event.clientY - startY;
    const newPrevH = startPrevH + dy;
    const newNextH = startNextH - dy;
    if (newPrevH < minHeight || newNextH < minHeight) return;
    previousPanel.style.height = `${newPrevH}px`;
    nextPanel.style.height = `${newNextH}px`;
    previousPanel.style.flex = "none";
    nextPanel.style.flex = "none";
  });
}

export function setStatusIndicator(dotEl, textEl, kind, message) {
  if (!dotEl || !textEl) return;
  dotEl.className = "statusDot";
  if (kind === "ok") dotEl.classList.add("ok");
  if (kind === "warn") dotEl.classList.add("warn");
  if (kind === "bad") dotEl.classList.add("bad");
  textEl.textContent = message || "";
}

export function createStatusSetter(dotEl, textEl) {
  return (kind, message) => {
    setStatusIndicator(dotEl, textEl, kind, message);
  };
}

export function createAsyncAction(fn, { onError = null, fallbackMessage = "Operation failed" } = {}) {
  return async () => {
    try {
      await fn();
    } catch (error) {
      console.error(error);
      onError?.(error);
      window.alert(error.message || fallbackMessage);
    }
  };
}

export function renderTreatmentCards(container, scores, labelMap = {}, recommendedList = []) {
  container.innerHTML = "";
  if (!scores || !Object.keys(scores).length) {
    container.innerHTML = '<div class="muted small">No data</div>';
    return;
  }

  const entries = Object.entries(scores);
  entries.sort((a, b) => {
    const diff = Number(b[1]) - Number(a[1]);
    if (diff !== 0) return diff;
    return String(a[0]).localeCompare(String(b[0]), "zh");
  });

  const grid = document.createElement("div");
  grid.className = "gtGrid";

  entries.forEach(([name, score]) => {
    const card = document.createElement("div");
    card.className = "gtCard";
    const recIndex = recommendedList.indexOf(name);
    if (recIndex !== -1) {
      card.classList.add("recommended");
    }

    const label = labelMap[name] || { indication: "unknown", contraindication: "unknown" };
    const indication = label.indication || "unknown";
    const contraindication = label.contraindication || "unknown";

    card.innerHTML = `
      <div class="k">${escapeHtml(name)}</div>
      <div class="v">${escapeHtml(String(score))}</div>
      <div class="gtLabels">
        <span class="gtPill ${escapeHtml(indication)}">indic: ${escapeHtml(indication)}</span>
        <span class="gtPill ${escapeHtml(contraindication)}">contra: ${escapeHtml(contraindication)}</span>
      </div>
      ${recIndex !== -1 ? `<div class="rec-rank">#${recIndex + 1}</div>` : ""}
    `;
    grid.append(card);
  });

  container.append(grid);
}

export function normalizeSubgraph(subgraph, keyMetaMap, { targetKeys = new Set(["treatment", "staging"]) } = {}) {
  return {
    nodes: (subgraph?.nodes || []).map((node) => {
      const meta = keyMetaMap.get(node.key);
      return {
        id: node.key_id,
        key: node.key,
        raw: node,
        displayName: meta?.desc || node.key,
        value: node.value,
        matched: Boolean(node.matched),
        type: targetKeys.has(node.key) ? "target" : "normal",
      };
    }),
    links: (subgraph?.routes || []).map((route) => ({
      source: route.from,
      target: route.to,
      raw: route,
    })),
  };
}

function defaultCircleClass(node) {
  const classes = ["node-circle"];
  if (node.type === "target") classes.push("target");
  if (node.matched) classes.push("matched");
  return classes.join(" ");
}

function defaultLabelClass() {
  return "node-label";
}

function defaultLinkClass() {
  return "link";
}

function defaultFormatNodeLabel(text, node) {
  text.selectAll("*").remove();
  text.append("tspan").attr("class", "cn").attr("x", 0).attr("dy", "-0.6em").text(node.displayName || node.key || node.id);
  text.append("tspan").attr("class", "key").attr("x", 0).attr("dy", "1.1em").text(node.key || "");
  text
    .append("tspan")
    .attr("class", "value")
    .attr("x", 0)
    .attr("dy", "1.1em")
    .text(`(${Array.isArray(node.value) ? node.value.join(", ") : String(node.value ?? "" )})`);
}

export class ForceGraphRenderer {
  constructor({
    svgId,
    wrapId,
    placeholderId,
    metaId,
    zoomScaleExtent = [0.1, 4],
    widthMin = 300,
    heightMin = 200,
    nodeRadius = 36,
    linkDistance = 120,
    chargeStrength = -250,
    collisionRadius = 70,
    fitPadding = 50,
    fitScaleMax = 1.5,
    metaFormatter = ({ nodes, links }) => `${nodes.length}N / ${links.length}E`,
    circleClass = defaultCircleClass,
    labelClass = defaultLabelClass,
    linkClass = defaultLinkClass,
    nodeShape = () => "circle",
    nodeMetrics = null,
    formatNodeLabel = defaultFormatNodeLabel,
    onNodeClick = null,
    onNodeDrag = null,
  }) {
    this.svgEl = document.getElementById(svgId);
    this.wrapEl = document.getElementById(wrapId);
    this.placeholderEl = document.getElementById(placeholderId);
    this.metaEl = document.getElementById(metaId);
    this.zoomScaleExtent = zoomScaleExtent;
    this.widthMin = widthMin;
    this.heightMin = heightMin;
    this.nodeRadius = nodeRadius;
    this.linkDistance = linkDistance;
    this.chargeStrength = chargeStrength;
    this.collisionRadius = collisionRadius;
    this.fitPadding = fitPadding;
    this.fitScaleMax = fitScaleMax;
    this.metaFormatter = metaFormatter;
    this.circleClass = circleClass;
    this.labelClass = labelClass;
    this.linkClass = linkClass;
    this.nodeShape = nodeShape;
    this.nodeMetrics = nodeMetrics;
    this.formatNodeLabel = formatNodeLabel;
    this.onNodeClick = onNodeClick;
    this.onNodeDrag = onNodeDrag;
    this.ctx = null;
    this.zoomBehavior = null;
    this.lastGraph = null;
    this.lastSubgraph = null;
    this.lastNodes = [];
    this.nodePositions = new Map();
  }

  init() {
    const svg = d3.select(this.svgEl);
    svg.selectAll("*").remove();

    const defs = svg.append("defs");
    defs
      .append("marker")
      .attr("id", `${this.svgEl.id}-arrow`)
      .attr("viewBox", "0 0 10 10")
      .attr("refX", 8)
      .attr("refY", 5)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,0 L10,5 L0,10 z")
      .attr("fill", "#64748b");

    const containerG = svg.append("g").attr("class", "graph-container");
    containerG.append("g").attr("class", "links");
    containerG.append("g").attr("class", "nodes");

    this.zoomBehavior = d3.zoom().scaleExtent(this.zoomScaleExtent).on("zoom", (event) => {
      containerG.attr("transform", event.transform);
    });
    svg.call(this.zoomBehavior);
    this.ctx = { svg, containerG };
  }

  clear() {
    const linkGroup = d3.select(`#${this.svgEl.id} .links`);
    const nodeGroup = d3.select(`#${this.svgEl.id} .nodes`);
    if (!linkGroup.empty()) linkGroup.selectAll("*").remove();
    if (!nodeGroup.empty()) nodeGroup.selectAll("*").remove();
  }

  clearLayout() {
    this.nodePositions.clear();
  }

  resetLayout() {
    this.nodePositions.clear();
    if (this.lastGraph) {
      this.render(this.lastGraph, { relayout: true });
    }
  }

  getNodePosition(nodeId) {
    return this.nodePositions.get(nodeId) || this.lastNodes.find((node) => node.id === nodeId) || null;
  }

  resolveNodeMetrics(node) {
    if (typeof this.nodeMetrics === "function") {
      const metrics = this.nodeMetrics(node) || {};
      return {
        rx: metrics.rx ?? this.nodeRadius,
        ry: metrics.ry ?? this.nodeRadius,
        collisionRadius: metrics.collisionRadius ?? Math.max(metrics.rx ?? this.nodeRadius, metrics.ry ?? this.nodeRadius, this.collisionRadius),
      };
    }
    return {
      rx: this.nodeRadius,
      ry: this.nodeRadius,
      collisionRadius: this.collisionRadius,
    };
  }

  offsetPointByNodeShape(source, target, gap = 0) {
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const unitX = dx / len;
    const unitY = dy / len;
    const shape = source._shape || "circle";
    const metrics = source._metrics || { rx: this.nodeRadius, ry: this.nodeRadius };

    if (shape === "ellipse") {
      const t = 1 / Math.sqrt((dx * dx) / (metrics.rx * metrics.rx) + (dy * dy) / (metrics.ry * metrics.ry));
      return {
        x: source.x + dx * t + unitX * gap,
        y: source.y + dy * t + unitY * gap,
      };
    }

    const radius = metrics.rx ?? this.nodeRadius;
    return {
      x: source.x + unitX * (radius + gap),
      y: source.y + unitY * (radius + gap),
    };
  }

  updateLinkPositions(linksSelection, nodes) {
    const arrowGap = 6;
    const innerGap = 4;
    const renderer = this;

    linksSelection.each(function (link) {
      const source = nodes.find((node) => node.id === link.source);
      const target = nodes.find((node) => node.id === link.target);
      if (!source || !target) return;

      const start = renderer.offsetPointByNodeShape(source, target, innerGap);
      const end = renderer.offsetPointByNodeShape(target, source, arrowGap);
      d3.select(this).attr("x1", start.x).attr("y1", start.y).attr("x2", end.x).attr("y2", end.y);
    });
  }

  fitToNodes(nodes, width, height) {
    const xs = nodes.flatMap((node) => [node.x - (node._metrics?.rx ?? this.nodeRadius), node.x + (node._metrics?.rx ?? this.nodeRadius)]);
    const ys = nodes.flatMap((node) => [node.y - (node._metrics?.ry ?? this.nodeRadius), node.y + (node._metrics?.ry ?? this.nodeRadius)]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const graphW = maxX - minX || 1;
    const graphH = maxY - minY || 1;
    const scale = Math.min(
      (width - this.fitPadding * 2) / graphW,
      (height - this.fitPadding * 2) / graphH,
      this.fitScaleMax,
    );
    const transform = d3.zoomIdentity
      .translate(width / 2, height / 2)
      .scale(scale)
      .translate(-(minX + maxX) / 2, -(minY + maxY) / 2);
    this.ctx.svg.transition().duration(400).call(this.zoomBehavior.transform, transform);
  }

  runLayout(nodes, links, width, height) {
    const simNodes = nodes.map((node) => ({ ...node }));
    const idToNode = new Map(simNodes.map((node) => [node.id, node]));
    const simLinks = links.map((link) => ({
      source: idToNode.get(link.source),
      target: idToNode.get(link.target),
    }));

    const simulation = d3
      .forceSimulation(simNodes)
      .force("link", d3.forceLink(simLinks).id((d) => d.id).distance(this.linkDistance))
      .force("charge", d3.forceManyBody().strength(this.chargeStrength))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("x", d3.forceX(width / 2).strength(0.1))
      .force("y", d3.forceY(height / 2).strength(0.1))
      .force("collision", d3.forceCollide((node) => node._metrics?.collisionRadius ?? this.collisionRadius))
      .stop();

    for (let i = 0; i < 180; i += 1) {
      simulation.tick();
    }

    simNodes.forEach((simNode) => {
      const realNode = nodes.find((node) => node.id === simNode.id);
      realNode.x = simNode.x;
      realNode.y = simNode.y;
      this.nodePositions.set(realNode.id, { x: realNode.x, y: realNode.y });
    });
  }

  render(graphData, { relayout = false } = {}) {
    this.lastGraph = graphData;
    this.lastSubgraph = graphData;

    const width = Math.max(this.widthMin, this.wrapEl.clientWidth);
    const height = Math.max(this.heightMin, this.wrapEl.clientHeight);
    this.ctx.svg.attr("viewBox", [0, 0, width, height]);

    const nodes = (graphData?.nodes || []).map((node) => {
      const savedPos = this.nodePositions.get(node.id);
      const metrics = this.resolveNodeMetrics(node);
      return {
        ...node,
        _shape: this.nodeShape(node),
        _metrics: metrics,
        x: savedPos?.x ?? node.x ?? null,
        y: savedPos?.y ?? node.y ?? null,
      };
    });
    const links = (graphData?.links || []).map((link) => ({ ...link }));
    this.lastNodes = nodes;

    if (this.metaEl) {
      this.metaEl.textContent = this.metaFormatter({ nodes, links });
    }
    if (!nodes.length) {
      if (this.placeholderEl) this.placeholderEl.style.display = "flex";
      this.clear();
      return;
    }

    if (this.placeholderEl) this.placeholderEl.style.display = "none";

    const linkGroup = this.ctx.containerG.select(".links");
    const nodeGroup = this.ctx.containerG.select(".nodes");

    const linkSelection = linkGroup.selectAll("line").data(links, (d) => `${d.source}-${d.target}`);
    linkSelection.exit().remove();
    const linksMerged = linkSelection
      .enter()
      .append("line")
      .attr("marker-end", `url(#${this.svgEl.id}-arrow)`)
      .merge(linkSelection);

    const nodeSelection = nodeGroup.selectAll("g.node").data(nodes, (d) => d.id);
    nodeSelection.exit().remove();
    const nodeEnter = nodeSelection.enter().append("g").attr("class", "node");
    nodeEnter.append("circle").attr("r", this.nodeRadius);
    nodeEnter.append("ellipse");
    nodeEnter.append("text");
    const nodesMerged = nodeEnter.merge(nodeSelection);

    nodesMerged
      .select("circle")
      .attr("class", (node) => this.circleClass(node, nodes, links))
      .attr("display", (node) => (node._shape === "circle" ? null : "none"))
      .attr("r", (node) => node._metrics?.rx ?? this.nodeRadius);
    nodesMerged
      .select("ellipse")
      .attr("class", (node) => this.circleClass(node, nodes, links))
      .attr("display", (node) => (node._shape === "ellipse" ? null : "none"))
      .attr("rx", (node) => node._metrics?.rx ?? this.nodeRadius)
      .attr("ry", (node) => node._metrics?.ry ?? this.nodeRadius);
    nodesMerged.select("text").attr("class", (node) => this.labelClass(node, nodes, links));
    nodesMerged.select("text").each((node, index, list) => {
      this.formatNodeLabel(d3.select(list[index]), node, nodes, links);
    });
    linksMerged.attr("class", (link) => this.linkClass(link, nodes, links));

    if (relayout) {
      this.runLayout(nodes, links, width, height);
      nodesMerged.attr("transform", (node) => `translate(${node.x},${node.y})`);
      this.updateLinkPositions(linksMerged, nodes);
      this.fitToNodes(nodes, width, height);
    } else {
      const needRelayout = nodes.some((node) => node.x == null || node.y == null);
      if (needRelayout) {
        this.render(graphData, { relayout: true });
        return;
      }
      nodesMerged.attr("transform", (node) => `translate(${node.x},${node.y})`);
      this.updateLinkPositions(linksMerged, nodes);
    }

    if (this.onNodeClick) {
      nodesMerged.on("click", (_event, node) => this.onNodeClick(node, this));
    } else {
      nodesMerged.on("click", null);
    }

    const thisRenderer = this;
    nodesMerged.call(
      d3
        .drag()
        .on("start", (_event, node) => {
          node.fx = node.x;
          node.fy = node.y;
        })
        .on("drag", function (event, node) {
          node.fx = node.x = event.x;
          node.fy = node.y = event.y;
          thisRenderer.nodePositions.set(node.id, { x: node.x, y: node.y });
          d3.select(this).attr("transform", `translate(${node.x},${node.y})`);
          thisRenderer.updateLinkPositions(linksMerged, nodes);
          if (thisRenderer.onNodeDrag) {
            thisRenderer.onNodeDrag(node, thisRenderer);
          }
        })
        .on("end", (_event, node) => {
          node.fx = null;
          node.fy = null;
        }),
    );
  }

  bindResizeObserver({ relayout = false } = {}) {
    const resizeObserver = new ResizeObserver(() => {
      if (this.lastGraph) {
        this.render(this.lastGraph, { relayout });
      }
    });
    resizeObserver.observe(this.wrapEl);
  }
}
