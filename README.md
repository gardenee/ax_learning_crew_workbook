# 오늘 점심 뭐 먹지?

Claude SDK `tool_use` 루프 기반 점심 메뉴 추천 에이전트. 6세션에 걸쳐 프롬프트를 만지고, tool을 추가하면서 에이전트를 점진적으로 발전시켜 나갑니다.

- **Frontend**: React + TypeScript + Vite
- **Backend**: FastAPI + Anthropic Python SDK
- **Storage**: PostgreSQL (메모리) + Qdrant (식당·메뉴 RAG)
- **Runtime**: Docker Compose

---

## 실행

```bash
cp .env.example .env        # ANTHROPIC_API_KEY 채우기
docker compose up           # 또는 make up
```

첫 기동은 5~10분 걸립니다 (이미지 빌드 + 벡터 스냅샷 복원). 이후는 30초 이내.

### 접속 주소

| 서비스 | URL |
|---|---|
| 웹 | http://localhost:3000 |
| API Swagger | http://localhost:8000/docs |
| API health | http://localhost:8000/health |
| Adminer (DB 뷰어) | http://localhost:8080 |
| Qdrant 대시보드 | http://localhost:6333/dashboard |

Adminer 로그인: server `postgres` / user `app` / password `app` / database `menu_agent`

---

## 커맨드

```bash
make up           # docker compose up --build (포그라운드)
make up-d         # 백그라운드 기동
make down         # 컨테이너 내리기
make reset        # 볼륨까지 날리기 (완전 초기화)
make logs         # api 로그 follow
make test         # pytest
make web-test     # jest
make lint         # ruff + eslint
make shell-api    # api 컨테이너 셸
make shell-web    # web 컨테이너 셸
```

자주 쓰는 Docker 커맨드:

```bash
docker compose ps                    # 컨테이너 상태 확인
docker compose logs -f api           # api 로그 실시간
docker compose logs qdrant-init      # 벡터 스냅샷 복원 결과 확인
docker compose restart api           # api만 재시작 (코드 안 반영될 때)
docker compose down -v               # 볼륨까지 삭제
```

---

## 구조

```
apps/
  api/
    app/
      agent/
        prompts/__init__.py    ← SYSTEM_PROMPT — 세션마다 여기를 고친다
        runner.py              ← tool_use 루프
        tools_registry.py      ← tool 스키마 + 핸들러 등록
      tools/                   ← 각 tool 구현체 (완성본)
      services/                ← 검색·메모리 도메인 서비스
      repositories/            ← Postgres/Qdrant 접근
      api/routes/              ← /api/agent, /api/users, /api/feedback
  web/
    src/
      pages/
      components/
        blocks/                ← UI block 렌더러
infra/db/migrations/           ← 001_init.sql
data/qdrant_snapshots/         ← 복원용 스냅샷
```

코드 변경은 저장하면 자동 반영됩니다 (uvicorn watchfiles + Vite HMR).

---

## 수정 범위

### 프롬프트

`apps/api/app/agent/prompts/__init__.py` 의 `SYSTEM_PROMPT` 한 변수. 세션마다 내용을 누적해서 추가합니다.

세션 6에서만 `BASE_SYSTEM_PROMPT + EVAL_RULES` split 구조로 바꿉니다.

### Tool 추가

새 tool을 직접 만들고 싶을 때 흐름:

1. `apps/api/app/tools/<name>.py` — `handle(input: dict) -> dict` 구현
2. `apps/api/app/agent/tools_registry.py` — `TOOL_DEFINITIONS` 에 JSON Schema 추가, `TOOL_HANDLERS` 에 매핑
3. `prompts/__init__.py` — SYSTEM_PROMPT 에 tool 설명 추가

Claude Code에 "새 tool 추가해줘" 하면 세 파일을 한번에 잡아줍니다.

---

## 토글

헤더 드롭다운에서 기능을 켜고 끌 수 있습니다. 세션마다 가이드가 시키는 대로 켜면 됩니다.

```
              remember  memory  search  weather  landmark  travel  ask_user  gen_ui  self_check
세션 1  →     [O]       [ ]     [ ]     [ ]      [ ]       [ ]     [ ]       [ ]     [ ]
세션 2  →     [O]       [O]     [ ]     [ ]      [ ]       [ ]     [ ]       [ ]     [ ]
세션 3  →     [O]       [O]     [O]     [ ]      [ ]       [ ]     [ ]       [ ]     [ ]
세션 4  →     [O]       [O]     [O]     [O]      [O]       [O]     [ ]       [ ]     [ ]
세션 5  →     [O]       [O]     [O]     [O]      [O]       [O]     [O]       [O]     [ ]
세션 6  →     [O]       [O]     [O]     [O]      [O]       [O]     [O]       [O]     [O]
```

토글 상태는 localStorage에 저장됩니다. 초기화하려면 DevTools → Application → Local Storage → `menu-agent:session-flags` 삭제.

---

## 트러블슈팅

| 증상 | 처방 |
|---|---|
| 포트 충돌 | `docker ps` 로 확인. `.env` 에서 `WEB_PORT` / `API_PORT` 변경 가능 |
| 메시지 보내면 빨간 에러 | `.env` 의 `ANTHROPIC_API_KEY` 확인 → `docker compose restart api` |
| 메뉴/식당 검색 빈 결과 | `docker compose logs qdrant-init` — 스냅샷 복원 실패 여부 확인 |
| `.env` 수정이 안 먹힘 | `make down && make up` 재기동 필요 (컨테이너는 기동 시점에만 env 읽음) |
