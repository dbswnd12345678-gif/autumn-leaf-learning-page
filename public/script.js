const LEAF_IMAGES = ["leaf1.jpg", "leaf2.jpg", "leaf3.jpg", "leaf4.jpg", "leaf5.jpg"];

const mainImage = document.getElementById("main-image");
const thumbnailRow = document.getElementById("thumbnail-row");
const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");

let selectedImage = LEAF_IMAGES[0];

function getSessionId() {
  let sid = localStorage.getItem("autumn_leaf_session_id");
  if (!sid) {
    sid = "student-" + Math.random().toString(36).slice(2) + Date.now();
    localStorage.setItem("autumn_leaf_session_id", sid);
  }
  return sid;
}
const sessionId = getSessionId();

function renderThumbnails() {
  thumbnailRow.innerHTML = "";
  LEAF_IMAGES.forEach((file) => {
    const img = document.createElement("img");
    img.src = `images/${file}`;
    img.alt = file;
    if (file === selectedImage) img.classList.add("selected");
    img.addEventListener("click", () => selectImage(file));
    thumbnailRow.appendChild(img);
  });
}

function selectImage(file) {
  selectedImage = file;
  mainImage.src = `images/${file}`;
  renderThumbnails();
}

function addMessage(text, type) {
  const div = document.createElement("div");
  div.className = `msg msg-${type}`;
  div.textContent = text;
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
        image: selectedImage,
        sessionId,
      }),
    });
    const data = await res.json();
    loadingEl.remove();

    if (!res.ok) {
      addMessage(data.error || "오류가 발생했습니다.", "error");
      return;
    }
    if (data.pheno) {
      const p = data.pheno;
      addMessage(
        `이미지 분류 모델(PhenoVisionL) 판정 — ` +
          `초록 잎이 있을 확률 ${Math.round(p.green * 100)}%, ` +
          `단풍든 잎이 있을 확률 ${Math.round(p.colored * 100)}%, ` +
          `새 잎눈이 있을 확률 ${Math.round(p.breaking_buds * 100)}%`,
        "pheno"
      );
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

renderThumbnails();
