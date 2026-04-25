"""prompt-history archive 의 누적 변화 통계.

PostToolUse hook (`.claude/scripts/archive_prompt.sh`) 이 매 Edit/Write 시
`.claude/prompt-history/<ts>.py` 로 스냅샷을 쌓는다. 이 스크립트는 그 스냅샷들의
크기 변화 / 직전 vs 현재 라인 추가/삭제를 정리해 보여준다.
"""
from __future__ import annotations

import sys
from difflib import unified_diff
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HISTORY_DIR = ROOT / ".claude/prompt-history"
PROMPT_PATH = ROOT / "apps/api/app/agent/prompts/__init__.py"


def main() -> int:
    if not HISTORY_DIR.exists() or not any(HISTORY_DIR.iterdir()):
        print("# Prompt history\n")
        print("- archive 비어있음. 첫 prompt 수정부터 자동 archive 가 시작됩니다.")
        print("- (hook 이 작동 중이라면 다음 Edit/Write 부터 `.claude/prompt-history/` 에 쌓임)")
        return 0

    snaps = sorted(HISTORY_DIR.glob("*.py"))
    print("# Prompt history\n")
    print(f"- archive 개수: **{len(snaps)}**")
    print(f"- 처음: `{snaps[0].name}` ({len(snaps[0].read_text(encoding='utf-8').splitlines())}줄)")
    print(f"- 최근: `{snaps[-1].name}` ({len(snaps[-1].read_text(encoding='utf-8').splitlines())}줄)")
    print()

    # 각 archive 간 라인 수 변화
    print("## 누적 라인 수 변화")
    prev = None
    for snap in snaps:
        n = len(snap.read_text(encoding="utf-8").splitlines())
        delta = "" if prev is None else (f"  ({'+' if n - prev >= 0 else ''}{n - prev})")
        print(f"- `{snap.name}` — {n}줄{delta}")
        prev = n
    print()

    # 직전 vs 현재 unified diff 통계
    if len(snaps) >= 2:
        a = snaps[-2].read_text(encoding="utf-8").splitlines(keepends=True)
        b = snaps[-1].read_text(encoding="utf-8").splitlines(keepends=True)
        diff = list(
            unified_diff(a, b, fromfile=snaps[-2].name, tofile=snaps[-1].name, lineterm="")
        )
        added = sum(1 for L in diff if L.startswith("+") and not L.startswith("+++"))
        removed = sum(1 for L in diff if L.startswith("-") and not L.startswith("---"))
        print(f"## 직전 → 최근 diff")
        print(f"- 추가: +{added}줄, 삭제: -{removed}줄")
        if diff:
            print(f"\n전체 unified diff 보려면: `diff -u {snaps[-2].name} {snaps[-1].name}` (in `.claude/prompt-history/`)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
