"""CLAB 하루 업데이트 (내 컴퓨터에서 실행)

  KOPIS 받기 → 태그 붙이기 → AI 곡목 읽기(새 클래식 공연만) → 사이트 만들기 → GitHub에 올리기

사용:
  update.bat 더블클릭              # 전체 업데이트
  python update.py --no-sync       # 디자인만 바꿨을 때: 데이터 수집 없이 사이트만 다시 올리기

인증키는 같은 폴더의 keys.env 파일에서 읽습니다 (GitHub에는 올라가지 않음).
"""
import datetime as dt
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
LOG = open(os.path.join(ROOT, "update.log"), "a", encoding="utf-8")


def log(msg):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M}] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def load_keys():
    path = os.path.join(ROOT, "keys.env")
    if not os.path.exists(path):
        return
    for raw in open(path, encoding="utf-8-sig"):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            os.environ[k.strip()] = v


def run(args, must=True):
    log("실행: " + " ".join(args))
    code = subprocess.run(args).returncode
    if code and must:
        log(f"실패 (코드 {code}) — 업데이트를 멈춥니다.")
        sys.exit(code)
    return code


def main():
    no_sync = "--no-sync" in sys.argv
    load_keys()
    log("===== CLAB 업데이트 시작" + (" (사이트만)" if no_sync else "") + " =====")
    py = sys.executable

    if not no_sync:
        if not os.environ.get("KOPIS_KEY"):
            log("keys.env 에 KOPIS_KEY 가 없습니다."); sys.exit(1)
        run([py, "sync.py", "--days", "365"])
        run([py, "enrich.py"])
        if os.environ.get("ANTHROPIC_API_KEY"):
            run([py, "enrich.py", "--ai", "--genre", "서양음악(클래식)"], must=False)
        else:
            log("ANTHROPIC_API_KEY 가 없어 AI 곡목 읽기는 건너뜁니다.")
    run([py, "export.py"])

    # GitHub에 올리기 (site 폴더 = 실제 사이트)
    run(["git", "pull", "--rebase", "--autostash", "-q"], must=False)
    run(["git", "rm", "--cached", "--ignore-unmatch", "-q", "performances.db"], must=False)
    run(["git", "add", "-A"])
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        log("바뀐 내용이 없어 올리지 않습니다.")
    else:
        run(["git", "commit", "-q", "-m", f"공연 데이터 업데이트 {dt.date.today()}"])
        run(["git", "push", "-q"])
        log("GitHub에 올렸습니다. 몇 분 뒤 사이트에 반영됩니다.")
    log("===== 완료 =====")


if __name__ == "__main__":
    main()
