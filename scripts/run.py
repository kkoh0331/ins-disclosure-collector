from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from insurance_disclosures.dbins import (  # noqa: E402
    discover_attachments,
    discover_disclosures,
    download_pdf,
    make_session,
)
from insurance_disclosures.company_sources import (  # noqa: E402
    COMPANY_SOURCES,
    discover_company_documents,
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

ALL_COMPANIES = ["dbins", "samsung", "kb", "meritz", "hyundai"]


def safe_segment(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", value).strip("_")
    return value[:100] or "unknown"


def save_local_pdf(source: Path, destination: Path) -> tuple[str, int]:
    """Copy a Playwright-captured file and verify it is really a PDF."""
    if not source.exists():
        raise FileNotFoundError(f"브라우저 다운로드 임시파일이 없습니다: {source}")
    with source.open("rb") as handle:
        header = handle.read(8)
    if not header.startswith(b"%PDF-"):
        raise ValueError(f"다운로드 결과가 PDF가 아닙니다: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    digest = hashlib.sha256()
    total = 0
    with destination.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 128), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="5개 손해보험사 정기경영공시 PDF 수집 및 텍스트/KPI 추출"
    )
    parser.add_argument(
        "--lookback-years", type=int, default=3,
        help="공시 목록에서 훑을 최근 연수 (기본: 3년)",
    )
    parser.add_argument(
        "--companies", default=",".join(ALL_COMPANIES),
        help="수집 회사 목록: dbins,samsung,kb,meritz,hyundai (기본: 전체)",
    )
    parser.add_argument(
        "--max-documents", type=int, default=None,
        help="회사별 테스트용 공시 최대 개수 제한",
    )
    parser.add_argument("--force", action="store_true", help="기존 PDF도 다시 다운로드/추출")
    parser.add_argument("--dry-run", action="store_true", help="공시/PDF 링크만 확인하고 저장하지 않음")
    parser.add_argument("--sleep", type=float, default=0.5, help="공시 사이 요청 간격(초)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("insurance-disclosure-collector")

    selected = [part.strip().lower() for part in args.companies.split(",") if part.strip()]
    invalid = sorted(set(selected) - set(ALL_COMPANIES))
    if invalid:
        log.error("알 수 없는 회사 코드: %s (가능: %s)", ",".join(invalid), ",".join(ALL_COMPANIES))
        return 2

    data_dir = ROOT / "data"
    conn = connect(data_dir / "db" / "disclosures.sqlite3")
    session = make_session()
    source_status: list[dict[str, object]] = []
    total_documents = 0
    total_downloaded = 0
    total_skipped = 0
    total_failures = 0

    try:
        for slug in selected:
            company_name = "DB손해보험" if slug == "dbins" else COMPANY_SOURCES[slug].company
            log.info("========== %s 수집 시작 =========", company_name)
            company_documents = 0
            company_downloaded = 0
            company_skipped = 0
            company_failures = 0
            collection_error = ""

            try:
                if slug == "dbins":
                    documents = [(item, None) for item in discover_disclosures(
                        session,
                        lookback_years=args.lookback_years,
                        max_documents=args.max_documents,
                        logger=log,
                    )]
                else:
                    documents = discover_company_documents(
                        slug,
                        lookback_years=args.lookback_years,
                        max_documents=args.max_documents,
                        logger=log,
                    )
                company_documents = len(documents)
                total_documents += company_documents

                for index, (disclosure, known_attachments) in enumerate(documents, start=1):
                    log.info("[%s %d/%d] %s", company_name, index, len(documents), disclosure.title)
                    try:
                        attachments = known_attachments
                        if attachments is None:
                            attachments = discover_attachments(session, disclosure, logger=log)
                        if args.dry_run:
                            for item in attachments:
                                log.info("  - %s | %s", item.filename, item.url)
                            continue

                        document_id = upsert_document(conn, disclosure)
                        period_folder = safe_segment(disclosure.period_label)
                        title_folder = f"doc_{document_id}_{safe_segment(disclosure.title)}"

                        for attachment in attachments:
                            existing = get_attachment_by_url(conn, attachment.url)
                            if (
                                not args.force and existing
                                and Path(existing["local_path"]).exists()
                                and existing["text_path"]
                                and Path(existing["text_path"]).exists()
                            ):
                                company_skipped += 1
                                total_skipped += 1
                                log.info("  기존 파일 유지: %s", attachment.filename)
                                continue

                            pdf_path = (
                                data_dir / "raw" / slug / period_folder / title_folder
                                / safe_segment(attachment.filename)
                            )
                            if pdf_path.suffix.lower() != ".pdf":
                                pdf_path = pdf_path.with_suffix(".pdf")
                            text_path = (
                                data_dir / "processed" / slug / period_folder / title_folder
                                / f"{pdf_path.stem}.txt"
                            )
                            try:
                                if attachment.local_path:
                                    sha256, byte_count = save_local_pdf(attachment.local_path, pdf_path)
                                else:
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
                                        "company_slug": slug,
                                        "title": disclosure.title,
                                        "posted_date": disclosure.posted_date,
                                        "period_year": disclosure.period_year,
                                        "period_kind": disclosure.period_kind,
                                        "period_label": disclosure.period_label,
                                        "detail_url": disclosure.detail_url,
                                        "source_pdf_url": attachment.url,
                                        "extraction": extraction_record,
                                        "metric_extraction_note": (
                                            "현재 지표 추출 규칙은 DB손해보험 공시 형식을 기준으로 작성되었습니다. "
                                            "타사 결과는 원본 PDF와 대조해 추출 규칙을 검증한 후 비교분석에 사용하세요."
                                            if slug != "dbins" else None
                                        ),
                                    },
                                )
                                company_downloaded += 1
                                total_downloaded += 1
                                log.info(
                                    "  저장 완료: %s (%s bytes, %s pages, %s metrics)",
                                    attachment.filename, byte_count, page_count, len(metrics),
                                )
                                if empty_pages:
                                    log.warning("  텍스트 추출 주의: 텍스트가 적은 페이지 %d개(OCR 검토)", empty_pages)
                            except Exception as exc:
                                company_failures += 1
                                total_failures += 1
                                log.exception("  PDF 처리 실패: %s (%s)", attachment.url, exc)
                            time.sleep(0.2)
                    except Exception as exc:
                        company_failures += 1
                        total_failures += 1
                        log.exception("공시 항목 처리 실패: %s (%s)", disclosure.title, exc)
                    time.sleep(max(0, args.sleep))
            except Exception as exc:
                collection_error = str(exc)
                company_failures += 1
                total_failures += 1
                log.exception("%s 수집 실패", company_name)

            status = "ok" if company_documents and not company_failures else (
                "partial" if company_documents else "no_documents_or_error"
            )
            source_status.append({
                "company_slug": slug,
                "company": company_name,
                "status": status,
                "documents_found": company_documents,
                "pdf_downloaded": company_downloaded,
                "pdf_skipped": company_skipped,
                "failures": company_failures,
                "error": collection_error,
            })
            log.info(
                "%s 결과: 공시 %d건 / 신규 PDF %d건 / 기존 유지 %d건 / 실패 %d건",
                company_name, company_documents, company_downloaded, company_skipped, company_failures,
            )

        if not args.dry_run:
            export_csv(conn, data_dir / "exports")
            status_path = data_dir / "exports" / "collection_status.csv"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            with status_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(source_status[0].keys()) if source_status else [])
                if source_status:
                    writer.writeheader()
                    writer.writerows(source_status)

        log.info(
            "전체 완료: 공시 %d건 / 신규 PDF %d건 / 기존 유지 %d건 / 실패 %d건",
            total_documents, total_downloaded, total_skipped, total_failures,
        )
        # Return success after recording per-company failures so that the
        # GitHub Actions commit step can still preserve successful companies.
        return 0
    finally:
        conn.close()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
