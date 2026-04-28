# Menu Agent — 크루원 스타터

"오늘 점심 뭐 먹지?" — Claude SDK tool_use 루프 기반 점심 메뉴 추천 에이전트.

## 아키텍처

- 런타임: Claude SDK (anthropic Python) + Anthropic API
- 패턴: tool_use loop — `stop_reason == "tool_use"` 동안 tool 실행 후 재호출, `end_turn` 에서 종료
- 응답: JSONL structured block (message / recommendation_card / alert_card / input block 등)

## 디렉터리

```
apps/api/app/
  agent/
    prompts/__init__.py     ← SYSTEM_PROMPT (세션마다 누적 수정)
    runner.py               ← tool_use 루프 본체
    tools_registry.py       ← TOOL_DEFINITIONS + TOOL_HANDLERS
  tools/                    ← 각 tool 구현체 (handle 함수)
  services/                 ← 검색·메모리 도메인 서비스
  repositories/             ← Postgres/Qdrant 접근
  api/routes/               ← /api/agent, /api/users, /api/feedback

apps/web/src/
  lib/session-flags.ts      ← 토글 flag 정의
  components/blocks/        ← UI block 렌더러
```

## 주요 파일

- **프롬프트**: `apps/api/app/agent/prompts/__init__.py` — `SYSTEM_PROMPT` 한 변수
- **에이전트 루프**: `apps/api/app/agent/runner.py::run_agent_stream`
- **Tool 등록**: `apps/api/app/agent/tools_registry.py`

## Tool 추가 패턴

1. `apps/api/app/tools/<name>.py` — `handle(...) -> dict` 구현
2. `tools_registry.py` — `TOOL_DEFINITIONS` 에 JSON Schema append, `TOOL_HANDLERS` 에 매핑
3. `prompts/__init__.py` — SYSTEM_PROMPT 에 tool 설명 추가
4. (토글 추가 시) `apps/web/src/lib/session-flags.ts` + `runner.py::_TOOL_GROUPS`

## 코드 규칙

- 커밋은 사용자 요청 시에만
- 코드 변경은 저장하면 자동 반영 (uvicorn watchfiles + Vite HMR)
- API만 재시작 필요하면: `docker compose restart api`
