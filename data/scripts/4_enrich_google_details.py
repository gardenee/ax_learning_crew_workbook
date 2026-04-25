"""Google Places Details (New)로 영업시간·식사제공·서비스옵션·가격범위 보강.

각 place_id에 대해 GET https://places.googleapis.com/v1/places/{id} 1회 호출.
Enterprise SKU 범위까지만 (리뷰 제외 → Enterprise+ 피함).

Usage:
    export $(grep -v '^#' .env | xargs)
    apps/api/.venv/bin/python data/scripts/4_enrich_google_details.py
    python data/scripts/4_enrich_google_details.py --limit 20
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

import httpx

ENDPOINT_TMPL = "https://places.googleapis.com/v1/places/{place_id}"
DEFAULT_RPS = 5.0

FIELD_MASK = ",".join(
    [
        "id",
        "regularOpeningHours.weekdayDescriptions",
        "regularOpeningHours.periods",
        "currentOpeningHours.openNow",
        "servesBreakfast",
        "servesLunch",
        "servesDinner",
        "servesBrunch",
        "servesVegetarianFood",
        "dineIn",
        "takeout",
        "delivery",
        "reservable",
        "priceRange",
    ]
)


@dataclass
class RateLimiter:
    rps: float
    _last: float = 0.0

    @property
    def min_interval(self) -> float:
        return 1.0 / self.rps if self.rps > 0 else 0.0

    def acquire(self) -> None:
        now = time.monotonic()
        wait = self.min_interval - (now - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()


def fetch_details(client: httpx.Client, api_key: str, place_id: str, limiter: RateLimiter) -> dict:
    limiter.acquire()
    url = ENDPOINT_TMPL.format(place_id=place_id)
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}
    params = {"languageCode": "ko", "regionCode": "KR"}
    for attempt in range(3):
        try:
            resp = client.get(url, headers=headers, params=params, timeout=12.0)
            if resp.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            if resp.status_code in (403, 404):
                return {"_error": f"http_{resp.status_code}", "_body": resp.text[:200]}
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            if attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))
            print(f"  [warn] {place_id} 재시도 {attempt + 1}: {e}", file=sys.stderr)
    raise RuntimeError("unreachable")


def normalize_details(d: dict) -> dict:
    """응답을 플랫한 형태로 정리."""
    if d.get("_error"):
        return {"status": "error", "error": d["_error"]}
    opening = d.get("regularOpeningHours") or {}
    price = d.get("priceRange") or {}
    return {
        "status": "ok",
        "weekday_text": opening.get("weekdayDescriptions") or [],
        "opening_periods": opening.get("periods") or [],
        "open_now": (d.get("currentOpeningHours") or {}).get("openNow"),
        "serves_breakfast": d.get("servesBreakfast"),
        "serves_brunch": d.get("servesBrunch"),
        "serves_lunch": d.get("servesLunch"),
        "serves_dinner": d.get("servesDinner"),
        "serves_vegetarian": d.get("servesVegetarianFood"),
        "dine_in": d.get("dineIn"),
        "takeout": d.get("takeout"),
        "delivery": d.get("delivery"),
        "reservable": d.get("reservable"),
        "price_start": price.get("startPrice", {}).get("units"),
        "price_end": price.get("endPrice", {}).get("units"),
        "price_currency": price.get("startPrice", {}).get("currencyCode")
        or price.get("endPrice", {}).get("currencyCode"),
    }


def find_latest_input() -> Path:
    c = sorted(Path("data/processed").glob("enriched_naver_*.jsonl"), reverse=True)
    if not c:
        sys.exit("[error] enriched_naver_*.jsonl 없음. 먼저 3_enrich_naver.py 실행.")
    return c[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="in_path", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        sys.exit("[error] GOOGLE_MAPS_API_KEY 환경변수 비어있음")

    in_path = args.in_path or find_latest_input()
    stamp = in_path.stem.split("_", 2)[-1]
    out_path = args.out or Path("data/processed") / f"enriched_google_{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    print(f"[details] {in_path} ({len(rows)} rows) rps={args.rps}")
    limiter = RateLimiter(args.rps)
    ok = err = skipped = 0
    t0 = time.monotonic()

    with httpx.Client() as client, out_path.open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            pid = r.get("place_id")
            if not pid:
                r["google_details"] = {"status": "skipped", "reason": "no_place_id"}
                skipped += 1
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                continue
            try:
                raw = fetch_details(client, api_key, pid, limiter)
                r["google_details"] = normalize_details(raw)
                if r["google_details"]["status"] == "ok":
                    ok += 1
                else:
                    err += 1
            except Exception as e:
                r["google_details"] = {"status": "error", "error": str(e)}
                err += 1
                print(f"  [{i}] [err] {r.get('name')}: {e}", file=sys.stderr)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

            if i % 50 == 0 or i == len(rows):
                elapsed = time.monotonic() - t0
                print(f"  [{i:>3}/{len(rows)}] ok={ok} err={err} skipped={skipped} elapsed={elapsed:.1f}s")

    elapsed = time.monotonic() - t0
    print(f"[ok] ok={ok} err={err} skipped={skipped} elapsed={elapsed:.1f}s -> {out_path}")


if __name__ == "__main__":
    main()
