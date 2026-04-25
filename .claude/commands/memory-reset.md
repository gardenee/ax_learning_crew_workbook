사용자의 메모리 (`preference_signals`) 를 비웁니다.

`$ARGUMENTS` 는 user UUID (필수). 안전 장치 — 인자 없으면 실행 안 함.

```bash
ARG="$ARGUMENTS"

if [ -z "$ARG" ]; then
  echo "❌ user UUID 가 필요합니다. 예: /memory-reset 00000000-0000-0000-0000-000000000001"
  exit 1
fi

docker compose exec -T postgres psql -U app -d menu_agent -c "
DELETE FROM preference_signals WHERE owner_id = '$ARG';
SELECT count(*) AS remaining FROM preference_signals WHERE owner_id = '$ARG';
"
```

언제 쓰나:
- 세션 2 라운드 비교 시 메모리 깨끗하게 리셋
- 세션 3 라운드 3 시작 전 빈 메모리 상태 만들기
- 옛 영문 concept_key (`seafood`, `cilantro`) 가 박혀있어 필터 매핑이 헷갈릴 때 — 한 번 지우고 다시 박기

`concepts` 테이블은 안 지워짐 (다른 사용자가 참조 중일 수 있어서). 메뉴 어휘 자체를 지우려면 별도 작업.
