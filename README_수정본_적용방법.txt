경영공시 수집기 수정 파일 묶음

이 ZIP은 전체 프로그램을 새로 설치하는 파일이 아니라, 기존 GitHub 저장소에서 아래 2개 파일을 교체하는 업데이트 묶음입니다.

1) .github/workflows/collect-all-insurers.yml
   -> ZIP 안의 같은 경로 파일로 교체
2) src/insurance_disclosures/company_sources.py
   -> ZIP 안의 같은 경로 파일로 교체

src/insurance_disclosures/storage.py는 기존 파일과 동일한 저장 로직 참고본이며, 교체하지 않아도 됩니다.

중요:
- data/ 폴더 및 기존 PDF/CSV/JSON/SQLite 파일은 삭제하거나 덮어쓰지 마세요.
- 첫 실행은 DB손해보험(dbins), KB손해보험(kb)만 대상으로 합니다.
- 기본값은 최근 1년, 회사별 최대 2건, dry_run=false(실제 다운로드)입니다.
- 삼성화재·메리츠화재·현대해상은 로그에서 목록/링크 오인 문제가 확인되어 첫 테스트에서 제외했습니다.
- 현대해상은 일반 입찰 공고가 공시로 잡히지 않도록 후보 필터를 강화했고, 메리츠화재는 Adobe Reader 주소 및 PDF가 아닌 응답을 제외하도록 했습니다.
- 삼성화재의 공시 목록 탐색은 아직 별도 수정·검증이 필요합니다.
- 이 수정본은 Python 문법 검사까지만 수행했습니다. GitHub Actions에서 실제 사이트 다운로드가 성공하는지 아직 실행 검증하지 않았습니다.

GitHub 웹사이트에서 적용:
1. 저장소의 .github/workflows 폴더를 엽니다.
2. collect-all-insurers.yml 파일을 열고 연필(Edit) 아이콘 옆 메뉴에서 Delete file로 지우지 말고, ZIP에서 해당 파일 내용을 복사해 전체 교체한 뒤 Commit changes를 누릅니다.
3. src/insurance_disclosures/company_sources.py도 같은 방식으로 전체 내용을 교체합니다.
4. ZIP의 파일을 하나씩 업로드하는 대신, GitHub 웹 편집기에서 위 두 파일만 교체하면 됩니다.
5. Actions 탭에서 Collect insurance management disclosures를 선택하고 Run workflow를 누릅니다. 기본값은 DB손해보험·KB손해보험, 1년, 회사별 2건, 실제 저장 모드입니다.

기존 data/ 자료를 포함하지 않는 이유는 이전 PDF와 누적 데이터가 실수로 삭제되는 것을 방지하기 위해서입니다.
