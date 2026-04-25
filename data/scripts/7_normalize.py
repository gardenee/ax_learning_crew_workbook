"""summarized_*.jsonl → 온톨로지대로 restaurants.jsonl + menus.jsonl 로 분리.

Restaurant (식당): 1엔티티 = 1행
  id=place_id
  name, categories[], primary_category, address, lat, lng, distance_m,
  phone, hours_text, price_min, price_max, price_currency, rating, rating_count,
  serves_breakfast/brunch/vegetarian, dine_in/takeout/delivery/reservable,
  tags[], dish_types[], review_summary,
  sources[], google_uri, naver_link, embedding_text

MenuItem (메뉴): 가게당 N행
  id={restaurant_id}__m{idx},  restaurant_id=place_id,
  name, description, embedding_text

embedding_text는 Qdrant 업서트 시 벡터화할 문자열을 미리 조립해둔 것.

Usage:
    apps/api/.venv/bin/python data/scripts/7_normalize.py
    python data/scripts/7_normalize.py --limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_latest_input() -> Path:
    c = sorted(Path("data/processed").glob("summarized_*.jsonl"), reverse=True)
    if not c:
        sys.exit("[error] summarized_*.jsonl 없음. 먼저 6_summarize.py 실행.")
    return c[0]


# categories 에서 쳐낼 정보 없는 구글 generic 타입들
NOISE_TYPES = {
    "food",
    "point_of_interest",
    "establishment",
    "store",
    "restaurant",  # "한식당" 같은 구체 타입이 있으면 "restaurant"는 중복
}


def build_categories(row: dict, summary: dict) -> tuple[list[str], str | None]:
    """google primary_type_display + naver category 중심으로 정리. generic 타입은 컷."""
    cats: list[str] = []
    if row.get("primary_type_display"):
        cats.append(row["primary_type_display"])
    # 세부 타입 중 generic 아닌 것만
    for t in row.get("types") or []:
        if t in NOISE_TYPES:
            continue
        if t == row.get("primary_type"):
            continue
        if t not in cats:
            cats.append(t)
    naver_cat = (row.get("naver") or {}).get("category")
    if naver_cat and naver_cat not in cats:
        cats.append(naver_cat)
    primary = cats[0] if cats else None
    return cats, primary


def build_sources(row: dict) -> list[str]:
    srcs = ["google"]
    if (row.get("naver") or {}).get("status") == "matched":
        srcs.append("naver_local")
    if (row.get("blogs") or {}).get("status") == "ok":
        srcs.append("naver_blog")
    return srcs


def build_restaurant(row: dict, now_iso: str) -> dict:
    summary = row.get("summary") or {}
    g = row.get("google_details") or {}
    naver = row.get("naver") or {}
    blogs = row.get("blogs") or {}
    categories, primary = build_categories(row, summary)

    name = row.get("name") or ""
    review_summary = summary.get("review_summary") or ""
    tags = summary.get("tags") or []
    dish_types = summary.get("dish_types") or []

    # 임베딩 텍스트: 식당 수준 RAG용
    emb_parts = [name]
    if primary:
        emb_parts.append(primary)
    if dish_types:
        emb_parts.append("음식: " + " ".join(dish_types))
    if tags:
        emb_parts.append("태그: " + " ".join(tags))
    if review_summary:
        emb_parts.append(review_summary)
    embedding_text = " | ".join(emb_parts)

    return {
        "id": row.get("place_id"),
        "name": name,
        "categories": categories,
        "primary_category": primary,
        "address": row.get("address"),
        "short_address": row.get("short_address"),
        "lat": row.get("lat"),
        "lng": row.get("lng"),
        "distance_m_from_center": row.get("distance_m_from_center"),
        "hours_text": g.get("weekday_text") or [],
        "price_min": g.get("price_start"),
        "price_max": g.get("price_end"),
        "price_currency": g.get("price_currency"),
        "rating": row.get("rating"),
        "rating_count": row.get("user_rating_count"),
        "serves_breakfast": g.get("serves_breakfast"),
        "serves_brunch": g.get("serves_brunch"),
        "serves_vegetarian": g.get("serves_vegetarian"),
        "dine_in": g.get("dine_in"),
        "takeout": g.get("takeout"),
        "delivery": g.get("delivery"),
        "reservable": g.get("reservable"),
        "tags": tags,
        "dish_types": dish_types,
        "review_summary": review_summary,
        "blog_hit_count": blogs.get("total_hits") or 0,
        "sources": build_sources(row),
        "google_maps_uri": row.get("google_maps_uri"),
        "homepage_url": naver.get("link"),  # 네이버 지역검색이 반환한 외부 홈페이지/SNS/블로그 링크 (네이버 플레이스 URL 아님)
        "business_status": row.get("business_status"),
        "embedding_text": embedding_text,
        "normalized_at": now_iso,
    }


def build_menus(row: dict, restaurant: dict, now_iso: str) -> list[dict]:
    """메뉴 임베딩 텍스트는 식당 컨텍스트 없이 메뉴 본연에만 집중.
    (식당 정보는 payload에 restaurant_id/name 으로 붙여 조회 시 join).
    """
    summary = row.get("summary") or {}
    menus = summary.get("menus") or []
    out = []
    for idx, m in enumerate(menus):
        m_name = (m.get("name") or "").strip()
        if not m_name:
            continue
        desc = (m.get("description") or "").strip()
        emb_text = f"{m_name} | {desc}" if desc else m_name
        out.append(
            {
                "id": f"{restaurant['id']}__m{idx}",
                "restaurant_id": restaurant["id"],
                "restaurant_name": restaurant["name"],
                "name": m_name,
                "description": desc or None,
                "embedding_text": emb_text,
                "normalized_at": now_iso,
            }
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="in_path", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--suffix", type=str, default=None, help="파일명 접미사 (샘플용 예: sample)")
    args = parser.parse_args()

    in_path = args.in_path or find_latest_input()
    rows = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    stamp = in_path.stem.split("_", 1)[-1]
    suffix = f"_{args.suffix}" if args.suffix else ""
    out_r = args.out_dir / f"restaurants_{stamp}{suffix}.jsonl"
    out_m = args.out_dir / f"menus_{stamp}{suffix}.jsonl"
    args.out_dir.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    restaurants = []
    menus: list[dict] = []
    skipped_foreign = 0
    for row in rows:
        if not row.get("place_id"):
            continue
        # 외국어 등록 이름은 제외 (검색 품질 저하 + 블로그 매칭 실패 많음)
        nl = row.get("name_language")
        if nl and nl != "ko":
            skipped_foreign += 1
            continue
        r = build_restaurant(row, now_iso)
        restaurants.append(r)
        menus.extend(build_menus(row, r, now_iso))

    with out_r.open("w", encoding="utf-8") as f:
        for r in restaurants:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with out_m.open("w", encoding="utf-8") as f:
        for m in menus:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    print(f"[in]  {in_path} ({len(rows)} rows)")
    print(f"[skip] 외국어 이름 제외: {skipped_foreign}")
    print(f"[out] {out_r} ({len(restaurants)} restaurants)")
    print(f"[out] {out_m} ({len(menus)} menu items)")


if __name__ == "__main__":
    main()
