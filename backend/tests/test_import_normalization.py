from datetime import date
from decimal import Decimal

from app.imports.adapters import StandardJobRow
from app.imports.normalization import (
    normalize_city,
    normalize_date,
    normalize_education,
    normalize_experience,
    normalize_row,
    normalize_salary,
)


def test_salary_normalization_supports_k_wan_daily_and_salary_months() -> None:
    assert normalize_salary("8-16k")[:2] == (8000, 16000)
    assert normalize_salary("1.5-3万")[:2] == (15000, 30000)
    assert normalize_salary("5000-10000元")[:2] == (5000, 10000)

    daily_min, daily_max, _, warnings = normalize_salary("100-150元/天")
    assert (daily_min, daily_max) == (2175, 3263)
    assert "salary_period_converted" in warnings

    monthly_min, monthly_max, salary_months, _ = normalize_salary("25-40k·15薪")
    assert (monthly_min, monthly_max, salary_months) == (25000, 40000, Decimal("15"))


def test_relative_date_normalization_uses_collection_anchor() -> None:
    anchor = date(2026, 8, 6)

    assert normalize_date("今日更新", anchor)[0] == anchor
    assert normalize_date("90天前更新", anchor)[0] == date(2026, 5, 8)
    assert normalize_date("7月28日更新", anchor)[0] == date(2026, 7, 28)


def test_experience_and_education_normalization() -> None:
    assert normalize_experience("应届生")[:2] == (0, 0)
    assert normalize_experience("1-3年")[:2] == (12, 36)
    assert normalize_experience("3年以上")[:2] == (36, None)
    assert normalize_education("本科") == "bachelor"
    assert normalize_education("硕士") == "master"
    assert normalize_education("学历不限") == "unknown"


def test_city_normalization_prefers_work_area_and_marks_conflicts() -> None:
    same = normalize_city("广州天河", "Guangzhou")
    conflict = normalize_city("深圳南山", "Guangzhou")

    assert same.city_name == "广州"
    assert same.city_code == "CN-GZ"
    assert conflict.city_name == "深圳"
    assert "city_conflict" in conflict.warnings


def test_normalize_row_cleans_text_and_calculates_quality_flags() -> None:
    row = StandardJobRow(
        row_number=2,
        source_code="liepin",
        external_id=None,
        source_url="https://example.test/1",
        job_name="  AI\x00 Engineer  ",
        company_name=None,
        salary_text="100-150元/天",
        work_area_text="深圳南山",
        city_text="Guangzhou",
        education_text="本科",
        work_year_text="1-3年",
        issue_date_text="今日更新",
        raw_text="Python\ufffd",
        source_tags=["Python"],
        raw_payload={"job_name": "  AI\x00 Engineer  "},
        parse_warnings=["missing_company_name"],
    )

    result = normalize_row(row, date(2026, 8, 6))

    assert result.normalized_title == "AI Engineer"
    assert result.education_level == "bachelor"
    assert result.city_name == "深圳"
    assert result.quality_score == Decimal("60")
    assert {
        "missing_company_name",
        "salary_period_converted",
        "city_conflict",
        "garbled_text",
    } <= set(result.quality_flags)
