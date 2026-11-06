from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from insurance_disclosures.dbins import (  # noqa: E402
    Attachment,
    discover_attachments,
    discover_disclosures,
    download_pdf,
    make_session,
)
from insurance_disclosures.extract import (  # noqa: E402
    build_extraction_record,
    extract_pdf_text,
    extract_summary_metrics,
)
from insurance_disclosures.storage import (  # noqa: E402
    connect,
    export_csv,
    get_attachment_by_url,
    replace_metrics,
    upsert_attachment,
    upsert_document,
    write_json,
)


def safe_segment(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", value).strip("_")
    return value[:100] or "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="DB손해보험 정기경영공시 PDF 수집 및 텍스트/KPI 추출"
    )
    parser.add_argument(
        "--lookback-years", type=int, default=3,
        help="등록일 기준 최근 몇 년 자료를 훑을지 (기본: 3년)",
    )
    parser.add_argument(
        "--max-documents", type=int, default=None,
        help="테스트용 상세 페이지 최대 개수 제한",
    )
    parser.add_argument(
        "--force", action="store_true", help="기존 첨부 PDF도 다시 다운로드/추출"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="공시/첨부 링크만 확인하고 파일은 받지 않음"
    )
    parser.add_argument(
        "--sleep", type=float, default=0.4,
        help="상세 페이지 사이 요청 간격(초)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("dbins-collector")

    data_dir = ROOT / "data"
    db_path = data_dir / "db" / "disclosures.sqlite3"
    conn = connect(db_path)
    session = make_session()

    try:
        disclosures = discover_disclosures(
            session,
            lookback_years=args.lookback_years,
            max_documents=args.max_documents,
            logger=log,
        )
        downloaded = 0
        skipped = 0
        failures = 0

        for index, disclosure in enumerate(disclosures, start=1):
            log.info("[%d/%d] 상세 페이지: %s", index, len(disclosures), disclosure.title)
            try:
                attachments = discover_attachments(session, disclosure, logger=log)
                if args.dry_run:
                    for item in attachments:
                        log.info("  - %s | %s", item.filename, item.url)
                    time.sleep(max(0, args.sleep))
                    continue

                document_id = upsert_document(conn, disclosure)
                period_folder = safe_segment(disclosure.period_label)
                title_folder = f"doc_{document_id}_{safe_segment(disclosure.title)}"

                for attachment in attachments:
                    existing = get_attachment_by_url(conn, attachment.url)
                    if (
                        not args.force
                        and existing
                        and Path(existing["local_path"]).exists()
                        and existing["text_path"]
                        and Path(existing["text_path"]).exists()
                    ):
                        skipped += 1
                        log.info("  기존 파일 유지: %s", attachment.filename)
                        continue

                    pdf_path = data_dir / "raw" / "dbins" / period_folder / title_folder / safe_segment(attachment.filename)
                    # Keep the source extension even after path sanitization.
                    if pdf_path.suffix.lower() != ".pdf":
                        pdf_path = pdf_path.with_suffix(".pdf")
                    text_path = data_dir / "processed" / "dbins" / period_folder / title_folder / f"{pdf_path.stem}.txt"
                    try:
                        sha256, byte_count = download_pdf(session, attachment, pdf_path)
                        text, page_count, empty_pages = extract_pdf_text(pdf_path)
                        text_path.parent.mkdir(parents=True, exist_ok=True)
                        text_path.write_text(text, encoding="utf-8")
                        metrics = extract_summary_metrics(text)
                        attachment_id = upsert_attachment(
                            conn=conn,
                            document_id=document_id,
                            filename=attachment.filename,
                            source_url=attachment.url,
                            local_path=str(pdf_path.relative_to(ROOT)),
                            sha256=sha256,
                            byte_count=byte_count,
                            text_path=str(text_path.relative_to(ROOT)),
                            page_count=page_count,
                        )
                        replace_metrics(conn, attachment_id, metrics)

                        extraction_record = build_extraction_record(
                            pdf_path=Path(pdf_path.relative_to(ROOT)),
                            text_path=Path(text_path.relative_to(ROOT)),
                            page_count=page_count,
                            empty_pages=empty_pages,
                            metrics=metrics,
                        )
                        write_json(
                            text_path.with_suffix(".json"),
                            {
                                "company": disclosure.company,
                                "title": disclosure.title,
                                "posted_date": disclosure.posted_date,
                                "period_year": disclosure.period_year,
                                "period_kind": disclosure.period_kind,
                                "period_label": disclosure.period_label,
                                "detail_url": disclosure.detail_url,
                                "extraction": extraction_record,
                            },
                        )
                        downloaded += 1
                        log.info(
                            "  저장 완료: %s (%s bytes, %s pages, %s metrics)",
                            attachment.filename,
                            byte_count,
                            page_count,
                            len(metrics),
                        )
                        if empty_pages:
                            log.warning(
                                "  텍스트가 거의 없는 페이지 %d개: OCR 검토 필요",
                                empty_pages,
                            )
                    except Exception:
                        failures += 1
                        log.exception("  첨부파일 처리 실패: %s", attachment.url)
                    time.sleep(0.2)
            except Exception:
                failures += 1
                log.exception("공시 상세 페이지 처리 실패: %s", disclosure.detail_url)
            time.sleep(max(0, args.sleep))

        if not args.dry_run:
            export_csv(conn, data_dir / "exports")
        log.info(
            "완료: 공시 %d건 / 신규 PDF %d건 / 기존 유지 %d건 / 실패 %d건",
            len(disclosures), downloaded, skipped, failures,
        )
        return 1 if failures else 0
    finally:
        conn.close()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
