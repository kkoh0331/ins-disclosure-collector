from insurance_disclosures.dbins import classify_period
from insurance_disclosures.extract import extract_summary_metrics


def test_classify_period():
    assert classify_period("2026년 1분기 DB손해보험 현황(경영공시)") == (
        2026, "Q1", "2026_Q1"
    )
    assert classify_period("2026년 상반기 DB손해보험 현황(경영공시)") == (
        2026, "H1", "2026_H1"
    )
    assert classify_period("FY 26 2분기 PDF 다운로드") == (2026, "H1", "2026_H1")
    assert classify_period("-2/4분기 경영통일공시", fallback_year=2026) == (
        2026, "H1", "2026_H1"
    )
    assert classify_period("2026년 3분기 경영통일공시") == (
        2026, "Q3", "2026_Q3"
    )
    assert classify_period("2026년 결산 경영통일공시") == (
        2026, "ANNUAL", "2026_ANNUAL"
    )
    assert classify_period("2025년 DB손해보험 현황(경영통일공시)") == (
        2025, "ANNUAL", "2025_ANNUAL"
    )


def test_extract_summary_kpis_from_db_sample_text():
    sample = """
    1-1. 주요 경영지표
    (단위 : 억원, %, %p)
    구 분 해당 분기 (26.1Q) 전년 동기 (25.1Q) 증 감
    재무·손익
    자 산 592,712 554,781 37,931
    부 채 488,834 479,850 8,984
    자 본 103,878 74,931 28,947
    당기순이익 2,685 4,470 (-)1,785
    건전성
    지급여력비율 (경과조치 전) 232.10 204.66 27.44
    지급여력비율 (경과조치 후) 232.10 204.66 27.44
    수익성 비율
    운용자산이익률(A/B) 4.29 4.20 0.09
    영업이익률 7.30 9.31 (-)2.01
    총자산수익률(ROA) 1.81 3.30 (-)1.49
    자기자본수익률(ROE) 10.61 22.48 (-)11.87
    1-2. 주요 경영효율 지표
    신계약률 56.22 59.93 -3.72
    효력상실 및 해약률 3.60 3.90 -0.30
    보험금지급률 (환급금 포함) 71.98 58.11 13.87
    자산운용률 93.57 93.22 0.35
    유지율 13회차 89.96 88.00 1.96
    2-1. 요약 포괄손익계산서(총괄)
    """
    metrics = extract_summary_metrics(sample)
    by_key = {metric["metric_key"]: metric for metric in metrics}

    assert by_key["assets"]["value"] == 592712
    assert by_key["net_income"]["change"] == -1785
    assert by_key["solvency_after"]["value"] == 232.1
    assert by_key["roe"]["prior_value"] == 22.48
    assert by_key["new_business_rate"]["value"] == 56.22
    assert by_key["retention_13m"]["value"] == 89.96
