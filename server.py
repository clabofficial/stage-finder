"""내 컴퓨터에서 사이트 미리보기.

  python server.py   →  http://localhost:8000

시작할 때 DB 내용으로 site/ 폴더를 새로 만들고(export.py), 그 폴더를 보여줍니다.
인터넷에 올라가는 것도 이 site/ 폴더와 똑같은 내용입니다.
"""
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import export

if __name__ == "__main__":
    export.build()
    port = int(os.environ.get("PORT", 8000))
    print(f"http://localhost:{port}  (끄려면 Ctrl + C)")
    handler = partial(SimpleHTTPRequestHandler, directory=export.SITE)
    ThreadingHTTPServer(("0.0.0.0", port), handler).serve_forever()
