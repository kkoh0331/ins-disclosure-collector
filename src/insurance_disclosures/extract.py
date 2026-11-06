from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

# Supports normal values, comma grouping, decimals, a dash for missing values,
# and DB's printed negative style such as "(-)1,785".
NUMBER = r"(?:\(-\)\s*)?(?:\d[\d,]*(?:\.\d+)?|[-–—])"

METRIC_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("assets", r"자\s*산", "자산", "억원"),
    ("liabilities", r"부\s*채", "부채", "억원"),
    ("equity", r"자\s*본", "자본", "억원"),
    ("net_income", r"당기순이익", "당기순이익", "억원"),
    ("solvency_before", r"지급여력비율\s*\(\s*경과조치\s*전\s*\)", "지급여력비율(경과조치 전)", "%"),
    ("solvency_after", r"지급여력비율\s*\(\s*경과조치\s*후\s*\)", "지급여력비율(경과조치 후)", "%"),
    ("investment_yield", r"운용자산이익률\s*\(\s*A/B\s*\)", "운용자산이익률(A/B)", "%"),
    ("operating_margin", r"영업이익률", "영업이익률", "%"),
    ("roa", r"총자산수익률\s*\(\s*ROA\s*\)", "총자산수익률(ROA)", "%"),
    ("roe", r"자기자본수익률\s*\(\s*ROE\s*\)", "자기자본수익률(ROE)", "%"),
)

EFFICIENCY_ROWS: tuple[tuple[str, str, str], ...] = (
    ("new_business_rate", r"신계약률", "신계약률"),
    ("lapse_surrender_rate", r"효력상실\s*및\s*해약률", "효력상실 및 해약률"),
    ("claim_payment_rate", r"보험금지급률\s*\(\s*환급금\s*포함\s*\)", "보험금지급률(환급금 포함)"),
    ("asset_management_rate", r"자산운용률", "자산운용률"),
)


def _to_number(token: str) -> float | int | None:
    value = token.strip().replace(",", "").replace(" ", "")
    if value in {"-", "–", "—", ""}:
        return None
    negative = value.startswith("(-)")
    value = value.replace("(-)", "")
    number = float(value)
    if negative:
        number *= -1
    return int(number) if number.is_integer() else number


def _extract_three_values(text: str, label_pattern: str) -> list[float | int | None] | None:
    match = re.search(
        rf"(?:{label_pattern})\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return [_to_number(match.group(i)) for i in range(1, 4)]


def extract_pdf_text(pdf_path: Path) -> tuple[str, int, int]:
    """Extract text from every page. Returns (text, page_count, empty_page_count)."""
    pages: list[str] = []
    empty_pages = 0
    with fitz.open(pdf_path) as pdf:
        page_count = pdf.page_count
        for page_number, page in enumerate(pdf, start=1):
            page_text = page.get_text("text", sort=True).strip()
            if len(page_text) < 15:
                empty_pages += 1
            pages.append(f"\n\n===== PAGE {page_number} =====\n\n{page_text}")
    return "".join(pages).strip(), page_count, empty_pages


def extract_summary_metrics(full_text: str) -> list[dict[str, Any]]:
    """Extract repeatable KPIs from DB's '주요 경영현황 요약' tables.

    Values are taken from the first numeric column (current period), second
    column (prior-year comparison), and third column (reported change).
    It deliberately returns only rows with a successful three-value match.
    """
    normalized = re.sub(r"\s+", " ", full_text)
    start_match = re.search(r"1\s*[-.]\s*1\.?\s*주요\s*경영지표", normalized)
    end_match = re.search(r"1\s*[-.]\s*2\.?\s*주요\s*경영효율\s*지표", normalized)
    if not start_match:
        # A few older forms may omit numbering punctuation.
        start_match = re.search(r"주요\s*경영지표", normalized)
    if start_match:
        end = end_match.start() if end_match and end_match.start() > start_match.start() else start_match.start() + 6000
        indicators_text = normalized[start_match.start() : end]
    else:
        indicators_text = normalized[:6000]

    metrics: list[dict[str, Any]] = []
    for key, pattern, label, unit in METRIC_ROWS:
        values = _extract_three_values(indicators_text, pattern)
        if values is None:
            continue
        metrics.append(
            {
                "section": "주요 경영지표",
                "metric_key": key,
                "metric_name": label,
                "value": values[0],
                "prior_value": values[1],
                "change": values[2],
                "unit": unit,
            }
        )

    eff_start = re.search(r"1\s*[-.]\s*2\.?\s*주요\s*경영효율\s*지표", normalized)
    eff_end = re.search(r"2\s*[-.]\s*1\.?\s*요약\s*포괄손익계산서", normalized)
    if eff_start:
        end = eff_end.start() if eff_end and eff_end.start() > eff_start.start() else eff_start.start() + 5000
        efficiency_text = normalized[eff_start.start() : end]
        for key, pattern, label in EFFICIENCY_ROWS:
            values = _extract_three_values(efficiency_text, pattern)
            if values is not None:
                metrics.append(
                    {
                        "section": "주요 경영효율 지표",
                        "metric_key": key,
                        "metric_name": label,
                        "value": values[0],
                        "prior_value": values[1],
                        "change": values[2],
                        "unit": "%",
                    }
                )

    # Retention rates are presented as one row per policy anniversary.
    if eff_start:
        end = eff_end.start() if eff_end and eff_end.start() > eff_start.start() else eff_start.start() + 5000
        efficiency_text = normalized[eff_start.start() : end]
        for anniversary in (13, 25, 37, 49, 61, 73, 85):
            values = _extract_three_values(efficiency_text, rf"{anniversary}\s*회차")
            if values is not None:
                metrics.append(
                    {
                        "section": "유지율",
                        "metric_key": f"retention_{anniversary}m",
                        "metric_name": f"{anniversary}회차 유지율",
                        "value": values[0],
                        "prior_value": values[1],
                        "change": values[2],
                        "unit": "%",
                    }
                )

    return metrics


def build_extraction_record(
    pdf_path: Path,
    text_path: Path,
    page_count: int,
    empty_pages: int,
    metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source_pdf": str(pdf_path),
        "extracted_text": str(text_path),
        "page_count": page_count,
        "pages_with_little_or_no_text": empty_pages,
        "text_extraction_warning": (
            "일부 페이지의 텍스트가 거의 없습니다. 스캔 이미지 PDF일 수 있어 OCR 검토가 필요합니다."
            if empty_pages
            else None
        ),
        "metrics": metrics,
    }
