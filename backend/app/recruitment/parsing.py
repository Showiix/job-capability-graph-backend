import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import APIError
from app.recruitment.schemas import RecruitmentJDParseResponse
from app.resumes.parsing import (
    DOCX_MEDIA_TYPES,
    PDF_MEDIA_TYPES,
    ExtractedDocument,
    detect_resume_document,
    extract_resume_text,
    locate_evidence,
    normalize_extracted_text,
)

MAX_JD_FILE_BYTES = 10 * 1024 * 1024
TXT_MEDIA_TYPES = {"text/plain", "application/octet-stream"}


@dataclass(frozen=True, slots=True)
class ValidatedJDParse:
    job_title: str
    summary: str | None
    responsibilities: list[dict]
    minimum_education_level: str | None
    recommended_experience_months: int | None
    skills: list[dict]
    warnings: list[str]


def detect_jd_document(filename: str, media_type: str, content: bytes) -> str:
    if not content:
        raise _invalid_document()
    if len(content) > MAX_JD_FILE_BYTES:
        raise APIError(413, "RECRUITMENT_JD_TOO_LARGE", "JD 文件超过 10 MB 限制")

    extension = Path(filename).suffix.lower()
    declared_type = media_type.split(";", 1)[0].strip().lower()
    if extension == ".txt":
        if declared_type not in TXT_MEDIA_TYPES:
            raise _invalid_document()
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise _invalid_document() from error
        return "txt"
    if extension == ".pdf" and declared_type not in PDF_MEDIA_TYPES:
        raise _invalid_document()
    if extension == ".docx" and declared_type not in DOCX_MEDIA_TYPES:
        raise _invalid_document()

    try:
        return detect_resume_document(filename, media_type, content)
    except APIError as error:
        raise _invalid_document() from error


async def extract_jd_text(path: Path, document_type: str) -> ExtractedDocument:
    if document_type == "txt":
        try:
            content = await asyncio.to_thread(path.read_bytes)
            raw_text = content.decode("utf-8-sig")
            return ExtractedDocument(
                text=normalize_extracted_text(raw_text),
                method="txt",
            )
        except UnicodeDecodeError as error:
            raise _invalid_document() from error
        except APIError as error:
            raise _translate_resume_error(error) from error

    try:
        return await extract_resume_text(path, document_type)
    except APIError as error:
        raise _translate_resume_error(error) from error


def validate_jd_evidence(
    payload: RecruitmentJDParseResponse,
    *,
    source_text: str,
) -> ValidatedJDParse:
    warnings: list[str] = []
    responsibilities = _ground_items(
        payload.responsibilities,
        label_field="text",
        category="RESPONSIBILITY",
        source_text=source_text,
        warnings=warnings,
    )
    skills = _ground_items(
        payload.skills,
        label_field="name",
        category="SKILL",
        source_text=source_text,
        warnings=warnings,
    )
    if not responsibilities and not skills:
        raise APIError(
            422,
            "RECRUITMENT_JD_EVIDENCE_EMPTY",
            "JD 抽取结果缺少可追溯证据",
        )
    return ValidatedJDParse(
        job_title=payload.job_title,
        summary=payload.summary,
        responsibilities=responsibilities,
        minimum_education_level=payload.minimum_education_level,
        recommended_experience_months=payload.recommended_experience_months,
        skills=skills,
        warnings=warnings,
    )


def _ground_items(
    items: list,
    *,
    label_field: str,
    category: str,
    source_text: str,
    warnings: list[str],
) -> list[dict]:
    grounded = []
    for item in items:
        value = item.model_dump(mode="python")
        offsets = locate_evidence(source_text, value["evidence_quote"])
        if offsets is None:
            warnings.append(f"{category}_EVIDENCE_NOT_FOUND:{value[label_field]}")
            continue
        value["evidence_start"], value["evidence_end"] = offsets
        grounded.append(value)
    return grounded


def _translate_resume_error(error: APIError) -> APIError:
    if error.code == "RESUME_TEXT_TOO_LONG":
        return APIError(413, "RECRUITMENT_JD_TOO_LARGE", "JD 正文超过处理上限")
    return _invalid_document()


def _invalid_document() -> APIError:
    return APIError(
        422,
        "RECRUITMENT_JD_INPUT_INVALID",
        "JD 文件格式或内容无效",
    )
