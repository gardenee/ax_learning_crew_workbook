"""카카오맵 로컬 API로 LG CNS 본사 반경 음식점/카페 POI를 수집한다.

Usage:
    # repo root에서 (httpx가 설치된 환경 필요 — apps/api venv 재활용 가능)
    export $(grep -v '^#' .env | xargs)   # KAKAO_REST_API_KEY 로드
    uv --project apps/api run python data/scripts/1_fetch_kakao.py
    # 또는 venv activate 후
    python data/scripts/1_fetch_kakao.py

    # 옵션
    python data/scripts/1_fetch_kakao.py --radius 1000 --categories FD6
    python data/scripts/1_fetch_kakao.py --out data/raw/kakao_custom.jsonl

Output:
    data/raw/kakao_YYYYMMDD.jsonl (default)
    한 줄당 식당 1개. category별 중복은 place_id 기준으로 제거.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx

KAKAO_ENDPOINT = "https://dapi.kakao.com/v2/local/search/category.json"
# LG CNS 본사 (가양제1동, 서울 강서구)
DEFAULT_CENTER_LAT = 37.562357
DEFAULT_CENTER_LNG = 126.835414
DEFAULT_RADIUS_M = 1500
# FD6: 음식점, CE7: 카페
DEFAULT_CATEGORIES = ("FD6", "CE7")
PAGE_SIZE = 15
MAX_PAGE = 45  # 카카오 제한: page * size <= 675


@dataclass
class FetchParams:
    lat: float
    lng: float
    radius_m: int
    category: str


def load_env_api_key() -> str:
    key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not key:
        sys.exit(
            "[error] KAKAO_REST_API_KEY 환경변수가 비어있습니다.\n"
            "  .env에 값을 넣고 `export $(grep -v '^#' .env | xargs)` 후 다시 실행하세요."
        )
    return key


def fetch_page(client: httpx.Client, api_key: str, params: FetchParams, page: int) -> dict:
    query = {
        "category_group_code": params.category,
        "x": f"{params.lng}",  # 카카오는 x=경도, y=위도
        "y": f"{params.lat}",
        "radius": params.radius_m,
        "page": page,
        "size": PAGE_SIZE,
        "sort": "distance",
    }
    headers = {"Authorization": f"KakaoAK {api_key}"}

    for attempt in range(3):
        try:
            resp = client.get(KAKAO_ENDPOINT, params=query, headers=headers, timeout=10.0)
            if resp.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            if attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))
            print(f"  [warn] {params.category} page={page} 재시도 {attempt + 1}: {e}", file=sys.stderr)
    raise RuntimeError("unreachable")


def iter_category(
    client: httpx.Client,
    api_key: str,
    lat: float,
    lng: float,
    radius_m: int,
    category: str,
) -> Iterable[dict]:
    params = FetchParams(lat=lat, lng=lng, radius_m=radius_m, category=category)
    for page in range(1, MAX_PAGE + 1):
        data = fetch_page(client, api_key, params, page)
        meta = data.get("meta", {})
        docs = data.get("documents", [])
        for doc in docs:
            yield doc
        if meta.get("is_end", True):
            break
        if page == MAX_PAGE and not meta.get("is_end", True):
            print(
                f"  [warn] {category} MAX_PAGE({MAX_PAGE}) 도달했지만 is_end=false. "
                f"반경을 줄이거나 좌표를 분할해 재수집을 고려하세요.",
                file=sys.stderr,
            )


def normalize_record(doc: dict, category: str, center_lat: float, center_lng: float, radius_m: int) -> dict:
    """카카오 응답을 원본 보존 + 파생 필드만 얹어서 그대로 저장."""
    return {
        "place_id": doc.get("id"),
        "name": doc.get("place_name"),
        "category_name": doc.get("category_name"),
        "category_group_code": doc.get("category_group_code"),
        "category_group_name": doc.get("category_group_name"),
        "phone": doc.get("phone") or None,
        "address_name": doc.get("address_name"),
        "road_address_name": doc.get("road_address_name") or None,
        "x": doc.get("x"),
        "y": doc.get("y"),
        "distance_m": int(doc["distance"]) if doc.get("distance") else None,
        "place_url": doc.get("place_url"),
        "_meta": {
            "source": "kakao_local_category",
            "query_center": [center_lat, center_lng],
            "query_radius_m": radius_m,
            "query_category": category,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }


def default_out_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    return Path("data/raw") / f"kakao_{stamp}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, default=DEFAULT_CENTER_LAT, help="중심 위도 (기본: LG CNS 본사)")
    parser.add_argument("--lng", type=float, default=DEFAULT_CENTER_LNG, help="중심 경도 (기본: LG CNS 본사)")
    parser.add_argument("--radius", type=int, default=DEFAULT_RADIUS_M, help=f"반경(m), 최대 20000 (기본 {DEFAULT_RADIUS_M})")
    parser.add_argument(
        "--categories",
        type=str,
        default=",".join(DEFAULT_CATEGORIES),
        help="카카오 category_group_code CSV (기본 FD6,CE7)",
    )
    parser.add_argument("--out", type=Path, default=None, help="출력 JSONL 경로 (기본 data/raw/kakao_YYYYMMDD.jsonl)")
    args = parser.parse_args()

    if not (1 <= args.radius <= 20000):
        sys.exit("[error] --radius 는 1~20000 범위여야 합니다.")

    api_key = load_env_api_key()
    out_path = args.out or default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    print(
        f"[fetch] center=({args.lat}, {args.lng}) radius={args.radius}m "
        f"categories={categories} -> {out_path}"
    )

    seen: dict[str, dict] = {}
    with httpx.Client() as client:
        for cat in categories:
            before = len(seen)
            for doc in iter_category(client, api_key, args.lat, args.lng, args.radius, cat):
                pid = str(doc.get("id"))
                if not pid or pid in seen:
                    continue
                seen[pid] = normalize_record(doc, cat, args.lat, args.lng, args.radius)
            print(f"  [done] {cat}: +{len(seen) - before} (누적 {len(seen)})")

    with out_path.open("w", encoding="utf-8") as f:
        for record in seen.values():
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[ok] {len(seen)} records -> {out_path}")


if __name__ == "__main__":
    main()
