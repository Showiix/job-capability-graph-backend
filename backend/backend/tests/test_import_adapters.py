import pytest

from app.imports.adapters import (
    AdapterError,
    ZhilianV1Adapter,
    detect_adapter,
    detect_encoding,
)

HEADERS = (
    "job_name\tcompany_name\tsalary\twork_area\tcity\teducation\twork_year\t"
    "issue_date\tsource\tskill_requirements\ttech_tags\tjob_url"
)


def test_detect_adapter_for_supported_sources() -> None:
    headers = HEADERS.split("\t")

    assert detect_adapter(headers, "standard").code == "standard_v1"
    assert detect_adapter(headers, "liepin").code == "liepin_v1"
    assert detect_adapter(headers, "zhilian").code == "zhilian_v1"
    assert detect_adapter(headers, "zhilian_direct").code == "zhilian_v1"


def test_liepin_adapter_preserves_raw_fields_and_splits_tags() -> None:
    adapter = detect_adapter(HEADERS.split("\t"), "liepin")
    rows = list(
        adapter.iter_rows(
            "\n".join(
                [
                    HEADERS,
                    "AI Engineer\tExample\t8-16k\t天河\t广州\t本科\t1-3年\t"
                    "今日更新\tliepin\tPython\tPython,机器学习\thttps://example.test/1",
                ]
            ),
            source_code="liepin",
        )
    )

    assert rows[0].salary_text == "8-16k"
    assert rows[0].source_url == "https://example.test/1"
    assert rows[0].source_tags == ["Python", "机器学习"]
    assert rows[0].raw_payload["salary"] == "8-16k"
    assert rows[0].parse_warnings == []


def test_zhilian_direct_uses_zhilian_adapter_and_keeps_source_value() -> None:
    adapter = detect_adapter(HEADERS.split("\t"), "zhilian_direct")
    rows = list(
        adapter.iter_rows(
            "\n".join(
                [
                    HEADERS,
                    "Data Engineer\tExample\t1.5-3万\t南山\tGuangzhou\t硕士\t"
                    "3年以上\t\tzhilian_direct\t\t\t",
                ]
            ),
            source_code="zhilian_direct",
        )
    )

    assert isinstance(adapter, ZhilianV1Adapter)
    assert rows[0].source_code == "zhilian_direct"
    assert "missing_issue_date" in rows[0].parse_warnings
    assert rows[0].source_tags == []


def test_missing_job_name_is_marked_rejected() -> None:
    adapter = detect_adapter(HEADERS.split("\t"), "standard")
    rows = list(
        adapter.iter_rows(
            "\n".join([HEADERS, "\tExample\t8-16k\t\t\t\t\t\tstandard\t\t\t"]),
            source_code="standard",
        )
    )

    assert rows[0].is_rejected
    assert "missing_job_name" in rows[0].parse_warnings


def test_unknown_header_is_retained_and_missing_optional_header_warns() -> None:
    adapter = detect_adapter(["job_name", "source", "new_column"], "standard")
    rows = list(
        adapter.iter_rows(
            "job_name\tsource\tnew_column\nAI Engineer\tstandard\tvalue\n",
            source_code="standard",
        )
    )

    assert rows[0].raw_payload["new_column"] == "value"
    assert "missing_company_name" in rows[0].parse_warnings


def test_encoding_detection_prefers_utf8_then_gb18030() -> None:
    text = "岗位名称\t公司\n算法工程师\t示例\n"

    encoding, decoded = detect_encoding(text.encode("gb18030"))

    assert encoding == "gb18030"
    assert decoded == text


def test_unknown_source_or_schema_has_stable_error_code() -> None:
    with pytest.raises(AdapterError) as error:
        detect_adapter(["job_name"], "unknown")

    assert error.value.code == "SOURCE_ADAPTER_MISMATCH"
