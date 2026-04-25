#!/usr/bin/env bash
# PostToolUse hook — prompts/__init__.py 가 Edit/Write 되면 .claude/prompt-history/ 로 timestamp 박힌 스냅샷을 archive.
#
# 입력: stdin 으로 hook payload (JSON). tool_input.file_path 를 보고 우리 대상 파일이면 archive.
# 출력: stderr 로 한 줄 안내. 그 외엔 조용히 종료 (성공 = 0).

set -e

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path') or '')
except Exception:
    pass
")

case "$FILE_PATH" in
  *apps/api/app/agent/prompts/__init__.py)
    PROJECT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
    ARCHIVE_DIR="$PROJECT/.claude/prompt-history"
    mkdir -p "$ARCHIVE_DIR"
    TS=$(date +%Y%m%d-%H%M%S)
    cp "$FILE_PATH" "$ARCHIVE_DIR/$TS.py"
    echo "[archive_prompt] saved → .claude/prompt-history/$TS.py" >&2
    ;;
esac

exit 0
