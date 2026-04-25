# 세션별 SYSTEM_PROMPT 기대 추가 항목

각 세션 진입 시 `prompts/__init__.py` 의 `SYSTEM_PROMPT` 에 누적될 것으로 기대되는 키워드 / 섹션. 가이드의 단계별 작업과 매핑.

> 키워드는 substring 매칭. 정확한 헤딩 텍스트가 달라도 (예: `## 도구` vs `## 도구 사용`) 매칭됨.

## 세션 1 — 시작 상태
- `행동 원칙`
- `응답 스타일`

## 세션 2 — 메모리 (`tool_memory`)
- `도구 사용`
- `get_user_memory`
- `update_user_memory`
- (선택) `concept_key 한국어`, `시스템 용어 노출 금지`, `tool 호출 응답 규칙`

## 세션 3 — RAG (`tool_search`)
- `search_menus`, `search_restaurants`
- `추천 플로우`
- `Memory × RAG` (또는 `filter`, `boost_concepts`, `exclude_keywords`)
- `근거 기반` (또는 `환각 방지`)
- (권장) `🚨 핵심 — dislikes 는 절대 추천 금지`
- (옵션) `Rerank`

## 세션 4 — Live context (`tool_weather`, `tool_landmark`, `tool_travel`)
- `실시간 맥락` 또는 `Live context`
- `get_landmark`, `get_weather`, `estimate_travel_time`
- `호출 흐름` (위치 / 날씨 / 거리 분기)
- (권장) 날씨 → 톤 매핑 (rain/snow/clear)

## 세션 5 — Generative UI (`gen_ui`)
- `JSONL` (응답 포맷 변화)
- `block 카탈로그` (또는 `recommendation_card`, `choice_chips`, `quick_actions`)
- `시나리오 분기` (A/B/C/D)
- `ask_user` 사용 규칙

## 세션 6 — 자기 평가 (`self_check`)
- `BASE_SYSTEM_PROMPT` 와 `EVAL_RULES` split (변수 단계)
- `evaluate_response`
- 호출 입력 / 호출 안 함 / 결과 처리 규칙
