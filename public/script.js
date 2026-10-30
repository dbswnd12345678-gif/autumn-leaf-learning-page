// 3개 탭(모드): assess(관찰력 진단), offload(오프로딩 진단), support(AI Agent 지원)
// 서버가 모드별 세션과 사진을 정한다. 제한 시간은 SESSION_SECONDS가 0보다 클 때만 흐른다.
const MODES = {
  assess: {
    subtitle: "AI 없이 사진을 보고 관찰한 내용을 문장으로 적어 보세요. 여러 문장을 쓸 수 있어요.",
    hint: "※ 사진에서 보이는 것을 한 문장씩 적어 주세요. 다 쓰면 최종 제출을 누르세요.",
    startTitle: "탭 1 · 관찰하기",
    startDesc: "단풍잎 사진을 보고 관찰한 내용을 문장으로 적습니다. 이 탭에서는 AI를 쓰지 않아요. 다 쓰면 최종 제출을 누르세요.",
    startDescTimed: "단풍잎 사진을 보고 관찰한 내용을 문장으로 적습니다. 이 탭에서는 AI를 쓰지 않아요. 시작하면 제한 시간이 흐르고, 시간이 끝나면 자동으로 제출돼요.",
    chat: false,
    sentenceToAI: false,
    sentenceTip: "AI 없이 직접 관찰하세요.",
  },
  offload: {
    subtitle: "AI에게 자유롭게 질문하거나 요청하면서 관찰 과제를 해 보세요. 마지막에 내 관찰 문장을 제출합니다.",
    hint: "※ AI에게 무엇이든 물어봐도 돼요. 제출할 관찰 문장은 오른쪽 아래 입력란에 따로 적어 주세요.",
    startTitle: "탭 2 · AI와 관찰하기",
    startDesc: "AI에게 자유롭게 질문하거나 요청하며 단풍잎을 관찰합니다. 관찰한 내용은 '내 관찰 문장'에 적어 최종 제출하세요.",
    startDescTimed: "AI에게 자유롭게 질문하거나 요청하며 단풍잎을 관찰합니다. 관찰한 내용은 '내 관찰 문장'에 적어 최종 제출하세요. 시작하면 제한 시간이 흐릅니다.",
    chat: true,
    sentenceToAI: false,
    greeting: "안녕하세요! 단풍잎 관찰을 도와줄게요. 궁금한 것이나 부탁할 것을 자유롭게 말해 주세요.",
    chatPlaceholder: "AI에게 질문하거나 요청하세요... (Enter 전송, Shift+Enter 줄바꿈)",
    sentenceTip: "AI 답변과 별개로, 내가 관찰한 내용을 적어요.",
  },
  support: {
    subtitle: "AI 도우미가 관찰하는 방법을 도와줍니다. 관찰 문장을 입력하면 도우미가 다음에 볼 것을 안내해요.",
    hint: "※ 관찰 문장을 추가하면 AI 도우미가 도움말을 줍니다. 궁금한 것은 위쪽 대화창에 물어보세요.",
    startTitle: "탭 3 · AI 도우미와 관찰하기",
    startDesc: "AI 도우미와 함께 단풍잎을 관찰합니다. 관찰 문장을 입력하면 도우미가 방법을 안내해요.",
    startDescTimed: "AI 도우미와 함께 단풍잎을 관찰합니다. 관찰 문장을 입력하면 도우미가 방법을 안내해요. 시작하면 제한 시간이 흐릅니다.",
    chat: true,
    sentenceToAI: true,
    greeting: "안녕하세요! 저는 관찰 도우미예요. 사진을 보고 관찰한 문장을 아래에 입력해 보세요. 궁금한 점은 여기에 물어봐도 돼요.",
    chatPlaceholder: "AI 도우미에게 질문하세요... (Enter 전송, Shift+Enter 줄바꿈)",
    sentenceTip: "문장을 추가하면 도우미가 답해요.",
  },
};
const MODE_ORDER = ["assess", "offload", "support"];

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
const compareBtn = $("compare-btn");
const compareHint = $("compare-hint");
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
  const data = await api(`/api/session/status?studentId=${encodeURIComponent(studentId)}`);
  serverStatus = data.modes;
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

function loadChat(mode = currentMode) {
  return loadJson(storeKey("chat", mode), []);
}

function pushChat(entry, mode = currentMode) {
  const list = loadChat(mode);
  list.push(entry);
  localStorage.setItem(storeKey("chat", mode), JSON.stringify(list.slice(-200)));
}

// ---------------------------------------------------------------------------
// 사진 고르기. 클릭하면 그 사진 한 장으로 바뀐다.
// 두 장은 '비교해서 관찰하기'를 누른 뒤에만 나란히 보인다.
// 비교 쌍은 고른 순서가 달라도 같다. 번호가 작은 사진이 왼쪽에 온다.
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

function selectedImages(mode = currentMode) {
  const names = storedImages(mode);
  if (!compareWanted(mode)) return names.slice(0, 1);
  return orderedImages(names, mode);
}

function saveSelectedImages(names, mode = currentMode) {
  localStorage.setItem(
    storeKey("images", mode),
    JSON.stringify(orderedImages(names, mode).slice(0, 2))
  );
}

function samePhotoPair(sentence, a, b) {
  const left = sentence.image;
  const right = sentence.imageRight;
  if (!left || !right) return false;
  return (left === a && right === b) || (left === b && right === a);
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
  if (typeof window.redrawMeasurements === "function") window.redrawMeasurements();
}

function updateCompareButton() {
  if (!compareBtn) return;
  const comparing = compareWanted() && selectedImages().length === 2;
  const waiting = compareWanted() && selectedImages().length < 2;
  compareBtn.setAttribute("aria-pressed", compareWanted() ? "true" : "false");
  if (comparing) compareBtn.textContent = "한 장으로 보기";
  else if (waiting) compareBtn.textContent = "비교할 사진을 클릭하세요";
  else compareBtn.textContent = "비교해서 관찰하기";
  if (!compareHint) return;
  if (!compareWanted()) {
    compareHint.hidden = true;
    compareHint.textContent = "";
  } else if (waiting) {
    compareHint.hidden = false;
    compareHint.textContent = "비교할 사진을 하나 더 누르세요. 고른 사진을 다시 누르면 빠집니다.";
  } else {
    compareHint.hidden = false;
    compareHint.textContent = "고른 사진을 다시 누르면 빠집니다. 다른 사진을 누르면 그 사진부터 다시 고릅니다.";
  }
}

if (compareBtn) {
  compareBtn.addEventListener("click", () => {
    if (compareWanted()) {
      setCompareWanted(false);
    } else {
      setCompareWanted(true);
      saveSelectedImages(selectedImages().slice(0, 1));
    }
    showSelectedImage();
  });
}

function renderImagePicker() {
  const list = modeImages();
  const picked = selectedImages();
  imagePicker.innerHTML = "";
  imagePicker.hidden = list.length < 2;
  list.forEach((name, i) => {
    const btn = document.createElement("button");
    const on = picked.includes(name);
    btn.type = "button";
    btn.className = "image-thumb" + (on ? " selected" : "");
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = `사진 ${i + 1}`;
    const img = document.createElement("img");
    img.src = `images/${name}`;
    img.alt = `사진 ${i + 1}`;
    img.loading = "lazy";
    const badge = document.createElement("span");
    badge.className = "image-thumb-badge";
    badge.textContent = String(i + 1);
    btn.appendChild(img);
    btn.appendChild(badge);
    btn.addEventListener("click", () => {
      const cur = selectedImages();
      let next;
      if (!compareWanted()) {
        next = [name];
      } else if (cur.includes(name)) {
        next = cur.filter((item) => item !== name);
        if (!next.length) next = [name];
      } else if (cur.length < 2) {
        next = cur.concat(name);
      } else {
        next = [name];
      }
      saveSelectedImages(next);
      showSelectedImage();
    });
    imagePicker.appendChild(btn);
  });
}

// 문장 옆에 붙일 사진 번호. 두 장이면 "왼쪽 사진 N 오른쪽 사진 M".
function photoLabel(name, mode = currentMode) {
  const idx = modeImages(mode).indexOf(name);
  return idx >= 0 ? `사진 ${idx + 1}` : "";
}

function sentencePhotoLabel(sentence, mode = currentMode) {
  if (sentence.image && sentence.imageRight) {
    const ordered = orderedImages([sentence.image, sentence.imageRight], mode);
    return `${photoLabel(ordered[0], mode)} · ${photoLabel(ordered[1], mode)}`;
  }
  return photoLabel(sentence.image, mode);
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
  return list.filter((s) => s.image === only && !s.imageRight);
}

let sentenceDrafts = {};
let draftSelection = "";

function selectionDraftId() {
  return `${currentMode}:${selectedImages().join("|")}`;
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
    if (label && s.imageRight) {
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
          item.text === s.text && item.t === s.t && item.image === s.image && (item.imageRight || null) === (s.imageRight || null)
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
    startMsg.textContent = "탭 1과 탭 2를 모두 마치면 열려요.";
  }
  startBtn.textContent =
    info?.timed === false
      ? "시작하기"
      : `시작하기 (${Math.round((info?.durationSeconds || 600) / 60)}분)`;

  if (showWork) {
    renderChat();
    renderSentences();
    const editable = status === "in_progress";
    sentenceInput.disabled = !editable;
    sentenceAddBtn.disabled = !editable;
    chatInput.disabled = !editable;
    sendBtn.disabled = !editable;
    submitBtn.disabled = !editable;
    submitStatus.textContent =
      status === "submitted"
        ? "제출했어요. 수고했습니다!"
        : status === "expired"
        ? "시간이 끝났어요. 제출하는 중..."
        : "";
    if (status === "expired" && !submitting) submitFinal(true);
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
    if (anyInProgress()) {
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
    (MODES[currentMode].chat ? chatInput : sentenceInput).focus();
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

function addMessage(text, type, { store = true } = {}) {
  const div = document.createElement("div");
  div.className = `msg msg-${type}`;
  if (type === "ai") {
    div.innerHTML = renderMarkdown(text);
  } else {
    div.textContent = text;
  }
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  if (store && (type === "ai" || type === "user")) pushChat({ text, type });
  return div;
}

async function sendToAI(text, kind) {
  const studentId = getStudentId();
  if (!studentId || chatBusy) return;
  chatBusy = true;
  sendBtn.disabled = true;
  sentenceAddBtn.disabled = true;
  const loadingEl = addMessage("AI가 답변을 준비 중입니다...", "loading", { store: false });
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: { message: text, studentId, sessionId, mode: currentMode, kind, image: selectedImage(), images: selectedImages() },
    });
    loadingEl.remove();
    addMessage(data.answer, "ai");
  } catch (err) {
    loadingEl.remove();
    addMessage(err.message || "서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", "error", { store: false });
  } finally {
    chatBusy = false;
    const editable = modeInfo(currentMode)?.status === "in_progress";
    sendBtn.disabled = !editable;
    sentenceAddBtn.disabled = !editable;
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
  cur.push({ text, t: elapsedSeconds(), image: picked[0] || null, imageRight: picked[1] || null });
  saveSentences(cur);
  renderSentences();
}

sentenceInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sentenceForm.requestSubmit();
  }
});

sentenceForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = sentenceInput.value.trim();
  if (!text) return;
  addSentence(text);
  sentenceInput.value = "";
  if (MODES[currentMode].sentenceToAI) {
    addMessage(`(관찰 문장) ${text}`, "user");
    await sendToAI(text, "sentence");
  }
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
    await api("/api/submit", { method: "POST", body: { studentId, mode, sentences, auto } });
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
  if (mode === "assess") return "탭 1을 제출했어요. 이제 탭 2로 이동해 보세요.";
  if (mode === "offload") return "탭 2를 제출했어요. 이제 탭 3으로 이동해 보세요.";
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
  measureToggle.setAttribute("aria-expanded", open ? "false" : "true");
  if (measureToolbarWrap) measureToolbarWrap.hidden = open;
});

// ---------------------------------------------------------------------------
// 시작
// ---------------------------------------------------------------------------
updateStudentIdStatus();
refresh().then(() => {
  // 서버 상태를 알기 전에 마지막으로 보던 탭이 잠겨 있으면 첫 탭으로 돌린다.
  if (modeInfo(currentMode)?.status === "locked") {
    currentMode = "assess";
    applyMode();
  }
});