"""공연 정보에서 작곡가·곡명·연주자 태그를 뽑아 검색 가능하게 만듭니다.

KOPIS에는 '곡목(프로그램)' 필드가 따로 없고, 대부분 소개이미지(styurl) 안에 글자로 들어 있습니다.
그래서 두 단계로 처리합니다.
  1) 기본(무료): 출연진(prfcast) 쉼표 분리 + 본문에서 작곡가 사전 매칭
  2) --ai : Claude가 소개이미지까지 읽어 작곡가/곡/연주자를 구조화 (ANTHROPIC_API_KEY 필요)

사용 예:
  python3 enrich.py                 # 규칙 기반만, 아직 처리 안 된 공연
  python3 enrich.py --ai --genre 서양음악(클래식) --limit 50
  python3 enrich.py --ai --all      # 이미 처리된 것도 다시
"""
import argparse
import base64
import io
import json
import os
import re
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import urllib.request

import kopis

MODEL = os.environ.get("ENRICH_MODEL", "claude-haiku-5-5")

# 규칙 기반 매칭용 (한글 표기, 영문) — 필요하면 계속 추가하세요.
COMPOSERS = {
    "바흐": "Bach", "헨델": "Handel", "비발디": "Vivaldi", "하이든": "Haydn", "모차르트": "Mozart",
    "베토벤": "Beethoven", "슈베르트": "Schubert", "멘델스존": "Mendelssohn", "슈만": "Schumann",
    "쇼팽": "Chopin", "리스트": "Liszt", "브람스": "Brahms", "바그너": "Wagner", "베르디": "Verdi",
    "푸치니": "Puccini", "차이콥스키": "Tchaikovsky", "드보르자크": "Dvořák", "말러": "Mahler",
    "드뷔시": "Debussy", "라벨": "Ravel", "라흐마니노프": "Rachmaninoff", "프로코피예프": "Prokofiev",
    "쇼스타코비치": "Shostakovich", "스트라빈스키": "Stravinsky", "시벨리우스": "Sibelius",
    "브루크너": "Bruckner", "포레": "Fauré", "생상스": "Saint-Saëns", "그리그": "Grieg",
    "엘가": "Elgar", "로시니": "Rossini", "비제": "Bizet", "슈트라우스": "Strauss",
    "피아졸라": "Piazzolla", "거슈윈": "Gershwin", "윤이상": "Isang Yun", "진은숙": "Unsuk Chin",
}
ALIASES = {"차이코프스키": "차이콥스키", "드보르작": "드보르자크", "라흐마니노브": "라흐마니노프"}


def rule_tags(p):
    tags = []
    cast = re.sub(r"\s*등\s*$", "", p["cast"] or "")
    for name in re.split(r"[,/·]", cast):
        name = name.strip()
        if 1 < len(name) < 30:
            tags.append(("performer", name, ""))
    text = " ".join([p["title"] or "", p["story"] or "", p["crew"] or ""])
    for alias, canon in ALIASES.items():
        text = text.replace(alias, canon)
    for ko, en in COMPOSERS.items():
        if ko in text or en.lower() in text.lower():
            tags.append(("composer", ko, en))
    return tags


PROMPT = """다음은 한국 공연 정보와 소개 이미지입니다. 이 공연에서 실제로 연주/상연되는 내용을 save_program 도구로 저장하세요.
규칙:
- 이미지나 글에 실제로 적힌 것만 넣으세요. 추측하지 말고, 정보가 없으면 빈 목록으로 두세요.
- 작곡가는 한국에서 흔히 쓰는 표기(예: 차이콥스키, 드보르자크, 라흐마니노프)로 통일하고 영문 표기도 함께 넣으세요.
- 곡명은 '피아노 협주곡 1번'처럼 한국어로, 영문 곡명도 함께 넣으세요.
- 연극/뮤지컬이면 composers에는 작곡가·작가, works에는 원작을 넣으세요.

공연명: {title}
장르: {genre}
출연: {cast}
제작진: {crew}
소개글: {story}"""


_NAME = {"type": "object", "properties": {"ko": {"type": "string"}, "en": {"type": "string"}},
         "required": ["ko"]}
TOOL = {
    "name": "save_program",
    "description": "공연의 작곡가, 곡목, 출연자, 키워드를 저장한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "composers": {"type": "array", "items": _NAME},
            "works": {"type": "array", "items": {
                "type": "object",
                "properties": {"ko": {"type": "string"}, "en": {"type": "string"},
                               "composer": {"type": "string"}},
                "required": ["ko"]}},
            "performers": {"type": "array", "items": {
                "type": "object",
                "properties": {"ko": {"type": "string"}, "en": {"type": "string"},
                               "role": {"type": "string"}},
                "required": ["ko"]}},
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["composers", "works", "performers", "keywords"],
    },
}

try:
    from PIL import Image  # pip install pillow — 긴 이미지를 조각내는 데 사용
except ImportError:
    Image = None

TILE_W, TILE_H, MAX_TILES = 1000, 1400, 12


def _download(url):
    req = urllib.request.Request(url, headers=kopis.HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _media_type(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_blocks(urls):
    """소개 이미지를 내려받아, 세로로 긴 이미지는 여러 조각(JPEG)으로 나눠 base64 블록으로 만든다."""
    blocks = []
    for u in urls:
        if len(blocks) >= MAX_TILES:
            break
        try:
            data = _download(u)
        except Exception as e:
            print(f"    이미지 받기 실패: {u} ({e})")
            continue
        if Image is None:  # Pillow 없으면 원본 그대로 (너무 크면 건너뜀)
            mt = _media_type(data)
            if mt and len(data) < 4_500_000:
                blocks.append((mt, data))
            continue
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            continue
        if im.width > TILE_W:
            im = im.resize((TILE_W, max(1, round(im.height * TILE_W / im.width))))
        top = 0
        while top < im.height and len(blocks) < MAX_TILES:
            tile = im.crop((0, top, im.width, min(im.height, top + TILE_H)))
            buf = io.BytesIO()
            tile.save(buf, "JPEG", quality=85)
            blocks.append(("image/jpeg", buf.getvalue()))
            top += TILE_H - 60  # 조각 경계의 글자가 잘리지 않게 살짝 겹치기
    return [{"type": "image", "source": {"type": "base64", "media_type": mt,
                                         "data": base64.b64encode(d).decode()}} for mt, d in blocks]


def ai_tags(p, api_key):
    content = image_blocks(json.loads(p["images"] or "[]"))
    content.append({"type": "text", "text": PROMPT.replace("{title}", p["title"] or "")
                    .replace("{genre}", p["genre"] or "").replace("{cast}", p["cast"] or "")
                    .replace("{crew}", p["crew"] or "").replace("{story}", (p["story"] or "")[:3000])})
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": MODEL, "max_tokens": 2000,
                         "tools": [TOOL], "tool_choice": {"type": "tool", "name": "save_program"},
                         "messages": [{"role": "user", "content": content}]}).encode(),
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.load(r)
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:  # 너무 빠름/일시 오류 → 기다렸다 재시도
                time.sleep(int(e.headers.get("retry-after") or 0) or 10 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} — {body}")
    data = next((b["input"] for b in resp.get("content", []) if b.get("type") == "tool_use"), None)
    if data is None:
        raise RuntimeError(f"형식에 맞는 답이 없음 (stop_reason={resp.get('stop_reason')})")
    def pairs(items):  # {"ko":..,"en":..} 또는 그냥 문자열 둘 다 허용
        for x in items or []:
            if isinstance(x, dict):
                yield x.get("ko") or x.get("en") or "", x.get("en") or ""
            elif isinstance(x, str):
                yield x, ""

    tags = [("composer", k, e) for k, e in pairs(data.get("composers"))]
    tags += [("work", k, e) for k, e in pairs(data.get("works"))]
    tags += [("performer", k, e) for k, e in pairs(data.get("performers"))]
    tags += [("keyword", k, e) for k, e in pairs(data.get("keywords"))]
    return tags


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--all", action="store_true", help="이미 처리된 공연도 다시")
    ap.add_argument("--genre", help="예: 서양음악(클래식)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--id", nargs="*", help="특정 공연 ID만 (예: PF293222)")
    ap.add_argument("--workers", type=int, default=4, help="AI 동시 처리 개수 (기본 4)")
    a = ap.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if a.ai and not api_key:
        raise SystemExit("--ai 를 쓰려면 ANTHROPIC_API_KEY 환경변수가 필요합니다.")
    if a.ai and Image is None:
        print("※ Pillow가 없어 긴 이미지는 건너뜁니다. 'python -m pip install pillow' 를 먼저 실행하세요.")

    # enriched: 0 = 미처리, 1 = 규칙만, 2 = AI까지 완료
    con = kopis.connect()
    sql, args = "SELECT * FROM performances WHERE 1=1", []
    if a.id:
        sql += f" AND id IN ({','.join('?' * len(a.id))})"
        args += a.id
    elif not a.all:
        sql += " AND enriched<2" if a.ai else " AND enriched=0"
    if a.genre:
        sql += " AND genre=?"
        args.append(a.genre)
    sql += " ORDER BY start"
    if a.limit:
        sql += f" LIMIT {int(a.limit)}"
    rows = con.execute(sql, args).fetchall()
    print(f"{len(rows)}건 처리 ({'AI, 동시 ' + str(a.workers) + '건' if a.ai else '규칙'})")

    def work(p):
        tags = rule_tags(p)
        ok = False
        if a.ai:
            try:
                tags += ai_tags(p, api_key)
                ok = True
            except Exception as e:
                print("  AI 실패", p["id"], p["title"][:30], "→", e)
        return p, tags, ok

    done = fail = 0
    with ThreadPoolExecutor(max_workers=a.workers if a.ai else 1) as ex:
        for i, (p, tags, ok) in enumerate(ex.map(work, rows), 1):
            kopis.save_tags(con, p["id"], tags)
            if ok:
                con.execute("UPDATE performances SET enriched=2 WHERE id=?", (p["id"],))
                done += 1
            elif a.ai:
                fail += 1
            if a.id:
                print(f"  [{p['title']}]")
                for t in tags:
                    print("    ", t[0], "|", t[1], "|", t[2])
            if i % 20 == 0:
                con.commit()
                print(f"  {i}/{len(rows)}")
    con.commit()
    print(f"완료 (AI 성공 {done}, 실패 {fail})" if a.ai else "완료")
    if fail:
        print("실패한 공연은 같은 명령을 다시 실행하면 그것만 다시 시도합니다.")
