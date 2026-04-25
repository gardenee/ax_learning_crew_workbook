"""restaurants 컬렉션에 geo payload 필드/인덱스 추가 (임베딩 재계산 없음).

동작:
  1. 컬렉션 `restaurants` 의 모든 point 를 scroll.
  2. 각 point 의 기존 payload 에 있는 `lat`/`lng` 를 Qdrant geo 포맷
     `location: {lat, lon}` 으로 복사해 `set_payload` (벡터는 안 건드림).
  3. `location` 필드에 geo payload index 생성 — `geo_radius` / `geo_bounding_box`
     필터가 빠르게 걸리게 한다.

왜 별도 필드를 두는가:
  - 기존 코드/쿼리는 `lat`/`lng` 두 별개 숫자 필드를 읽어온다 (payload 인덱스 없이
    단순 값 조회). 그걸 깨지 않으면서, Qdrant geo 인덱스가 요구하는 `{lat, lon}`
    객체 필드를 새로 추가하는 게 안전하다.

실행:
  python data/scripts/9_qdrant_geo_payload.py
"""
from __future__ import annotations

import argparse
import os

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

DEFAULT_QDRANT_URL = "http://localhost:6333"
RESTAURANT_COLLECTION = "restaurants"
SCROLL_BATCH = 256


def backfill_location(client: QdrantClient) -> int:
    """모든 point 에 `location` 필드를 추가한다."""
    next_offset = None
    total = 0
    while True:
        points, next_offset = client.scroll(
            collection_name=RESTAURANT_COLLECTION,
            limit=SCROLL_BATCH,
            with_payload=True,
            with_vectors=False,
            offset=next_offset,
        )
        if not points:
            break

        for p in points:
            payload = p.payload or {}
            lat = payload.get("lat")
            lng = payload.get("lng")
            if lat is None or lng is None:
                continue
            client.set_payload(
                collection_name=RESTAURANT_COLLECTION,
                payload={"location": {"lat": float(lat), "lon": float(lng)}},
                points=[p.id],
            )
            total += 1

        if next_offset is None:
            break
    return total


def ensure_geo_index(client: QdrantClient) -> None:
    """location 필드에 geo payload index 를 만든다 (이미 있으면 no-op)."""
    try:
        client.create_payload_index(
            collection_name=RESTAURANT_COLLECTION,
            field_name="location",
            field_schema=qmodels.PayloadSchemaType.GEO,
        )
        print("  [create] payload index: location (GEO)")
    except Exception as e:  # 이미 존재 등
        print(f"  [skip]   payload index: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qdrant-url", type=str, default=os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL))
    args = parser.parse_args()

    url = args.qdrant_url
    if "qdrant:6333" in url:
        url = url.replace("qdrant:6333", "localhost:6333")

    print(f"[geo-payload] qdrant={url} collection={RESTAURANT_COLLECTION}")
    client = QdrantClient(url=url)

    print("\n[backfill] location payload")
    n = backfill_location(client)
    print(f"  updated {n} points")

    print("\n[index] geo payload index on 'location'")
    ensure_geo_index(client)

    print("\n[ok] 이제 search_service 가 filter.near 로 geo_radius 를 걸 수 있습니다.")


if __name__ == "__main__":
    main()
