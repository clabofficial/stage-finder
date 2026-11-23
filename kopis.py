"""KOPIS(공연예술통합전산망) 오픈API 호출 + XML 파싱 + SQLite 저장.

표준 라이브러리만 사용합니다 (설치할 패키지 없음).
"""
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "http://www.kopis.or.kr/openApi/restful"
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "performances.db"))

# KOPIS 장르 코드
GENRES = {
    "AAAA": "연극",
    "GGGA": "뮤지컬",
    "CCCA": "서양음악(클래식)",
    "CCCC": "한국음악(국악)",
    "CCCD": "대중음악",
    "BBBC": "무용(서양/한국무용)",
    "BBBE": "대중무용",
    "EEEA": "복합",
    "EEEB": "서커스/마술",
}


# ---------------------------------------------------------------- API 호출
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
ROWS = 50  # 한 번에 받을 개수


def _get(path, params, retries=3):
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return ET.fromstring(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if i == retries - 1:
                raise RuntimeError(f"KOPIS 호출 실패: {path} (HTTP {e.code})\n  KOPIS 응답: {body}")
            time.sleep(1.5 * (i + 1))
        except Exception as e:  # 네트워크 오류 시 잠깐 쉬고 재시도
            if i == retries - 1:
                raise RuntimeError(f"KOPIS 호출 실패: {path} ({e})")
            time.sleep(1.5 * (i + 1))


def _t(el, tag):
    v = el.findtext(tag)
    return v.strip() if v else ""


def list_performances(key, stdate, eddate, genre=None, page=1, rows=ROWS):
    """공연목록 조회. 날짜는 YYYYMMDD, 기간은 최대 31일."""
    params = {"service": key, "stdate": stdate, "eddate": eddate, "cpage": page, "rows": rows}
    if genre:
        params["shcate"] = genre
    root = _get("pblprfr", params)
    return [_t(db, "mt20id") for db in root.findall("db")]


def get_detail(key, mt20id):
    """공연상세 조회 → dict"""
    root = _get(f"pblprfr/{mt20id}", {"service": key})
    db = root.find("db")
    if db is None:
        return None
    return {
        "id": _t(db, "mt20id"),
        "title": _t(db, "prfnm"),
        "start": _t(db, "prfpdfrom").replace(".", "-"),
        "end": _t(db, "prfpdto").replace(".", "-"),
        "venue": _t(db, "fcltynm"),
        "cast": _t(db, "prfcast"),
        "crew": _t(db, "prfcrew"),
        "runtime": _t(db, "prfruntime"),
        "age": _t(db, "prfage"),
        "producer": _t(db, "entrpsnm"),
        "price": _t(db, "pcseguidance"),
        "poster": _t(db, "poster"),
        "story": _t(db, "sty"),
        "area": _t(db, "area"),
        "genre": _t(db, "genrenm"),
        "state": _t(db, "prfstate"),
        "schedule": _t(db, "dtguidance"),
        "images": [s.text.strip() for s in db.findall("styurls/styurl") if s.text],
        "booking": [
            {"name": _t(r, "relatenm"), "url": _t(r, "relateurl")}
            for r in db.findall("relates/relate") if _t(r, "relateurl")
        ],
    }


# ---------------------------------------------------------------- DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS performances (
  id TEXT PRIMARY KEY, title TEXT, genre TEXT, state TEXT,
  start TEXT, end TEXT, venue TEXT, area TEXT,
  cast TEXT, crew TEXT, runtime TEXT, age TEXT, producer TEXT, price TEXT,
  poster TEXT, story TEXT, schedule TEXT,
  images TEXT, booking TEXT,
  enriched INTEGER DEFAULT 0, updated TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tags (
  perf_id TEXT, type TEXT, value TEXT, alias TEXT,
  UNIQUE(perf_id, type, value)
);
CREATE INDEX IF NOT EXISTS idx_tags_value ON tags(type, value);
CREATE INDEX IF NOT EXISTS idx_perf_dates ON performances(start, end);
"""


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def save(con, p):
    con.execute(
        """INSERT INTO performances (id,title,genre,state,start,end,venue,area,cast,crew,runtime,age,
             producer,price,poster,story,schedule,images,booking,updated)
           VALUES (:id,:title,:genre,:state,:start,:end,:venue,:area,:cast,:crew,:runtime,:age,
             :producer,:price,:poster,:story,:schedule,:images,:booking,CURRENT_TIMESTAMP)
           ON CONFLICT(id) DO UPDATE SET
             title=excluded.title, genre=excluded.genre, state=excluded.state, start=excluded.start,
             end=excluded.end, venue=excluded.venue, area=excluded.area, cast=excluded.cast,
             crew=excluded.crew, runtime=excluded.runtime, age=excluded.age, producer=excluded.producer,
             price=excluded.price, poster=excluded.poster, story=excluded.story,
             schedule=excluded.schedule, images=excluded.images, booking=excluded.booking,
             updated=CURRENT_TIMESTAMP""",
        {**p, "images": json.dumps(p["images"], ensure_ascii=False),
         "booking": json.dumps(p["booking"], ensure_ascii=False)},
    )


def save_tags(con, perf_id, tags):
    """tags: [(type, value, alias), ...]  type = composer | work | performer | keyword"""
    con.execute("DELETE FROM tags WHERE perf_id=?", (perf_id,))
    for t, v, a in tags:
        if v:
            con.execute("INSERT OR IGNORE INTO tags VALUES (?,?,?,?)", (perf_id, t, v.strip(), (a or "").strip()))
    con.execute("UPDATE performances SET enriched=1 WHERE id=?", (perf_id,))
