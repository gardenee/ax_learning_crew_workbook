"""get_user_memory tool — 사용자 선호 조회 (read 전용).

이 파일은 얇은 어댑터다. 실제 조립 로직은 서비스 계층에 있다:
- `app.repositories.users`             — SQL 쿼리 (preference signals / feedback reasons)
- `app.services.memory.memory_service` — 조립

read 와 write 가 파일 경계로 분리되어 있다는 감각도 함께 익히자.
write 쪽은 `app.tools.memory_update` 에 있다.

세션 플래그(`tool_memory`)로 껐다 켤 수 있습니다.
"""

from __future__ import annotations


def handle(user_ids: list[str]) -> dict:
    """user_ids 의 memory 를 조회해 반환한다.

    assemble_memory 가 만들어주는 응답 구조:
      {
        "users": {
          "<uuid>": {
            "likes": [...], "dislikes": [...],
            "likedRestaurants": [...], "dislikedRestaurants": [...],
            "recentDislikeReasons": [...]
          }
        }
      }
    """
    from app.core.db import SessionLocal
    from app.services.memory.memory_service import assemble_memory

    with SessionLocal() as db:
        return assemble_memory(db, user_ids)
