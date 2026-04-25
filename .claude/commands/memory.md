사용자 메모리 (`preference_signals` + `concepts`) 조회.

`$ARGUMENTS` 처리:
- 비어있으면: 모든 사용자의 메모리.
- UUID 한 개: 그 사용자만.
- handle (예: `me`): users 테이블에서 handle 로 user 찾아 그 메모리만.

다음 명령으로 조회 (현재 디렉터리의 docker compose stack 의 postgres 사용):

```bash
ARG="$ARGUMENTS"

if [ -z "$ARG" ]; then
  WHERE=""
elif echo "$ARG" | grep -qE '^[0-9a-f-]{36}$'; then
  WHERE="WHERE s.owner_id = '$ARG'"
else
  WHERE="WHERE u.handle = '$ARG'"
fi

docker compose exec -T postgres psql -U app -d menu_agent -c "
SELECT
  COALESCE(u.handle, s.owner_id::text) AS who,
  s.signal_type,
  c.key                    AS concept,
  s.target_restaurant_name AS restaurant,
  s.created_at::date       AS date
FROM preference_signals s
LEFT JOIN concepts c ON c.id = s.concept_id
LEFT JOIN users u ON u.id = s.owner_id
$WHERE
ORDER BY u.handle, s.created_at DESC;
"
```

결과 읽는 법:
- `signal_type` — `likes` / `dislikes`
- `concept` — 카테고리 어휘. **한국어가 정상** (영문은 옛 데이터일 가능성)
- `restaurant` — 특정 식당 선호일 때 채워짐
- `date` — 박힌 날짜

빈 결과면 그 사용자는 아직 메모리 없음 — 세션 2 시나리오로 박아보세요.
