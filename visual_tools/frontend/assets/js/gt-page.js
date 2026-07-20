import { fetchJson } from "./api.js";
import {
  ForceGraphRenderer,
  bindToggleGroup,
  createAsyncAction,
  createStatusSetter,
  createOption,
  escapeHtml,
  jsonTree,
  normalizeSubgraph,
  renderJsonPanel,
  renderTreatmentCards,
  setupColumnResize,
  setupVerticalResize,
} from "./viewer-common.js";

const state = {
  sessionId: null,
  referenceId: null,
  gtFilename: null,
  graphMeta: [],
  currentRecord: null,
  filters: { auto: "all", manual: "all" },
  modes: {
    seer: "tree",
    emr: "tree",
    thinking: "raw",
    thinkingTag: "raw",
    gtCheck: "readable",
  },
  expandedState: {
    seer: new Set(["root"]),
    emr: new Set(["root"]),
  },
};

const els = {
  referenceSelect: document.getElementById("referenceSelect"),
  gtSelect: document.getElementById("gtSelect"),
  openButton: document.getElementById("openButton"),
  autoFilter: document.getElementById("autoFilter"),
  manualFilter: document.getElementById("manualFilter"),
  applyFilterButton: document.getElementById("applyFilterButton"),
  fileChip: document.getElementById("fileChip"),
  loadDot: document.getElementById("loadDot"),
  loadText: document.getElementById("loadText"),
  seerBox: document.getElementById("seerBox"),
  emrBox: document.getElementById("emrBox"),
  gtTableBox: document.getElementById("gtTableBox"),
  thinkingBox: document.getElementById("thinkingBox"),
  thinkingTagBox: document.getElementById("thinkingTagBox"),
  btnResetGraph: document.getElementById("btnResetGraph"),
  gtCheckBox: document.getElementById("gtCheckBox"),
  statusBox: document.getElementById("statusBox"),
  commentText: document.getElementById("commentText"),
  manualRadioGroup: document.getElementById("manualRadioGroup"),
  autoCheckShow: document.getElementById("autoCheckShow"),
  prevButton: document.getElementById("prevButton"),
  nextButton: document.getElementById("nextButton"),
  randomButton: document.getElementById("randomButton"),
  positionInput: document.getElementById("positionInput"),
  jumpButton: document.getElementById("jumpButton"),
  posChip: document.getElementById("posChip"),
  uuidChip: document.getElementById("uuidChip"),
  guidanceTooltip: document.getElementById("guidanceTooltip"),
};

marked.setOptions({ breaks: true, gfm: true });

const guidanceCache = new Map();
const graphRenderer = new ForceGraphRenderer({
  svgId: "graphSvg",
  wrapId: "graphWrap",
  placeholderId: "graphPlaceholder",
  metaId: "graphMeta",
});
const setStatus = createStatusSetter(els.loadDot, els.loadText);
const handleAsync = (fn) => createAsyncAction(fn, {
  onError: () => setStatus("bad", "Error"),
});

function escapeAngleBrackets(value) {
  return String(value ?? "").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function escapeKnowledgeTagsOnly(value) {
  return String(value ?? "").replace(/<knowledge_id=['"][^'"]+['"]>/g, (match) => escapeAngleBrackets(match));
}

function getRecommendedList(responseRecord) {
  const list = responseRecord?.record?.recommended_list ?? responseRecord?.record?.parsed_response?.recommended_list;
  return Array.isArray(list) ? list : [];
}

function getLabelMap(responseRecord) {
  const mapping = responseRecord?.record?.label;
  return mapping && typeof mapping === "object" ? mapping : {};
}

function getThinking(responseRecord) {
  return responseRecord?.thinking || "";
}

function getThinkingTag(responseRecord) {
  return responseRecord?.thinking_tag || "";
}

function keyMetaMap() {
  return new Map(state.graphMeta.map((node) => [node.key, node]));
}

function renderTreatmentGt(responseRecord) {
  renderTreatmentCards(els.gtTableBox, responseRecord?.record?.treatment_gt || {}, getLabelMap(responseRecord), getRecommendedList(responseRecord));
}

function renderTextPanel(target, text, mode) {
  const rawText = text ?? "";
  target.innerHTML = "";
  if (!rawText) {
    target.innerHTML = '<div class="muted small">No content yet</div>';
    return;
  }

  const isThinkingTag = target === els.thinkingTagBox;
  let processedText = mode === "raw" ? escapeHtml(rawText) : isThinkingTag ? escapeAngleBrackets(rawText) : escapeKnowledgeTagsOnly(rawText);

  if (isThinkingTag && state.currentRecord?.violations?.length) {
    const errorKeySet = new Set();
    state.currentRecord.violations.forEach((item) => {
      if (item.target?.key) errorKeySet.add(item.target.key);
      if (Array.isArray(item.required_keys)) {
        item.required_keys.forEach((key) => key && errorKeySet.add(key));
      }
    });

    errorKeySet.forEach((key) => {
      processedText = processedText.replace(new RegExp(`(&lt;/?${key}&gt;)`, "g"), '<span class="highlight-error">$1</span>');
    });
  }

  if (mode === "raw") {
    target.innerHTML = `<pre class="mono" style="margin:0; white-space:pre-wrap;">${processedText}</pre>`;
  } else {
    target.innerHTML = `<div class="mono" style="font-size:13px;">${marked.parse(processedText)}</div>`;
  }

  decorateKnowledgeTags(target);
}

function decorateKnowledgeTags(container) {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const parent = node.parentElement;
    if (!parent || parent.closest(".guidance-tag")) continue;
    if (!node.nodeValue || !node.nodeValue.includes("<knowledge_id=")) continue;
    textNodes.push(node);
  }

  const regex = /(<knowledge_id=['"]([^'"]+)['"]>)/g;
  textNodes.forEach((node) => {
    const text = node.nodeValue;
    const matches = [...text.matchAll(regex)];
    if (!matches.length) return;

    const fragment = document.createDocumentFragment();
    let lastIndex = 0;
    matches.forEach((match) => {
      const [fullMatch, tagText, guidanceId] = match;
      const start = match.index ?? 0;
      if (start > lastIndex) {
        fragment.append(document.createTextNode(text.slice(lastIndex, start)));
      }
      const span = document.createElement("span");
      span.className = "guidance-tag";
      span.dataset.id = guidanceId;
      span.textContent = tagText;
      fragment.append(span);
      lastIndex = start + fullMatch.length;
    });
    if (lastIndex < text.length) {
      fragment.append(document.createTextNode(text.slice(lastIndex)));
    }
    node.parentNode.replaceChild(fragment, node);
  });
}

function renderGtCheck(responseRecord) {
  const violations = responseRecord?.violations || [];
  els.gtCheckBox.innerHTML = "";

  if (state.modes.gtCheck === "raw") {
    const pre = document.createElement("pre");
    pre.className = "textContent";
    pre.textContent = JSON.stringify(violations, null, 2);
    els.gtCheckBox.append(pre);
    return;
  }

  if (!violations.length) {
    els.gtCheckBox.innerHTML = '<div class="small" style="color:var(--success); font-weight:700;">No conflicts</div>';
    return;
  }

  violations.forEach((item) => {
    const card = document.createElement("div");
    card.className = "listCard";
    card.innerHTML = `
      <div><strong>${escapeHtml(item.kind || "rule")}</strong></div>
      <div class="small muted">id: ${escapeHtml(String(item.id ?? "-"))}</div>
      <div class="small">${escapeHtml(item.describe || "")}</div>
    `;
    els.gtCheckBox.append(card);
  });
}

function renderStatus(responseRecord) {
  els.statusBox.innerHTML = `
    uuid: <span class="mono">${escapeHtml(responseRecord.uuid || "-")}</span>
    <span style="margin:0 8px; color:#ddd;">|</span>
    raw_index: <span class="mono">${escapeHtml(String(responseRecord.raw_index))}</span>
  `;

  els.commentText.textContent = responseRecord.comment || "(No comment)";

  const auto = responseRecord.auto_check_pass;
  els.autoCheckShow.textContent = auto == null ? "null" : String(auto);
  els.autoCheckShow.classList.remove("is-pass", "is-fail", "is-neutral");
  els.autoCheckShow.classList.add(auto === 1 ? "is-pass" : auto === 0 ? "is-fail" : "is-neutral");

  const manualValue = responseRecord.manual_check == null ? "null" : String(responseRecord.manual_check);
  els.manualRadioGroup.querySelectorAll(".radio-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.val === manualValue);
  });
}

function renderBottomBar(responseRecord) {
  els.posChip.textContent = `${responseRecord.pos}/${responseRecord.filtered_total}`;
  els.uuidChip.textContent = `uuid: ${responseRecord.uuid || "-"}`;
  els.positionInput.value = String(responseRecord.pos);
  els.prevButton.disabled = responseRecord.pos <= 1;
  els.nextButton.disabled = responseRecord.pos >= responseRecord.filtered_total;
  els.randomButton.disabled = false;
  els.jumpButton.disabled = false;
}

function renderRecord(responseRecord) {
  state.currentRecord = responseRecord;

  renderJsonPanel(els.seerBox, responseRecord.record?.meta_data?.seer_data || {}, state.modes.seer, state.expandedState.seer);
  renderJsonPanel(els.emrBox, responseRecord.record?.emr || {}, state.modes.emr, state.expandedState.emr);
  renderTreatmentGt(responseRecord);
  renderTextPanel(els.thinkingBox, getThinking(responseRecord), state.modes.thinking);
  renderTextPanel(els.thinkingTagBox, getThinkingTag(responseRecord), state.modes.thinkingTag);
  graphRenderer.render(normalizeSubgraph(responseRecord.subgraph, keyMetaMap()), { relayout: true });
  renderGtCheck(responseRecord);
  renderStatus(responseRecord);
  renderBottomBar(responseRecord);

  els.fileChip.textContent = `${responseRecord.reference_id} · ${responseRecord.gt_filename}`;
  setStatus(responseRecord.has_conflict ? "warn" : "ok", responseRecord.has_conflict ? "Conflict" : "Ready");
}

async function loadInitialOptions() {
  const [references, groundTruths] = await Promise.all([fetchJson("/api/reference/options"), fetchJson("/api/ground-truth/options")]);

  els.referenceSelect.innerHTML = "";
  references.items.forEach((item) => {
    els.referenceSelect.append(createOption(item.reference_id, item.reference_id));
  });

  els.gtSelect.innerHTML = "";
  groundTruths.items.forEach((item) => {
    els.gtSelect.append(createOption(item.filename, item.filename));
  });
}

async function openSession() {
  const referenceId = els.referenceSelect.value;
  const gtFilename = els.gtSelect.value;
  if (!referenceId || !gtFilename) {
    throw new Error("Please select a reference and a ground truth file first");
  }

  setStatus("warn", "Loading");
  const opened = await fetchJson("/api/gt/session/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reference_id: referenceId, gt_filename: gtFilename }),
  });

  state.sessionId = opened.session_id;
  state.referenceId = referenceId;
  state.gtFilename = gtFilename;
  graphRenderer.clearLayout();
  state.graphMeta = (await fetchJson(`/api/reference/${referenceId}/graph-meta`)).nodes || [];
  await loadRecordByPosition(1);
}

async function loadRecordByPosition(pos) {
  if (!state.sessionId) {
    throw new Error("Please load a GT session first");
  }

  const params = new URLSearchParams({
    pos: String(pos),
    auto: state.filters.auto,
    manual: state.filters.manual,
  });
  renderRecord(await fetchJson(`/api/gt/session/${state.sessionId}/record?${params.toString()}`));
}

async function loadRandomRecord() {
  if (!state.sessionId) {
    throw new Error("Please load a GT session first");
  }

  const params = new URLSearchParams({
    auto: state.filters.auto,
    manual: state.filters.manual,
  });
  renderRecord(await fetchJson(`/api/gt/session/${state.sessionId}/random?${params.toString()}`));
}

function applyFilters() {
  state.filters.auto = els.autoFilter.value;
  state.filters.manual = els.manualFilter.value;
  return loadRecordByPosition(1);
}

function getGuidanceTarget(node) {
  if (!node) return null;
  if (node.nodeType === Node.TEXT_NODE) {
    return node.parentElement?.closest(".guidance-tag") || null;
  }
  if (typeof node.closest === "function") {
    return node.closest(".guidance-tag");
  }
  return null;
}

function bindGuidanceTooltip() {
  document.addEventListener("mouseover", async (event) => {
    const target = getGuidanceTarget(event.target);
    if (!target || !state.referenceId) return;

    const guidanceId = target.dataset.id;
    els.guidanceTooltip.style.display = "block";
    els.guidanceTooltip.innerHTML = `<div class="muted">Loading ${guidanceId}...</div>`;

    try {
      let data = guidanceCache.get(guidanceId);
      if (!data) {
        data = await fetchJson(`/api/reference/${state.referenceId}/guidance/${guidanceId}`);
        guidanceCache.set(guidanceId, data);
      }
      els.guidanceTooltip.innerHTML = `<div class="tooltip-title">Knowledge base reference: ${escapeHtml(guidanceId)}</div>`;
      els.guidanceTooltip.append(jsonTree(data, "Content", "root", new Set(["root"])));
    } catch (_error) {
      els.guidanceTooltip.innerHTML = `<div style="color:var(--danger);">Reference data not found (${escapeHtml(guidanceId)})</div>`;
    }
  });

  document.addEventListener("mousemove", (event) => {
    if (els.guidanceTooltip.style.display !== "block") return;
    const offsetX = 15;
    const offsetY = 15;
    let x = event.clientX + offsetX;
    let y = event.clientY + offsetY;
    if (x + els.guidanceTooltip.offsetWidth > window.innerWidth) {
      x = event.clientX - els.guidanceTooltip.offsetWidth - offsetX;
    }
    if (y + els.guidanceTooltip.offsetHeight > window.innerHeight) {
      y = event.clientY - els.guidanceTooltip.offsetHeight - offsetY;
    }
    els.guidanceTooltip.style.left = `${x}px`;
    els.guidanceTooltip.style.top = `${y}px`;
  });

  document.addEventListener("mouseout", (event) => {
    if (getGuidanceTarget(event.target)) {
      els.guidanceTooltip.style.display = "none";
    }
  });
}

function bindEvents() {
  els.openButton.addEventListener("click", handleAsync(openSession));
  els.applyFilterButton.addEventListener("click", handleAsync(applyFilters));
  els.randomButton.addEventListener("click", handleAsync(loadRandomRecord));
  els.prevButton.addEventListener("click", handleAsync(async () => state.currentRecord && loadRecordByPosition(Math.max(1, state.currentRecord.pos - 1))));
  els.nextButton.addEventListener(
    "click",
    handleAsync(async () => state.currentRecord && loadRecordByPosition(Math.min(state.currentRecord.filtered_total, state.currentRecord.pos + 1))),
  );
  els.jumpButton.addEventListener(
    "click",
    handleAsync(async () => {
      const value = Number.parseInt(els.positionInput.value, 10);
      if (!Number.isFinite(value) || value < 1) {
        throw new Error("Please enter a valid position");
      }
      await loadRecordByPosition(value);
    }),
  );
  els.btnResetGraph.addEventListener("click", () => graphRenderer.resetLayout());

  bindToggleGroup("toggleSeer", (mode) => {
    state.modes.seer = mode;
  }, () => state.currentRecord && renderRecord(state.currentRecord));
  bindToggleGroup("toggleEmr", (mode) => {
    state.modes.emr = mode;
  }, () => state.currentRecord && renderRecord(state.currentRecord));
  bindToggleGroup("toggleThinking", (mode) => {
    state.modes.thinking = mode;
  }, () => state.currentRecord && renderRecord(state.currentRecord));
  bindToggleGroup("toggleThinkingTag", (mode) => {
    state.modes.thinkingTag = mode;
  }, () => state.currentRecord && renderRecord(state.currentRecord));
  bindToggleGroup("toggleGtCheck", (mode) => {
    state.modes.gtCheck = mode;
  }, () => state.currentRecord && renderRecord(state.currentRecord));

  bindGuidanceTooltip();
  setupColumnResize("resV1", "col1", "col2");
  setupColumnResize("resV2", "col2", "col3");
  setupVerticalResize("resH1_1");
  setupVerticalResize("resH1_2");
  setupVerticalResize("resH2_1");
  setupVerticalResize("resH3_1");
  setupVerticalResize("resH3_2");
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
