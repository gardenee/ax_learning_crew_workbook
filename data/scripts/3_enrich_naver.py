"""filtered_*.jsonl에 네이버 지역검색 API로 매칭 정보를 보강한다.

- 네이버 Open API (v1/search/local) 사용
- 초당 호출 제한 기본 10 rps (CLI로 조정 가능)
- 이름 유사도 + 주소 "강서구" 검증으로 매칭
- 매칭 성공 시 naver.place_id·link·category·telephone 등 부착
- 실패 시 naver.status=unmatched 플래그 (행은 보존)

Usage:
    export $(grep -v '^#' .env | xargs)
    apps/api/.venv/bin/python data/scripts/3_enrich_naver.py
    # 소수 테스트
    python data/scripts/3_enrich_naver.py --limit 20
    # rate 조정
    python data/scripts/3_enrich_naver.py --rps 5
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

NAVER_ENDPOINT = "https://openapi.naver.com/v1/search/local.json"
DEFAULT_RPS = 10.0
DEFAULT_SIM_THRESHOLD = 0.55
REQUIRED_ADDR_KEYWORD = "강서구"  # LG CNS 반경 내는 거의 전부 강서구


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


def strip_html_tags(s: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


def extract_place_id(link: str | None) -> str | None:
    if not link:
        return None
    m = re.search(r"/(?:restaurant|place)/(\d+)", link)
    return m.group(1) if m else None


def normalize_name(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def pick_best_match(items: list[dict], google_name: str, threshold: float) -> dict | None:
    g_norm = normalize_name(google_name)
    if not g_norm:
        return None
    best = None
    best_score = 0.0
    for it in items:
        title = strip_html_tags(it.get("title"))
        if not title:
            continue
        addr = (it.get("address") or "") + " " + (it.get("roadAddress") or "")
        if REQUIRED_ADDR_KEYWORD not in addr:
            continue
        t_norm = normalize_name(title)
        if not t_norm:
            continue
        if g_norm == t_norm:
            score = 1.0
        elif g_norm in t_norm or t_norm in g_norm:
            score = 0.95
        else:
            score = difflib.SequenceMatcher(None, g_norm, t_norm).ratio()
        if score >= threshold and score > best_score:
            best_score = score
            best = {**it, "_match_score": score, "_title_clean": title}
    return best


def search_naver(
    client: httpx.Client,
    client_id: str,
    client_secret: str,
    query: str,
    limiter: RateLimiter,
) -> dict:
    limiter.acquire()
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    params = {"query": query, "display": 5, "start": 1}
    for attempt in range(3):
        try:
            resp = client.get(NAVER_ENDPOINT, params=params, headers=headers, timeout=10.0)
            if resp.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            if attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))
            print(f"  [warn] 재시도 {attempt + 1}: {e}", file=sys.stderr)
    raise RuntimeError("unreachable")


def build_query(row: dict) -> str:
    name = row.get("name") or ""
    short_addr = row.get("short_address") or row.get("address") or ""
    # 주소 앞 토큰 1~2개만 힌트로 (예: "서울특별시 강서구")
    parts = short_addr.split()
    hint = " ".join(parts[:2]) if parts else ""
    return f"{name} {hint}".strip()


def find_latest_filtered() -> Path:
    candidates = sorted(Path("data/processed").glob("filtered_*.jsonl"), reverse=True)
    if not candidates:
        sys.exit("[error] data/processed/filtered_*.jsonl 없음. 먼저 2_filter.py 실행.")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="in_path", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS)
    parser.add_argument("--limit", type=int, default=None, help="처음 N개만 (테스트용)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_SIM_THRESHOLD)
    args = parser.parse_args()

    cid = os.getenv("NAVER_CLIENT_ID", "").strip()
    cs = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not cid or not cs:
        sys.exit("[error] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 비어있음")

    in_path = args.in_path or find_latest_filtered()
    stamp = in_path.stem.split("_", 1)[1]
    out_path = args.out or Path("data/processed") / f"enriched_naver_{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    print(f"[enrich] {in_path} ({len(rows)} rows) rps={args.rps} threshold={args.threshold}")
    limiter = RateLimiter(args.rps)
    matched = unmatched = errors = 0
    t0 = time.monotonic()

    with httpx.Client() as client, out_path.open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            query = build_query(r)
            try:
                data = search_naver(client, cid, cs, query, limiter)
                items = data.get("items", [])
                match = pick_best_match(items, r.get("name") or "", args.threshold)
            except Exception as e:
                print(f"  [{i:>3}] [err] {r.get('name')}: {e}", file=sys.stderr)
                r["naver"] = {"status": "error", "error": str(e), "query": query}
                errors += 1
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                continue

            if match:
                place_id = extract_place_id(match.get("link"))
                r["naver"] = {
                    "status": "matched" if place_id else "matched_no_id",
                    "place_id": place_id,
                    "link": match.get("link"),
                    "category": match.get("category"),
                    "title": match["_title_clean"],
                    "address": match.get("address"),
                    "road_address": match.get("roadAddress"),
                    "telephone": match.get("telephone") or None,
                    "mapx": match.get("mapx"),
                    "mapy": match.get("mapy"),
                    "match_score": round(match["_match_score"], 3),
                    "query": query,
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                matched += 1
            else:
                r["naver"] = {
                    "status": "unmatched",
                    "query": query,
                    "candidates": len(items) if "items" in locals() else 0,
                }
                unmatched += 1
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

            if i % 50 == 0 or i == len(rows):
                elapsed = time.monotonic() - t0
                print(f"  [{i:>3}/{len(rows)}] matched={matched} unmatched={unmatched} errors={errors} elapsed={elapsed:.1f}s")

    elapsed = time.monotonic() - t0
    print(f"[ok] matched={matched} unmatched={unmatched} errors={errors} elapsed={elapsed:.1f}s -> {out_path}")


if __name__ == "__main__":
    main()
