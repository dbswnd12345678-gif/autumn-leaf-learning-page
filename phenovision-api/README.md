# PhenoVisionL 추론 API

잎 사진의 계절적 상태(초록잎 / 단풍든 잎 / 새 잎눈)를 판정하는 작은 API 서버입니다.
모델은 [phenobase/phenovisionL](https://huggingface.co/phenobase/phenovisionL) (ViT-Large, MIT 라이선스)을 사용합니다.

## 엔드포인트

### `GET /health`
```json
{ "ok": true, "model_loaded": true, "model_id": "phenobase/phenovisionL" }
```

### `POST /classify`

요청:
```json
{ "image_base64": "data:image/jpeg;base64,...(또는 순수 base64)" }
```

응답:
```json
{
  "green": 0.0412,
  "colored": 0.9327,
  "breaking_buds": 0.0158,
  "summary": "단풍든 잎 감지됨"
}
```

`PHENOVISION_SHARED_SECRET` 환경변수를 설정한 경우, 요청에 `X-API-Key` 헤더로 같은 값을 보내야 합니다.

## 환경변수

| 이름 | 필수 | 설명 |
|---|---|---|
| `PHENOVISION_SHARED_SECRET` | 선택 | 설정하면 `X-API-Key` 헤더 인증을 요구 |
| `DECISION_THRESHOLD` | 선택 | `summary` 문구를 만들 때 쓰는 임계값 (기본 0.5) |
| `MODEL_ID` | 선택 | 다른 모델로 교체할 때만 사용 |
| `PORT` | 자동 | Railway가 자동 주입 |

## Railway 배포 시 주의

- 서비스의 **Root Directory**를 `phenovision-api`로 지정해야 Python 서비스로 인식됩니다.
- 최초 기동 시 모델 가중치(약 1.2GB)를 내려받으므로 몇 분 걸릴 수 있습니다.
- 메모리는 2GB 이상 권장입니다.

## 모델의 한계 (교육 자료로 안내할 때 참고)

- 낙엽성 목본식물만 대상입니다. 상록수·초본식물은 학습 범위 밖입니다.
- 색의 종류(빨강/노랑), 색소 종류, 잎 면적 비율, 수종(species)은 판정하지 않습니다.
- 감지(presence)만 보고하며, 낮은 확률이 "확실히 없음"을 뜻하지는 않습니다.
