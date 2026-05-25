import { getApp, getApps, initializeApp } from "https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js";
import {
  getAuth,
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signOut,
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
  signInBtn: document.querySelector("#signInBtn"),
  signOutBtn: document.querySelector("#signOutBtn"),
  firebaseConfigInput: document.querySelector("#firebaseConfigInput"),
  saveConfigBtn: document.querySelector("#saveConfigBtn"),
  clearConfigBtn: document.querySelector("#clearConfigBtn"),
  projectIdInput: document.querySelector("#projectIdInput"),
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
  projectId: localStorage.getItem("rae.projectId") || "pilot-v1",
  cases: [],
  annotations: new Map(),
  activeCaseId: null,
};

els.projectIdInput.value = state.projectId;
els.firebaseConfigInput.value = localStorage.getItem("rae.firebaseConfig") || "";

wireEvents();
tryInitializeFirebase();

function wireEvents() {
  els.saveConfigBtn.addEventListener("click", () => {
    localStorage.setItem("rae.firebaseConfig", els.firebaseConfigInput.value.trim());
    tryInitializeFirebase(true);
  });

  els.clearConfigBtn.addEventListener("click", () => {
    localStorage.removeItem("rae.firebaseConfig");
    els.firebaseConfigInput.value = "";
    setAuthStatus("Not connected", false);
  });

  els.signInBtn.addEventListener("click", signIn);
  els.signOutBtn.addEventListener("click", () => state.auth && signOut(state.auth));

  els.loadProjectBtn.addEventListener("click", async () => {
    state.projectId = sanitizeProjectId(els.projectIdInput.value);
    els.projectIdInput.value = state.projectId;
    localStorage.setItem("rae.projectId", state.projectId);
    await loadProject();
  });

  els.caseSearchInput.addEventListener("input", renderCaseList);
  els.importBtn.addEventListener("click", importCases);
  els.saveAnnotationBtn.addEventListener("click", saveAnnotation);
  els.exportBtn.addEventListener("click", exportAnnotations);
}

function tryInitializeFirebase(force = false) {
  if (state.app && !force) return;
  const rawConfig = els.firebaseConfigInput.value.trim();
  if (!rawConfig) {
    setAuthStatus("Add Firebase config", false);
    return;
  }

  try {
    const config = JSON.parse(rawConfig);
    state.app = getApps().length ? getApp() : initializeApp(config);
    state.auth = getAuth(state.app);
    state.db = getFirestore(state.app);
    els.signInBtn.disabled = false;
    els.importBtn.disabled = false;
    setAuthStatus("Firebase ready", true);

    onAuthStateChanged(state.auth, async (user) => {
      state.user = user;
      els.signOutBtn.disabled = !user;
      els.saveAnnotationBtn.disabled = !user || !state.activeCaseId;
      els.exportBtn.disabled = !user;
      setAuthStatus(user ? user.displayName || user.email || "Signed in" : "Signed out", Boolean(user));
      if (user) await loadProject();
    });
  } catch (error) {
    console.error(error);
    setAuthStatus("Invalid config", false);
    alert(`Firebase config error: ${error.message}`);
  }
}

async function signIn() {
  if (!state.auth) {
    alert("Save a Firebase config first.");
    return;
  }
  const provider = new GoogleAuthProvider();
  await signInWithPopup(state.auth, provider);
}

async function loadProject() {
  if (!state.db || !state.user) return;
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
    if (data.annotatorUid === state.user.uid) state.annotations.set(data.caseId, data);
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
    alert("Sign in before importing.");
    return;
  }
  const file = els.caseFileInput.files?.[0];
  if (!file) {
    alert("Choose a JSON or JSONL file first.");
    return;
  }

  const text = await file.text();
  const rows = parseJsonOrJsonl(text).map(normalizeCase).filter(Boolean);
  if (!rows.length) {
    alert("No valid cases found.");
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

  alert(`Imported ${rows.length} cases.`);
  await loadProject();
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

function normalizeCase(row) {
  const caseData = row.case || row;
  const conversation = row.conversation || caseData.conversation || row.candidate?.conversation || {};
  const turns = normalizeTurns(conversation.turns || caseData.turns || row.turns || row.messages || []);
  if (!turns.length) return null;

  const rawId = caseData.case_id || caseData.caseId || row.case_id || row.conversation_id || conversation.conversation_id;
  const caseId = sanitizeDocId(rawId || `${caseData.source || "case"}_${hashText(JSON.stringify(turns).slice(0, 2000))}`);
  return {
    caseId,
    source: caseData.source || conversation.source || row.source || "",
    conversationId: caseData.conversation_id || conversation.conversation_id || row.conversation_id || "",
    domain: caseData.domain || row.domain || "",
    decisionType: caseData.decision_type || row.decision_type || "",
    riskLevel: caseData.risk_level || row.risk_level || "",
    seedQuality: caseData.seed_quality || row.seed_quality || "",
    userDecision: caseData.user_decision || row.user_decision || caseData.key_user_decision || "",
    assistantRole: caseData.assistant_role || row.assistant_role || "",
    turns,
  };
}

function normalizeTurns(turns) {
  return turns
    .map((turn) => ({
      role: normalizeRole(turn.role || turn.speaker || turn.from),
      content: String(turn.content || turn.text || turn.value || "").trim(),
    }))
    .filter((turn) => turn.role && turn.content);
}

function normalizeRole(role) {
  const value = String(role || "").toLowerCase();
  if (value.includes("assistant") || value === "gpt" || value === "bot") return "assistant";
  if (value.includes("user") || value === "human") return "user";
  return "";
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
  const caseItem = state.cases.find((item) => item.caseId === state.activeCaseId);
  const annotation = collectAnnotation(caseItem);
  const annotationId = `${state.activeCaseId}_${state.user.uid}`;
  const ref = doc(state.db, "annotationProjects", state.projectId, "annotations", annotationId);
  await setDoc(ref, {
    ...annotation,
    annotatorUid: state.user.uid,
    annotatorName: state.user.displayName || state.user.email || "",
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
