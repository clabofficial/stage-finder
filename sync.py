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


LIST_GAP = 0.5     # 목록 요청 사이 쉬는 시간(초)
DETAIL_GAP = 0.7   # 상세 요청 사이 쉬는 시간(초)
REFRESH_DAYS = 7   # 이미 받은 공연은 7일에 한 번만 상세 정보를 다시 받음


def sync(key, days, genres):
    con = kopis.connect()
    ids = set()
    failed = 0
    blocked = False
    for g in genres:
        if blocked:
            break
        for s, e in windows(dt.date.today(), days):
            page = 1
            while True:
                try:
                    got = kopis.list_performances(key, s, e, genre=g, page=page)
                except kopis.Blocked as ex:
                    print(" ", ex)
                    blocked = True
                    break
                except Exception as ex:  # 이 구간만 건너뛰고 계속 (내일 다시 받음)
                    failed += 1
                    print(f"  목록 실패, 건너뜀: {kopis.GENRES.get(g, g)} {s}~{e} p{page} ({ex})")
                    break
                ids.update(got)
                print(f"  목록 {kopis.GENRES.get(g, g)} {s}~{e} p{page}: {len(got)}건")
                if len(got) < kopis.ROWS:
                    break
                page += 1
                time.sleep(LIST_GAP)
            if blocked:
                break
            time.sleep(LIST_GAP)
    if not ids:
        sys.exit("공연 목록을 하나도 받지 못했어요. 인터넷 연결, KOPIS 인증키, 또는 KOPIS 차단 여부를 확인하세요.")
    if failed:
        print(f"※ 목록 {failed}개 구간을 받지 못했어요. 나머지는 계속 진행합니다.")

    # 새 공연 + 오래된 공연만 상세 조회 (매일 수천 건을 다시 받지 않도록)
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=REFRESH_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    known = dict(con.execute("SELECT id, updated FROM performances"))
    todo = sorted(i for i in ids if i not in known or (known[i] or "") < cutoff)
    print(f"목록 {len(ids)}건 중 새로 받을 상세 정보 {len(todo)}건" + (" (목록이 일부만 받아졌어요)" if blocked else ""))
    for i, mid in enumerate(todo, 1):
        try:
            p = kopis.get_detail(key, mid)
            if p:
                kopis.save(con, p)
        except kopis.Blocked as ex:
            print(" ", ex)
            blocked = True
            break
        except Exception as ex:
            print("  건너뜀", mid, ex)
        if i % 50 == 0:
            con.commit()
            print(f"  {i}/{len(todo)}")
        time.sleep(DETAIL_GAP)
    con.commit()
    if blocked:
        print("※ KOPIS 차단으로 일부만 받았어요. 받은 데이터는 저장했고, 다음 실행 때 이어서 받습니다.")
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
