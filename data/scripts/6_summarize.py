"""enriched_blogs_*.jsonl → Claude로 정제·요약한 summarized_*.jsonl 생성.

각 가게에 대해 1회 LLM 호출로 JSON 생성:
  - review_summary (2~3문장)
  - dish_types    (정규화 음식 분류)
  - menus         (메뉴명 + 가격 + 한 줄 설명)
  - tags          (controlled vocab: 혼밥/회식/빠른점심/국물/매운맛/가성비 등)

ThreadPoolExecutor로 병렬화 (기본 10 workers).

Usage:
    export $(grep -v '^#' .env | xargs)
    apps/api/.venv/bin/python data/scripts/6_summarize.py
    python data/scripts/6_summarize.py --limit 20 --workers 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

DEFAULT_WORKERS = 10
DEFAULT_MODEL_ID = "claude-haiku-4-5-20251001"
MAX_TOKENS = 800

SYSTEM_PROMPT = """당신은 식당 정보 정제기입니다. 주어진 식당 메타데이터와 블로그 리뷰 발췌에서
점메추 봇이 사용할 검색 가능한 JSON 데이터를 만듭니다.

규칙:
- 반드시 JSON 객체 하나만 출력. 설명/markdown/backtick 절대 금지.
- 근거 없는 내용은 쓰지 말 것. 블로그/메타에 나온 것만.
- 과장·광고 어조 금지. 관찰 기반 중립 서술.
- controlled vocabulary 준수.

스키마:
{
  "review_summary": "2~3문장. 점심 추천 맥락에서 유용한 특징(맛·분위기·회식/혼밥 적합성·대기·가격감). 정보 부족 시 빈 문자열.",
  "dish_types": ["국밥", "파스타", ...],   // 음식 분류 정규화. 최대 5개.
  "menus": [
    {"name": "...", "price": 12000, "description": "..."}
  ],
  // menus 규칙:
  //   1. 블로그/메타에 명시 언급된 메뉴를 우선 포함.
  //   2. dish_types 에 있는 분류는 메뉴로도 반드시 포함 (예: dish_types=["국밥"] 이면 menus 에도 {"name":"국밥",...}). 검색 재현율 확보 목적.
  //   3. price 불명은 null. 최대 6개. 없으면 [].
  //   4. description 은 메뉴 자체 특성(재료·맛·조리법·양·매운정도)만. 근거 없으면 null.
  //   5. "다른 메뉴와 함께 제공", "세트 구성" 같이 그 메뉴 자체 정보가 없는 서술은 description 에 쓰지 말고 null.
  "tags": [...]  // 아래 vocab 중에서만, 근거 있는 것만, 최대 6개.
}

tag vocabulary:
혼밥, 단체, 회식, 빠른점심, 여유있는식사, 국물, 매운맛, 담백, 든든한, 가벼운,
가성비, 프리미엄, 대기많음, 예약필수, 조용함, 활기찬, 뷰좋음, 포장가능, 배달가능,
아침, 점심, 저녁, 주말영업, 주말휴무"""


def build_user_prompt(row: dict) -> str:
    name = row.get("name") or ""
    primary = row.get("primary_type_display") or row.get("primary_type") or ""
    naver_cat = (row.get("naver") or {}).get("category") or ""
    addr = row.get("short_address") or row.get("address") or ""

    g = row.get("google_details") or {}
    hours = g.get("weekday_text") or []
    serves_lunch = g.get("serves_lunch")
    serves_dinner = g.get("serves_dinner")
    dine_in = g.get("dine_in")
    takeout = g.get("takeout")
    delivery = g.get("delivery")
    p_start, p_end, p_cur = g.get("price_start"), g.get("price_end"), g.get("price_currency")
    price_level = row.get("price_level")

    lines = [
        "[가게 정보]",
        f"이름: {name}",
        f"카테고리(google): {primary}",
        f"카테고리(naver): {naver_cat or '-'}",
        f"주소: {addr}",
    ]
    if hours:
        lines.append("영업시간:")
        for h in hours:
            lines.append(f"  - {h}")
    if serves_lunch is not None or serves_dinner is not None:
        lines.append(f"식사제공: 점심={serves_lunch} 저녁={serves_dinner}")
    if dine_in is not None or takeout is not None or delivery is not None:
        lines.append(f"서비스: 매장={dine_in} 포장={takeout} 배달={delivery}")
    if p_start or p_end:
        lines.append(f"가격범위: {p_start or '-'} ~ {p_end or '-'} {p_cur or ''}")
    if price_level:
        lines.append(f"구글 priceLevel: {price_level}")

    blogs = (row.get("blogs") or {}).get("items") or []
    if blogs:
        lines.append("\n[블로그 리뷰 발췌]")
        for i, b in enumerate(blogs, 1):
            lines.append(f"{i}. {b.get('title','')}")
            desc = (b.get("description") or "").replace("\n", " ")
            lines.append(f"   {desc}")
    else:
        lines.append("\n[블로그 리뷰 발췌] 없음")

    lines.append("\n위 정보만으로 JSON을 생성하세요.")
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """LLM 응답에서 첫 번째 JSON 객체 추출."""
    text = text.strip()
    # 혹시 ```json``` 으로 감쌌을 경우 대비
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"JSON 미발견: {text[:200]}")
    return json.loads(m.group(0))


def make_client():
    # SDK 자체 retry를 넉넉히 (429/overloaded 자동 backoff)
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        sys.exit("[error] ANTHROPIC_API_KEY 비어있음")
    return anthropic.Anthropic(api_key=api_key, max_retries=8)


def resolve_model_id(cli_arg: str | None) -> str:
    if cli_arg:
        return cli_arg
    env_model = os.getenv("MODEL_ID", "").strip()
    if env_model:
        return env_model
    return DEFAULT_MODEL_ID


def summarize_one(client, model_id: str, row: dict) -> dict:
    prompt = build_user_prompt(row)
    resp = client.messages.create(
        model=model_id,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return extract_json(text)


def find_latest_input() -> Path:
    c = sorted(Path("data/processed").glob("enriched_blogs_*.jsonl"), reverse=True)
    if not c:
        sys.exit("[error] enriched_blogs_*.jsonl 없음. 먼저 5_enrich_blogs.py 실행.")
    return c[0]


def process_row(args_tuple):
    idx, row, client, model_id = args_tuple
    try:
        result = summarize_one(client, model_id, row)
        row["summary"] = {"status": "ok", **result}
    except Exception as e:
        row["summary"] = {"status": "error", "error": str(e)[:200]}
    return idx, row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="in_path", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    in_path = args.in_path or find_latest_input()
    stamp = in_path.stem.split("_", 2)[-1]
    out_path = args.out or Path("data/processed") / f"summarized_{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]

    # idempotent: 기존 출력 파일에서 이미 ok 인 것은 재사용, 에러/누락만 재처리
    prior_ok: dict[str, dict] = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if (r.get("summary") or {}).get("status") == "ok":
                prior_ok[r.get("place_id")] = r
        if prior_ok:
            print(f"  [resume] 기존 ok {len(prior_ok)}건 재사용")

    client = make_client()
    model_id = resolve_model_id(args.model)
    print(f"[summarize] {in_path} ({len(rows)} rows) workers={args.workers} model={model_id}")

    ok = err = 0
    t0 = time.monotonic()
    results: dict[int, dict] = {}

    # 이미 ok 인 행은 futures 제출하지 않음
    to_process: list[tuple[int, dict]] = []
    for i, r in enumerate(rows):
        pid = r.get("place_id")
        if pid and pid in prior_ok:
            results[i] = prior_ok[pid]
            ok += 1
        else:
            to_process.append((i, r))

    if not to_process:
        print(f"  [skip] 재처리 대상 없음 (모두 ok)")
    else:
        print(f"  [run] 처리할 행: {len(to_process)}")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_row, (i, r, client, model_id)): i for i, r in to_process}
        for done in as_completed(futures):
            idx, row = done.result()
            results[idx] = row
            status = row["summary"]["status"]
            if status == "ok":
                ok += 1
            else:
                err += 1
            completed = len(results)
            if completed % 50 == 0 or completed == len(rows):
                elapsed = time.monotonic() - t0
                rate = completed / elapsed if elapsed else 0
                eta = (len(rows) - completed) / rate if rate else 0
                print(f"  [{completed:>3}/{len(rows)}] ok={ok} err={err} elapsed={elapsed:.0f}s eta={eta:.0f}s")

    with out_path.open("w", encoding="utf-8") as f:
        for i in range(len(rows)):
            f.write(json.dumps(results[i], ensure_ascii=False) + "\n")

    elapsed = time.monotonic() - t0
    print(f"[ok] ok={ok} err={err} elapsed={elapsed:.0f}s -> {out_path}")


if __name__ == "__main__":
    main()
