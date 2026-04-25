"""google_*.jsonl → enrich 대상만 추린 filtered_*.jsonl 생성.

Rules:
  - business_status == "OPERATIONAL"          (폐점/임시휴업 제외)
  - primary_type/types에 cafe·coffee_shop·bakery 계열 없음   (카페 제외)
  - rating >= MIN_RATING (기본 3.8)           (평점 없는 가게는 제외)
  - user_rating_count >= MIN_REVIEWS (기본 10)

Usage:
    apps/api/.venv/bin/python data/scripts/2_filter.py
    python data/scripts/2_filter.py --in data/raw/google_20260419.jsonl --min-rating 4.0
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

DEFAULT_IN = Path("data/raw")
DEFAULT_OUT = Path("data/processed")

# primary_type 또는 types에 아래가 하나라도 있으면 컷
CAFE_TYPES = {
    "cafe",
    "coffee_shop",
    "bakery",
    "dessert_shop",
    "tea_house",
    "juice_shop",
    "ice_cream_shop",
}


def is_cafe_like(rec: dict) -> bool:
    pt = rec.get("primary_type")
    if pt in CAFE_TYPES:
        return True
    types = set(rec.get("types") or [])
    # types에 restaurant 계열이 하나라도 있으면 음식점으로 간주 (cafe 겸업은 통과)
    restaurant_like = {t for t in types if t.endswith("_restaurant") or t == "restaurant"}
    if restaurant_like:
        return False
    return bool(types & CAFE_TYPES)


def find_latest_google_raw() -> Path:
    candidates = sorted(DEFAULT_IN.glob("google_*.jsonl"), reverse=True)
    if not candidates:
        raise SystemExit("[error] data/raw/google_*.jsonl 을 찾을 수 없습니다.")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="in_path", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--min-rating", type=float, default=3.8)
    parser.add_argument("--min-reviews", type=int, default=10)
    args = parser.parse_args()

    in_path = args.in_path or find_latest_google_raw()
    out_path = args.out or (DEFAULT_OUT / f"filtered_{in_path.stem.split('_', 1)[1]}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    reasons = Counter()
    kept: list[dict] = []

    for r in rows:
        if r.get("business_status") != "OPERATIONAL":
            reasons["not_operational"] += 1
            continue
        if is_cafe_like(r):
            reasons["cafe_like"] += 1
            continue
        if args.min_rating > 0:
            rating = r.get("rating")
            if rating is None:
                reasons["no_rating"] += 1
                continue
            if rating < args.min_rating:
                reasons["low_rating"] += 1
                continue
        if args.min_reviews > 0:
            if (r.get("user_rating_count") or 0) < args.min_reviews:
                reasons["few_reviews"] += 1
                continue
        kept.append(r)

    kept.sort(key=lambda x: x.get("distance_m_from_center", 0))
    with out_path.open("w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[in]  {in_path}  ({len(rows)} rows)")
    print(f"[out] {out_path}  ({len(kept)} rows)")
    print("\n[dropped breakdown]")
    for k, v in reasons.most_common():
        print(f"  {v:>4}  {k}")


if __name__ == "__main__":
    main()
