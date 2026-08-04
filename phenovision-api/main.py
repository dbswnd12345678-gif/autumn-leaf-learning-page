"""PhenoVisionL 추론 API.

잎 사진을 받아 초록잎 / 단풍잎(변색) / 새 잎눈 세 가지 상태의 확률을 반환한다.
모델: https://huggingface.co/phenobase/phenovisionL (ViT-Large, MIT)
"""

import base64
import binascii
import io
import os
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, Header, HTTPException
from PIL import Image
from pydantic import BaseModel
from transformers import AutoImageProcessor, AutoModelForImageClassification

MODEL_ID = os.getenv("MODEL_ID", "phenobase/phenovisionL")
SHARED_SECRET = os.getenv("PHENOVISION_SHARED_SECRET")
DECISION_THRESHOLD = float(os.getenv("DECISION_THRESHOLD", "0.5"))

state = {"processor": None, "model": None}


def load_model():
    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForImageClassification.from_pretrained(MODEL_ID)
    model.eval()
    state["processor"] = processor
    state["model"] = model


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 모델 가중치(약 1.2GB)를 내려받아 메모리에 올린다. 최초 기동 시 수 분 걸릴 수 있다.
    load_model()
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
    return {"ok": True, "model_loaded": state["model"] is not None, "model_id": MODEL_ID}


@app.post("/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest, x_api_key: str | None = Header(default=None)):
    if SHARED_SECRET and x_api_key != SHARED_SECRET:
        raise HTTPException(status_code=401, detail="인증 실패")
    if state["model"] is None:
        raise HTTPException(status_code=503, detail="모델을 아직 불러오는 중입니다.")

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
