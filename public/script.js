const LEAF_IMAGES = ["leaf1.jpg", "leaf2.jpg", "leaf3.webp", "leaf4.jpg", "leaf5.png"];
const MAX_SELECTED_IMAGES = 2;

const mainImage = document.getElementById("main-image");
const compareImage = document.getElementById("compare-image");
const imageSlot2 = document.getElementById("image-slot-2");
const thumbnailRow = document.getElementById("thumbnail-row");
const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const downloadXlsxBtn = document.getElementById("download-xlsx-btn");
const downloadDocxBtn = document.getElementById("download-docx-btn");
const studentIdInput = document.getElementById("student-id-input");
const studentIdSaveBtn = document.getElementById("student-id-save-btn");
const studentIdStatus = document.getElementById("student-id-status");

// 관찰 대상 사진은 최대 2장까지 선택할 수 있고, 2장을 고르면 비교 관찰 모드가 된다.
let selectedImages = [LEAF_IMAGES[0]];

function getSessionId() {
  let sid = localStorage.getItem("autumn_leaf_session_id");
  if (!sid) {
    sid = "session-" + Math.random().toString(36).slice(2) + Date.now();
    localStorage.setItem("autumn_leaf_session_id", sid);
  }
  return sid;
}
const sessionId = getSessionId();

// 학번(학생 번호)은 3회차 수업에 걸쳐 학생의 관찰 이력을 이어주는 고정 식별자다.
// 브라우저/기기가 바뀌어도 학생이 같은 학번을 입력하면 이전 관찰 기록을 계속 이어서 쌓을 수 있다.
function getStudentId() {
  return localStorage.getItem("autumn_leaf_student_id") || "";
}

function setStudentId(id) {
  localStorage.setItem("autumn_leaf_student_id", id);
  updateStudentIdStatus();
}

function updateStudentIdStatus() {
  const id = getStudentId();
  if (id) {
    studentIdInput.value = id;
    studentIdStatus.textContent = `현재 학번: ${id} (다른 학번으로 바꾸려면 입력 후 확인을 눌러주세요)`;
    studentIdStatus.classList.remove("student-id-missing");
  } else {
    studentIdStatus.textContent = "학번을 입력하고 확인을 눌러주세요.";
    studentIdStatus.classList.add("student-id-missing");
  }
}

studentIdSaveBtn.addEventListener("click", () => {
  const value = studentIdInput.value.trim();
  if (!value) {
    studentIdStatus.textContent = "학번을 입력해주세요.";
    return;
  }
  setStudentId(value);
});

updateStudentIdStatus();

function isComparisonMode() {
  return selectedImages.length === MAX_SELECTED_IMAGES;
}

function renderThumbnails() {
  thumbnailRow.innerHTML = "";
  LEAF_IMAGES.forEach((file) => {
    const wrap = document.createElement("div");
    wrap.className = "thumbnail-item";

    const img = document.createElement("img");
    img.src = `images/${file}`;
    img.alt = file;
    const order = selectedImages.indexOf(file);
    if (order === 0) img.classList.add("selected", "selected-1");
    if (order === 1) img.classList.add("selected", "selected-2");
    img.addEventListener("click", () => toggleImage(file));

    wrap.appendChild(img);
    if (order >= 0) {
      const badge = document.createElement("span");
      badge.className = "thumbnail-badge";
      badge.textContent = order + 1;
      wrap.appendChild(badge);
    }
    thumbnailRow.appendChild(wrap);
  });
}

function toggleImage(file) {
  const idx = selectedImages.indexOf(file);
  if (idx >= 0) {
    // 이미 선택된 사진을 다시 누르면 선택을 취소한다. 단, 최소 1장은 항상 선택되어 있어야 한다.
    if (selectedImages.length > 1) {
      selectedImages.splice(idx, 1);
    }
  } else if (selectedImages.length < MAX_SELECTED_IMAGES) {
    selectedImages.push(file);
  } else {
    // 이미 2장이 선택된 상태에서 새 사진을 고르면, 먼저 선택했던 사진을 새 사진으로 바꾼다.
    selectedImages.shift();
    selectedImages.push(file);
  }
  updateImageDisplay();
  renderThumbnails();
}

function updateImageDisplay() {
  mainImage.src = `images/${selectedImages[0]}`;
  if (isComparisonMode()) {
    compareImage.src = `images/${selectedImages[1]}`;
    imageSlot2.classList.remove("hidden");
  } else {
    imageSlot2.classList.add("hidden");
  }
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// AnythingLLM 답변의 **굵게**, 목록, 줄바꿈을 학습 페이지에서도 보이게 한다.
function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");

  return html
    .split(/\n\n+/)
    .map((block) => {
      const lines = block.split("\n").filter((line) => line.trim().length > 0);
      if (lines.length > 0 && lines.every((line) => /^\s*[-*]\s+/.test(line))) {
        const items = lines
          .map((line) => `<li>${line.replace(/^\s*[-*]\s+/, "")}</li>`)
          .join("");
        return `<ul>${items}</ul>`;
      }
      return `<p>${block.replace(/\n/g, "<br>")}</p>`;
    })
    .join("");
}

function addMessage(text, type) {
  const div = document.createElement("div");
  div.className = `msg msg-${type}`;
  if (type === "ai") {
    div.innerHTML = renderMarkdown(text);
  } else {
    div.textContent = text;
  }
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

// Enter = 전송, Shift+Enter = 줄바꿈
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  const studentId = getStudentId();
  if (!studentId) {
    studentIdStatus.textContent = "먼저 상단에 학번을 입력하고 확인을 눌러주세요.";
    studentIdInput.focus();
    return;
  }

  addMessage(text, "user");
  chatInput.value = "";
  sendBtn.disabled = true;
  const loadingEl = addMessage("AI가 지식그래프를 조회하며 답변을 준비 중입니다...", "loading");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        images: selectedImages,
        studentId,
        sessionId,
        comparisonMode: isComparisonMode(),
      }),
    });
    const data = await res.json();
    loadingEl.remove();

    if (!res.ok) {
      addMessage(data.error || "오류가 발생했습니다.", "error");
      return;
    }
    addMessage(data.answer, "ai");
  } catch (err) {
    loadingEl.remove();
    addMessage("서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.", "error");
  } finally {
    sendBtn.disabled = false;
    chatInput.focus();
  }
});

// 지금까지 나눈 대화(내 질문 + AI 답변)를 엑셀 또는 워드 파일로 받는다.
// 학번을 기준으로 저장되므로, 3회차 수업에서 나눈 대화가 모두 하나의 파일로 합쳐져 내려받아진다.
function downloadHistory(format) {
  const studentId = getStudentId();
  if (!studentId) {
    studentIdStatus.textContent = "먼저 상단에 학번을 입력하고 확인을 눌러주세요.";
    studentIdInput.focus();
    return;
  }
  const url = `/api/history/${encodeURIComponent(studentId)}/export?format=${format}`;
  window.location.href = url;
}

downloadXlsxBtn?.addEventListener("click", () => downloadHistory("xlsx"));
downloadDocxBtn?.addEventListener("click", () => downloadHistory("docx"));

renderThumbnails();
updateImageDisplay();