from io import BytesIO

import pytest
from docx import Document

from app.core.errors import APIError
from app.recruitment.parsing import (
    MAX_JD_FILE_BYTES,
    detect_jd_document,
    extract_jd_text,
    validate_jd_evidence,
)
from app.recruitment.schemas import RecruitmentJDParseResponse
from app.resumes.parsing import DOCX_MEDIA_TYPE
from tests.test_recruitment_schemas import VALID_JD_PARSE


def make_docx_bytes(text: str = "负责 Python 开发") -> bytes:
    output = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(output)
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "media_type", "content", "expected"),
    [
        ("jd.pdf", "application/pdf", b"%PDF-1.7", "pdf"),
        ("jd.docx", DOCX_MEDIA_TYPE, make_docx_bytes(), "docx"),
        ("jd.txt", "text/plain", "岗位职责".encode(), "txt"),
    ],
)
def test_detect_jd_document_supports_three_formats(
    filename,
    media_type,
    content,
    expected,
) -> None:
    assert detect_jd_document(filename, media_type, content) == expected


@pytest.mark.parametrize(
    ("filename", "media_type", "content", "code"),
    [
        ("jd.png", "image/png", b"png", "RECRUITMENT_JD_INPUT_INVALID"),
        ("jd.pdf", "application/pdf", b"not-pdf", "RECRUITMENT_JD_INPUT_INVALID"),
        (
            "jd.txt",
            "text/plain",
            b"x" * (MAX_JD_FILE_BYTES + 1),
            "RECRUITMENT_JD_TOO_LARGE",
        ),
    ],
)
def test_detect_jd_document_rejects_invalid_inputs(
    filename,
    media_type,
    content,
    code,
) -> None:
    with pytest.raises(APIError) as error:
        detect_jd_document(filename, media_type, content)

    assert error.value.code == code


async def test_extract_jd_text_normalizes_txt(tmp_path) -> None:
    path = tmp_path / "jd.txt"
    path.write_bytes("  岗位职责\r\n\r\n 熟练掌握 Python  ".encode())

    result = await extract_jd_text(path, "txt")

    assert result.text == "岗位职责\n\n熟练掌握 Python"
    assert result.method == "txt"


async def test_extract_jd_text_reuses_docx_parser(tmp_path) -> None:
    path = tmp_path / "jd.docx"
    path.write_bytes(make_docx_bytes("负责 Python 开发"))

    result = await extract_jd_text(path, "docx")

    assert result.text == "负责 Python 开发"
    assert result.method == "docx"


def test_validate_jd_evidence_drops_unanchored_items() -> None:
    payload = RecruitmentJDParseResponse.model_validate(VALID_JD_PARSE)
    text = "负责基于 RAG 的企业知识库应用开发。熟练掌握 Python。"

    result = validate_jd_evidence(payload, source_text=text)

    assert [item["text"] for item in result.responsibilities] == ["负责 RAG 应用开发"]
    assert [item["name"] for item in result.skills] == ["Python"]
    assert result.skills[0]["evidence_start"] == text.index("熟练掌握 Python")
    assert result.warnings == []

    missing = RecruitmentJDParseResponse.model_validate(
        {
            **VALID_JD_PARSE,
            "skills": [
                {
                    **VALID_JD_PARSE["skills"][0],
                    "name": "Rust",
                    "evidence_quote": "熟练掌握 Rust",
                }
            ],
        }
    )
    partial = validate_jd_evidence(missing, source_text=text)
    assert partial.skills == []
    assert partial.warnings == ["SKILL_EVIDENCE_NOT_FOUND:Rust"]


def test_validate_jd_evidence_requires_at_least_one_grounded_item() -> None:
    payload = RecruitmentJDParseResponse.model_validate(VALID_JD_PARSE)

    with pytest.raises(APIError) as error:
        validate_jd_evidence(payload, source_text="无关正文")

    assert error.value.code == "RECRUITMENT_JD_EVIDENCE_EMPTY"
