# 상위 5개 손해보험사 정기경영공시 수집기

DB손해보험, 삼성화재, KB손해보험, 메리츠화재, 현대해상의 정기경영공시 목록을 확인하고 신규 PDF를 수집해 원본·전체 텍스트·기본 경영지표를 공통 데이터베이스와 CSV로 정리하는 Python 프로젝트입니다. GitHub Actions에서 매월 자동 실행하도록 구성했습니다.

## 1. 수집 대상 회사와 공식 출처

| 회사 | 정기경영공시 목록 | 수집 방식 |
|---|---|---|
| DB손해보험 | <https://www.idbins.com/pc/bizxpress/contentTemplet/pb/mp/rg/list.jsp> | requests + HTML 상세 페이지 |
| 삼성화재 | <https://www.samsungfire.com/v2/html/publication/02/J_020_010_001.html> | Chromium 브라우저 렌더링 + PDF 다운로드 |
| KB손해보험 | <https://www.kbinsure.co.kr/CG801010001.ec> | Chromium 브라우저 렌더링 + 표 행 클릭/첨부 수집 |
| 메리츠화재 | <https://www.meritzfire.com/disclosure/managerial-announcement/periodic.do#!/> | Chromium 브라우저 렌더링 + SPA 링크/다운로드 탐색 |
| 현대해상 | <https://www.hi.co.kr/serviceAction.do?menuId=100999> | Chromium 브라우저 렌더링 + 정기경영공시 목록/상세 탐색 |

현대해상에서 사용자가 전달한 `serviceAction.do`는 공통 진입 URL입니다. 실제 정기경영공시 목록은 공식 사이트 검색 결과에서 확인되는 `menuId=100999` 주소를 사용합니다. 삼성화재는 공시 페이지에서 FY별 1분기·2분기·3분기·결산 PDF 다운로드 항목이 노출되고, KB손해보험은 정기공시 표에 `-2/4분기 경영통일공시` 등의 항목이 표시됩니다.

메리츠화재 페이지와 현대해상 목록은 JavaScript 기반 렌더링이 포함되어 있어 GitHub Actions에서 Chromium을 실행합니다. 회사 사이트의 프런트엔드나 다운로드 방식이 바뀌면 `data/exports/collection_status.csv`에서 해당 회사 상태를 먼저 확인하고 `src/insurance_disclosures/company_sources.py`를 점검하세요.

## 2. 보고기간 표준화

다섯 회사의 표현이 달라도 동일한 기준일 자료끼리 비교할 수 있도록 공시기간을 다음처럼 표준화합니다.

| 원문 표기 예시 | 저장 period_kind | 비교 기준 |
|---|---|---|
| 1분기, 1/4분기 | `Q1` | 3월 말 |
| 2분기, 2/4분기, 상반기 | `H1` | 6월 말 |
| 3분기, 3/4분기 | `Q3` | 9월 말 |
| 4분기, 결산, 연간 | `ANNUAL` | 12월 말 |

즉 회사별로 `2분기` 또는 `2/4분기`라고 표시한 정기경영공시는 비교용으로 `H1`에 통합합니다. 1·3분기는 간단한 확인, 상반기·연간 자료는 상세 비교에 활용하도록 만들어진 기본 분류입니다. 실제 공시의 기준일과 포함 기간은 PDF 본문에서도 확인해야 합니다.

## 3. 저장 결과

| 경로 | 내용 |
|---|---|
| `data/raw/{회사코드}/` | 회사별 원본 PDF |
| `data/processed/{회사코드}/` | PDF 전체 페이지 텍스트 TXT 및 문서별 JSON |
| `data/exports/documents.csv` | 회사별 공시 게시물 및 기준기간 |
| `data/exports/attachments.csv` | PDF 첨부파일, URL, 해시, 페이지 수 |
| `data/exports/metrics.csv` | 규칙 기반으로 추출한 핵심 경영지표 |
| `data/exports/collection_status.csv` | 회사별 수집 성공/부분 성공/목록 미발견 상태 |
| `data/db/disclosures.sqlite3` | 공시·첨부파일·지표 통합 SQLite |

`documents.csv`, `attachments.csv`, `metrics.csv`에는 `company`와 `period_label`을 포함하므로 같은 보고기간 기준의 회사별 비교표를 만들 수 있습니다.

## 4. 로컬 실행

Python 3.11을 권장합니다.

```bash
# 1) 가상환경
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 2) Python 패키지 설치
python -m pip install -r requirements.txt

# 3) Chromium 설치 (삼성/KB/메리츠/현대 페이지 수집에 필요)
python -m playwright install chromium

# 4) 먼저 링크·목록 탐색만 시험
python scripts/run.py --dry-run --lookback-years 3 --max-documents 3

# 5) 5개 회사 실제 수집
python scripts/run.py --lookback-years 3

# 6) 테스트
pytest -q
```

특정 회사만 시험하려면:

```bash
python scripts/run.py --companies samsung,kb --dry-run --max-documents 2
python scripts/run.py --companies meritz,hyundai --dry-run --max-documents 2
python scripts/run.py --companies dbins --lookback-years 3
```

주요 옵션:

- `--companies`: `dbins,samsung,kb,meritz,hyundai` 중 실행할 회사 코드. 기본은 전체.
- `--lookback-years`: 공시 게시일 기준 최근 몇 년의 목록을 확인할지 지정. 기본 3년.
- `--max-documents`: 회사별 시험 수집 공시 건수 제한.
- `--force`: 이미 받은 PDF도 다시 다운로드/추출.
- `--dry-run`: 목록·첨부 링크 탐색만 하고 Git 저장 데이터는 변경하지 않음. 일부 JS 다운로드 항목은 내부 확인을 위해 임시 다운로드를 시도할 수 있습니다.

## 5. GitHub Actions 자동 실행

워크플로 파일은 `.github/workflows/collect-all-insurers.yml`입니다.

- 자동 실행: 매월 5일 오전 9시(한국 시간)
- 수동 실행: GitHub 저장소의 **Actions → Collect insurance management disclosures → Run workflow**
- 기본 수집 대상: 5개 회사 전체
- 기본 조회 기간: 최근 3년
- 수동 실행 기본값은 `dry_run=true`, 회사별 최대 3건으로 되어 있어 우선 목록/PDF 링크를 시험합니다. 수집 결과가 정상인지 Actions 로그에서 확인한 뒤 `dry_run=false`, `max_documents` 빈칸으로 다시 실행하면 실제 PDF를 저장합니다.

GitHub 저장소의 **Settings → Actions → General → Workflow permissions**에서 `Read and write permissions`를 허용해야 수집 결과를 저장소에 커밋할 수 있습니다.

## 6. 중요 검증 사항

1. 사이트 개편, 다운로드 버튼 변경, 브라우저 차단 등으로 특정 회사의 목록/PDF 탐색이 실패할 수 있습니다. 전체 실행이 끝나면 반드시 `collection_status.csv`와 Actions 로그에서 다섯 회사 모두 수집됐는지 확인하세요.
2. 회사별로 같은 보고기간의 PDF가 여러 파일로 나뉠 수 있습니다. 해당 공시의 첨부파일 전체가 저장됐는지 `attachments.csv`를 확인하세요.
3. 모든 PDF는 원본과 텍스트 추출본을 함께 보관합니다. 텍스트가 거의 없는 페이지는 OCR이 필요한 스캔본일 수 있습니다. 현재 버전은 OCR을 자동 수행하지 않습니다.
4. `metrics.csv`의 KPI 규칙은 최초 DB손해보험 공시 형식에 맞춰 작성되어 있습니다. 다른 4개 회사에도 적용되지만, 회사별 PDF 표기·표 구성 차이를 검증하기 전에는 비교 분석의 확정 수치로 사용하지 마세요. 원본 PDF와 TXT를 대조한 뒤 회사별 추출 규칙을 보완해야 합니다.
5. 비교 목적이라면 회사명, `period_label`, 실제 기준일, 단위, 별도/연결 여부를 반드시 맞춰야 합니다. 특히 경과조치 전후 K-ICS 등은 서로 같은 기준의 수치인지 확인해야 합니다.
6. Git 저장소에 PDF 원본을 계속 커밋하면 저장소가 커집니다. 장기 운영 시 원본은 별도 파일 저장소에 두고 GitHub에는 코드·CSV·메타데이터만 보관하는 구조를 권장합니다.

## 7. 주요 코드

```text
.
├── .github/workflows/collect-all-insurers.yml
├── data/
├── scripts/run.py
├── src/insurance_disclosures/
│   ├── dbins.py             # DB손해보험 HTML 수집기 및 공통 기간 분류
│   ├── company_sources.py   # 삼성/KB/메리츠/현대 브라우저 수집기
│   ├── extract.py           # PDF 텍스트·핵심 지표 추출
│   └── storage.py           # SQLite 및 CSV/JSON 저장
├── tests/test_extract.py
└── requirements.txt
```
