"""prompts/__init__.py 의 SYSTEM_PROMPT 분석.

현재 prompt 의 섹션 헤딩을 추출하고 세션별 기대 항목과 매칭해
어느 세션까지 누적됐는지 추정한다.

분석 대상은 `SYSTEM_PROMPT` 변수의 문자열 값만 — module docstring 이나
다른 변수의 영향을 받지 않는다.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # .claude/skills/prompt-evolution/scripts → repo root
PROMPT_PATH = ROOT / "apps/api/app/agent/prompts/__init__.py"


def extract_system_prompt(src: str) -> str | None:
    """모듈 소스에서 `SYSTEM_PROMPT` 변수의 문자열 값을 ast 로 추출."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SYSTEM_PROMPT":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return node.value.value
    return None


# 세션별 기대 섹션 키워드 — 매칭은 substring 으로 (정확한 헤딩 텍스트가 다를 수 있음).
SESSION_MARKERS: dict[int, list[str]] = {
    1: ["행동 원칙", "응답 스타일"],
    2: ["도구 사용", "메모리", "get_user_memory", "update_user_memory"],
    3: ["검색", "RAG", "search_menus", "search_restaurants", "추천 플로우", "Memory × RAG", "근거"],
    4: ["실시간 맥락", "Live context", "get_landmark", "get_weather", "estimate_travel_time", "호출 흐름"],
    5: ["JSONL", "block 카탈로그", "시나리오 분기", "ask_user", "Generative UI"],
    6: ["evaluate_response", "EVAL_RULES", "BASE_SYSTEM_PROMPT", "자기 평가"],
}


def extract_sections(text: str) -> list[str]:
    return re.findall(r"^##+ (.+)$", text, re.MULTILINE)


def estimate_session(text: str) -> tuple[int, dict[int, list[str]]]:
    """누적 prompt 가 어느 세션까지 닿았는지 추정 + 세션별 매치된 키워드."""
    matched: dict[int, list[str]] = {}
    for sess, kws in SESSION_MARKERS.items():
        hits = [kw for kw in kws if kw.lower() in text.lower()]
        if hits:
            matched[sess] = hits
    last_session = max(matched.keys()) if matched else 0
    return last_session, matched


def find_missing(text: str, target_session: int) -> dict[int, list[str]]:
    missing: dict[int, list[str]] = {}
    for sess in range(1, target_session + 1):
        misses = [kw for kw in SESSION_MARKERS[sess] if kw.lower() not in text.lower()]
        if misses:
            missing[sess] = misses
    return missing


def main() -> int:
    if not PROMPT_PATH.exists():
        print(f"❌ {PROMPT_PATH} 가 없습니다.")
        return 1

    full = PROMPT_PATH.read_text(encoding="utf-8")
    body = extract_system_prompt(full)
    if body is None:
        print("❌ `SYSTEM_PROMPT = \"...\"` 형태의 할당을 찾지 못했습니다.")
        print("   세션 6 진입 등으로 `SYSTEM_PROMPT = BASE_SYSTEM_PROMPT + EVAL_RULES` 같이 결합 표현으로 바뀐 경우면")
        print("   변수를 직접 분석하지 못합니다 — `BASE_SYSTEM_PROMPT` 와 `EVAL_RULES` 본문을 직접 검토해 주세요.")
        return 1

    sections = extract_sections(body)
    last_session, matched = estimate_session(body)

    print(f"# Prompt 분석 — `apps/api/app/agent/prompts/__init__.py` (SYSTEM_PROMPT 본문)\n")
    print(f"- 본문 줄 수: **{len(body.splitlines())}**")
    print(f"- 추정 진행 세션: **{last_session}**" + (" (시작 상태)" if last_session <= 1 else ""))
    print(f"- `##` 섹션 수: {len(sections)}")
    print()

    print("## 섹션 헤딩")
    if sections:
        for s in sections:
            print(f"- {s}")
    else:
        print("- (헤딩 없음 — `## ...` 섹션 형태로 작성하면 분석이 정확해집니다)")
    print()

    print("## 세션별 누적 매칭")
    for sess in range(1, 7):
        kws = matched.get(sess)
        status = f"✅ {len(kws)} 키워드" if kws else "—"
        print(f"- 세션 {sess}: {status}")
    print()

    if last_session >= 2:
        missing = find_missing(src, last_session)
        if missing:
            print(f"## 빠진 기대 항목 (세션 {last_session} 까지)")
            for sess, kws in missing.items():
                print(f"- 세션 {sess}: {', '.join(kws)}")
            print()
        else:
            print(f"## 빠진 기대 항목 — 없음 (세션 {last_session} 까지의 핵심 키워드 모두 있음)\n")

    if last_session < 6:
        next_sess = last_session + 1
        print(f"## 다음 세션 ({next_sess}) 진입 시 추가할 항목 후보")
        print(f"- 세션 {next_sess} 핵심 키워드: {', '.join(SESSION_MARKERS[next_sess])}")
        print(f"- 가이드: `guide/session-{next_sess}.md`")

    return 0


if __name__ == "__main__":
    sys.exit(main())
