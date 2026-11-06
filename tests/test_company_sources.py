from insurance_disclosures.company_sources import _period_fields, _year_from


def test_company_period_label_normalization():
    assert _period_fields("FY 26 2분기 PDF 다운로드", "FY 26 2분기")[0:3] == (
        2026, "H1", "2026_H1"
    )
    assert _period_fields("-2/4분기 경영통일공시", "FY 2026년 2026-08-31")[0:3] == (
        2026, "H1", "2026_H1"
    )
    assert _period_fields("2026년 3분기 정기경영공시", "2026.11.30")[0:3] == (
        2026, "Q3", "2026_Q3"
    )
    assert _period_fields("2025년 결산 경영통일공시", "2026.03.31")[0:3] == (
        2025, "ANNUAL", "2025_ANNUAL"
    )


def test_period_year_can_come_from_post_date():
    assert _year_from("제17기 2분기 경영공시", "2026-08-31") == 2026
