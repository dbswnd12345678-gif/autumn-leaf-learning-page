// 3개 탭: assess(사전 과제), offload(탭 2 AI 과제), support(사후 과제).
// 탭 2는 주소의 group=A(생성형 AI) 또는 group=B(AI Agent)에 따라 달라진다.
// 서버가 모드별 세션과 사진을 정한다. 제한 시간은 SESSION_SECONDS가 0보다 클 때만 흐른다.
const MODES = {
  assess: {
    subtitle: "사진을 보고 관찰한 내용을 문장으로 적어보세요. 여러 문장을 쓸 수 있어요.",
    hint: "※ 사진에서 보이는 것을 한 문장씩 적어 주세요. 다 쓰면 최종 제출을 누르세요.",
    startTitle: "탭 1 · 사전 과제",
    startDesc: "단풍잎 사진을 보고 관찰한 내용을 문장으로 적습니다.\n다 쓰면 최종 제출을 누르세요.",
    startDescTimed: "단풍잎 사진을 보고 관찰한 내용을 문장으로 적습니다. 시작하면 제한 시간이 흐르고, 시간이 끝나면 자동으로 제출돼요.",
    chat: false,
    sentenceToAI: false,
    sentenceTip: "AI 없이 직접 관찰하세요.",
  },
  offload: {
    subtitle: "생성형 AI에게 질문하거나 요청하면서 단풍잎을 관찰합니다. 관찰 문장은 따로 적어 제출합니다.",
    hint: "※ AI에게 무엇이든 물어봐도 돼요. 관찰 문장은 아래 입력란에 따로 적어요. 질문할 때 AI는 적어 둔 문장을 알고 답해요.",
    startTitle: "탭 2 · 생성형 AI 활용 과제",
    startDesc: "생성형 AI에게 질문하거나 요청하며 단풍잎을 관찰합니다. 관찰한 내용은 '내 관찰 문장'에 적어 최종 제출하세요.",
    startDescTimed: "생성형 AI에게 질문하거나 요청하며 단풍잎을 관찰합니다. 관찰한 내용은 '내 관찰 문장'에 적어 최종 제출하세요. 시작하면 제한 시간이 흐릅니다.",
    chat: true,
    sentenceToAI: false,
    greeting: "안녕하세요. 단풍잎 관찰을 도와드릴게요. 궁금한 것이나 부탁할 것을 자유롭게 말해 주세요.",
    chatPlaceholder: "AI에게 질문하거나 요청하세요... (Enter 전송, Shift+Enter 줄바꿈)",
    sentenceTip: "AI 답변과 별개로, 내가 관찰한 내용을 적어요.",
  },
  support: {
    subtitle: "사진을 보고 관찰한 내용을 문장으로 적어보세요. 여러 문장을 쓸 수 있어요.",
    hint: "※ 사진에서 보이는 것을 한 문장씩 적어 주세요. 다 쓰면 최종 제출을 누르세요.",
    startTitle: "탭 3 · 사후 과제",
    startDesc: "단풍잎 사진을 보고 관찰한 내용을 문장으로 적습니다.\n다 쓰면 최종 제출을 누르세요.",
    startDescTimed: "단풍잎 사진을 보고 관찰한 내용을 문장으로 적습니다. 시작하면 제한 시간이 흐르고, 시간이 끝나면 자동으로 제출돼요.",
    chat: false,
    sentenceToAI: false,
    sentenceTip: "AI 없이 직접 관찰하세요.",
  },
};
const MODE_ORDER = ["assess", "offload", "support"];

function urlGroup() {
  const value = new URLSearchParams(location.search).get("group") || "";
  const code = value.trim().toUpperCase();
  return code === "A" || code === "B" ? code : "";
}

let studyGroup = urlGroup() || localStorage.getItem("autumn_leaf_group") || "";

function applyStudyGroup(group, mismatch = false) {
  if (group === "A" || group === "B") {
    studyGroup = group;
    localStorage.setItem("autumn_leaf_group", group);
  }
  const tab2 = document.querySelector('.lesson-tab[data-mode="offload"]');
  const spec = MODES.offload;
  if (studyGroup === "B") {
    if (tab2) tab2.textContent = "탭 2 AI Agent 활용 과제";
    spec.subtitle = "AI 도우미에게 질문하면서 단풍잎을 관찰합니다. 관찰 문장은 직접 적고, 물어본 내용에만 도우미가 답해요.";
    spec.hint = "※ 관찰 문장은 아래 입력란에 직접 적어요. 궁금한 것은 위쪽 대화창에 물어보세요. 물어볼 때 도우미는 적어 둔 문장을 알고 답해요.";
    spec.startTitle = "탭 2 · AI Agent 활용 과제";
    spec.startDesc = "사진을 고를 때마다, 혼자 할 수 있는 관찰을 먼저 고르고 시작합니다.\n관찰 문장은 직접 적고, 필요할 때만 AI 도우미에게 물어보세요.";
    spec.startDescTimed = "사진을 고를 때마다, 혼자 할 수 있는 관찰을 먼저 고르고 시작합니다. 관찰 문장은 직접 적고, 필요할 때만 AI 도우미에게 물어보세요. 시작하면 제한 시간이 흐릅니다.";
    spec.sentenceToAI = false;
    spec.greeting = "안녕하세요! 저는 관찰 도우미예요. 관찰 문장은 아래에 직접 적어 주세요. 궁금한 점이 있으면 여기에 물어보세요.";
    spec.chatPlaceholder = "AI 도우미에게 질문하세요... (Enter 전송, Shift+Enter 줄바꿈)";
    spec.sentenceTip = "관찰한 내용을 직접 적어요.";
  } else if (studyGroup === "A") {
    if (tab2) tab2.textContent = "탭 2 생성형 AI 활용 과제";
    spec.subtitle = "생성형 AI에게 질문하거나 요청하면서 단풍잎을 관찰합니다. 관찰 문장은 따로 적어 제출합니다.";
    spec.hint = "※ AI에게 무엇이든 물어봐도 돼요. 관찰 문장은 아래 입력란에 따로 적어요. 질문할 때 AI는 적어 둔 문장을 알고 답해요.";
    spec.startTitle = "탭 2 · 생성형 AI 활용 과제";
    spec.startDesc = "생성형 AI에게 질문하거나 요청하며 단풍잎을 관찰합니다. 관찰한 내용은 '내 관찰 문장'에 적어 최종 제출하세요.";
    spec.startDescTimed = "생성형 AI에게 질문하거나 요청하며 단풍잎을 관찰합니다. 관찰한 내용은 '내 관찰 문장'에 적어 최종 제출하세요. 시작하면 제한 시간이 흐릅니다.";
    spec.sentenceToAI = false;
    spec.greeting = "안녕하세요. 단풍잎 관찰을 도와드릴게요. 궁금한 것이나 부탁할 것을 자유롭게 말해 주세요.";
    spec.chatPlaceholder = "AI에게 질문하거나 요청하세요... (Enter 전송, Shift+Enter 줄바꿈)";
    spec.sentenceTip = "AI 답변과 별개로, 내가 관찰한 내용을 적어요.";
  } else if (tab2) {
    tab2.textContent = "탭 2 AI 활용 과제";
  }
  if (mismatch && studyGroup) {
    const label = studyGroup === "B" ? "실험군(B)" : "대조군(A)";
    showNotice(`이 학번은 ${label}으로 배정되어 있어 그 과제가 열립니다.`);
  }
}

const $ = (id) => document.getElementById(id);
const mainImage = $("main-image");
const chatLog = $("chat-log");
const chatForm = $("chat-form");
const chatInput = $("chat-input");
const sendBtn = $("send-btn");
const sentenceForm = $("sentence-form");
const sentenceInput = $("sentence-input");
const sentenceAddBtn = $("sentence-add-btn");
const sentenceList = $("sentence-list");
const sentenceCount = $("sentence-count");
const sentenceScope = $("sentence-scope");
const chatScope = $("chat-scope");
const observeSingleBtn = $("observe-single-btn");
const observeCompareBtn = $("observe-compare-btn");
const submitBtn = $("submit-btn");
const submitStatus = $("submit-status");
const startCard = $("start-card");
const startBtn = $("start-btn");
const startMsg = $("start-msg");
const workArea = $("work-area");
const timerEl = $("timer");
const noticeEl = $("notice");
const studentIdInput = $("student-id-input");
const studentIdSaveBtn = $("student-id-save-btn");
const studentIdStatus = $("student-id-status");

let currentMode = localStorage.getItem("autumn_leaf_mode_v3") || "assess";
if (!MODES[currentMode]) currentMode = "assess";
let serverStatus = null; // /api/session/status 응답의 modes
let timerBase = { mode: null, seconds: 0, at: 0 };
let submitting = false;
let chatBusy = false;
const imagePicker = $("image-picker");

// ---------------------------------------------------------------------------
// 학번, 브라우저 세션
// ---------------------------------------------------------------------------
function getSessionId() {
  let sid = localStorage.getItem("autumn_leaf_session_id");
  if (!sid) {
    sid = "session-" + Math.random().toString(36).slice(2) + Date.now();
    localStorage.setItem("autumn_leaf_session_id", sid);
  }
  return sid;
}
const sessionId = getSessionId();

function getStudentId() {
  return localStorage.getItem("autumn_leaf_student_id") || "";
}

function updateStudentIdStatus() {
  const id = getStudentId();
  if (id) {
    studentIdInput.value = id;
    studentIdStatus.textContent = `현재 학번: ${id}`;
    studentIdStatus.classList.remove("student-id-missing");
  } else {
    studentIdStatus.textContent = "학번을 입력하고 확인을 눌러주세요.";
    studentIdStatus.classList.add("student-id-missing");
  }
}

studentIdSaveBtn.addEventListener("click", async () => {
  const value = studentIdInput.value.trim();
  if (!value) {
    studentIdStatus.textContent = "학번을 입력해주세요.";
    return;
  }
  if (anyInProgress() && value !== getStudentId()) {
    showNotice("진행 중에는 학번을 바꿀 수 없어요.");
    return;
  }
  localStorage.setItem("autumn_leaf_student_id", value);
  updateStudentIdStatus();
  await refresh();
});

// ---------------------------------------------------------------------------
// 서버 통신
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {} };
  if (options.body) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, init);
  let data = {};
  try {
    data = await res.json();
  } catch (e) {
    data = {};
  }
  if (!res.ok) {
    const err = new Error(data.error || "오류가 발생했습니다.");
    err.status = res.status;
    throw err;
  }
  return data;
}

async function fetchStatus() {
  const studentId = getStudentId();
  if (!studentId) {
    serverStatus = null;
    return;
  }
  const params = new URLSearchParams({ studentId });
  const requested = urlGroup();
  if (requested) params.set("group", requested);
  const data = await api(`/api/session/status?${params.toString()}`);
  serverStatus = data.modes;
  applyStudyGroup(data.group || "", !!data.groupMismatch);
}

function modeInfo(mode) {
  return serverStatus ? serverStatus[mode] : null;
}

function anyInProgress() {
  return MODE_ORDER.some((m) => modeInfo(m)?.status === "in_progress");
}

// ---------------------------------------------------------------------------
// 안내 문구
// ---------------------------------------------------------------------------
let noticeTimer = null;
function showNotice(text) {
  noticeEl.textContent = text;
  noticeEl.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => {
    noticeEl.hidden = true;
  }, 5000);
}

// ---------------------------------------------------------------------------
// 로컬 저장: 새로고침해도 문장과 대화가 사라지지 않게 한다.
// ---------------------------------------------------------------------------
function storeKey(kind, mode) {
  return `autumn_${kind}_v3_${getStudentId()}_${mode}`;
}

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) || fallback;
  } catch (e) {
    return fallback;
  }
}

function loadSentences(mode = currentMode) {
  return loadJson(storeKey("sentences", mode), []);
}

function saveSentences(list, mode = currentMode) {
  localStorage.setItem(storeKey("sentences", mode), JSON.stringify(list));
}

// 대화는 사진(또는 비교 쌍)마다 따로 둔다. AnythingLLM sessionId도 같은 키를 쓴다.
function photoThreadKey(mode = currentMode) {
  const picked = selectedImages(mode);
  if (!picked.length) return "none";
  if (picked.length === 1) return picked[0];
  return pairKey(picked, mode);
}

// 실험군 탭 2: 사진(또는 비교 쌍)마다, 관찰 전에 혼자 할 수 있는 관찰을 고른다.
const META_ABILITIES = [
  { id: "whole", label: "잎의 전체 특성을 관찰" },
  { id: "part", label: "잎의 일부분을 관찰" },
  { id: "one", label: "잎 하나를 관찰", compareOnly: true },
  { id: "many", label: "잎 여러개를 비교한 관찰", compareOnly: true },
  { id: "qualitative", label: "정성적인 관찰", groupBreak: true },
  { id: "quantitative", label: "정량적인 관찰" },
];
let metaDraftKey = "";
let metaDraft = new Set();

function metaApplies() {
  return currentMode === "offload" && studyGroup === "B";
}

function loadMetaMap(mode = currentMode) {
  const saved = loadJson(storeKey("meta", mode), {});
  return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
}

function currentMetaRecord() {
  return loadMetaMap()[photoThreadKey()] || null;
}

function metaGateActive() {
  return metaApplies() && modeInfo(currentMode)?.status === "in_progress" && !currentMetaRecord();
}

function canEditObservation() {
  return modeInfo(currentMode)?.status === "in_progress" && !metaGateActive();
}

function syncObservationLock() {
  const editable = canEditObservation();
  if (sentenceInput) sentenceInput.disabled = !editable;
  if (sentenceAddBtn) sentenceAddBtn.disabled = !editable;
  if (chatInput) chatInput.disabled = !editable;
  if (sendBtn) sendBtn.disabled = !editable;
  if (submitBtn) submitBtn.disabled = modeInfo(currentMode)?.status !== "in_progress";
}

function metaAbilitiesForView() {
  const compare = compareWanted();
  return META_ABILITIES.filter((item) => !item.compareOnly || compare);
}

function ensureMetaOptions() {
  const box = $("meta-options");
  if (!box || box.childElementCount) return;
  META_ABILITIES.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "meta-option" + (item.groupBreak || item.id === "one" ? " meta-option-break" : "");
    btn.dataset.ability = item.id;
    btn.textContent = item.label;
    btn.setAttribute("aria-pressed", "false");
    btn.addEventListener("click", () => {
      if (metaDraft.has(item.id)) metaDraft.delete(item.id);
      else metaDraft.add(item.id);
      btn.setAttribute("aria-pressed", metaDraft.has(item.id) ? "true" : "false");
    });
    box.appendChild(btn);
  });
}

function syncMetaOptionVisibility() {
  ensureMetaOptions();
  const visible = new Set(metaAbilitiesForView().map((item) => item.id));
  document.querySelectorAll(".meta-option").forEach((btn) => {
    const show = visible.has(btn.dataset.ability);
    btn.hidden = !show;
    if (!show && metaDraft.has(btn.dataset.ability)) {
      metaDraft.delete(btn.dataset.ability);
      btn.setAttribute("aria-pressed", "false");
    }
  });
}

function metaResultText(record, sentenceCount, twoPhotos) {
  const labels = META_ABILITIES.filter((item) => (record.abilities || []).includes(item.id)).map((item) => item.label);
  const place = twoPhotos ? "이 두 사진에서는" : "이 사진에서는";
  const expected = labels.length
    ? `혼자 할 수 있다고 예상한 것은 ${labels.join(", ")}입니다.`
    : `${place} 혼자 하기 어렵다고 예상했습니다.`;
  const actual = sentenceCount > 0
    ? `지금까지 직접 쓴 문장은 ${sentenceCount}개입니다.`
    : "아직 직접 쓴 문장은 없습니다.";
  return `${expected} ${actual}`;
}

function renderMetaGate() {
  const gate = $("meta-check");
  const result = $("meta-result");
  if (!gate || !result) return;
  const active = metaGateActive();
  workArea.classList.toggle("is-meta-gate", active);
  gate.hidden = !active;
  if (active) {
    syncMetaOptionVisibility();
    const key = photoThreadKey();
    if (metaDraftKey !== key) {
      metaDraftKey = key;
      metaDraft = new Set();
      document.querySelectorAll(".meta-option").forEach((btn) => btn.setAttribute("aria-pressed", "false"));
    }
    const two = selectedImages().length === 2;
    $("meta-check-title").textContent = `${selectionTitle()} 관찰을 시작하기 전에`;
    $("meta-check-lead").textContent = two
      ? "이 두 사진에서 내가 혼자 할 수 있는 관찰을 고르세요. AI에게 맡기지 않고 직접 쓸 수 있다고 생각하는 것만 고르면 됩니다."
      : "이 사진에서 내가 혼자 할 수 있는 관찰을 고르세요. AI에게 맡기지 않고 직접 쓸 수 있다고 생각하는 것만 고르면 됩니다.";
    result.hidden = true;
    return;
  }
  const record = metaApplies() ? currentMetaRecord() : null;
  const showResult = !!record && !workArea.hidden;
  result.hidden = !showResult;
  if (showResult) {
    result.textContent = metaResultText(record, sentencesForSelection().length, selectedImages().length === 2);
  }
}

function metaChecksForSubmit(mode) {
  return Object.entries(loadMetaMap(mode)).map(([key, rec]) => ({
    key,
    abilities: Array.isArray(rec?.abilities) ? rec.abilities : [],
    images: Array.isArray(rec?.images) ? rec.images : [],
  }));
}

function loadChatBucket(mode = currentMode) {
  const raw = loadJson(storeKey("chat", mode), null);
  if (Array.isArray(raw)) {
    const key = photoThreadKey(mode);
    const bucket = { [key]: raw.slice(-200) };
    localStorage.setItem(storeKey("chat", mode), JSON.stringify(bucket));
    return bucket;
  }
  return raw && typeof raw === "object" ? raw : {};
}

function loadChat(mode = currentMode, threadKey = photoThreadKey(mode)) {
  const bucket = loadChatBucket(mode);
  const list = bucket[threadKey];
  return Array.isArray(list) ? list : [];
}

function pushChat(entry, mode = currentMode, threadKey = photoThreadKey(mode)) {
  const bucket = loadChatBucket(mode);
  const list = Array.isArray(bucket[threadKey]) ? bucket[threadKey] : [];
  list.push(entry);
  bucket[threadKey] = list.slice(-200);
  localStorage.setItem(storeKey("chat", mode), JSON.stringify(bucket));
}

function chatSessionId(mode = currentMode, threadKey = photoThreadKey(mode)) {
  const photo = String(threadKey).replace(/[^a-zA-Z0-9_-]/g, "_");
  return `${sessionId}__${mode}__${photo}`;
}

function isChatThreadOnScreen(mode, threadKey) {
  return mode === currentMode && threadKey === photoThreadKey(currentMode);
}

// ---------------------------------------------------------------------------
// 사진 고르기. 클릭하면 그 사진 한 장으로 바뀐다.
// 두 장은 '사진 2장 비교 관찰'일 때만 나란히 보인다.
// 비교 시 먼저 클릭한 사진이 1번째(왼쪽), 나중에 클릭한 사진이 2번째(오른쪽).
// 문장·대화 키는 사진 번호 순으로 맞춰, 클릭 순서가 달라도 같은 쌍으로 본다.
// ---------------------------------------------------------------------------
function modeImages(mode = currentMode) {
  return modeInfo(mode)?.images || [];
}

function compareWanted(mode = currentMode) {
  return localStorage.getItem(storeKey("compare", mode)) === "1";
}

function setCompareWanted(on, mode = currentMode) {
  localStorage.setItem(storeKey("compare", mode), on ? "1" : "0");
}

function storedImages(mode = currentMode) {
  const list = modeImages(mode);
  const saved = loadJson(storeKey("images", mode), null);
  let names = Array.isArray(saved) ? saved.filter((name) => list.includes(name)) : [];
  if (!names.length) {
    const older = localStorage.getItem(storeKey("image", mode));
    if (list.includes(older)) names = [older];
  }
  if (!names.length && list[0]) names = [list[0]];
  return names.slice(0, 2);
}

function orderedImages(names, mode = currentMode) {
  const list = modeImages(mode);
  return names.slice().sort((a, b) => list.indexOf(a) - list.indexOf(b));
}

// 화면·선택 안내용: 비교 모드에서는 클릭한 순서를 그대로 쓴다.
function selectedImages(mode = currentMode) {
  const names = storedImages(mode);
  if (!compareWanted(mode)) return names.slice(0, 1);
  return names.slice(0, 2);
}

// 같은 두 장이면 클릭 순서와 관계없이 하나의 키로 묶는다.
function pairKey(names, mode = currentMode) {
  const picked = (names || []).filter(Boolean).slice(0, 2);
  if (picked.length < 2) return picked[0] || "none";
  return orderedImages(picked, mode).join("|");
}

function saveSelectedImages(names, mode = currentMode) {
  const list = modeImages(mode);
  const unique = [];
  for (const name of names || []) {
    if (list.includes(name) && !unique.includes(name)) unique.push(name);
    if (unique.length >= 2) break;
  }
  localStorage.setItem(storeKey("images", mode), JSON.stringify(unique));
}

function sentenceImages(sentence) {
  if (Array.isArray(sentence?.images)) return sentence.images.filter(Boolean).slice(0, 2);
  return [sentence?.image, sentence?.imageRight].filter(Boolean);
}

function samePhotoPair(sentence, a, b) {
  const names = sentenceImages(sentence);
  if (names.length !== 2) return false;
  return (names[0] === a && names[1] === b) || (names[0] === b && names[1] === a);
}

function selectedImage(mode = currentMode) {
  return selectedImages(mode)[0] || null;
}

function showSelectedImage() {
  const picked = selectedImages();
  const left = picked[0];
  const right = picked[1];
  const slot2 = $("image-slot-2");
  const compare = $("compare-image");
  if (left) {
    const next = `images/${left}`;
    if (!mainImage.src.endsWith(next)) mainImage.src = next;
  }
  if (right && compare && slot2) {
    const next = `images/${right}`;
    if (!compare.src.endsWith(next)) compare.src = next;
    slot2.classList.remove("hidden");
  } else if (slot2) {
    slot2.classList.add("hidden");
    if (compare) compare.removeAttribute("src");
  }
  renderImagePicker();
  updateCompareButton();
  renderSentences();
  if (MODES[currentMode].chat) {
    syncChatDraft();
    renderChat();
  }
  if (typeof window.redrawMeasurements === "function") window.redrawMeasurements();
}

function updateCompareButton() {
  const compareOn = compareWanted();
  if (observeSingleBtn) observeSingleBtn.setAttribute("aria-pressed", compareOn ? "false" : "true");
  if (observeCompareBtn) observeCompareBtn.setAttribute("aria-pressed", compareOn ? "true" : "false");
}

function setObserveMode(compare) {
  if (compare) {
    setCompareWanted(true);
    saveSelectedImages(selectedImages().slice(0, 1));
  } else {
    setCompareWanted(false);
    saveSelectedImages(selectedImages().slice(0, 1));
  }
  showSelectedImage();
}

if (observeSingleBtn) {
  observeSingleBtn.addEventListener("click", () => setObserveMode(false));
}
if (observeCompareBtn) {
  observeCompareBtn.addEventListener("click", () => setObserveMode(true));
}

function renderImagePicker() {
  const list = modeImages();
  const picked = selectedImages();
  const compareOn = compareWanted();
  imagePicker.innerHTML = "";
  imagePicker.hidden = list.length < 2;
  list.forEach((name, i) => {
    const btn = document.createElement("button");
    const pickIndex = picked.indexOf(name);
    const on = pickIndex >= 0;
    btn.type = "button";
    btn.className = "image-thumb" + (on ? " selected" : "");
    if (compareOn && on) btn.classList.add(`pick-slot-${pickIndex + 1}`);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    if (compareOn && !on && picked.length === 0) btn.title = `첫 번째 사진으로 선택 · 사진 ${i + 1}`;
    else if (compareOn && !on && picked.length === 1) btn.title = `두 번째 사진으로 선택 · 사진 ${i + 1}`;
    else btn.title = `사진 ${i + 1}`;
    const img = document.createElement("img");
    img.src = `images/${name}`;
    img.alt = `사진 ${i + 1}`;
    img.loading = "lazy";
    const badge = document.createElement("span");
    badge.className = "image-thumb-badge";
    badge.textContent = String(i + 1);
    btn.appendChild(img);
    btn.appendChild(badge);
    if (compareOn && on) {
      const slot = document.createElement("span");
      slot.className = "image-thumb-slot";
      slot.textContent = pickIndex === 0 ? "1번째" : "2번째";
      btn.appendChild(slot);
    }
    btn.addEventListener("click", () => {
      const cur = selectedImages();
      let next;
      if (!compareWanted()) {
        next = [name];
      } else if (cur.length === 2 && cur.includes(name)) {
        // 두 장이 선택된 상태에서 고른 사진(앞·뒷번호 무관)을 다시 누르면
        // 그 사진을 1번째로 두고 2번째를 다시 고른다.
        next = [name];
      } else if (cur.includes(name)) {
        // 한 장만 고른 상태에서 같은 사진을 다시 누르면 1번째로 유지
        next = [name];
      } else if (cur.length < 2) {
        next = cur.concat(name);
      } else {
        // 두 장이 선택된 상태에서 다른 사진을 누르면 그 사진부터 1번째로 다시 고른다.
        next = [name];
      }
      if (!next.length) {
        const fallback = modeImages()[0];
        next = fallback ? [fallback] : [];
      }
      saveSelectedImages(next);
      showSelectedImage();
    });
    imagePicker.appendChild(btn);
  });
}

// 문장 옆에 붙일 사진 번호. 두 장이면 "사진 N · 사진 M"이고, 앞이 1번째다.
function photoLabel(name, mode = currentMode) {
  const idx = modeImages(mode).indexOf(name);
  return idx >= 0 ? `사진 ${idx + 1}` : "";
}

function photoNumberForFile(name) {
  const idx = modeImages().indexOf(name);
  return idx >= 0 ? idx + 1 : null;
}
window.photoNumberForFile = photoNumberForFile;

function sentencePhotoLabel(sentence, mode = currentMode) {
  const names = sentenceImages(sentence);
  if (names.length >= 2) {
    return `${photoLabel(names[0], mode)} · ${photoLabel(names[1], mode)}`;
  }
  return photoLabel(names[0], mode);
}

function selectionTitle() {
  const picked = selectedImages();
  if (picked.length === 2) return `${photoLabel(picked[0])} · ${photoLabel(picked[1])} 비교`;
  return photoLabel(picked[0]) || "사진";
}

function sentencesForSelection(list = loadSentences()) {
  const picked = selectedImages();
  if (picked.length === 2) {
    return list.filter((s) => samePhotoPair(s, picked[0], picked[1]));
  }
  const only = picked[0];
  return list.filter((s) => {
    const names = sentenceImages(s);
    return names.length === 1 && names[0] === only;
  });
}

let sentenceDrafts = {};
let draftSelection = "";
let chatDrafts = {};
let chatDraftSelection = "";

function selectionDraftId() {
  const picked = selectedImages();
  const key = picked.length >= 2 ? pairKey(picked) : picked[0] || "none";
  return `${currentMode}:${key}`;
}

function syncSentenceDraft() {
  if (!sentenceInput) return;
  const id = selectionDraftId();
  if (draftSelection && draftSelection !== id) {
    sentenceDrafts[draftSelection] = sentenceInput.value;
    sentenceInput.value = sentenceDrafts[id] || "";
  }
  draftSelection = id;
}

function syncChatDraft() {
  if (!chatInput) return;
  const id = selectionDraftId();
  if (chatDraftSelection && chatDraftSelection !== id) {
    chatDrafts[chatDraftSelection] = chatInput.value;
    chatInput.value = chatDrafts[id] || "";
  }
  chatDraftSelection = id;
}

// ---------------------------------------------------------------------------
// 타이머
// ---------------------------------------------------------------------------
function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function remainingNow() {
  if (timerBase.mode !== currentMode) return null;
  return Math.max(0, timerBase.seconds - (performance.now() - timerBase.at) / 1000);
}

function syncTimer() {
  const info = modeInfo(currentMode);
  if (info && info.status === "in_progress") {
    timerBase = { mode: currentMode, seconds: info.remainingSeconds, at: performance.now() };
  } else {
    timerBase = { mode: null, seconds: 0, at: 0 };
  }
}

function tick() {
  const info = modeInfo(currentMode);
  if (info && info.timed === false) {
    timerEl.classList.remove("timer-low");
    timerEl.classList.add("timer-idle");
    timerEl.textContent = info.status === "submitted" ? "제출 완료" : "제한 없음";
    return;
  }
  if (info && info.status === "in_progress") {
    const left = remainingNow();
    if (left !== null) {
      timerEl.textContent = formatClock(left);
      timerEl.classList.toggle("timer-low", left <= 60);
      timerEl.classList.remove("timer-idle");
      if (left <= 0 && !submitting) {
        submitFinal(true);
      }
      return;
    }
  }
  timerEl.classList.remove("timer-low");
  timerEl.classList.add("timer-idle");
  timerEl.textContent = info && info.status === "submitted" ? "제출 완료" : formatClock(info ? info.durationSeconds : 600);
}
setInterval(tick, 500);

// 서버와 남은 시간을 주기적으로 맞춘다(탭이 오래 열려 있어도 어긋나지 않게).
setInterval(async () => {
  if (!getStudentId() || !anyInProgress()) return;
  try {
    await fetchStatus();
    syncTimer();
  } catch (e) {
    /* 일시적인 오류는 다음 주기에 다시 시도 */
  }
}, 30000);

// ---------------------------------------------------------------------------
// 화면 그리기
// ---------------------------------------------------------------------------
function renderTabs() {
  document.querySelectorAll(".lesson-tab").forEach((tab) => {
    const mode = tab.dataset.mode;
    const info = modeInfo(mode);
    const selected = mode === currentMode;
    tab.setAttribute("aria-selected", selected ? "true" : "false");
    tab.classList.toggle("locked", info?.status === "locked");
    tab.classList.toggle("done", info?.status === "submitted");
  });
}

function renderChat() {
  chatLog.innerHTML = "";
  const spec = MODES[currentMode];
  if (!spec.chat) return;
  syncChatDraft();
  if (chatScope) chatScope.textContent = selectionTitle();
  if (spec.greeting) addMessage(spec.greeting, "ai", { store: false });
  loadChat().forEach((m) => addMessage(m.text, m.type, { store: false }));
}

function renderSentences() {
  const info = modeInfo(currentMode);
  const editable = info?.status === "in_progress";
  syncSentenceDraft();
  const all = loadSentences();
  const list = sentencesForSelection(all);
  if (sentenceScope) sentenceScope.textContent = selectionTitle();
  sentenceList.innerHTML = "";
  list.forEach((s) => {
    const li = document.createElement("li");
    const label = sentencePhotoLabel(s);
    if (label && sentenceImages(s).length >= 2) {
      const tag = document.createElement("span");
      tag.className = "sentence-photo";
      tag.textContent = label;
      li.appendChild(tag);
    }
    const span = document.createElement("span");
    span.textContent = s.text;
    li.appendChild(span);
    if (editable) {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "sentence-del";
      del.textContent = "삭제";
      del.addEventListener("click", () => {
        const cur = loadSentences();
        const idx = cur.findIndex((item) =>
          item.text === s.text && item.t === s.t && sentenceImages(item).join("|") === sentenceImages(s).join("|")
        );
        if (idx >= 0) cur.splice(idx, 1);
        saveSentences(cur);
        renderSentences();
      });
      li.appendChild(del);
    }
    sentenceList.appendChild(li);
  });
  sentenceCount.textContent = String(list.length);
  sentenceList.scrollTop = sentenceList.scrollHeight;
  renderMetaGate();
}

function applyMode() {
  const spec = MODES[currentMode];
  const info = modeInfo(currentMode);
  localStorage.setItem("autumn_leaf_mode_v3", currentMode);

  document.body.className = `mode-${currentMode}`;
  $("lesson-subtitle").textContent = spec.subtitle;
  $("lesson-hint").textContent = spec.hint;
  $("sentence-tip").textContent = spec.sentenceTip;
  chatInput.placeholder = spec.chatPlaceholder || "";
  showSelectedImage();

  renderTabs();
  syncTimer();

  const status = info?.status || "not_started";
  const hasStudent = !!getStudentId();

  // 시작 카드와 작업 영역 중 하나만 보인다.
  const showWork = hasStudent && (status === "in_progress" || status === "submitted" || status === "expired");
  startCard.hidden = showWork;
  workArea.hidden = !showWork;
  $("start-title").textContent = spec.startTitle;
  $("start-desc").textContent = info?.timed === false ? spec.startDesc : spec.startDescTimed || spec.startDesc;
  startMsg.textContent = "";
  startBtn.disabled = false;
  if (!hasStudent) {
    startBtn.disabled = true;
    startMsg.textContent = "먼저 학번을 입력하고 확인을 눌러주세요.";
  } else if (status === "locked") {
    startBtn.disabled = true;
    startMsg.textContent = currentMode === "offload"
      ? "탭 1 사전 과제를 마치면 열려요."
      : "탭 1과 탭 2를 모두 마치면 열려요.";
  } else if (currentMode === "offload" && !studyGroup) {
    startBtn.disabled = true;
    startMsg.textContent = "안내받은 집단 링크(?group=A 또는 ?group=B)로 들어와 주세요.";
  }
  startBtn.textContent =
    info?.timed === false
      ? "시작하기"
      : `시작하기 (${Math.round((info?.durationSeconds || 600) / 60)}분)`;

  if (showWork) {
    renderChat();
    renderSentences();
    syncObservationLock();
    renderMetaGate();
    submitStatus.textContent =
      status === "submitted"
        ? "제출했어요. 수고했습니다!"
        : status === "expired"
        ? "시간이 끝났어요. 제출하는 중..."
        : "";
    if (status === "expired" && !submitting) submitFinal(true);
  } else {
    workArea.classList.remove("is-meta-gate");
  }
  tick();
}

async function refresh() {
  try {
    await fetchStatus();
  } catch (e) {
    showNotice("서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.");
  }
  applyMode();
}

// ---------------------------------------------------------------------------
// 탭 이동과 시작
// ---------------------------------------------------------------------------
document.querySelectorAll(".lesson-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const mode = tab.dataset.mode;
    if (mode === currentMode) return;
    const running = MODE_ORDER.find((item) => modeInfo(item)?.status === "in_progress");
    if (running && mode !== running) {
      showNotice("진행 중인 탭을 제출한 뒤에 다른 탭으로 이동할 수 있어요.");
      return;
    }
    currentMode = mode;
    applyMode();
  });
});

startBtn.addEventListener("click", async () => {
  const studentId = getStudentId();
  if (!studentId) return;
  startBtn.disabled = true;
  try {
    await api("/api/session/start", { method: "POST", body: { studentId, mode: currentMode } });
    await fetchStatus();
    applyMode();
    if (!metaGateActive()) (MODES[currentMode].chat ? chatInput : sentenceInput).focus();
  } catch (err) {
    startMsg.textContent = err.message;
    startBtn.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// 채팅(탭 2, 3)
// ---------------------------------------------------------------------------
function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// AI 답변의 **굵게**, 목록, 줄바꿈을 화면에서도 보이게 한다.
function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  return html
    .split(/\n\n+/)
    .map((block) => {
      const lines = block.split("\n").filter((line) => line.trim().length > 0);
      if (lines.length > 0 && lines.every((line) => /^\s*[-*]\s+/.test(line))) {
        const items = lines.map((line) => `<li>${line.replace(/^\s*[-*]\s+/, "")}</li>`).join("");
        return `<ul>${items}</ul>`;
      }
      return `<p>${block.replace(/\n/g, "<br>")}</p>`;
    })
    .join("");
}

function addMessage(text, type, { store = true, mode = currentMode, threadKey = photoThreadKey(mode) } = {}) {
  let div = null;
  if (isChatThreadOnScreen(mode, threadKey)) {
    div = document.createElement("div");
    div.className = `msg msg-${type}`;
    if (type === "ai") {
      div.innerHTML = renderMarkdown(text);
    } else {
      div.textContent = text;
    }
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
  }
  if (store && (type === "ai" || type === "user")) pushChat({ text, type }, mode, threadKey);
  return div;
}

async function sendToAI(text, kind) {
  const studentId = getStudentId();
  if (!studentId || chatBusy) return;
  // 응답이 오기 전에 사진을 바꿔도, 보낸 사진 스레드에만 답이 붙도록 고정한다.
  const mode = currentMode;
  const threadKey = photoThreadKey(mode);
  const images = selectedImages(mode);
  const image = images[0] || null;
  const llmSessionId = chatSessionId(mode, threadKey);
  chatBusy = true;
  sendBtn.disabled = true;
  sentenceAddBtn.disabled = true;
  const loadingEl = addMessage("AI가 답변을 준비 중입니다...", "loading", {
    store: false,
    mode,
    threadKey,
  });
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: {
        message: text,
        studentId,
        sessionId: llmSessionId,
        mode,
        kind,
        image,
        images,
        observations: sentencesForSelection().map((item) => item.text).filter((text) => text && text.trim()),
      },
    });
    loadingEl?.remove();
    addMessage(data.answer, "ai", { mode, threadKey });
  } catch (err) {
    loadingEl?.remove();
    addMessage(err.message || "서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", "error", {
      store: false,
      mode,
      threadKey,
    });
  } finally {
    chatBusy = false;
    syncObservationLock();
  }
}

chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (metaGateActive()) return;
  const text = chatInput.value.trim();
  if (!text || chatBusy) return;
  addMessage(text, "user");
  chatInput.value = "";
  await sendToAI(text, "question");
  chatInput.focus();
});

// ---------------------------------------------------------------------------
// 관찰 문장 목록과 최종 제출
// ---------------------------------------------------------------------------
function elapsedSeconds() {
  const info = modeInfo(currentMode);
  if (!info) return null;
  if (info.timed === false && info.startedAt) {
    const started = Date.parse(info.startedAt);
    if (!Number.isNaN(started)) return Math.max(0, Math.round((Date.now() - started) / 1000));
  }
  const left = remainingNow();
  if (left === null) return null;
  return Math.round(info.durationSeconds - left);
}

function addSentence(text) {
  const cur = loadSentences();
  const picked = selectedImages();
  cur.push({ text, t: elapsedSeconds(), images: picked.filter(Boolean) });
  saveSentences(cur);
  renderSentences();
}

sentenceInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sentenceForm.requestSubmit();
  }
});

sentenceForm.addEventListener("submit", (e) => {
  e.preventDefault();
  if (metaGateActive()) return;
  const text = sentenceInput.value.trim();
  if (!text) return;
  addSentence(text);
  sentenceInput.value = "";
  sentenceInput.focus();
});

async function submitFinal(auto = false) {
  if (submitting) return;
  const studentId = getStudentId();
  if (!studentId) return;
  const mode = currentMode;

  // 입력란에 쓰다 만 문장이 있으면 함께 제출한다.
  const pending = sentenceInput.value.trim();
  if (pending) {
    addSentence(pending);
    sentenceInput.value = "";
  }
  const sentences = loadSentences(mode);
  if (!auto) {
    if (sentences.length === 0) {
      showNotice("제출할 관찰 문장이 없어요. 한 문장 이상 적어 주세요.");
      return;
    }
    if (!window.confirm("최종 제출하면 더 이상 고칠 수 없어요. 제출할까요?")) return;
  }

  submitting = true;
  submitBtn.disabled = true;
  submitStatus.textContent = "제출하는 중...";
  try {
    await api("/api/submit", {
      method: "POST",
      body: { studentId, mode, sentences, auto, metaChecks: metaChecksForSubmit(mode) },
    });
    await fetchStatus();
    applyMode();
    const next = nextModeHint(mode);
    if (next) showNotice(next);
  } catch (err) {
    submitStatus.textContent = err.message;
    submitBtn.disabled = false;
  } finally {
    submitting = false;
  }
}

function nextModeHint(mode) {
  if (mode === "assess") return "사전 과제를 제출했어요. 이제 탭 2로 이동해 보세요.";
  if (mode === "offload") return "탭 2를 제출했어요. 이제 사후 과제로 이동해 보세요.";
  return "모든 탭을 마쳤어요. 수고했습니다!";
}

submitBtn.addEventListener("click", () => submitFinal(false));

// ---------------------------------------------------------------------------
// 관찰 도구 열고 닫기
// ---------------------------------------------------------------------------
const measureToggle = $("measure-toggle");
const measureToolbarWrap = $("measure-toolbar-wrap");
measureToggle?.addEventListener("click", () => {
  const open = measureToggle.getAttribute("aria-expanded") === "true";
  const nextOpen = !open;
  measureToggle.setAttribute("aria-expanded", nextOpen ? "true" : "false");
  if (measureToolbarWrap) {
    measureToolbarWrap.classList.toggle("is-collapsed", !nextOpen);
    measureToolbarWrap.setAttribute("aria-hidden", nextOpen ? "false" : "true");
  }
  if (!nextOpen && typeof window.releaseMeasureTool === "function") {
    window.releaseMeasureTool();
  }
});

$("meta-check-start")?.addEventListener("click", () => {
  if (!metaGateActive()) return;
  const map = loadMetaMap();
  map[photoThreadKey()] = {
    abilities: metaAbilitiesForView().map((item) => item.id).filter((id) => metaDraft.has(id)),
    images: selectedImages().slice(),
    at: Date.now(),
  };
  localStorage.setItem(storeKey("meta", currentMode), JSON.stringify(map));
  renderMetaGate();
  syncObservationLock();
  sentenceInput?.focus();
});

// ---------------------------------------------------------------------------
// 시작
// ---------------------------------------------------------------------------
updateStudentIdStatus();
applyStudyGroup(studyGroup);
refresh().then(() => {
  const running = MODE_ORDER.find((item) => modeInfo(item)?.status === "in_progress");
  if (running && running !== currentMode) {
    currentMode = running;
    applyMode();
    return;
  }
  // 서버 상태를 알기 전에 마지막으로 보던 탭이 잠겨 있으면 첫 탭으로 돌린다.
  if (modeInfo(currentMode)?.status === "locked") {
    currentMode = "assess";
    applyMode();
  }
});