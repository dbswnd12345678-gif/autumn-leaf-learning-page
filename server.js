require("dotenv").config();
const express = require("express");
const fs = require("fs");
const path = require("path");
const fetch = require("node-fetch");

const app = express();
app.use(express.json({ limit: "12mb" }));
app.use(express.static(path.join(__dirname, "public")));

const {
  ANYTHINGLLM_BASE_URL,
  ANYTHINGLLM_API_KEY,
  ANYTHINGLLM_WORKSPACE_SLUG,
  PHENOVISION_API_URL,
  PHENOVISION_SHARED_SECRET,
  PORT = 3000,
} = process.env;

const IMAGES_DIR = path.join(__dirname, "public", "images");
const ALLOWED_IMAGES = ["leaf1.jpg", "leaf2.jpg", "leaf3.jpg", "leaf4.jpg", "leaf5.jpg"];
// 같은 샘플 이미지는 매 질문마다 다시 분류하지 않도록 메모리 캐시
const phenoCache = new Map();

if (!ANYTHINGLLM_BASE_URL || !ANYTHINGLLM_API_KEY || !ANYTHINGLLM_WORKSPACE_SLUG) {
  console.warn(
    "[경고] .env 파일(또는 Railway 환경변수)에 ANYTHINGLLM_BASE_URL / ANYTHINGLLM_API_KEY / ANYTHINGLLM_WORKSPACE_SLUG 가 설정되지 않았습니다."
  );
}

function normalizeBaseUrl(rawUrl) {
  const trimmed = rawUrl.trim().replace(/\/+$/, "");
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
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

function isValidPheno(pheno) {
  return (
    pheno &&
    typeof pheno === "object" &&
    typeof pheno.green === "number" &&
    typeof pheno.colored === "number" &&
    typeof pheno.breaking_buds === "number"
  );
}

// PhenoVisionL은 보조 신호일 뿐이므로, 실패하면 null을 돌려주고 대화는 그대로 진행한다.
async function classifyLeafImage(attachment, imageName) {
  if (!PHENOVISION_API_URL || !attachment) return null;
  if (imageName && phenoCache.has(imageName)) {
    return phenoCache.get(imageName);
  }

  try {
    const url = `${normalizeBaseUrl(PHENOVISION_API_URL)}/classify`;
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(PHENOVISION_SHARED_SECRET ? { "X-API-Key": PHENOVISION_SHARED_SECRET } : {}),
      },
      body: JSON.stringify({ image_base64: attachment.contentString }),
      timeout: 30000,
    });

    if (!response.ok) {
      console.error("[PhenoVisionL 오류]", response.status, (await response.text()).slice(0, 200));
      return null;
    }
    const result = await response.json();
    if (imageName && isValidPheno(result)) {
      phenoCache.set(imageName, result);
    }
    return result;
  } catch (err) {
    console.error("[PhenoVisionL 호출 실패]", err.message);
    return null;
  }
}

function toPercent(value) {
  return `${Math.round(value * 100)}%`;
}

function buildEnrichedMessage(message, pheno) {
  if (!pheno) return message;

  return (
    `[AI 이미지 분석 결과 - 초록 잎이 있을 확률 ${toPercent(pheno.green)}, ` +
    `단풍든 잎이 있을 확률 ${toPercent(pheno.colored)}, ` +
    `새 잎눈이 있을 확률 ${toPercent(pheno.breaking_buds)} ` +
    `(PhenoVisionL 모델 판정: ${pheno.summary})]\n\n` +
    `학생 질문: ${message}`
  );
}

// AnythingLLM 에이전트 제어용 "/exit" 등이 답변 문구에 섞여 나올 때 제거한다.
function sanitizeAnswer(text) {
  return String(text || "")
    .replace(/\s*\/exit\b/gi, "")
    .replace(/['"`]?\/?exit['"`]?\s*입력을?\s*확인했어요\.?\s*/gi, "")
    .replace(/['"`]?edit['"`]?\s*입력을?\s*확인했어요\.?\s*/gi, "")
    .replace(/\s*관찰을\s*마칠게요\.?\s*/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

app.post("/api/pheno", async (req, res) => {
  try {
    const { image } = req.body || {};
    const attachment = loadImageAttachment(image);
    if (!attachment) {
      return res.status(400).json({ error: "허용된 이미지가 필요합니다.", pheno: null });
    }
    const pheno = await classifyLeafImage(attachment, image);
    res.json({ pheno });
  } catch (err) {
    console.error("[/api/pheno 예외 발생]", err);
    res.status(500).json({ error: `서버 내부 오류: ${err.message}`, pheno: null });
  }
});

app.post("/api/chat", async (req, res) => {
  try {
    const { message, image, sessionId, pheno: providedPheno } = req.body;

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

    let pheno = isValidPheno(providedPheno) ? providedPheno : null;
    if (pheno && image) {
      phenoCache.set(image, pheno);
    }
    if (!pheno) {
      pheno = await classifyLeafImage(attachment, image);
    }

    if (pheno) {
      console.log("[PhenoVisionL]", image, pheno);
    } else if (!PHENOVISION_API_URL) {
      console.warn("[PhenoVisionL] PHENOVISION_API_URL 환경변수가 없어 이미지 분석을 건너뜁니다.");
    } else if (!attachment) {
      console.warn("[PhenoVisionL] 허용된 이미지가 없어 분석을 건너뜁니다:", image);
    } else {
      console.warn("[PhenoVisionL] 분석 실패 — AnythingLLM에는 학생 문장만 전달합니다.");
    }

    const targetUrl = `${normalizeBaseUrl(ANYTHINGLLM_BASE_URL)}/api/v1/workspace/${ANYTHINGLLM_WORKSPACE_SLUG}/chat`;
    console.log("[요청] AnythingLLM 호출:", targetUrl);

    // Developer API는 메시지 앞에 "@agent"가 있어야만 Agent Flow(지식그래프 도구) 호출을 시도한다.
    const agentMessage = `@agent ${buildEnrichedMessage(message, pheno)}`;

    const response = await fetch(targetUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${ANYTHINGLLM_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message: agentMessage,
        mode: "chat",
        sessionId,
        attachments: attachment ? [attachment] : [],
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      console.error("[AnythingLLM API 오류]", response.status, text);
      return res.status(502).json({ error: `AnythingLLM 응답 오류 (${response.status}): ${text.slice(0, 200)}` });
    }

    const data = await response.json();
    const answer = sanitizeAnswer(data.textResponse || "(응답이 비어 있습니다)");
    res.json({ answer, pheno });
  } catch (err) {
    console.error("[/api/chat 예외 발생]", err);
    res.status(500).json({ error: `서버 내부 오류: ${err.message}` });
  }
});

app.get("/api/health", (req, res) => {
  res.json({ ok: true });
});

app.listen(PORT, () => {
  console.log(`학습 페이지 서버 실행 중: http://localhost:${PORT}`);
});
