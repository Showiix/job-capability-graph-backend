import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.core.errors import APIError
from app.resumes.llm import (
    LLMParseResult,
    ResponsesClient,
    create_responses_http_client,
)
from app.resumes.parsing import (
    ExtractedDocument,
    ValidatedParse,
    detect_resume_document,
    extract_resume_text,
    normalize_extracted_text,
    redact_resume_text,
    validate_parse_evidence,
)

StageCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ResumeAnalysisResult:
    extracted_text: str
    extraction_method: str
    source_sha256: str
    validated: ValidatedParse
    llm_result: LLMParseResult
    requested_model: str


async def analyze_resume_document(
    path: Path,
    *,
    filename: str,
    media_type: str,
    processing_run_id: UUID,
    responses_client: ResponsesClient | None = None,
    settings: Any | None = None,
    on_stage: StageCallback | None = None,
) -> ResumeAnalysisResult:
    await _stage(on_stage, "extract_text")
    content = await asyncio.to_thread(path.read_bytes)
    document_type = detect_resume_document(filename, media_type, content)
    resolved_settings = settings or get_settings()
    if document_type == "image":
        if not all(
            (
                resolved_settings.llm_responses_url,
                resolved_settings.llm_api_key,
                resolved_settings.llm_model,
            )
        ):
            raise APIError(503, "LLM_NOT_CONFIGURED", "简历解析服务尚未配置")
        image_request = {
            "url": str(resolved_settings.llm_responses_url),
            "api_key": resolved_settings.llm_api_key.get_secret_value(),
            "model": resolved_settings.llm_model,
            "image": content,
            "media_type": "image/png"
            if filename.lower().endswith(".png")
            else "image/jpeg",
            "processing_run_id": processing_run_id,
        }
        if responses_client is None:
            async with create_responses_http_client() as http:
                transcript = await ResponsesClient(http=http).transcribe_image(
                    **image_request
                )
        else:
            transcript = await responses_client.transcribe_image(**image_request)
        extracted = ExtractedDocument(
            text=normalize_extracted_text(transcript),
            method="image_llm",
        )
    else:
        extracted = await extract_resume_text(path, document_type)

    await _stage(on_stage, "redact_text")
    redacted_text = redact_resume_text(extracted.text)
    await _stage(on_stage, "call_llm")
    if not all(
        (
            resolved_settings.llm_responses_url,
            resolved_settings.llm_api_key,
            resolved_settings.llm_model,
        )
    ):
        raise APIError(503, "LLM_NOT_CONFIGURED", "简历解析服务尚未配置")
    request = {
        "url": str(resolved_settings.llm_responses_url),
        "api_key": resolved_settings.llm_api_key.get_secret_value(),
        "model": resolved_settings.llm_model,
        "redacted_text": redacted_text,
        "processing_run_id": processing_run_id,
    }
    if responses_client is None:
        async with create_responses_http_client() as http:
            llm_result = await ResponsesClient(http=http).parse_resume(**request)
    else:
        llm_result = await responses_client.parse_resume(**request)

    await _stage(on_stage, "validate_response")
    await _stage(on_stage, "validate_evidence")
    validated = validate_parse_evidence(
        llm_result.payload,
        redacted_text=redacted_text,
    )
    return ResumeAnalysisResult(
        extracted_text=extracted.text,
        extraction_method=extracted.method,
        source_sha256=hashlib.sha256(extracted.text.encode()).hexdigest(),
        validated=validated,
        llm_result=llm_result,
        requested_model=resolved_settings.llm_model,
    )


async def _stage(callback: StageCallback | None, stage: str) -> None:
    if callback is not None:
        await callback(stage)
