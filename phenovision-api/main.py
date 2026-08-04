"""PhenoVisionL 추론 API.

잎 사진을 받아 초록잎 / 단풍잎(변색) / 새 잎눈 세 가지 상태의 확률을 반환한다.
모델: https://huggingface.co/phenobase/phenovisionL (ViT-Large, MIT)
"""

import base64
import binascii
import io
import os
import threading
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, Header, HTTPException
from PIL import Image
from pydantic import BaseModel
from transformers import AutoImageProcessor, AutoModelForImageClassification

MODEL_ID = os.getenv("MODEL_ID", "phenobase/phenovisionL")
SHARED_SECRET = os.getenv("PHENOVISION_SHARED_SECRET")
DECISION_THRESHOLD = float(os.getenv("DECISION_THRESHOLD", "0.5"))

state = {
    "processor": None,
    "model": None,
    "loading": False,
    "ready": False,
    "error": None,
}


def load_model():
    state["loading"] = True
    state["error"] = None
    try:
        print(f"[PhenoVisionL] 모델 로딩 시작: {MODEL_ID}")
        processor = AutoImageProcessor.from_pretrained(MODEL_ID)
        model = AutoModelForImageClassification.from_pretrained(MODEL_ID)
        model.eval()
        state["processor"] = processor
        state["model"] = model
        state["ready"] = True
        print("[PhenoVisionL] 모델 로딩 완료")
    except Exception as err:
        state["error"] = str(err)
        state["ready"] = False
        print(f"[PhenoVisionL] 모델 로딩 실패: {err}")
    finally:
        state["loading"] = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버를 먼저 띄운 뒤 백그라운드에서 모델을 내려받는다.
    # (Railway healthcheck가 모델 다운로드를 기다리다 실패하지 않도록)
    threading.Thread(target=load_model, daemon=True).start()
    yield


app = FastAPI(title="PhenoVisionL API", lifespan=lifespan)


class ClassifyRequest(BaseModel):
    image_base64: str


class ClassifyResponse(BaseModel):
    green: float
    colored: float
    breaking_buds: float
    summary: str


def decode_image(image_base64: str) -> Image.Image:
    payload = image_base64.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="base64 이미지를 해석할 수 없습니다.")
    try:
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except OSError:
        raise HTTPException(status_code=400, detail="이미지 파일을 열 수 없습니다.")


def build_summary(green: float, colored: float, breaking_buds: float) -> str:
    detected = []
    if colored >= DECISION_THRESHOLD:
        detected.append("단풍든 잎")
    if green >= DECISION_THRESHOLD:
        detected.append("초록잎")
    if breaking_buds >= DECISION_THRESHOLD:
        detected.append("새 잎눈")
    if not detected:
        return "뚜렷하게 감지된 상태 없음"
    return ", ".join(detected) + " 감지됨"


@app.get("/health")
def health():
    return {
        "ok": True,
        "model_loaded": state["ready"],
        "model_loading": state["loading"],
        "model_id": MODEL_ID,
        "error": state["error"],
    }


@app.post("/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest, x_api_key: str | None = Header(default=None)):
    if SHARED_SECRET and x_api_key != SHARED_SECRET:
        raise HTTPException(status_code=401, detail="인증 실패")
    if state["loading"] and not state["ready"]:
        raise HTTPException(status_code=503, detail="모델을 아직 불러오는 중입니다. 1~3분 후 다시 시도해주세요.")
    if state["model"] is None:
        detail = state["error"] or "모델을 아직 불러오지 못했습니다."
        raise HTTPException(status_code=503, detail=detail)

    image = decode_image(req.image_base64)
    inputs = state["processor"](images=image, return_tensors="pt")

    with torch.no_grad():
        logits = state["model"](**inputs).logits
        probs = torch.sigmoid(logits)[0]

    green, colored, breaking_buds = (round(p.item(), 4) for p in probs[:3])
    return ClassifyResponse(
        green=green,
        colored=colored,
        breaking_buds=breaking_buds,
        summary=build_summary(green, colored, breaking_buds),
    )
