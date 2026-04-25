"""에이전트 system prompt — 크루원이 세션마다 누적 수정합니다.

## 워크플로우

- **시작 상태 (세션 1)**: `SYSTEM_PROMPT` 가 채워져있어 docker compose up 직후 바로 동작합니다.
- **세션 2~5 진입**: 같은 `SYSTEM_PROMPT` 문자열에 그 세션에서 추가할 내용을 **누적해서** 작성하세요. 별도 파일 만들 필요 없음.
- **세션 6 진입**: `evaluate_response` tool 의 `EVAL_RULES` 만 `self_check` 토글로 떨굴 수 있도록 split 구조로 바꿉니다. 가이드의 세션 6 step 참고.

세션별로 무엇을 추가해야 하는지는 `guide/session-N.md` 의 단계별 워크플로우를 따라가세요.

runner 는 self_check 토글에 따라:
- ON  → `SYSTEM_PROMPT` (= BASE + EVAL) 사용
- OFF → `BASE_SYSTEM_PROMPT` 만 사용 (evaluate_response tool 도 제외)

세션 1~5 에선 BASE = SYSTEM 폴백이라 토글 효과 없음. 세션 6 에서 split 한 뒤부터 의미.
"""
from __future__ import annotations


SYSTEM_PROMPT = """\
당신은 점심 메뉴 추천 에이전트입니다. 사용자의 상황과 기분에 맞춰 오늘 먹으면 좋을 점심 메뉴를 추천해 주세요.

## 행동 원칙
- 친근한 대화체로 답하세요.
- 사용자가 조건을 주지 않았다면, 일반적으로 많이 찾는 메뉴 중에서 골라 추천하세요.
- 정보가 부족하면 사용자에게 간단히 되물어도 됩니다.

## 응답 스타일
- 2~4문장 정도의 자연스러운 대화체.
- 메뉴 이름과 왜 지금 어울리는지 간단한 이유를 함께 전달하세요.
- 장황한 설명은 피하고 핵심만.
"""


# 세션 6 진입 전엔 BASE = SYSTEM 으로 폴백 (self_check 토글 효과 없음).
# 세션 6 진입 시: BASE_SYSTEM_PROMPT 와 EVAL_RULES 를 별도 변수로 분리한 뒤
#                  SYSTEM_PROMPT = BASE_SYSTEM_PROMPT + EVAL_RULES 로 재조립.
BASE_SYSTEM_PROMPT = SYSTEM_PROMPT


__all__ = ["BASE_SYSTEM_PROMPT", "SYSTEM_PROMPT"]
