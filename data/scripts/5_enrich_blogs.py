"""네이버 블로그 검색 API로 가게당 블로그 리뷰 원재료 수집.

각 가게에 대해 `{name} {area_hint}` 쿼리로 상위 N건을 모아 LLM 요약용 원재료로 저장.
description에 가게명 substring이 없으면 버려서 노이즈 컷.

Usage:
    export $(grep -v '^#' .env | xargs)
    apps/api/.venv/bin/python data/scripts/5_enrich_blogs.py
"""

from __future__ import annotations

import argparse
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

ENDPOINT = "https://openapi.naver.com/v1/search/blog.json"
DEFAULT_RPS = 10.0
DEFAULT_DISPLAY = 5
AREA_KEYWORDS = ("마곡", "가양", "발산", "등촌", "염창", "화곡", "강서")


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


def strip_tags(s: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


def area_hint(row: dict) -> str:
    addr = (row.get("address") or "") + " " + (row.get("short_address") or "")
    for kw in AREA_KEYWORDS:
        if kw in addr:
            return kw
    return ""


def build_query(row: dict) -> str:
    name = row.get("name") or ""
    # 긴 다국어 이름(|) 은 앞쪽만
    name = name.split("｜")[0].split("|")[0].strip()
    hint = area_hint(row)
    return f"{name} {hint}".strip() if hint else name


def normalize_name(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def search_blogs(
    client: httpx.Client, cid: str, cs: str, query: str, display: int, limiter: RateLimiter
) -> dict:
    limiter.acquire()
    headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": cs}
    params = {"query": query, "display": display, "start": 1, "sort": "sim"}
    for attempt in range(3):
        try:
            resp = client.get(ENDPOINT, params=params, headers=headers, timeout=10.0)
            if resp.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            if attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError("unreachable")


def pick_relevant(items: list[dict], name: str) -> list[dict]:
    """가게명이 title/description에 포함된 글만 필터."""
    n_norm = normalize_name(name.split("｜")[0].split("|")[0])
    if not n_norm:
        return []
    kept = []
    for it in items:
        title = strip_tags(it.get("title"))
        desc = strip_tags(it.get("description"))
        blob = normalize_name(title + desc)
        if n_norm in blob:
            kept.append(
                {
                    "title": title,
                    "description": desc,
                    "link": it.get("link"),
                    "blogger": it.get("bloggername"),
                    "postdate": it.get("postdate"),
                }
            )
    return kept


def find_latest_input() -> Path:
    c = sorted(Path("data/processed").glob("enriched_google_*.jsonl"), reverse=True)
    if not c:
        sys.exit("[error] enriched_google_*.jsonl 없음. 먼저 4_enrich_google_details.py 실행.")
    return c[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="in_path", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS)
    parser.add_argument("--display", type=int, default=DEFAULT_DISPLAY)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    cid = os.getenv("NAVER_CLIENT_ID", "").strip()
    cs = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not cid or not cs:
        sys.exit("[error] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 비어있음")

    in_path = args.in_path or find_latest_input()
    stamp = in_path.stem.split("_", 2)[-1]
    out_path = args.out or Path("data/processed") / f"enriched_blogs_{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    print(f"[blogs] {in_path} ({len(rows)} rows) rps={args.rps} display={args.display}")
    limiter = RateLimiter(args.rps)
    have_blogs = zero_blogs = errors = 0
    t0 = time.monotonic()

    with httpx.Client() as client, out_path.open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            query = build_query(r)
            try:
                data = search_blogs(client, cid, cs, query, args.display, limiter)
                items = data.get("items", [])
                relevant = pick_relevant(items, r.get("name") or "")
            except Exception as e:
                r["blogs"] = {"status": "error", "error": str(e), "query": query, "items": []}
                errors += 1
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                continue

            r["blogs"] = {
                "status": "ok" if relevant else "no_relevant",
                "query": query,
                "total_hits": data.get("total", 0),
                "kept": len(relevant),
                "items": relevant,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if relevant:
                have_blogs += 1
            else:
                zero_blogs += 1
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

            if i % 50 == 0 or i == len(rows):
                elapsed = time.monotonic() - t0
                print(f"  [{i:>3}/{len(rows)}] have={have_blogs} zero={zero_blogs} err={errors} elapsed={elapsed:.1f}s")

    elapsed = time.monotonic() - t0
    print(f"[ok] have_blogs={have_blogs} zero={zero_blogs} err={errors} elapsed={elapsed:.1f}s -> {out_path}")


if __name__ == "__main__":
    main()
