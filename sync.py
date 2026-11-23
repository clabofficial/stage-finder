"""KOPIS 데이터를 내려받아 로컬 DB(performances.db)에 저장합니다.

사용 예:
  KOPIS_KEY=발급키 python3 sync.py                 # 오늘부터 1년, 전체 장르
  KOPIS_KEY=발급키 python3 sync.py --days 60 --genre CCCA AAAA
  python3 sync.py --demo                           # 인증키 없이 샘플 데이터로 화면 확인

하루 1번 정도 cron 등으로 돌리면 됩니다 (사이트 방문자가 KOPIS를 직접 호출하지 않게).
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import kopis


def windows(start, days, size=31):
    """KOPIS 목록 조회는 기간이 최대 31일이라 구간을 나눠서 요청."""
    d = start
    end = start + dt.timedelta(days=days)
    while d < end:
        e = min(d + dt.timedelta(days=size - 1), end)
        yield d.strftime("%Y%m%d"), e.strftime("%Y%m%d")
        d = e + dt.timedelta(days=1)


def sync(key, days, genres):
    con = kopis.connect()
    ids = set()
    for g in genres:
        for s, e in windows(dt.date.today(), days):
            page = 1
            while True:
                got = kopis.list_performances(key, s, e, genre=g, page=page)
                ids.update(got)
                print(f"  목록 {kopis.GENRES.get(g, g)} {s}~{e} p{page}: {len(got)}건")
                if len(got) < kopis.ROWS:
                    break
                page += 1
                time.sleep(0.2)
    print(f"공연 {len(ids)}건 상세 조회 중…")
    for i, mid in enumerate(sorted(ids), 1):
        try:
            p = kopis.get_detail(key, mid)
            if p:
                kopis.save(con, p)
        except Exception as ex:
            print("  건너뜀", mid, ex)
        if i % 50 == 0:
            con.commit()
            print(f"  {i}/{len(ids)}")
        time.sleep(0.1)  # 서버 부담 줄이기
    con.commit()
    print("완료:", kopis.DB_PATH)


def demo():
    """네트워크/인증키 없이 화면을 확인하기 위한 가짜 샘플 데이터."""
    with open(os.path.join(os.path.dirname(__file__), "demo_data.json"), encoding="utf-8") as f:
        items = json.load(f)
    con = kopis.connect()
    for it in items:
        tags = it.pop("tags")
        kopis.save(con, it)
        kopis.save_tags(con, it["id"], [tuple(t) for t in tags])
    con.commit()
    print(f"샘플 {len(items)}건 저장 → {kopis.DB_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365, help="오늘부터 며칠 뒤까지 (기본 365)")
    ap.add_argument("--genre", nargs="*", default=list(kopis.GENRES), help="장르 코드 (기본: 전체)")
    ap.add_argument("--demo", action="store_true", help="샘플 데이터만 넣기")
    a = ap.parse_args()
    if a.demo:
        demo()
        sys.exit()
    key = os.environ.get("KOPIS_KEY")
    if not key:
        sys.exit("환경변수 KOPIS_KEY 에 인증키를 넣어주세요.")
    sync(key, a.days, a.genre)
