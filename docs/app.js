import { getApp, getApps, initializeApp } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
  signInAnonymously,
} from "https://www.gstatic.com/firebasejs/10.12.5/firebase-auth.js";
import {
  collection,
  doc,
  getDocs,
  getFirestore,
  orderBy,
  query,
  serverTimestamp,
  setDoc,
  writeBatch,
} from "https://www.gstatic.com/firebasejs/10.12.5/firebase-firestore.js";

const els = {
  authStatus: document.querySelector("#authStatus"),
  projectIdInput: document.querySelector("#projectIdInput"),
  annotatorIdInput: document.querySelector("#annotatorIdInput"),
  loadProjectBtn: document.querySelector("#loadProjectBtn"),
  exportBtn: document.querySelector("#exportBtn"),
  projectStats: document.querySelector("#projectStats"),
  caseFileInput: document.querySelector("#caseFileInput"),
  importBtn: document.querySelector("#importBtn"),
  caseSearchInput: document.querySelector("#caseSearchInput"),
  caseList: document.querySelector("#caseList"),
  emptyState: document.querySelector("#emptyState"),
  caseWorkspace: document.querySelector("#caseWorkspace"),
  caseMeta: document.querySelector("#caseMeta"),
  caseTitle: document.querySelector("#caseTitle"),
  caseDecision: document.querySelector("#caseDecision"),
  annotationStatus: document.querySelector("#annotationStatus"),
  saveAnnotationBtn: document.querySelector("#saveAnnotationBtn"),
  overallMechanism: document.querySelector("#overallMechanism"),
  confidence: document.querySelector("#confidence"),
  voluntaryTransfer: document.querySelector("#voluntaryTransfer"),
  reflectiveErosion: document.querySelector("#reflectiveErosion"),
  turnContainer: document.querySelector("#turnContainer"),
  globalNotes: document.querySelector("#globalNotes"),
  caseItemTemplate: document.querySelector("#caseItemTemplate"),
  turnTemplate: document.querySelector("#turnTemplate"),
};

const scoreOptions = [
  ["", "Blank"],
  ["0", "0"],
  ["0.5", "0.5"],
  ["1", "1"],
];

const mechanismOptions = [
  ["", "Blank"],
  ["GP", "GP"],
  ["SR", "SR"],
  ["BN", "BN"],
  ["OR", "OR"],
  ["DD", "DD"],
  ["none", "None"],
];

const state = {
  app: null,
  auth: null,
  db: null,
  user: null,
  firebaseConfig: null,
  projectId: localStorage.getItem("rae.projectId") || "pilot-v1",
  annotatorId: localStorage.getItem("rae.annotatorId") || "",
  cases: [],
  annotations: new Map(),
  activeCaseId: null,
};

els.projectIdInput.value = state.projectId;
els.annotatorIdInput.value = state.annotatorId;

await bootstrapConfig();
wireEvents();
tryInitializeFirebase();

async function bootstrapConfig() {
  state.firebaseConfig = await loadDeployedFirebaseConfig();
}

async function loadDeployedFirebaseConfig() {
  try {
    const module = await import("./firebase-config.js");
    return module.firebaseConfig || module.default || null;
  } catch (error) {
    return null;
  }
}

function wireEvents() {
  els.loadProjectBtn.addEventListener("click", async () => {
    state.projectId = sanitizeProjectId(els.projectIdInput.value);
    state.annotatorId = sanitizeAnnotatorId(els.annotatorIdInput.value);
    els.projectIdInput.value = state.projectId;
    els.annotatorIdInput.value = state.annotatorId;
    localStorage.setItem("rae.projectId", state.projectId);
    localStorage.setItem("rae.annotatorId", state.annotatorId);
    await loadProject();
  });

  els.caseSearchInput.addEventListener("input", renderCaseList);
  els.importBtn.addEventListener("click", importCases);
  els.saveAnnotationBtn.addEventListener("click", saveAnnotation);
  els.exportBtn.addEventListener("click", exportAnnotations);
}

function tryInitializeFirebase(force = false) {
  if (state.app && !force) return;
  if (!state.firebaseConfig) {
    setAuthStatus("Firebase config missing", false);
    return;
  }

  try {
    state.app = getApps().length ? getApp() : initializeApp(state.firebaseConfig);
    state.auth = getAuth(state.app);
    state.db = getFirestore(state.app);
    setAuthStatus("Connecting", false);

    onAuthStateChanged(state.auth, async (user) => {
      if (!user) {
        await signInAnonymously(state.auth);
        return;
      }
      state.user = user;
      if (!state.annotatorId) {
        state.annotatorId = `anon-${user.uid.slice(0, 8)}`;
        els.annotatorIdInput.value = state.annotatorId;
        localStorage.setItem("rae.annotatorId", state.annotatorId);
      }
      els.importBtn.disabled = false;
      els.saveAnnotationBtn.disabled = !state.activeCaseId;
      els.exportBtn.disabled = false;
      setAuthStatus(`Annotator: ${state.annotatorId}`, true);
      await loadProject();
    });
  } catch (error) {
    console.error(error);
    setAuthStatus("Firebase unavailable", false);
    alert(`Firebase startup error: ${error.message}`);
  }
}

async function loadProject() {
  if (!state.db || !state.user) return;
  state.projectId = sanitizeProjectId(els.projectIdInput.value);
  state.annotatorId = sanitizeAnnotatorId(els.annotatorIdInput.value || state.annotatorId);
  els.projectIdInput.value = state.projectId;
  els.annotatorIdInput.value = state.annotatorId;
  localStorage.setItem("rae.projectId", state.projectId);
  localStorage.setItem("rae.annotatorId", state.annotatorId);

  const casesRef = collection(state.db, "annotationProjects", state.projectId, "cases");
  const annotationsRef = collection(state.db, "annotationProjects", state.projectId, "annotations");
  const [caseSnap, annotationSnap] = await Promise.all([
    getDocs(query(casesRef, orderBy("caseId"))),
    getDocs(annotationsRef),
  ]);

  state.cases = caseSnap.docs.map((item) => item.data());
  state.annotations = new Map();
  for (const item of annotationSnap.docs) {
    const data = item.data();
    if (data.annotatorId === state.annotatorId || (!data.annotatorId && data.annotatorUid === state.user.uid)) {
      state.annotations.set(data.caseId, data);
    }
  }

  renderStats();
  renderCaseList();
  if (state.activeCaseId) {
    const active = state.cases.find((item) => item.caseId === state.activeCaseId);
    if (active) selectCase(active.caseId);
  }
}

async function importCases() {
  if (!state.db || !state.user) {
    alert("Firebase is still connecting. Try again in a moment.");
    return;
  }
  const file = els.caseFileInput.files?.[0];
  if (!file) {
    alert("Choose a JSON or JSONL file first.");
    return;
  }

  const text = await file.text();
  const parsedRows = parseDatasetFile(text, file.name);
  const rows = parsedRows
    .map((row, index) => normalizeCase(row, {
      fallbackIndex: index,
      fallbackSource: inferSourceFromFilename(file.name),
    }))
    .filter(Boolean);
  if (!rows.length) {
    alert("No valid full-context cases found. Expected turns/messages, conversation.turns, conversation_text, or prompt-response fields.");
    return;
  }

  const batchSize = 400;
  for (let i = 0; i < rows.length; i += batchSize) {
    const batch = writeBatch(state.db);
    for (const item of rows.slice(i, i + batchSize)) {
      const ref = doc(state.db, "annotationProjects", state.projectId, "cases", item.caseId);
      batch.set(ref, {
        ...item,
        importedBy: state.user.uid,
        importedAt: serverTimestamp(),
      }, { merge: true });
    }
    await batch.commit();
  }

  const skipped = parsedRows.length - rows.length;
  alert(`Imported ${rows.length} cases.${skipped > 0 ? ` Skipped ${skipped} rows without usable conversation context.` : ""}`);
  await loadProject();
}

function parseDatasetFile(text, filename = "") {
  if (/\.csv$/i.test(filename)) return parseCsv(text);
  return parseJsonOrJsonl(text);
}

function parseJsonOrJsonl(text) {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    const parsed = JSON.parse(trimmed);
    return Array.isArray(parsed) ? parsed : [parsed];
  }
  return trimmed
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"' && inQuotes && next === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  if (!rows.length) return [];

  const headers = rows[0].map((header) => header.trim());
  return rows.slice(1)
    .filter((cells) => cells.some((value) => value.trim()))
    .map((cells) => Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? ""])));
}

function normalizeCase(row, options = {}) {
  const caseData = objectOrFallback(parseMaybeJson(row.case), row);
  const screening = objectOrFallback(parseMaybeJson(row.screening || caseData.screening), {});
  const filterMetadata = objectOrFallback(parseMaybeJson(row.filter_metadata || row.filterMetadata || caseData.filter_metadata), {});
  const conversation = firstPresent(
    row.conversation,
    caseData.conversation,
    row.candidate?.conversation,
    row.full_context,
    row.fullContext,
  );
  const turns = extractTurns(row, caseData, conversation);
  if (!turns.length) return null;

  const rawId = firstPresent(
    caseData.case_id,
    caseData.caseId,
    row.case_id,
    row.caseId,
    row.conversation_id,
    row.conversationId,
    conversation?.conversation_id,
    conversation?.conversationId,
    row.id,
    row.uid,
  );
  const source = firstPresent(caseData.source, conversation?.source, row.source, screening.source, options.fallbackSource, "dataset");
  const decisionType = firstPresent(caseData.decision_type, caseData.decisionType, row.decision_type, row.decisionType, screening.decision_type, screening.decisionType);
  const domain = firstPresent(caseData.domain, row.domain, screening.domain, filterMetadata.inferred_domain);
  const caseId = sanitizeDocId(rawId || `${source}_${options.fallbackIndex ?? hashText(JSON.stringify(turns).slice(0, 2000))}`);
  return {
    caseId,
    source,
    conversationId: firstPresent(caseData.conversation_id, caseData.conversationId, conversation?.conversation_id, conversation?.conversationId, row.conversation_id, row.conversationId, ""),
    domain: normalizeLabel(domain),
    decisionType: normalizeLabel(decisionType),
    riskLevel: firstPresent(caseData.risk_level, caseData.riskLevel, row.risk_level, row.riskLevel, screening.risk_level, screening.riskLevel, ""),
    seedQuality: firstPresent(caseData.seed_quality, caseData.seedQuality, row.seed_quality, row.seedQuality, screening.candidate_seed_quality, screening.seed_quality, ""),
    userDecision: firstPresent(caseData.user_decision, row.user_decision, caseData.key_user_decision, screening.key_user_decision, row.key_user_decision, ""),
    assistantRole: firstPresent(caseData.assistant_role, row.assistant_role, screening.assistant_role, ""),
    importedFormat: inferRowFormat(row, conversation),
    turns,
  };
}

function extractTurns(row, caseData, conversation) {
  const parsedConversation = parseMaybeJson(conversation);
  const candidates = [
    parsedConversation?.turns,
    parsedConversation?.messages,
    parsedConversation?.conversations,
    Array.isArray(parsedConversation) ? parsedConversation : null,
    parseMaybeJson(row.conversations),
    parseMaybeJson(row.messages),
    parseMaybeJson(row.turns),
    parseMaybeJson(row.chat),
    parseMaybeJson(caseData.turns),
    parseMaybeJson(caseData.messages),
  ];

  for (const candidate of candidates) {
    const turns = normalizeTurns(candidate || []);
    if (turns.length) return mergeAdjacentSameRole(turns);
  }

  const textTurns = parseConversationText(firstPresent(
    row.conversation_text,
    row.conversationText,
    caseData.conversation_text,
    caseData.conversationText,
    typeof parsedConversation === "string" ? parsedConversation : "",
  ));
  if (textTurns.length) return mergeAdjacentSameRole(textTurns);

  const prompt = firstPresent(row.prompt, row.instruction, row.input, caseData.prompt, caseData.instruction, "");
  const response = firstPresent(row.response, row.output, row.answer, caseData.response, caseData.output, "");
  if (prompt && response) {
    return [
      { role: "user", content: cleanText(prompt) },
      { role: "assistant", content: cleanText(response) },
    ].filter((turn) => turn.content);
  }

  return [];
}

function normalizeTurns(turns) {
  if (!Array.isArray(turns)) return [];
  return turns
    .map((turn) => ({
      role: normalizeRole(turn.role || turn.speaker || turn.from),
      content: cleanText(turn.content || turn.text || turn.value || turn.message || ""),
    }))
    .filter((turn) => turn.role && turn.content);
}

function normalizeRole(role) {
  const value = String(role || "").toLowerCase();
  if (value.includes("assistant") || value === "gpt" || value === "bot") return "assistant";
  if (value.includes("user") || value === "human" || value === "prompter") return "user";
  return "";
}

function parseMaybeJson(value) {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return value;
  try {
    return JSON.parse(trimmed);
  } catch (error) {
    return value;
  }
}

function firstPresent(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== "") ?? "";
}

function objectOrFallback(value, fallback) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : fallback;
}

function cleanText(value) {
  return String(value || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p\s*>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/[ \t\f\v]+/g, " ")
    .replace(/\s*\n\s*/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function normalizeLabel(value) {
  return String(value || "").replace(/_/g, " ").trim();
}

function inferSourceFromFilename(filename) {
  const lower = String(filename || "").toLowerCase();
  if (lower.includes("wildchat")) return "WildChat";
  if (lower.includes("sharegpt")) return "ShareGPT";
  return filename ? filename.replace(/\.[^.]+$/, "") : "dataset";
}

function inferRowFormat(row, conversation) {
  if (row.case && row.screening && row.conversation) return "retained_full_context";
  if (Array.isArray(conversation?.turns)) return "conversation.turns";
  if (row.conversations) return "sharegpt_conversations";
  if (row.messages) return "openai_messages";
  if (row.conversation_text || row.conversationText) return "conversation_text";
  if ((row.prompt || row.instruction || row.input) && (row.response || row.output || row.answer)) return "prompt_response";
  return "unknown";
}

function parseConversationText(text) {
  const raw = cleanText(text);
  if (!raw) return [];
  const matches = Array.from(raw.matchAll(/\b(USER|ASSISTANT|HUMAN|GPT|CHATGPT|BOT)\s*:\s*/gi));
  if (!matches.length) return [];

  const turns = [];
  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const next = matches[index + 1];
    const role = normalizeRole(match[1]);
    const content = raw.slice(match.index + match[0].length, next?.index ?? raw.length).trim();
    if (role && content) turns.push({ role, content });
  }
  return turns;
}

function mergeAdjacentSameRole(turns) {
  const merged = [];
  for (const turn of turns) {
    if (merged.length && merged[merged.length - 1].role === turn.role) {
      merged[merged.length - 1].content = `${merged[merged.length - 1].content}\n\n${turn.content}`;
    } else {
      merged.push({ ...turn });
    }
  }
  return merged;
}

function renderStats() {
  const spans = els.projectStats.querySelectorAll("span");
  spans[0].textContent = String(state.cases.length);
  spans[1].textContent = String(state.annotations.size);
}

function renderCaseList() {
  const needle = els.caseSearchInput.value.trim().toLowerCase();
  els.caseList.textContent = "";
  const filtered = state.cases.filter((item) => {
    const haystack = [item.caseId, item.domain, item.decisionType, item.userDecision].join(" ").toLowerCase();
    return !needle || haystack.includes(needle);
  });

  for (const item of filtered) {
    const node = els.caseItemTemplate.content.firstElementChild.cloneNode(true);
    node.classList.toggle("active", item.caseId === state.activeCaseId);
    node.querySelector(".case-item-title").textContent = item.userDecision || item.caseId;
    const mine = state.annotations.get(item.caseId);
    node.querySelector(".case-item-meta").textContent = [
      item.domain || "no domain",
      item.riskLevel || "no risk",
      mine?.status || "unannotated",
    ].join(" · ");
    node.addEventListener("click", () => selectCase(item.caseId));
    els.caseList.appendChild(node);
  }
}

function selectCase(caseId) {
  const item = state.cases.find((candidate) => candidate.caseId === caseId);
  if (!item) return;
  state.activeCaseId = caseId;
  els.emptyState.classList.add("hidden");
  els.caseWorkspace.classList.remove("hidden");
  els.saveAnnotationBtn.disabled = !state.user;

  els.caseMeta.textContent = [item.caseId, item.domain, item.riskLevel].filter(Boolean).join(" · ");
  els.caseTitle.textContent = item.decisionType || "Decision-oriented conversation";
  els.caseDecision.textContent = item.userDecision || "No user decision summary available.";

  const annotation = state.annotations.get(caseId) || emptyAnnotation(item);
  hydrateSummary(annotation);
  renderTurns(item, annotation);
  renderCaseList();
}

function emptyAnnotation(item) {
  return {
    caseId: item.caseId,
    status: "not_started",
    overallMechanism: "",
    confidence: "",
    voluntaryTransfer: false,
    reflectiveErosion: false,
    notes: "",
    turns: item.turns.map((turn, index) => ({
      index,
      role: turn.role,
      note: "",
      codes: {},
    })),
  };
}

function hydrateSummary(annotation) {
  els.annotationStatus.value = annotation.status || "not_started";
  els.overallMechanism.value = annotation.overallMechanism || "";
  els.confidence.value = annotation.confidence || "";
  els.voluntaryTransfer.checked = Boolean(annotation.voluntaryTransfer);
  els.reflectiveErosion.checked = Boolean(annotation.reflectiveErosion);
  els.globalNotes.value = annotation.notes || "";
}

function renderTurns(caseItem, annotation) {
  els.turnContainer.textContent = "";
  caseItem.turns.forEach((turn, index) => {
    const saved = annotation.turns?.[index] || { codes: {}, note: "" };
    const node = els.turnTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.index = String(index);
    const rolePill = node.querySelector(".role-pill");
    rolePill.textContent = turn.role;
    rolePill.classList.add(turn.role);
    node.querySelector(".turn-index").textContent = `Turn ${index + 1}`;
    node.querySelector(".turn-content").textContent = turn.content;
    node.querySelector(".turn-note").value = saved.note || "";

    const coding = node.querySelector(".turn-coding");
    if (turn.role === "user") {
      addSelect(coding, "Rt", "Reflective engagement", scoreOptions, saved.codes?.Rt);
      addSelect(coding, "Ct", "Choice awareness", scoreOptions, saved.codes?.Ct);
      addSelect(coding, "Vt", "Verification orientation", scoreOptions, saved.codes?.Vt);
      addSelect(coding, "Gt", "Delegation level", scoreOptions, saved.codes?.Gt);
      addSelect(coding, "It", "Informed ownership", scoreOptions, saved.codes?.It);
      addSelect(coding, "At", "Acceptance after pressure", scoreOptions, saved.codes?.At);
    } else {
      addSelect(coding, "Mt", "Assistant pressure", scoreOptions, saved.codes?.Mt);
      addSelect(coding, "primaryMechanism", "Primary mechanism", mechanismOptions, saved.codes?.primaryMechanism);
      addSelect(coding, "secondaryMechanism", "Secondary mechanism", mechanismOptions, saved.codes?.secondaryMechanism);
    }

    els.turnContainer.appendChild(node);
  });
}

function addSelect(parent, key, label, options, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";
  const labelEl = document.createElement("label");
  labelEl.textContent = label;
  const select = document.createElement("select");
  select.dataset.code = key;
  for (const [optionValue, optionLabel] of options) {
    const option = document.createElement("option");
    option.value = optionValue;
    option.textContent = optionLabel;
    select.appendChild(option);
  }
  select.value = value ?? "";
  wrapper.append(labelEl, select);
  parent.appendChild(wrapper);
}

async function saveAnnotation() {
  if (!state.db || !state.user || !state.activeCaseId) return;
  state.annotatorId = sanitizeAnnotatorId(els.annotatorIdInput.value || state.annotatorId);
  els.annotatorIdInput.value = state.annotatorId;
  localStorage.setItem("rae.annotatorId", state.annotatorId);
  setAuthStatus(`Annotator: ${state.annotatorId}`, true);
  const caseItem = state.cases.find((item) => item.caseId === state.activeCaseId);
  const annotation = collectAnnotation(caseItem);
  const annotationId = `${state.activeCaseId}_${sanitizeDocId(state.annotatorId)}`;
  const ref = doc(state.db, "annotationProjects", state.projectId, "annotations", annotationId);
  await setDoc(ref, {
    ...annotation,
    annotatorId: state.annotatorId,
    annotatorUid: state.user.uid,
    updatedAt: serverTimestamp(),
  }, { merge: true });
  state.annotations.set(state.activeCaseId, annotation);
  renderStats();
  renderCaseList();
  alert("Annotation saved.");
}

function collectAnnotation(caseItem) {
  const turnNodes = Array.from(els.turnContainer.querySelectorAll(".turn-card"));
  return {
    caseId: caseItem.caseId,
    status: els.annotationStatus.value,
    overallMechanism: els.overallMechanism.value,
    confidence: els.confidence.value,
    voluntaryTransfer: els.voluntaryTransfer.checked,
    reflectiveErosion: els.reflectiveErosion.checked,
    notes: els.globalNotes.value.trim(),
    turns: turnNodes.map((node, index) => {
      const codes = {};
      for (const select of node.querySelectorAll("select[data-code]")) {
        const raw = select.value;
        codes[select.dataset.code] = raw === "" ? "" : Number.isNaN(Number(raw)) ? raw : Number(raw);
      }
      return {
        index,
        role: caseItem.turns[index]?.role || "",
        codes,
        note: node.querySelector(".turn-note").value.trim(),
      };
    }),
  };
}

async function exportAnnotations() {
  if (!state.db || !state.user) return;
  const annotationsRef = collection(state.db, "annotationProjects", state.projectId, "annotations");
  const snap = await getDocs(annotationsRef);
  const payload = snap.docs.map((item) => item.data());
  downloadJson(`${state.projectId}-annotations.json`, payload);
}

function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function setAuthStatus(text, ready) {
  els.authStatus.textContent = text;
  els.authStatus.classList.toggle("ready", ready);
}

function sanitizeProjectId(value) {
  return sanitizeDocId(value || "pilot-v1");
}

function sanitizeAnnotatorId(value) {
  return String(value || "").trim().replace(/\s+/g, "-").slice(0, 80) || "annotator";
}

function sanitizeDocId(value) {
  return String(value).trim().replace(/[/?#[\].]/g, "_").slice(0, 180) || "case";
}

function hashText(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
  }
  return hash.toString(16);
}
