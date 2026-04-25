"""restaurants.jsonl / menus.jsonl → Qdrant 2컬렉션 임베딩·업서트.

컬렉션:
  - restaurants : 식당 수준 검색 (식당 직접/태그/요약 매칭)
  - menus       : 메뉴 수준 검색 (메뉴→식당 역방향)

임베딩: fastembed의 `intfloat/multilingual-e5-small` (384-dim, 다국어, ONNX, CPU OK)
  e5 모델은 passage 임베딩 시 prefix `"passage: "` 권장. query 시에는 `"query: "` prefix.

Usage:
    apps/api/.venv/bin/python data/scripts/8_index_qdrant.py
    python data/scripts/8_index_qdrant.py --recreate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

DEFAULT_QDRANT_URL = "http://localhost:6333"
# 다국어 SOTA. 첫 실행 시 ~2GB 다운로드. CPU에서 느리지만 품질 우수.
# e5 계열은 passage/query prefix 필요 — 아래 PASSAGE_PREFIX 참조.
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
EMBEDDING_DIM = 1024
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "
RESTAURANT_COLLECTION = "restaurants"
MENU_COLLECTION = "menus"
BATCH = 32


def find_latest(pattern: str) -> Path:
    c = sorted(
        [p for p in Path("data/processed").glob(pattern) if "_sample" not in p.stem],
        reverse=True,
    )
    if not c:
        sys.exit(f"[error] data/processed/{pattern} (non-sample) 없음")
    return c[0]


def ensure_collection(client: QdrantClient, name: str, recreate: bool) -> None:
    exists = client.collection_exists(name)
    if exists and recreate:
        client.delete_collection(name)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=EMBEDDING_DIM, distance=qmodels.Distance.COSINE),
        )
        print(f"  [create] {name} (dim={EMBEDDING_DIM}, cosine)")
    else:
        print(f"  [keep]   {name} (이미 존재)")


def batched(seq, n):
    buf = []
    for item in seq:
        buf.append(item)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def embed_texts(model: TextEmbedding, texts: list[str]) -> list[list[float]]:
    prefixed = [PASSAGE_PREFIX + t for t in texts]
    return [list(v) for v in model.embed(prefixed)]


def deterministic_uuid(key: str) -> str:
    """place_id / menu_id 같은 문자열을 점수 ID용 UUID로 변환 (Qdrant는 int/UUID만 허용)."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, key))


def index_restaurants(client: QdrantClient, model: TextEmbedding, path: Path) -> int:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    total = 0
    for batch in batched(rows, BATCH):
        vectors = embed_texts(model, [r["embedding_text"] for r in batch])
        points = []
        for r, vec in zip(batch, vectors):
            points.append(
                qmodels.PointStruct(
                    id=deterministic_uuid(r["id"]),
                    vector=vec,
                    payload={
                        "restaurant_id": r["id"],
                        "name": r["name"],
                        "primary_category": r.get("primary_category"),
                        "categories": r.get("categories") or [],
                        "lat": r.get("lat"),
                        "lng": r.get("lng"),
                        # geo payload index 용 (qdrant 는 {lat,lon} 형식만 인식)
                        "location": (
                            {"lat": float(r["lat"]), "lon": float(r["lng"])}
                            if r.get("lat") is not None and r.get("lng") is not None
                            else None
                        ),
                        "distance_m_from_center": r.get("distance_m_from_center"),
                        "tags": r.get("tags") or [],
                        "dish_types": r.get("dish_types") or [],
                        "review_summary": r.get("review_summary"),
                        "rating": r.get("rating"),
                        "rating_count": r.get("rating_count"),
                        "price_min": r.get("price_min"),
                        "price_max": r.get("price_max"),
                        "dine_in": r.get("dine_in"),
                        "takeout": r.get("takeout"),
                        "delivery": r.get("delivery"),
                    },
                )
            )
        client.upsert(collection_name=RESTAURANT_COLLECTION, points=points)
        total += len(points)
        print(f"  [upsert] restaurants +{len(points)} (누적 {total})")
    return total


def index_menus(client: QdrantClient, model: TextEmbedding, path: Path) -> int:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    total = 0
    for batch in batched(rows, BATCH):
        vectors = embed_texts(model, [m["embedding_text"] for m in batch])
        points = []
        for m, vec in zip(batch, vectors):
            points.append(
                qmodels.PointStruct(
                    id=deterministic_uuid(m["id"]),
                    vector=vec,
                    payload={
                        "menu_id": m["id"],
                        "restaurant_id": m["restaurant_id"],
                        "restaurant_name": m.get("restaurant_name"),
                        "name": m["name"],
                        "description": m.get("description"),
                    },
                )
            )
        client.upsert(collection_name=MENU_COLLECTION, points=points)
        total += len(points)
        print(f"  [upsert] menus +{len(points)} (누적 {total})")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--restaurants", type=Path, default=None)
    parser.add_argument("--menus", type=Path, default=None)
    parser.add_argument("--qdrant-url", type=str, default=os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL))
    parser.add_argument("--recreate", action="store_true", help="컬렉션 삭제 후 재생성 (--only와 함께 쓰면 해당 컬렉션만)")
    parser.add_argument("--only", choices=["restaurants", "menus"], default=None, help="특정 컬렉션만 처리 (기본: 둘 다)")
    args = parser.parse_args()

    # .env 의 QDRANT_URL 은 docker 내부(qdrant:6333) 값이라, 호스트 스크립트에선 localhost 로 교정
    url = args.qdrant_url
    if "qdrant:6333" in url:
        url = url.replace("qdrant:6333", "localhost:6333")

    do_rest = args.only != "menus"
    do_menu = args.only != "restaurants"

    r_path = (args.restaurants or find_latest("restaurants_*.jsonl")) if do_rest else None
    m_path = (args.menus or find_latest("menus_*.jsonl")) if do_menu else None

    print(f"[index] qdrant={url} model={EMBEDDING_MODEL}")
    if do_rest:
        print(f"  restaurants: {r_path}")
    if do_menu:
        print(f"  menus      : {m_path}")

    client = QdrantClient(url=url)
    if do_rest:
        ensure_collection(client, RESTAURANT_COLLECTION, args.recreate)
    if do_menu:
        ensure_collection(client, MENU_COLLECTION, args.recreate)

    print("\n[load] 임베딩 모델 로드 (첫 실행 시 모델 다운로드)")
    model = TextEmbedding(model_name=EMBEDDING_MODEL)

    r_count = 0
    m_count = 0
    if do_rest:
        print("\n[embed+upsert] restaurants")
        r_count = index_restaurants(client, model, r_path)
    if do_menu:
        print("\n[embed+upsert] menus")
        m_count = index_menus(client, model, m_path)

    parts = []
    if do_rest:
        parts.append(f"restaurants={r_count}")
    if do_menu:
        parts.append(f"menus={m_count}")
    print(f"\n[ok] {' '.join(parts)}")
    print(f"  Qdrant UI: http://localhost:6333/dashboard")


if __name__ == "__main__":
    main()
