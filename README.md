# DB손해보험 경영공시 PDF 수집기

DB손해보험의 정기경영공시 목록을 주기적으로 확인하고, 새 공시의 PDF 첨부파일을 내려받아 텍스트와 핵심 경영지표를 정리하는 Python 프로젝트입니다. GitHub Actions에서 자동 실행하도록 구성했습니다.

## 1. DB손해보험 공시 페이지 확인 결과

- 정기경영공시 목록: <https://www.idbins.com/pc/bizxpress/contentTemplet/pb/mp/rg/list.jsp>
- 목록에서 게시물 상세 페이지로 이동한 뒤 PDF 첨부 링크를 수집합니다.
- 확인 시점의 2026년 상반기 공시(등록일 2026-08-31)는 `2026083101.pdf`, `2026083102.pdf`, `2026083103.pdf`의 3개 PDF로 나뉘어 있었습니다.
- 2026년 1분기 공시(등록일 2026-05-29)도 `2026052901.pdf`, `2026052902.pdf`, `2026052903.pdf`의 3개 PDF로 구성되어 있었습니다.
- 공시 제목이 `1분기`, `상반기`, `3분기`, `경영통일공시` 형태로 혼합되어 있어 기간 유형을 별도 컬럼으로 구분합니다.

> 사이트 HTML 또는 파일 링크 방식이 바뀔 수 있습니다. 수집기가 링크를 찾지 못하면 조용히 빈 데이터로 종료하지 않고 오류를 내도록 했습니다.

## 2. 수집·저장 결과

실행하면 다음 데이터가 `data/` 아래에 쌓입니다.

| 위치 | 내용 |
|---|---|
| `data/raw/dbins/` | 원본 PDF 파일 |
| `data/processed/dbins/` | PDF 전체 페이지에서 추출한 TXT와 문서별 JSON |
| `data/exports/documents.csv` | 공시 게시물 목록 |
| `data/exports/attachments.csv` | 공시별 PDF 첨부파일 목록, URL, 해시, 페이지 수 |
| `data/exports/metrics.csv` | 주요 경영지표 구조화 결과 |
| `data/db/disclosures.sqlite3` | 공시·첨부파일·지표를 저장하는 SQLite 데이터베이스 |

### 첫 버전에서 구조화하는 지표

PDF 첫 번째 요약 첨부파일에 있는 `주요 경영현황 요약`을 기준으로 추출합니다.

- 자산, 부채, 자본, 당기순이익
- 지급여력비율(경과조치 전/후)
- 운용자산이익률, 영업이익률, ROA, ROE
- 신계약률, 효력상실 및 해약률, 보험금지급률, 자산운용률
- 13·25·37·49·61·73·85회차 유지율

숫자 추출은 PDF 텍스트의 표 순서에 의존하는 규칙 기반 방식입니다. PDF 원본과 전체 TXT도 항상 함께 보관해 검증할 수 있게 했습니다. 지표가 바뀌거나 추출 결과가 비어 있으면 TXT와 PDF를 확인하고 `src/insurance_disclosures/extract.py`의 규칙을 조정하면 됩니다.

## 3. 로컬 실행

Python 3.11을 권장합니다.

```bash
# 1) 가상환경
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate

# 2) 설치
python -m pip install -r requirements.txt

# 3) 링크만 먼저 확인 (파일 다운로드 없음)
python scripts/run.py --dry-run --lookback-years 3 --max-documents 5

# 4) 실제 수집
python scripts/run.py --lookback-years 3

# 5) 테스트
pytest -q
```

### 옵션

```bash
python scripts/run.py --lookback-years 3
python scripts/run.py --lookback-years 1 --max-documents 2
python scripts/run.py --lookback-years 3 --force
```

- `--lookback-years`: 게시일 기준 최근 몇 년의 목록을 확인할지 지정합니다. 기본 3년입니다.
- `--max-documents`: 시험 실행 시 상세 게시물 수를 제한합니다.
- `--force`: DB에 이미 저장된 첨부파일도 다시 내려받아 재추출합니다.
- `--dry-run`: 상세 페이지와 PDF 링크만 확인합니다.

반복 실행 시 이미 다운로드되어 있고 TXT도 존재하는 첨부파일은 건너뜁니다. URL을 키로 중복을 방지합니다. 단, 사이트가 같은 URL에 파일 내용을 교체하는 경우까지 자동으로 감지하지는 않으므로 중요한 정정공시 확인 시 `--force`로 재실행할 수 있습니다.

## 4. GitHub에 올리고 정기 실행하기

1. GitHub에서 새 저장소를 만듭니다.
2. 이 폴더의 파일을 저장소 루트에 업로드하거나 `git push` 합니다.
3. 저장소의 **Settings → Actions → General → Workflow permissions**에서 `Read and write permissions`를 선택합니다. 조직 정책으로 권한을 바꿀 수 없다면 관리자에게 허용을 요청해야 합니다.
4. **Actions** 탭에서 `Collect DB Insurance management disclosures` 워크플로를 선택하고 `Run workflow`로 최초 실행합니다.
5. 실행이 성공하면 PDF·TXT·CSV·SQLite 산출물이 `data/`에 반영되어 GitHub 저장소에 커밋됩니다.

워크플로는 매월 5일 09:00(KST)에 목록을 확인합니다. DB 공시는 분기말에 즉시 올라오지 않고 1분기·상반기·3분기·연간 형태로 게시되며 정정 자료가 추가될 수도 있어, 분기 말 당일만 한 번 실행하는 대신 월 1회 확인하도록 했습니다. 원하는 일정은 `.github/workflows/collect-dbins.yml`의 cron을 바꾸면 됩니다.

GitHub Actions의 예약 실행은 GitHub 측 부하에 따라 지연될 수 있습니다. 정확한 시각 실행이 꼭 필요하면 외부 스케줄러를 사용하세요.

## 5. 디렉터리 구조

```text
.
├── .github/workflows/collect-dbins.yml
├── data/
│   ├── db/
│   ├── exports/
│   ├── processed/dbins/
│   └── raw/dbins/
├── scripts/run.py
├── src/insurance_disclosures/
│   ├── dbins.py       # DB 공시 목록/상세 페이지/PDF 링크 수집
│   ├── extract.py     # PDF 텍스트·핵심 지표 추출
│   └── storage.py     # SQLite 및 CSV/JSON 저장
├── tests/test_extract.py
└── requirements.txt
```

## 6. 5개사로 확장할 때

현재는 DB손해보험 수집기에 한정되어 있습니다. 다음 회사 추가 시에는 회사별 사이트 수집기(`meritz.py`, `samsung.py` 등)를 별도 모듈로 만들고, `Disclosure`/`Attachment` 데이터 구조와 SQLite 스키마 및 추출 결과 포맷은 공통으로 재사용하도록 확장하는 것이 좋습니다. 각 회사의 공시 URL, 상세 페이지 구조, PDF 첨부 방식이 다르므로 회사별 링크 수집 부분을 억지로 하나의 selector로 통합하지 않는 편이 유지보수에 유리합니다.

## 참고 및 유의사항

- 이 프로젝트는 공개된 공시 게시물과 첨부 PDF를 요청 간격을 두고 수집합니다. 인증 우회나 비공개 영역 접근을 하지 않습니다.
- 원본 공시의 해석과 최종 수치는 PDF를 기준으로 확인하세요. 규칙 기반 추출 결과는 검토용 보조 데이터입니다.
- 일부 PDF가 이미지 스캔본이면 PyMuPDF 텍스트 추출 결과가 비어 있을 수 있습니다. 현재 버전은 OCR을 자동 수행하지 않고 JSON에 점검 경고를 남깁니다.
- Git 저장소에 원본 PDF를 계속 커밋하면 저장소 용량이 증가합니다. 장기 운영 시 원본 PDF는 S3·Cloud Storage·사내 파일 저장소 등으로 옮기고 GitHub에는 코드와 CSV/메타데이터만 남기는 구조를 권장합니다.
