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

function formatPhenoMessage(p) {
  return (
    `이미지 분류 모델(PhenoVisionL) 판정 — ` +
    `초록 잎이 있을 확률 ${Math.round(p.green * 100)}%, ` +
    `단풍든 잎이 있을 확률 ${Math.round(p.colored * 100)}%, ` +
    `새 잎눈이 있을 확률 ${Math.round(p.breaking_buds * 100)}%`
  );
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
  const loadingEl = addMessage("이미지 분석 후 지식그래프를 조회하며 답변을 준비 중입니다...", "loading");

  let pheno = null;
  try {
    // PhenoVision을 먼저 끝내 화면에 바로 보여주고, 같은 결과는 채팅 API에서 재사용한다.
    const phenoRes = await fetch("/api/pheno", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: selectedImage }),
    });
    const phenoData = await phenoRes.json();
    if (phenoRes.ok && phenoData.pheno) {
      pheno = phenoData.pheno;
      addMessage(formatPhenoMessage(pheno), "pheno");
      loadingEl.textContent = "AI가 지식그래프를 조회하며 답변을 준비 중입니다...";
    }

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        image: selectedImage,
        sessionId,
        pheno,
      }),
    });
    const data = await res.json();
    loadingEl.remove();

    if (!res.ok) {
      addMessage(data.error || "오류가 발생했습니다.", "error");
      return;
    }
    if (!pheno && data.pheno) {
      addMessage(formatPhenoMessage(data.pheno), "pheno");
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
