from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docx import Document

from app.core.errors import APIError
from app.resumes.analysis import analyze_resume_document
from app.resumes.llm import LLMParseResult
from app.resumes.parsing import DOCX_MEDIA_TYPE
from app.resumes.schemas import ResumeParseResponse


class CapturingResponsesClient:
    def __init__(self, payload: dict) -> None:
        self.payload = ResumeParseResponse.model_validate(payload)
        self.redacted_text = None

    async def parse_resume(self, **kwargs):
        self.redacted_text = kwargs["redacted_text"]
        return LLMParseResult(
            payload=self.payload,
            response_id="resp_analysis",
            returned_model="fake-model",
            status="completed",
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            provider_attempts=1,
            response_sha256="a" * 64,
        )


def _settings():
    return SimpleNamespace(
        llm_responses_url="https://provider.test/v1/responses",
        llm_api_key=SimpleNamespace(get_secret_value=lambda: "secret"),
        llm_model="test-model",
    )


def _write_docx(path, text: str) -> None:
    document = Document()
    document.add_paragraph(text)
    document.save(path)


async def test_analysis_redacts_pii_and_returns_grounded_profile(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "resume.docx"
    source_text = "手机 13812345678。使用 Python 开发项目"
    _write_docx(path, source_text)
    client = CapturingResponsesClient(
        {
            "schema_version": "resume_parse_v1",
            "document_language": "zh-CN",
            "summary": "Python 开发者",
            "educations": [],
            "experiences": [],
            "projects": [],
            "skills": [
                {
                    "name": "Python",
                    "proficiency": "intermediate",
                    "explicit_experience_months": 12,
                    "evidence_strength": "project",
                    "evidence_quote": "使用 Python 开发项目",
                    "confidence": 0.95,
                }
            ],
        }
    )
    monkeypatch.setattr("app.resumes.analysis.get_settings", _settings)

    result = await analyze_resume_document(
        path,
        filename="resume.docx",
        media_type=DOCX_MEDIA_TYPE,
        processing_run_id=uuid4(),
        responses_client=client,
    )

    assert result.extracted_text == source_text
    assert result.extraction_method == "docx"
    assert result.validated.summary == "Python 开发者"
    assert result.validated.skills[0]["evidence_start"] == source_text.index("使用")
    assert "13812345678" not in client.redacted_text
    assert "*" * 11 in client.redacted_text
    assert result.source_sha256 == sha256(source_text.encode()).hexdigest()


async def test_analysis_accepts_non_skill_evidence_and_rejects_empty_document(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "education.docx"
    _write_docx(path, "示例大学 计算机科学 本科")
    client = CapturingResponsesClient(
        {
            "schema_version": "resume_parse_v1",
            "document_language": "zh-CN",
            "summary": None,
            "educations": [
                {
                    "school_name": "示例大学",
                    "major": "计算机科学",
                    "education_level": "bachelor",
                    "start_month": None,
                    "end_month": None,
                    "is_current": False,
                    "evidence_quote": "示例大学 计算机科学 本科",
                    "confidence": 0.9,
                }
            ],
            "experiences": [],
            "projects": [],
            "skills": [],
        }
    )
    monkeypatch.setattr("app.resumes.analysis.get_settings", _settings)

    result = await analyze_resume_document(
        path,
        filename="education.docx",
        media_type=DOCX_MEDIA_TYPE,
        processing_run_id=uuid4(),
        responses_client=client,
    )
    assert result.validated.skills == []
    assert result.validated.educations[0]["education_level"] == "bachelor"

    empty = tmp_path / "empty.docx"
    _write_docx(empty, "   ")
    with pytest.raises(APIError) as error:
        await analyze_resume_document(
            empty,
            filename="empty.docx",
            media_type=DOCX_MEDIA_TYPE,
            processing_run_id=uuid4(),
            responses_client=client,
        )
    assert error.value.code == "RESUME_TEXT_EMPTY"
