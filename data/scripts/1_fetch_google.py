"""Google Places API (New) nearbySearch로 LG CNS 본사 근처 음식점/카페 POI를 수집한다.

Usage:
    export $(grep -v '^#' .env | xargs)   # GOOGLE_MAPS_API_KEY 로드
    apps/api/.venv/bin/python data/scripts/1_fetch_google.py
    # 옵션
    python data/scripts/1_fetch_google.py --radius 1500 --types restaurant,cafe,bakery
    python data/scripts/1_fetch_google.py --max-depth 3

Output:
    data/raw/google_YYYYMMDD.jsonl (default)

Quadtree 분할:
    API가 한 번에 최대 20개만 반환하므로, 결과가 포화(20개)되면
    원을 4분할해서 재귀적으로 호출한다. place.id 기준 dedup.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

GOOGLE_ENDPOINT = "https://places.googleapis.com/v1/places:searchNearby"

# LG CNS 본사 (가양제1동, 서울 강서구)
DEFAULT_CENTER_LAT = 37.562357
DEFAULT_CENTER_LNG = 126.835414
DEFAULT_RADIUS_M = 1000
DEFAULT_TYPES = ("restaurant", "cafe")

# Places API (New) 한 번 호출 최대 20개. 포화 판단 임계값.
API_MAX_RESULTS = 20
SATURATION_THRESHOLD = 20
MIN_RADIUS_M = 150  # 이보다 작아지면 분할 중단
DEFAULT_MAX_DEPTH = 2
MAX_TOTAL_CALLS = 100  # 전체 호출 상한 (폭주 방지)

# Pro SKU 선에서 필요한 필드만 (영업시간 등 Enterprise 필드 제외 → 비용 절감)
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.shortFormattedAddress",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.nationalPhoneNumber",
        "places.googleMapsUri",
        "places.businessStatus",
    ]
)


@dataclass
class Circle:
    lat: float
    lng: float
    radius_m: float
    depth: int = 0


def load_api_key() -> str:
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        sys.exit("[error] GOOGLE_MAPS_API_KEY 환경변수가 비어있습니다.")
    return key


def call_nearby(client: httpx.Client, api_key: str, circle: Circle, included_types: list[str]) -> list[dict]:
    body = {
        "includedTypes": included_types,
        "maxResultCount": API_MAX_RESULTS,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": circle.lat, "longitude": circle.lng},
                "radius": circle.radius_m,
            }
        },
        "languageCode": "ko",
        "regionCode": "KR",
        "rankPreference": "DISTANCE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    for attempt in range(3):
        try:
            resp = client.post(GOOGLE_ENDPOINT, json=body, headers=headers, timeout=15.0)
            if resp.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json().get("places", [])
        except httpx.HTTPError as e:
            if attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))
            print(f"  [warn] 재시도 {attempt + 1}: {e}", file=sys.stderr)
    raise RuntimeError("unreachable")


def split_circle(circle: Circle) -> list[Circle]:
    """부모 원을 2x2 grid로 나눈 4개의 자식 원. 자식 반경은 r/√2 (오버랩 有, 완전 커버)."""
    r = circle.radius_m
    child_r = r / math.sqrt(2)
    # 자식 중심 이동량: 부모 중심에서 (±r/2, ±r/2)
    dlat = (r / 2) / 111_320.0
    dlng = (r / 2) / (111_320.0 * math.cos(math.radians(circle.lat)))
    children = []
    for slat in (+1, -1):
        for slng in (+1, -1):
            children.append(
                Circle(
                    lat=circle.lat + slat * dlat,
                    lng=circle.lng + slng * dlng,
                    radius_m=child_r,
                    depth=circle.depth + 1,
                )
            )
    return children


@dataclass
class Stats:
    calls: int = 0
    saturated: int = 0

    def exceeded(self) -> bool:
        return self.calls >= MAX_TOTAL_CALLS


def fetch_recursive(
    client: httpx.Client,
    api_key: str,
    circle: Circle,
    included_types: list[str],
    max_depth: int,
    seen: dict[str, dict],
    stats: Stats,
) -> None:
    if stats.exceeded():
        print(f"  [stop] MAX_TOTAL_CALLS({MAX_TOTAL_CALLS}) 도달, 이후 분할 중단", file=sys.stderr)
        return
    stats.calls += 1
    places = call_nearby(client, api_key, circle, included_types)
    indent = "  " * circle.depth
    print(
        f"{indent}[call] d={circle.depth} ({circle.lat:.5f},{circle.lng:.5f}) "
        f"r={circle.radius_m:.0f}m types={included_types} -> {len(places)}"
    )
    for p in places:
        pid = p.get("id")
        if pid and pid not in seen:
            seen[pid] = p

    # 포화 시 분할 조건 확인
    if len(places) < SATURATION_THRESHOLD:
        return
    stats.saturated += 1
    if circle.depth >= max_depth:
        print(f"{indent}  [warn] 포화지만 max_depth 도달 — 일부 누락 가능", file=sys.stderr)
        return
    if circle.radius_m / math.sqrt(2) < MIN_RADIUS_M:
        print(f"{indent}  [warn] 포화지만 MIN_RADIUS_M 도달", file=sys.stderr)
        return

    for child in split_circle(circle):
        fetch_recursive(client, api_key, child, included_types, max_depth, seen, stats)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def normalize_record(p: dict, query_center: tuple[float, float], query_radius_m: int) -> dict | None:
    """쿼리 원 밖(distance > radius)은 None 반환 — quadtree 오버랩으로 긁힌 영역 컷."""
    display = p.get("displayName") or {}
    loc = p.get("location") or {}
    lat = loc.get("latitude")
    lng = loc.get("longitude")
    dist_m: int | None = None
    if lat is not None and lng is not None:
        d = haversine_m(query_center[0], query_center[1], lat, lng)
        if d > query_radius_m:
            return None
        dist_m = int(round(d))
    return {
        "place_id": p.get("id"),
        "name": display.get("text"),
        "name_language": display.get("languageCode"),
        "primary_type": p.get("primaryType"),
        "primary_type_display": (p.get("primaryTypeDisplayName") or {}).get("text"),
        "types": p.get("types") or [],
        "address": p.get("formattedAddress"),
        "short_address": p.get("shortFormattedAddress"),
        "lat": lat,
        "lng": lng,
        "distance_m_from_center": dist_m,
        "rating": p.get("rating"),
        "user_rating_count": p.get("userRatingCount"),
        "price_level": p.get("priceLevel"),
        "phone": p.get("nationalPhoneNumber"),
        "google_maps_uri": p.get("googleMapsUri"),
        "business_status": p.get("businessStatus"),
        "_meta": {
            "source": "google_places_new_nearby",
            "query_center": list(query_center),
            "query_radius_m": query_radius_m,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }


def default_out_path() -> Path:
    return Path("data/raw") / f"google_{datetime.now().strftime('%Y%m%d')}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, default=DEFAULT_CENTER_LAT)
    parser.add_argument("--lng", type=float, default=DEFAULT_CENTER_LNG)
    parser.add_argument("--radius", type=int, default=DEFAULT_RADIUS_M, help=f"반경(m), 기본 {DEFAULT_RADIUS_M}")
    parser.add_argument(
        "--types",
        type=str,
        default=",".join(DEFAULT_TYPES),
        help="includedTypes CSV (기본 restaurant,cafe). 타입은 개별 호출 아닌 한 번에 합쳐 호출.",
    )
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH, help=f"quadtree 최대 깊이 (기본 {DEFAULT_MAX_DEPTH})")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    api_key = load_api_key()
    out_path = args.out or default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    root = Circle(lat=args.lat, lng=args.lng, radius_m=float(args.radius), depth=0)
    print(f"[fetch] center=({args.lat}, {args.lng}) radius={args.radius}m types={types} max_depth={args.max_depth} -> {out_path}")

    seen: dict[str, dict] = {}
    stats = Stats()
    with httpx.Client() as client:
        fetch_recursive(client, api_key, root, types, args.max_depth, seen, stats)

    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for p in seen.values():
            rec = normalize_record(p, (args.lat, args.lng), args.radius)
            if rec is None:
                continue
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1

    print(
        f"[ok] fetched={len(seen)} within_radius={written} outside={len(seen) - written} "
        f"| calls={stats.calls} saturated={stats.saturated} -> {out_path}"
    )


if __name__ == "__main__":
    main()
