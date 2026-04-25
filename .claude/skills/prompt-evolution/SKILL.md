---
name: prompt-evolution
description: prompts/__init__.py 의 SYSTEM_PROMPT 를 분석해 누적 변경을 추적합니다. 사용 자연어 — "지금 프롬프트 어디까지 왔어", "내 프롬프트 진단해줘", "세션 N 기대 항목 다 들어갔어", "prompt history diff", "누적 변경 추적".
---

# prompt-evolution

크루원이 매 세션 누적 수정하는 `apps/api/app/agent/prompts/__init__.py` 의 `SYSTEM_PROMPT` 를 분석하고 자가 진단을 돕는 skill.

## 같이 작동하는 hook

`.claude/settings.json` 의 PostToolUse hook 이 `prompts/__init__.py` Edit/Write 시점마다 `.claude/prompt-history/<timestamp>.py` 로 자동 archive. 개발자는 신경 안 써도 매 변경이 쌓임.

## 사용 흐름

사용자가 위 description 의 자연어 요청을 하면 다음을 실행:

1. **현재 분석** — `scripts/analyze.py` 실행:
   - 현재 SYSTEM_PROMPT 의 `## ...` 섹션 헤딩 추출
   - `resources/expected-sections.md` 와 매칭해 어느 세션까지 누적됐는지 추정
   - 빠진 기대 항목 / 추가된 사용자 정의 항목 마커

2. **history diff** (archive 가 있을 때) — `scripts/diff_history.py` 실행:
   - `.claude/prompt-history/` 의 archive 중 가장 최근 vs 직전 unified diff 라인 카운트
   - "최근 N 회 누적 변경" 같은 통계

3. **markdown 보고서** — 결과를 다음 4 섹션으로 출력:
   - 현재 추정 세션
   - 빠진 기대 항목 (있을 때)
   - 추가된 사용자 정의 항목 (있을 때)
   - history 통계

## 출력 톤

- 진단 — 크루원이 자기 진행을 객관적으로 보게.
- 비판 X. "다음 세션 진입 전엔 이 항목을 추가해 보세요" 처럼 제안.
- 코드 한 줄 한 줄 인용 X. 섹션 단위 요약.
