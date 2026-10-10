# Agent Flows 설정서 (AnythingLLM > Agent Skills > Agent Flows)

모든 Flow는 "API Call" 블록 하나로 만들고, 공통 설정은 같습니다.

- Method: GET
- Header: `X-Tool-Key` = Railway의 `TOOL_API_KEY` 값
- Base URL: `https://<학습 페이지 주소>` (로컬 점검 시 AnythingLLM이 닿을 수 있는 주소)
- Flow 입력 변수: `studentId` (메시지 태그 `[studentId: ...]`의 값)
- 응답은 JSON이며, Agent는 `howToUse`와 본문 필드를 읽어 답변에 씁니다.

| Flow 이름 | URL | 주 사용 모드 | 하는 일 |
|---|---|---|---|
| 관찰력 평가 데이터 조회 | `/api/tools/observation-assessment?studentId={studentId}` | 3 (선택), 연구 확인 | 평가 기준과 이 학생의 탭 1 진단 결과(수준, 쓰지 않은 범주) |
| 오프로딩 단계 진단 조회 | `/api/tools/offloading-diagnosis?studentId={studentId}` | 3 (선택), 연구 확인 | 단계 정의와 이 학생의 탭 2 진단 결과(요청 유형, 반영 비율) |
| 오프로딩 단계별 지원방법 조회 | `/api/tools/support-methods?studentId={studentId}` | 3 (매 턴) | 서버가 계산한 지원 수준의 방법, 하지 말 것, 오프로딩 단계 메모 |
| 단풍잎 관찰 시 관찰 유형 및 방법 지원 | `/api/tools/observation-methods?studentId={studentId}` | 3 (문장 입력 시) | 학생이 아직 쓰지 않은 관찰 유형 최대 3개와 방법, 질문, 문장 틀 |
| 개인별 대화 로그 조회 | `/api/tools/dialogue-log?studentId={studentId}&mode=support&limit=10` | 3 (필요 시) | 최근 대화. 기록은 서버가 항상 저장하고 Agent는 읽기만 함 |

## 역할 정리
- 탭 1(관찰력 진단)과 탭 2(오프로딩 진단)에는 실시간 Agent가 없습니다. 최종 제출 때 서버가 키워드 채점을 하고, 이어서 채점용 워크스페이스에 JSON 판정을 요청해 `diagnoses` 표에 저장합니다.
- 위 Flow 중 진단 조회 2개는 저장된 진단을 읽는 용도라서, 탭 3 Agent가 필요할 때 쓰거나 연구자가 점검할 때 씁니다.
- 대화 로그 "기록"은 Flow가 아니라 서버(`/api/chat`)가 항상 저장합니다. Agent가 호출을 빼먹어도 기록은 남습니다.

## 호출 준수 확인
- 서버는 탭 3의 각 턴에서 `support_methods` 또는 `observation_methods` 호출이 없으면 `tool_calls`에 `tool_skipped`를 남기고, 관찰 기록 행에 `tool_skipped=1`을 적습니다.
- 연구자 확인: `GET /api/admin/tool-calls?key=ADMIN_KEY`, 엑셀 내보내기의 `Tool호출이력`, `진단결과` 시트(도구 누락 턴 수).

## Railway 환경변수 (학습 페이지 서비스)
- `WS_SLUG_ASSESS`, `WS_SLUG_OFFLOAD`, `WS_SLUG_SUPPORT`: 워크스페이스 slug
- `WS_SLUG_JUDGE`: 선택. 비우면 `WS_SLUG_ASSESS`로 채점 요청
- `SESSION_SECONDS`: 선택. 기본 600
- `UNLOCK_ALL=1`: 선택. 점검용. 탭 3 잠금을 풉니다(수업 때는 설정하지 않음)

## 워크스페이스 1 (관찰력 진단) Flow 2개: 실제 구성 (AnythingLLM에 만들어 둠)
워크스페이스 slug는 `autumn-assess`, 채팅 모드는 "에이전트"이며 서버가 메시지를 `@agent [studentId: 학번]`으로 시작해 보냅니다. `[task: ...]` 같은 꼬리표는 쓰지 않습니다.

| Flow 이름 | 호출 | 주소 | 변수 | 역할 |
| --- | --- | --- | --- | --- |
| 관찰력 진단 기준 조회 | GET | `/api/tools/observation-criteria?studentId=${studentId}` | studentId, criteriaResult(응답 저장) | 범주 정의, 수준 정의, 사진 일치 값을 돌려줌 |
| 관찰력 진단 결과 기록 | POST (JSON) | `/api/tools/observation-result` | studentId, level, categories, photoMatch, rationale, recordResult(응답 저장) | Agent가 채점한 수준을 DB(diagnoses)에 기록. 학생에게는 답을 하지 않음 |

- 두 Flow 모두 헤더 `X-Tool-Key`에 Railway의 `TOOL_API_KEY`와 같은 값을 넣습니다.
- 기록 Flow의 본문(JSON): `{"studentId": "${studentId}", "level": "${level}", "categories": "${categories}", "photoMatch": "${photoMatch}", "rationale": "${rationale}"}`
- 서버는 제출 직후 키워드 채점을 먼저 저장하고, Agent가 기록 Flow를 부르면 그 결과로 최종 수준을 덮어씁니다(`judgeStatus: done`, `judge.recordedBy: agent`). 부르지 않으면 `judgeStatus: failed`로 남고 키워드 채점이 최종값입니다.
- Flow는 AnythingLLM 전체에서 공유됩니다. 이 워크스페이스에서 쓰지 않을 이전 Flow(교육학 안내 조회, 학생 관찰 이력 조회)는 시스템 프롬프트가 두 Flow만 부르도록 제한합니다.