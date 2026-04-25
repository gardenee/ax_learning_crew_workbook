한 줄 시나리오 호출 — `/api/agent/run` 한 번 부르고 tool 호출 흐름 + 응답 요약 출력.

`$ARGUMENTS` 형식:
```
[user_uuid] [msg] [flags]
```

- `user_uuid`: participant_ids 에 들어갈 UUID. `me` 라고 쓰면 `00000000-0000-0000-0000-000000000001` (기본 테스트 user).
- `msg`: 사용자 메시지 (따옴표로 감싸거나 인자 끝까지).
- `flags`: 콤마로 묶은 tool flag 목록 (예: `memory,search`). `all` 이면 전부 ON. 생략하면 default (전부 OFF + history 만 ON).

예:
```
/scenario me "마곡역 한식 추천해줘" memory,search,landmark,travel
/scenario me "뭐 먹지?" all
/scenario 00000000-0000-0000-0000-000000000002 "점심 추천해줘" memory
```

```bash
ARG="$ARGUMENTS"

# parse args — UUID, msg ("..." 안), flags
USER_INPUT=$(echo "$ARG" | awk '{print $1}')
case "$USER_INPUT" in
  me) USER_ID="00000000-0000-0000-0000-000000000001" ;;
  *)  USER_ID="$USER_INPUT" ;;
esac

# msg = 따옴표 안 (없으면 두 번째 단어부터 마지막 단어 직전)
MSG=$(echo "$ARG" | python3 -c "
import sys, re
s = sys.stdin.read()
m = re.search(r'\"([^\"]+)\"', s)
print(m.group(1) if m else '')
")
if [ -z "$MSG" ]; then
  MSG=$(echo "$ARG" | awk '{$1=\"\"; $NF=\"\"; print $0}' | sed 's/^ *//;s/ *$//')
fi

# flags
FLAGS_RAW=$(echo "$ARG" | awk '{print $NF}')
case "$FLAGS_RAW" in
  all) ENABLED="memory,search,weather,landmark,travel,gen_ui,self_check" ;;
  *)   ENABLED="$FLAGS_RAW" ;;
esac

# build flags JSON
FLAGS_JSON=$(python3 -c "
keys = ['remember_history','self_check','gen_ui','tool_memory','tool_search','tool_weather','tool_landmark','tool_travel','tool_ask_user']
short = {'memory':'tool_memory','search':'tool_search','weather':'tool_weather','landmark':'tool_landmark','travel':'tool_travel','self_check':'self_check','gen_ui':'gen_ui'}
enabled = set(['remember_history'])
for s in '$ENABLED'.split(','):
    s = s.strip()
    if s in short: enabled.add(short[s])
    elif s.startswith('tool_') or s in ('self_check','gen_ui','remember_history'): enabled.add(s)
import json
print(json.dumps({k: (k in enabled) for k in keys}))
")

API_PORT=$(docker compose port api 8000 2>/dev/null | sed 's/.*://')
API_PORT="${API_PORT:-8000}"

echo "→ user=$USER_ID  msg=\"$MSG\"  flags=$FLAGS_JSON"
echo

curl -s -N -X POST "http://localhost:$API_PORT/api/agent/run" \
  -H "Content-Type: application/json" \
  -d "{
    \"participant_ids\":[\"$USER_ID\"],
    \"user_message\":\"$MSG\",
    \"session_flags\":$FLAGS_JSON
  }" 2>&1 | python3 -c "
import sys, json
for line in sys.stdin:
    if not line.startswith('data:'): continue
    e = json.loads(line[5:].strip())
    t = e.get('type')
    if t == 'tool_status' and e.get('state') == 'start':
        print(f\"  → {e['tool']}: {json.dumps(e.get('input',{}), ensure_ascii=False)[:140]}\")
    elif t == 'tool_status' and e.get('state') == 'done':
        r = e.get('result', {})
        if isinstance(r, dict) and 'error' in r:
            print(f\"    ERROR: {r['error'][:120]}\")
    elif t == 'message_delta':
        print(f\"  msg: {e['text'][:240]}\")
    elif t == 'recommendation_card':
        print(f\"  card: rank={e.get('rank')} {e.get('restaurant',{}).get('name')}\")
    elif t == 'choice_chips':
        opts = [o.get('label') for o in e.get('options',[])]
        print(f\"  chips: {opts}\")
    elif t in ('text_input','number_input','chips_input','submit_button'):
        print(f\"  form_block: {t} ({e.get('label') or e.get('name') or ''})\")
    elif t == 'alert_card':
        print(f\"  alert: {e.get('severity')} — {e.get('title')} ({e.get('summary','')[:80]})\")
"
```

진단:
- 토글 OFF 상태에서 그 tool 이 호출되는지 (LLM 의 history 모방)
- 환각/요구 위반이 evaluate_response 에서 잡히는지
- ask_user 가 emit 한 form block 들이 정상인지
