require("dotenv").config();
const express = require("express");
const fs = require("fs");
const path = require("path");

const app = express();
app.use(express.json({ limit: "12mb" }));
app.use(express.static(path.join(__dirname, "public")));

const {
  ANYTHINGLLM_BASE_URL,
  ANYTHINGLLM_API_KEY,
  ANYTHINGLLM_WORKSPACE_SLUG,
  PORT = 3000,
} = process.env;

const IMAGES_DIR = path.join(__dirname, "public", "images");
const ALLOWED_IMAGES = ["leaf1.jpg", "leaf2.jpg", "leaf3.jpg", "leaf4.jpg", "leaf5.jpg"];

if (!ANYTHINGLLM_BASE_URL || !ANYTHINGLLM_API_KEY || !ANYTHINGLLM_WORKSPACE_SLUG) {
  console.warn(
    "[경고] .env 파일(또는 Railway 환경변수)에 ANYTHINGLLM_BASE_URL / ANYTHINGLLM_API_KEY / ANYTHINGLLM_WORKSPACE_SLUG 가 설정되지 않았습니다."
  );
}

function mimeFromExt(filename) {
  const ext = path.extname(filename).slice(1).toLowerCase();
  if (ext === "png") return "image/png";
  if (ext === "webp") return "image/webp";
  return "image/jpeg";
}

// 학생 브라우저가 보내는 이미지 파일명을 화이트리스트로만 허용 (경로 조작 방지)
function loadImageAttachment(imageName) {
  if (!imageName || !ALLOWED_IMAGES.includes(imageName)) return null;
  const imagePath = path.join(IMAGES_DIR, imageName);
  if (!fs.existsSync(imagePath)) return null;

  const base64 = fs.readFileSync(imagePath).toString("base64");
  const mime = mimeFromExt(imageName);
  return {
    name: imageName,
    mime,
    contentString: `data:${mime};base64,${base64}`,
  };
}

app.post("/api/chat", async (req, res) => {
  try {
    const { message, image, sessionId } = req.body;

    if (!message || typeof message !== "string") {
      return res.status(400).json({ error: "message가 필요합니다." });
    }
    if (!sessionId || typeof sessionId !== "string") {
      return res.status(400).json({ error: "sessionId가 필요합니다." });
    }
    if (!ANYTHINGLLM_BASE_URL || !ANYTHINGLLM_API_KEY || !ANYTHINGLLM_WORKSPACE_SLUG) {
      return res.status(500).json({ error: "서버에 AnythingLLM 연결 정보(환경변수)가 설정되지 않았습니다." });
    }

    const attachment = loadImageAttachment(image);

    const response = await fetch(
      `${ANYTHINGLLM_BASE_URL}/api/v1/workspace/${ANYTHINGLLM_WORKSPACE_SLUG}/chat`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${ANYTHINGLLM_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message,
          mode: "chat",
          sessionId,
          attachments: attachment ? [attachment] : [],
        }),
      }
    );

    if (!response.ok) {
      const text = await response.text();
      console.error("AnythingLLM API 오류:", response.status, text);
      return res.status(502).json({ error: `AnythingLLM 응답 오류 (${response.status})` });
    }

    const data = await response.json();
    res.json({ answer: data.textResponse || "(응답이 비어 있습니다)" });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "서버 내부 오류가 발생했습니다." });
  }
});

app.get("/api/health", (req, res) => {
  res.json({ ok: true });
});

app.listen(PORT, () => {
  console.log(`학습 페이지 서버 실행 중: http://localhost:${PORT}`);
});
