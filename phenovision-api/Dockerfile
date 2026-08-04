# Railway에서 PyTorch CPU 빌드가 안정적으로 되도록 Docker로 고정
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY . .

EXPOSE 8080

# 모델 가중치는 첫 기동 시 내려받는다 (빌드 시간/이미지 용량을 줄이기 위함)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
