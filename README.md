# CLAB — 공연 통합 검색

KOPIS(공연예술통합전산망) 공연 정보에 AI가 읽어 낸 작곡가·곡목을 더해, 한 번에 검색하는 사이트입니다.

## 구조
| 파일 | 역할 |
|---|---|
| `kopis.py` | KOPIS API 호출, DB 저장 |
| `sync.py` | KOPIS 공연 목록·상세 수집 |
| `enrich.py` | 작곡가/곡/연주자 태그 (규칙 + `--ai`로 소개 이미지 읽기) |
| `export.py` | DB → `site/` (index.html + data.json) 정적 사이트 생성 |
| `server.py` | 내 컴퓨터에서 미리보기 (http://localhost:8000) |
| `static/index.html` | 화면 (검색은 브라우저 안에서 처리) |
| `.github/workflows/update.yml` | 매일 자동 업데이트 + GitHub Pages 배포 |
| `performances.db` | 공연 데이터 (처음 배포할 때 씨앗 데이터로 사용) |

## 내 컴퓨터에서 실행
```
$env:KOPIS_KEY="KOPIS 인증키"
$env:ANTHROPIC_API_KEY="Anthropic API 키"
python sync.py --days 90
python enrich.py
python enrich.py --ai --genre "서양음악(클래식)"
python server.py
```

## 인터넷 공개 (GitHub Pages)
- 저장소 Settings → Secrets and variables → Actions 에 `KOPIS_KEY`, `ANTHROPIC_API_KEY` 등록
- Settings → Pages → Source: **GitHub Actions**
- Actions 탭 → "매일 공연 업데이트" → Run workflow
- 이후 매일 한국시간 새벽 4시쯤 자동으로 갱신됩니다.

공연 정보 출처: KOPIS 공연예술통합전산망. 곡목은 AI 추출 정보로 오류가 있을 수 있습니다.
