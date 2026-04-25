# Menu Agent — 크루원 스타터

"오늘 뭐 먹지?" — Claude SDK tool_use 기반 점심 메뉴 추천 에이전트를 6개 세션에 걸쳐 완성해 나갑니다.

## 학습 방식

기본 기능은 완성본으로 제공되고 **토글** 로 껐다 켤 수 있습니다 (헤더 드롭다운). 크루원은 세션을 진행하면서:

1. **프롬프트 작성** (메인 과제) — `apps/api/app/agent/prompts/__init__.py` 의 `SYSTEM_PROMPT` 한 변수를 세션마다 누적 수정합니다. 시작 상태는 세션 1 프롬프트로 채워져있어 docker compose up 직후 바로 동작합니다. 세션 6 진입 시점에만 `EVAL_RULES` 를 분리해 `BASE_SYSTEM_PROMPT + EVAL_RULES` split 구조로 바꿉니다 (self_check 토글 효과를 위해).
2. **Tool 수정 포인트** — tool 파일 안 `# [student-edit]` 주석이 붙은 곳을 본인 취향대로 고쳐봅니다. 선택 과제입니다.
3. **(심화)** 새로운 tool / 새로운 block 타입 / 새로운 UI 를 직접 추가합니다.

## 아키텍처

- 런타임: Claude SDK (anthropic Python) + Anthropic API
- 패턴: tool_use loop (stop_reason 체크하며 LLM 호출 반복)
- 응답: structured block 배열 (message / recommendation_card / choice_chips / alert_card / input block 등)

## Tool 목록 (전부 완성본으로 제공 · 토글로 on/off)

| Tool | 세션 | 설명 |
|---|---|---|
| `get_user_memory` | 2 | Postgres 에서 사용자 선호 조회 |
| `update_user_memory` | 2 | 대화에서 나온 선호를 Postgres 에 기록 |
| `search_menus` | 3 | "뭐 먹지?" 단계의 메뉴 RAG |
| `search_restaurants` | 3 | 식당 결정 단계의 RAG + rerank |
| `get_weather` | 4 | Open-Meteo 실시간 날씨 |
| `get_landmark` | 4 | 랜드마크/역 이름 → 좌표 |
| `estimate_travel_time` | 4 | 도보 이동시간 (haversine) |
| `ask_user` | 5 | form 으로 추가 정보 요청 (Generative UI) |
| `evaluate_response` | 6 | LLM-as-judge 기반 응답 평가 + 환각 감지 |

## 기술 스택

- Frontend: React + TypeScript + Vite
- Backend: FastAPI + Pydantic
- DB: PostgreSQL (memory/metadata) + Qdrant (RAG)
- Infra: Docker Compose

## 디렉터리 구조

```
apps/api/app/
  agent/
    prompts/__init__.py     ← 크루원이 매 세션 SYSTEM_PROMPT 를 누적 수정
    runner.py               ← tool_use 루프
    tools_registry.py       ← tool 스키마 + 핸들러 등록 (완성본)
  tools/*.py                ← tool 구현체 (완성본, 일부 edit 포인트)
  services/, repositories/  ← 인프라 계층

apps/web/
  src/lib/session-flags.ts  ← 토글 정의
  src/components/SessionFlagsDropdown.tsx  ← 헤더 토글 UI
  src/components/blocks/    ← UI block 렌더러
```

## 실행

1. `.env` 준비 (Anthropic API 키 등). `.env.example` 참고.
2. `docker compose up` — Postgres / Qdrant / migrate / api / web 순차 기동.
3. 웹 `http://localhost:3000` 접속.

## 크루원 과제 가이드

세션별 학습 목표·실습 스텝·토글 설정·테스트 시나리오·추가 과제는 **`guide/`** 폴더에 정리돼 있습니다.

- [`guide/00_setup.md`](./guide/00_setup.md) — 환경 세팅 / 토글 UI / 편집 위치
- [`guide/01_overview.md`](./guide/01_overview.md) — 6 세션 전체 흐름 + 토글 매핑
- `guide/session-N.md` — 각 세션 실습

빠른 참조:

- 프롬프트 편집 위치: `apps/api/app/agent/prompts/__init__.py` 의 `SYSTEM_PROMPT` (세션 6 진입 시점에 `BASE_SYSTEM_PROMPT` + `EVAL_RULES` 로 split)
- Tool 수정 포인트: 코드 안 `# [student-edit]` 주석 검색
- 심화: 새 tool 추가는 `apps/api/app/tools/` + `tools_registry.py` + `__init__.py` 프롬프트
