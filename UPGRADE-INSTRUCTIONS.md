# 기존 GitHub 저장소 업데이트 안내

이 ZIP은 5개 손해보험사 수집 기능으로 바꾸기 위한 코드 파일만 담고 있습니다. 기존에 내려받은 DB손해보험 PDF와 SQLite 데이터는 포함하지 않습니다.

## 교체/추가할 파일

ZIP 내부 경로 그대로 기존 저장소에 업로드하거나 기존 파일과 교체하세요.

- `README.md` 교체
- `requirements.txt` 교체 (Playwright 추가)
- `scripts/run.py` 교체
- `src/insurance_disclosures/dbins.py` 교체
- `src/insurance_disclosures/company_sources.py` 새 파일 추가
- `tests/test_extract.py` 교체
- `tests/test_company_sources.py` 새 파일 추가
- `.github/workflows/collect-all-insurers.yml` 새 파일 추가
- `docs/company-source-notes.md` 새 파일 추가

## 반드시 할 일

기존 `.github/workflows/collect-dbins.yml` 파일은 GitHub에서 삭제하세요. 삭제하지 않으면 기존 DB손해보험 전용 일정과 새 5개사 일정이 중복 실행될 수 있습니다.

## 보존할 폴더

기존 `data/` 폴더는 삭제하거나 덮어쓰지 마세요. 최근 3개년 DB손해보험 PDF, TXT, CSV, SQLite 데이터가 여기에 저장되어 있습니다. 새 수집기는 같은 DB를 이어 사용합니다.

## 첫 실행 권장값

GitHub 저장소의 Actions에서 `Collect insurance management disclosures`를 선택해 `Run workflow`를 누릅니다. 기본값은 다음과 같습니다.

- `dry_run`: true
- `max_documents`: 3
- `companies`: dbins,samsung,kb,meritz,hyundai

이 상태로 실행하면 목록과 다운로드 동작을 시험합니다. 로그에서 각 회사의 공시/PDF 링크가 정상 확인된 뒤 `dry_run=false`, `max_documents` 빈칸으로 다시 실행해 실제 파일을 저장합니다.
