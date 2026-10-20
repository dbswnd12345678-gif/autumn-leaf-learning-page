# Agent Flows 설정서 (AnythingLLM > Agent Skills > Agent Flows)

모든 Flow는 "API Call" 블록 하나로 만들고, 공통 설정은 같습니다.

- Method: GET
- Header: `X-Tool-Key` = Railway의 `TOOL_API_KEY` 값
- Base URL: `https://<학습 페이지 주소>` (로컬 점검 시 AnythingLLM이 닿을 수 있는 주소)
- Flow 입력 변수: `studentId` (메시지 태그 `[studentId: ...]`의 값)
- 응답은 JSON이며, Agent는 `howToUse`와 본문 필드를 읽어 답변에 씁니다.

| Flow 이름 | URL | 주 사용 모드 | 하는 일 |
|---|---|---|---|
| 관찰력 평가 데이터 조회 | `/api/tools/observation-assessment?studentId={studentId}` | 3 (선택), 연구 확인 | 평가 기준과 이 학생의 탭 1 진단 결과(수준, OQ_A, 다양도 D, 쓰지 않은 관찰 유형, 범위 밖 표시 수) |
| 오프로딩 단계 진단 조회 | `/api/tools/offloading-diagnosis?studentId={studentId}` | 3 (선택), 연구 확인 | 단계 정의와 이 학생의 탭 2 진단 결과(요청 유형, 반영 비율) |
| 오프로딩 단계별 지원방법 조회 | `/api/tools/support-methods?studentId={studentId}` | 3 (매 턴) | 관찰 진단(무엇을 물을지)과 오프로딩 단계(어떻게 말할지)를 각각 돌려줌. 둘을 하나의 지원 수준으로 합치지 않음 |
| 단풍잎 관찰 시 관찰 유형 및 방법 지원 | `/api/tools/observation-methods?studentId={studentId}` | 3 (문장 입력 시) | 학생이 아직 쓰지 않은 관찰 유형(측정 x 비교 x 범위 8가지 중) 최대 3개와 방법, 질문, 문장 틀. 방금 쓴 문장이 시각 이외 감각이나 시간 흐름이면 바꾸어 쓰는 안내(outOfScopeGuidance)도 함께 |
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

## 워크스페이스 1 (관찰력 진단) Flow 2개
워크스페이스 slug는 `autumn-assess`, 채팅 모드는 "에이전트"이며 서버가 메시지를 `@agent [studentId: 학번]`으로 시작해 보냅니다. `[task: ...]` 같은 꼬리표는 쓰지 않습니다. 시스템 프롬프트는 `prompts/ws1_assess_judge_system_prompt.txt`입니다.

평가 기준은 `knowledge/observation_rubric.json`(연구자 검토 초안 v4를 반영)입니다. 문장(채팅 메시지 한 번)을 정보 단위로 나누고, 단위마다 객관도(0~3)와 측정/비교/범위, 범위 밖(시각 이외 감각, 시간 흐름) 표시를 정합니다. 기존 7개 범주(색, 모양, 잎맥 등)는 쓰지 않습니다.

| Flow 이름 | 호출 | 주소 | 변수 | 역할 |
| --- | --- | --- | --- | --- |
| 관찰력 진단 기준 조회 | GET | `/api/tools/observation-criteria?studentId=${studentId}` | studentId, criteriaResult(응답 저장) | 정보 단위, 6차원 분류(측정/비교/범위), 범위 밖 표시, 관찰 수준(LE), 객관도 0~3, 기록 형식, 사진 일치 값을 돌려줌 |
| 관찰력 진단 결과 기록 | POST (JSON) | `/api/tools/observation-result` | studentId, messages, photoMatch, rationale, recordResult(응답 저장) | Agent가 문장별로 분류한 결과를 보내면 서버가 지수를 계산해 DB(diagnoses)에 기록. 학생에게는 답을 하지 않음 |

- 두 Flow 모두 헤더 `X-Tool-Key`에 Railway의 `TOOL_API_KEY`와 같은 값을 넣습니다.
- 기록 Flow의 본문(JSON): `{"studentId": "${studentId}", "messages": "${messages}", "photoMatch": "${photoMatch}", "rationale": "${rationale}"}`
  - **변경:** 이전 변수 `level`, `categories`는 더 이상 쓰지 않으므로 Flow에서 빼고 `messages`를 추가합니다. (서버는 이전 형식의 `level`만 와도 받아서 수준만 기록하지만, 지수가 계산되지 않습니다.)
- `messages` 형식(따옴표, 중괄호, 줄바꿈 없는 한 줄): `문장번호:LE:단위,단위;문장번호:LE:단위`
  - 단위 하나는 `객관도-측정-비교-범위`입니다. 예: `2-정성-단수-부분`, `3-정량-단수-전체`
  - 관찰이 아닌 단위는 `0`, 시각 이외 감각은 `OOS-감각`, 시간 흐름은 `OOS-시간`
  - 예: `1:2:2-정성-단수-부분,2-정성-단수-부분;2:1:3-정량-단수-전체;3:1:OOS-감각;4:1:0`
- 서버는 제출 직후 문장 원문만 저장합니다(`judgeStatus: pending`, 유형과 객관도는 비어 있음). Agent가 기록 Flow를 부르면 그 분류만으로 서버가 다음을 계산합니다. 단어 규칙으로 빈칸을 채우지 않습니다.
  - 문장 기여값 = LE x ΣDO (범위 밖 단위와 객관도 0 단위는 제외)
  - 다양도 D = 사용한 관찰 유형 수(측정 x 비교 x 범위, 최대 8)
  - OQ_A = (모든 문장 기여값의 합) x D, 그리고 지원 수준 계산에 쓰는 관찰력 수준(1~3)
- Agent가 일부 문장만 기록하면 응답의 `missingIndexes`에 빠진 번호가 나옵니다. 그 문장은 분류 전으로 남고, 수준과 OQ_A는 모든 문장이 기록된 뒤에만 확정됩니다. 기록을 전혀 하지 않으면 `judgeStatus: failed`로 남고 문장 원문만 최종 기록입니다.
- 관찰력 수준(1~3) 구간(`levelThresholds`)과 LE 기준은 **임시 값**입니다. 연구자가 확정하면 `knowledge/observation_rubric.json`에서 고칩니다. 서버를 다시 배포하면 반영됩니다.
- Flow는 AnythingLLM 전체에서 공유됩니다. 이 워크스페이스에서 쓰지 않을 이전 Flow(교육학 안내 조회, 학생 관찰 이력 조회 등)는 시스템 프롬프트가 두 Flow만 부르도록 제한합니다.