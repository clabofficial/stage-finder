"""DB(performances.db) → 정적 사이트 폴더(site/) 만들기.

site/index.html + site/data.json 만 있으면 어디든(GitHub Pages 등) 올려서 동작합니다.
  python export.py
"""
import datetime as dt
import json
import os
import shutil

import kopis

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, "site")
FIELDS = ["id", "title", "genre", "state", "start", "end", "venue", "area", "cast", "crew",
          "runtime", "age", "price", "poster", "story", "schedule"]


def https(u):  # 사이트가 https라서 이미지 주소도 https로 (http 이미지는 브라우저가 막을 수 있음)
    return u.replace("http://www.kopis.or.kr", "https://www.kopis.or.kr") if u else u


def build():
    con = kopis.connect()
    today = dt.date.today().isoformat()
    tags = {}
    for pid, t, v, a in con.execute("SELECT perf_id, type, value, alias FROM tags"):
        tags.setdefault(pid, []).append([t, v, a] if a else [t, v])
    items = []
    for r in con.execute("SELECT * FROM performances WHERE end >= ? ORDER BY start", (today,)):
        d = {k: r[k] for k in FIELDS if r[k]}
        if d.get("poster"):
            d["poster"] = https(d["poster"])
        imgs = [https(u) for u in json.loads(r["images"] or "[]")]
        book = json.loads(r["booking"] or "[]")
        if imgs:
            d["images"] = imgs
        if book:
            d["booking"] = book
        d["tags"] = tags.get(r["id"], [])
        items.append(d)
    os.makedirs(SITE, exist_ok=True)
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    with open(os.path.join(SITE, "data.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": now, "items": items}, f, ensure_ascii=False, separators=(",", ":"))
    shutil.copy(os.path.join(ROOT, "static", "index.html"), os.path.join(SITE, "index.html"))
    open(os.path.join(SITE, ".nojekyll"), "w").close()
    print(f"site/ 생성: 공연 {len(items)}건 ({now})")


if __name__ == "__main__":
    build()
