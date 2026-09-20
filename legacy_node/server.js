require("dotenv").config();
const express = require("express");
const fs = require("fs");
const path = require("path");
const fetch = require("node-fetch");
const ExcelJS = require("exceljs");
const { Document, Packer, Paragraph, HeadingLevel, TextRun } = require("docx");

const app = express();
app.use(express.json({ limit: "12mb" }));
app.use(express.static(path.join(__dirname, "public")));

const {
  ANYTHINGLLM_BASE_URL,
  ANYTHINGLLM_API_KEY,
  ANYTHINGLLM_WORKSPACE_SLUG,
  PHENOVISION_API_URL,
  PHENOVISION_SHARED_SECRET,
  ADMIN_KEY,
  DATA_DIR: DATA_DIR_ENV,
  PORT = 3000,
} = process.env;

const IMAGES_DIR = path.join(__dirname, "public", "images");
const ALLOWED_IMAGES = ["leaf1.jpg", "leaf2.jpg", "leaf3.webp", "leaf4.jpg", "leaf5.png"];
// 같은 샘플 이미지는 매 질문마다 다시 분류하지 않도록 메모리 캐시
const phenoCache = new Map();

// 학생별 대화 기록(질문+답변)을 저장하는 폴더.
// Railway에서는 이 경로에 Volume을 연결해야 재배포 후에도 기록이 사라지지 않는다.
const DATA_DIR = path.isAbsolute(DATA_DIR_ENV || "")
  ? DATA_DIR_ENV
  : path.join(__dirname, DATA_DIR_ENV || "data");
if (!fs.existsSync(DATA_DIR)) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

if (!ANYTHINGLLM_BASE_URL || !ANYTHINGLLM_API_KEY || !ANYTHINGLLM_WORKSPACE_SLUG) {
  console.warn(
    "[경고] .env 파일(또는 Railway 환경변수)에 ANYTHINGLLM_BASE_URL / ANYTHINGLLM_API_KEY / ANYTHINGLLM_WORKSPACE_SLUG 가 설정되지 않았습니다."
  );
}
if (!ADMIN_KEY) {
  console.warn(
    "[경고] ADMIN_KEY 환경변수가 설정되지 않았습니다. 연구자용 전체 대화 기록 다운로드(/api/admin/*)를 쓸 수 없습니다."
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

// ---------------------------------------------------------------------------
// 대화 기록 저장/조회
// 세션(학생)마다 data/<sessionId>.jsonl 파일에 한 줄씩 append한다.
// AnythingLLM의 Agent Skill/Flow가 아니라, 모든 요청이 이미 지나가는 이 서버에서
// 직접 기록하기 때문에 빠짐없이 저장되고 형식도 우리가 원하는 대로 만들 수 있다.
// ---------------------------------------------------------------------------

function sanitizeSessionId(sessionId) {
  return String(sessionId || "").replace(/[^a-zA-Z0-9_-]/g, "");
}

function sessionLogPath(sessionId) {
  const safe = sanitizeSessionId(sessionId);
  return safe ? path.join(DATA_DIR, `${safe}.jsonl`) : null;
}

function appendConversationLog(sessionId, entry) {
  const filePath = sessionLogPath(sessionId);
  if (!filePath) return;
  try {
    fs.appendFileSync(filePath, `${JSON.stringify(entry)}\n`, "utf8");
  } catch (err) {
    console.error("[대화 기록 저장 실패]", err.message);
  }
}

function readConversationLog(sessionId) {
  const filePath = sessionLogPath(sessionId);
  if (!filePath || !fs.existsSync(filePath)) return [];
  return fs
    .readFileSync(filePath, "utf8")
    .replace(/^\uFEFF/, "") // 일부 편집기가 남기는 BOM 방어
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

function listSessionIds() {
  if (!fs.existsSync(DATA_DIR)) return [];
  return fs
    .readdirSync(DATA_DIR)
    .filter((name) => name.endsWith(".jsonl"))
    .map((name) => name.slice(0, -".jsonl".length));
}

function toFilenameSafe(str) {
  return String(str).replace(/[^a-zA-Z0-9_-]/g, "_");
}

function requireAdminKey(req, res, next) {
  if (!ADMIN_KEY) {
    return res.status(500).json({ error: "서버에 ADMIN_KEY 환경변수가 설정되지 않았습니다." });
  }
  const providedKey = req.query.key || req.headers["x-admin-key"];
  if (!providedKey || providedKey !== ADMIN_KEY) {
    return res.status(403).json({ error: "관리자 키가 올바르지 않습니다." });
  }
  next();
}

// --- Excel(.xlsx) 생성 ---

function addConversationSheet(workbook, sheetTitle, entries) {
  const sheet = workbook.addWorksheet(sheetTitle);
  sheet.columns = [
    { header: "시간", key: "timestamp", width: 22 },
    { header: "이미지", key: "image", width: 12 },
    { header: "학생 질문", key: "question", width: 45 },
    { header: "AI 답변", key: "answer", width: 65 },
    { header: "PhenoVisionL 판정", key: "phenoSummary", width: 22 },
  ];
  sheet.getRow(1).font = { bold: true };
  entries.forEach((entry) => {
    const row = sheet.addRow({
      timestamp: entry.timestamp || "",
      image: entry.image || "",
      question: entry.question || "",
      answer: entry.answer || "",
      phenoSummary: entry.pheno && entry.pheno.summary ? entry.pheno.summary : "",
    });
    row.alignment = { wrapText: true, vertical: "top" };
  });
  return sheet;
}

async function buildSessionXlsxBuffer(sessionId, entries) {
  const workbook = new ExcelJS.Workbook();
  addConversationSheet(workbook, "대화 기록", entries);
  return workbook.xlsx.writeBuffer();
}

async function buildAdminXlsxBuffer(sessions) {
  const workbook = new ExcelJS.Workbook();
  const usedNames = new Set();
  sessions.forEach(({ sessionId, entries }) => {
    let sheetName = sessionId.replace(/[\\/*?:[\]]/g, "").slice(0, 31) || "session";
    let suffix = 1;
    while (usedNames.has(sheetName)) {
      sheetName = `${sheetName.slice(0, 28)}_${suffix++}`;
    }
    usedNames.add(sheetName);
    addConversationSheet(workbook, sheetName, entries);
  });
  return workbook.xlsx.writeBuffer();
}

// --- Word(.docx) 생성 ---

function buildSessionDocChildren(sessionId, entries) {
  const children = [
    new Paragraph({ text: `대화 기록 - ${sessionId}`, heading: HeadingLevel.HEADING_1 }),
  ];
  if (entries.length === 0) {
    children.push(new Paragraph({ text: "저장된 대화 기록이 없습니다." }));
  }
  entries.forEach((entry) => {
    children.push(
      new Paragraph({
        text: `[${entry.timestamp || ""}] 이미지: ${entry.image || "-"}${
          entry.pheno && entry.pheno.summary ? ` · PhenoVisionL 판정: ${entry.pheno.summary}` : ""
        }`,
        heading: HeadingLevel.HEADING_3,
      })
    );
    children.push(
      new Paragraph({
        children: [new TextRun({ text: "학생: ", bold: true }), new TextRun(entry.question || "")],
      })
    );
    children.push(
      new Paragraph({
        children: [new TextRun({ text: "AI: ", bold: true }), new TextRun(entry.answer || "")],
      })
    );
    children.push(new Paragraph({ text: "" }));
  });
  return children;
}

async function buildSessionDocxBuffer(sessionId, entries) {
  const doc = new Document({
    sections: [{ children: buildSessionDocChildren(sessionId, entries) }],
  });
  return Packer.toBuffer(doc);
}

async function buildAdminDocxBuffer(sessions) {
  const children = [];
  sessions.forEach(({ sessionId, entries }, idx) => {
    const sectionChildren = buildSessionDocChildren(sessionId, entries);
    // 학생마다 새 페이지에서 시작하도록 첫 번째 제목 단락에만 pageBreakBefore를 준다.
    sectionChildren[0] = new Paragraph({
      text: `대화 기록 - ${sessionId}`,
      heading: HeadingLevel.HEADING_1,
      pageBreakBefore: idx > 0,
    });
    children.push(...sectionChildren);
  });
  const doc = new Document({ sections: [{ children }] });
  return Packer.toBuffer(doc);
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

    appendConversationLog(sessionId, {
      timestamp: new Date().toISOString(),
      image,
      pheno,
      question: message,
      answer,
    });

    res.json({ answer, pheno });
  } catch (err) {
    console.error("[/api/chat 예외 발생]", err);
    res.status(500).json({ error: `서버 내부 오류: ${err.message}` });
  }
});

// 학생 본인의 대화 기록을 엑셀/워드 파일로 다운로드한다.
// sessionId는 브라우저 localStorage에만 저장되는 임의의 값이라 URL 자체가 접근 권한 역할을 한다.
app.get("/api/history/:sessionId/export", async (req, res) => {
  try {
    const { sessionId } = req.params;
    const format = String(req.query.format || "xlsx").toLowerCase();
    const entries = readConversationLog(sessionId);
    if (entries.length === 0) {
      return res.status(404).json({ error: "저장된 대화 기록이 없습니다." });
    }

    const filenameBase = `autumn-leaf-chat-${toFilenameSafe(sessionId)}`;
    if (format === "docx") {
      const buffer = await buildSessionDocxBuffer(sessionId, entries);
      res.setHeader(
        "Content-Type",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      );
      res.setHeader("Content-Disposition", `attachment; filename="${filenameBase}.docx"`);
      return res.send(buffer);
    }

    const buffer = await buildSessionXlsxBuffer(sessionId, entries);
    res.setHeader(
      "Content-Type",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    );
    res.setHeader("Content-Disposition", `attachment; filename="${filenameBase}.xlsx"`);
    res.send(buffer);
  } catch (err) {
    console.error("[/api/history export 예외 발생]", err);
    res.status(500).json({ error: `서버 내부 오류: ${err.message}` });
  }
});

// --- 연구자(관리자)용: 학생 전체 목록 및 전체 다운로드 (?key=ADMIN_KEY 필요) ---

app.get("/api/admin/sessions", requireAdminKey, (req, res) => {
  const sessions = listSessionIds()
    .map((sessionId) => {
      const entries = readConversationLog(sessionId);
      return {
        sessionId,
        turnCount: entries.length,
        firstAt: entries[0]?.timestamp || null,
        lastAt: entries[entries.length - 1]?.timestamp || null,
      };
    })
    .sort((a, b) => (a.firstAt || "").localeCompare(b.firstAt || ""));
  res.json({ sessions });
});

app.get("/api/admin/export", requireAdminKey, async (req, res) => {
  try {
    const format = String(req.query.format || "xlsx").toLowerCase();
    const sessions = listSessionIds()
      .map((sessionId) => ({ sessionId, entries: readConversationLog(sessionId) }))
      .filter((session) => session.entries.length > 0);

    if (sessions.length === 0) {
      return res.status(404).json({ error: "저장된 대화 기록이 없습니다." });
    }

    if (format === "docx") {
      const buffer = await buildAdminDocxBuffer(sessions);
      res.setHeader(
        "Content-Type",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      );
      res.setHeader("Content-Disposition", `attachment; filename="autumn-leaf-chat-all-students.docx"`);
      return res.send(buffer);
    }

    const buffer = await buildAdminXlsxBuffer(sessions);
    res.setHeader(
      "Content-Type",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    );
    res.setHeader("Content-Disposition", `attachment; filename="autumn-leaf-chat-all-students.xlsx"`);
    res.send(buffer);
  } catch (err) {
    console.error("[/api/admin/export 예외 발생]", err);
    res.status(500).json({ error: `서버 내부 오류: ${err.message}` });
  }
});

app.get("/api/health", (req, res) => {
  res.json({ ok: true });
});

app.listen(PORT, () => {
  console.log(`학습 페이지 서버 실행 중: http://localhost:${PORT}`);
});
