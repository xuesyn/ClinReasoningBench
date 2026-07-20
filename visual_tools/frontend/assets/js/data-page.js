import { fetchJson } from "./api.js";
import {
  ForceGraphRenderer,
  bindToggleGroup,
  createAsyncAction,
  createStatusSetter,
  createOption,
  escapeHtml,
  normalizeSubgraph,
  renderJsonPanel,
  renderTreatmentCards,
  setupColumnResize,
  setupVerticalResize,
} from "./viewer-common.js";

marked.setOptions({ breaks: true, gfm: true });

const state = {
  sessionId: null,
  referenceId: null,
  dataFilename: null,
  graphMeta: [],
  currentRecord: null,
  modes: {
    seer: "tree",
    prompt: "raw",
    gtThinkingTag: "raw",
    prediction: "raw",
    predictionThinking: "raw",
    score: "tree",
  },
  expandedState: {
    seer: new Set(["root"]),
    score: new Set(["root"]),
  },
};

const els = {
  referenceSelect: document.getElementById("referenceSelect"),
  dataSelect: document.getElementById("dataSelect"),
  openButton: document.getElementById("openButton"),
  fileChip: document.getElementById("fileChip"),
  loadDot: document.getElementById("loadDot"),
  loadText: document.getElementById("loadText"),
  seerBox: document.getElementById("seerBox"),
  gtTableBox: document.getElementById("gtTableBox"),
  predictionTreatmentBox: document.getElementById("predictionTreatmentBox"),
  gtThinkingTagBox: document.getElementById("gtThinkingTagBox"),
  promptBox: document.getElementById("promptBox"),
  predictionThinkingBox: document.getElementById("predictionThinkingBox"),
  scoreBox: document.getElementById("scoreBox"),
  prevButton: document.getElementById("prevButton"),
  nextButton: document.getElementById("nextButton"),
  randomButton: document.getElementById("randomButton"),
  positionInput: document.getElementById("positionInput"),
  jumpButton: document.getElementById("jumpButton"),
  posChip: document.getElementById("posChip"),
  uuidChip: document.getElementById("uuidChip"),
  btnResetGtGraph: document.getElementById("btnResetGtGraph"),
  btnResetPredGraph: document.getElementById("btnResetPredGraph"),
};

function keyMetaMap() {
  return new Map(state.graphMeta.map((node) => [node.key, node]));
}

const gtGraph = new ForceGraphRenderer({
  svgId: "gtGraphSvg",
  wrapId: "gtGraphWrap",
  placeholderId: "gtGraphPlaceholder",
  metaId: "gtGraphMeta",
});

const predGraph = new ForceGraphRenderer({
  svgId: "predGraphSvg",
  wrapId: "predGraphWrap",
  placeholderId: "predGraphPlaceholder",
  metaId: "predGraphMeta",
});

const setStatus = createStatusSetter(els.loadDot, els.loadText);
const handleAsync = (fn) => createAsyncAction(fn, {
  onError: () => setStatus("bad", "Error"),
});

function renderTreatmentGt(responseRecord) {
  const gt = responseRecord.record?.metadata?.original_data?.treatment_gt || {};
  const labelMap = responseRecord.record?.metadata?.original_data?.label || {};
  renderTreatmentCards(els.gtTableBox, gt, labelMap, []);
}

function normalizePredictionLabel(value) {
  const s = String(value ?? "").trim().toLowerCase();
  if (s === "yes" || s === "true") return "true";
  if (s === "no" || s === "false") return "false";
  return "unknown";
}

function renderPredictionTreatment(responseRecord) {
  const parsed = responseRecord.prediction_parsed || {};
  const scores = parsed.scores || {};
  const indications = parsed.indication || {};
  const contraindications = parsed.contraindication || {};
  const labelMap = {};

  Object.keys(scores).forEach((name) => {
    labelMap[name] = {
      indication: normalizePredictionLabel(indications[name]),
      contraindication: normalizePredictionLabel(contraindications[name]),
    };
  });

  renderTreatmentCards(els.predictionTreatmentBox, scores, labelMap, []);
}

function renderTextPanel(target, text, mode) {
  const content = text || "";
  target.innerHTML = "";
  if (!content) {
    target.innerHTML = '<div class="muted small">No content yet</div>';
    return;
  }
  if (mode === "raw") {
    target.innerHTML = `<pre class="textContent">${escapeHtml(content)}</pre>`;
  } else {
    target.innerHTML = `<div class="textContent markdown">${marked.parse(escapeHtml(content).replaceAll("\n", "<br>"))}</div>`;
  }
}

function renderRecord(responseRecord) {
  state.currentRecord = responseRecord;

  renderJsonPanel(
    els.seerBox,
    responseRecord.record?.metadata?.original_data?.meta_data?.seer_data || {},
    state.modes.seer,
    state.expandedState.seer,
  );
  renderTreatmentGt(responseRecord);
  renderPredictionTreatment(responseRecord);
  renderTextPanel(els.gtThinkingTagBox, responseRecord.gt_thinking_tag, state.modes.gtThinkingTag);
  renderTextPanel(els.promptBox, responseRecord.prompt, state.modes.prompt);
  renderTextPanel(els.predictionThinkingBox, responseRecord.prediction_thinking, state.modes.predictionThinking);
  renderJsonPanel(els.scoreBox, responseRecord.score_results || {}, state.modes.score, state.expandedState.score);

  gtGraph.render(normalizeSubgraph(responseRecord.gt_subgraph, keyMetaMap()), { relayout: true });
  predGraph.render(normalizeSubgraph(responseRecord.pred_subgraph, keyMetaMap()), { relayout: true });

  els.fileChip.textContent = `${responseRecord.reference_id} · ${responseRecord.data_filename}`;
  els.posChip.textContent = `${responseRecord.pos}/${responseRecord.total}`;
  els.uuidChip.textContent = `uuid: ${responseRecord.uuid || "-"}`;
  els.positionInput.value = String(responseRecord.pos);
  els.prevButton.disabled = responseRecord.pos <= 1;
  els.nextButton.disabled = responseRecord.pos >= responseRecord.total;
  els.randomButton.disabled = false;
  els.jumpButton.disabled = false;
  setStatus("ok", "Ready");
}

async function loadInitialOptions() {
  const [references, dataFiles] = await Promise.all([
    fetchJson("/api/reference/options"),
    fetchJson("/api/data/options"),
  ]);

  els.referenceSelect.innerHTML = "";
  references.items.forEach((item) => {
    els.referenceSelect.append(createOption(item.reference_id, item.reference_id));
  });

  els.dataSelect.innerHTML = "";
  dataFiles.items.forEach((item) => {
    els.dataSelect.append(createOption(item.filename, item.filename));
  });
}

async function openSession() {
  const referenceId = els.referenceSelect.value;
  const dataFilename = els.dataSelect.value;
  if (!referenceId || !dataFilename) {
    throw new Error("Please select a reference and a data file first");
  }

  setStatus("warn", "Loading");
  const opened = await fetchJson("/api/data/session/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reference_id: referenceId, data_filename: dataFilename }),
  });

  state.sessionId = opened.session_id;
  state.referenceId = referenceId;
  state.dataFilename = dataFilename;
  const graphMeta = await fetchJson(`/api/reference/${referenceId}/graph-meta`);
  state.graphMeta = graphMeta.nodes || [];
  await loadRecordByPosition(1);
}

async function loadRecordByPosition(pos) {
  if (!state.sessionId) throw new Error("Please load a data session first");
  const responseRecord = await fetchJson(`/api/data/session/${state.sessionId}/record?pos=${pos}`);
  renderRecord(responseRecord);
}

async function loadRandomRecord() {
  if (!state.sessionId) throw new Error("Please load a data session first");
  const responseRecord = await fetchJson(`/api/data/session/${state.sessionId}/random`);
  renderRecord(responseRecord);
}

function bindEvents() {
  els.openButton.addEventListener("click", handleAsync(openSession));
  els.randomButton.addEventListener("click", handleAsync(loadRandomRecord));
  els.prevButton.addEventListener(
    "click",
    handleAsync(async () => {
      if (!state.currentRecord) return;
      await loadRecordByPosition(Math.max(1, state.currentRecord.pos - 1));
    }),
  );
  els.nextButton.addEventListener(
    "click",
    handleAsync(async () => {
      if (!state.currentRecord) return;
      await loadRecordByPosition(Math.min(state.currentRecord.total, state.currentRecord.pos + 1));
    }),
  );
  els.jumpButton.addEventListener(
    "click",
    handleAsync(async () => {
      const value = Number.parseInt(els.positionInput.value, 10);
      if (!Number.isFinite(value) || value < 1) throw new Error("Please enter a valid position");
      await loadRecordByPosition(value);
    }),
  );

  els.btnResetGtGraph.addEventListener("click", () => {
    gtGraph.resetLayout();
  });
  els.btnResetPredGraph.addEventListener("click", () => {
    predGraph.resetLayout();
  });

  bindToggleGroup("toggleSeer", (mode) => { state.modes.seer = mode; }, () => state.currentRecord && renderRecord(state.currentRecord));
  bindToggleGroup("togglePrompt", (mode) => { state.modes.prompt = mode; }, () => state.currentRecord && renderRecord(state.currentRecord));
  bindToggleGroup("toggleGtThinkingTag", (mode) => { state.modes.gtThinkingTag = mode; }, () => state.currentRecord && renderRecord(state.currentRecord));
  bindToggleGroup("togglePredictionThinking", (mode) => { state.modes.predictionThinking = mode; }, () => state.currentRecord && renderRecord(state.currentRecord));
  bindToggleGroup("toggleScore", (mode) => { state.modes.score = mode; }, () => state.currentRecord && renderRecord(state.currentRecord));

  setupColumnResize("resV1", "col1", "col2");
  setupColumnResize("resV2", "col2", "col3");
  setupVerticalResize("resH1_1");
  setupVerticalResize("resH1_2");
  setupVerticalResize("resH2_1");
  setupVerticalResize("resH2_2");
  setupVerticalResize("resH3_1");
  setupVerticalResize("resH3_2");
}

async function init() {
  gtGraph.init();
  predGraph.init();
  gtGraph.bindResizeObserver({ relayout: true });
  predGraph.bindResizeObserver({ relayout: true });
  bindEvents();
  await loadInitialOptions();
}

init().catch((error) => {
  console.error(error);
  setStatus("bad", "Init Error");
  window.alert(error.message || "Initialization failed");
});
