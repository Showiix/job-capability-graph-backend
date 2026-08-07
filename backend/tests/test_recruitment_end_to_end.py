from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from docx import Document
from pydantic import SecretStr
from sqlalchemy import select

from app.catalog.models import Capability, Domain
from app.infrastructure.file_storage import FileStorage
from app.llm.responses import ResponsesAPIError, StructuredResponseResult
from app.processing.models import ProcessingRun
from app.recruitment.models import RecruitmentMatchRun, RecruitmentProject
from app.recruitment.schemas import RecruitmentJDParseResponse
from app.recruitment.tasks import (
    run_parse_recruitment_candidates,
    run_parse_recruitment_jd,
)
from app.resumes.llm import LLMParseResult
from app.resumes.parsing import DOCX_MEDIA_TYPE
from app.resumes.schemas import ResumeParseResponse


def _docx_bytes(text: str) -> bytes:
    output = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(output)
    return output.getvalue()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        llm_responses_url="https://provider.test/v1/responses",
        llm_api_key=SecretStr("test-secret"),
        llm_model="test-model",
    )


class _FakeJDClient:
    async def parse_jd(self, **_kwargs):
        payload = RecruitmentJDParseResponse.model_validate(
            {
                "job_title": "AI 应用工程师",
                "summary": "负责企业 AI 应用开发",
                "responsibilities": [
                    {
                        "text": "负责 Python 应用开发",
                        "evidence_quote": "负责 Python 应用开发",
                    }
                ],
                "minimum_education_level": "bachelor",
                "recommended_experience_months": 24,
                "skills": [
                    {
                        "name": "Python",
                        "requirement_type": "required",
                        "importance": 1.0,
                        "evidence_quote": "Python",
                        "confidence": 0.99,
                    }
                ],
            }
        )
        return StructuredResponseResult(
            payload=payload,
            response_id="jd-response",
            returned_model="fake-model",
            status="completed",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            provider_attempts=1,
            response_sha256="a" * 64,
        )


class _FakeResumeClient:
    def __init__(self) -> None:
        self.calls = 0

    async def parse_resume(self, *, redacted_text: str, **_kwargs) -> LLMParseResult:
        self.calls += 1
        if "Java" in redacted_text:
            raise ResponsesAPIError("LLM_TIMEOUT", "request", True)
        payload = ResumeParseResponse.model_validate(
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
                        "explicit_experience_months": 24,
                        "evidence_strength": "project",
                        "evidence_quote": "使用 Python 完成项目",
                        "confidence": 0.95,
                    }
                ],
            }
        )
        return LLMParseResult(
            payload=payload,
            response_id=f"resume-response-{self.calls}",
            returned_model="fake-model",
            status="completed",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            provider_attempts=1,
            response_sha256="b" * 64,
        )


async def _login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def test_recruitment_workflow_end_to_end(
    client,
    db_session,
    make_user,
    monkeypatch,
    tmp_path,
) -> None:
    hr, hr_password = await make_user(role="hr", username="e2e_hr")
    other_hr, other_password = await make_user(role="hr", username="e2e_other_hr")
    applicant, applicant_password = await make_user(
        role="applicant", username="e2e_applicant"
    )
    admin, admin_password = await make_user(role="admin", username="e2e_admin")
    domain = Domain(
        id=uuid4(),
        code=f"e2e-{uuid4().hex[:8]}",
        name="软件工程",
        status="active",
        sort_order=0,
    )
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        skill_type="language",
        status="active",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add(capability)
    await db_session.flush()

    storage = FileStorage(tmp_path / "recruitment-e2e-files")
    monkeypatch.setattr("app.recruitment.service.storage", storage)
    monkeypatch.setattr("app.recruitment.tasks.storage", storage)
    monkeypatch.setattr("app.files.router.storage", storage)
    monkeypatch.setattr("app.recruitment.tasks.get_settings", _settings)
    monkeypatch.setattr(
        "app.recruitment.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="task"),
    )

    csrf = await _login(client, hr.username, hr_password)
    created = await client.post(
        "/api/v1/recruitment-projects",
        json={"title": "AI 应用招聘", "description": "端到端演示"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    project_id = created.json()["data"]["id"]
    assert created.json()["data"]["confirmed_requirement_summary"] == {}

    submitted = await client.post(
        f"/api/v1/recruitment-projects/{project_id}/jd",
        data={"text": "负责 Python 应用开发"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "e2e-jd"},
    )
    assert submitted.status_code == 202
    jd_run_id = submitted.json()["data"]["run_id"]
    await run_parse_recruitment_jd(
        db_session,
        jd_run_id,
        responses_client=_FakeJDClient(),
    )
    jd_run = await db_session.get(ProcessingRun, jd_run_id)
    assert jd_run.status == "completed"

    replace = await client.put(
        f"/api/v1/recruitment-projects/{project_id}/requirements",
        json={
            "job_title": "AI 应用工程师",
            "summary": "负责企业 AI 应用开发",
            "responsibilities": ["负责 Python 应用开发"],
            "minimum_education_level": "bachelor",
            "recommended_experience_months": 24,
            "requirements": [
                {
                    "capability_id": str(capability.id),
                    "requirement_type": "required",
                    "importance": 1.0,
                }
            ],
            "unmapped_skills": [],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert replace.status_code == 200
    confirmed = await client.post(
        f"/api/v1/recruitment-projects/{project_id}/requirements/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    confirmed_again = await client.post(
        f"/api/v1/recruitment-projects/{project_id}/requirements/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["requirements_revision"] == 1
    assert confirmed_again.json()["data"]["reused"] is True

    files = [
        (
            "files",
            (
                "python-candidate.docx",
                _docx_bytes("使用 Python 完成项目"),
                DOCX_MEDIA_TYPE,
            ),
        ),
        (
            "files",
            ("java-candidate.docx", _docx_bytes("使用 Java 完成项目"), DOCX_MEDIA_TYPE),
        ),
    ]
    uploaded = await client.post(
        f"/api/v1/recruitment-projects/{project_id}/candidates",
        files=files,
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "e2e-candidates"},
    )
    assert uploaded.status_code == 202
    candidate_run_id = uploaded.json()["data"]["run_id"]
    candidate_ids = [item["id"] for item in uploaded.json()["data"]["candidates"]]
    candidate_result = await run_parse_recruitment_candidates(
        db_session,
        candidate_run_id,
        responses_client=_FakeResumeClient(),
    )
    assert len(candidate_result["success_candidate_ids"]) == 1
    assert len(candidate_result["failed_candidates"]) == 1

    candidates = (
        await db_session.scalars(
            select(RecruitmentProject).where(RecruitmentProject.id == project_id)
        )
    ).one()
    assert candidates.jd_source_text == "负责 Python 应用开发"
    candidate_listing = await client.get(
        f"/api/v1/recruitment-projects/{project_id}/candidates"
    )
    assert candidate_listing.status_code == 200
    listed_by_status = {
        item["parse_status"]: item for item in candidate_listing.json()["data"]
    }
    assert set(listed_by_status) == {"ready", "failed"}
    ready_candidate_id = listed_by_status["ready"]["id"]
    ready_file_id = listed_by_status["ready"]["file_id"]

    match_url = f"/api/v1/recruitment-projects/{project_id}/match-runs"
    first_match = await client.post(match_url, headers={"X-CSRF-Token": csrf})
    reused_match = await client.post(match_url, headers={"X-CSRF-Token": csrf})
    assert first_match.status_code == 200
    assert first_match.json()["data"]["run"]["result_count"] == 1
    assert first_match.json()["data"]["run"]["skipped_count"] == 1
    assert reused_match.json()["data"]["reused"] is True
    match_run_id = first_match.json()["data"]["run"]["id"]
    match_run = await db_session.get(RecruitmentMatchRun, match_run_id)
    assert match_run.skipped_candidates[0]["parse_status"] == "failed"
    results = await client.get(f"{match_url}/{match_run_id}/results")
    detail = await client.get(
        f"{match_url}/{match_run_id}/results/{ready_candidate_id}"
    )
    assert results.status_code == 200
    assert results.json()["data"][0]["candidate_id"] == ready_candidate_id
    assert detail.status_code == 200
    assert detail.json()["data"]["matched_capabilities"][0]["canonical_name"] == (
        "Python"
    )

    file_metadata = await client.get(f"/api/v1/files/{ready_file_id}")
    file_content = await client.get(f"/api/v1/files/{ready_file_id}/content")
    assert file_metadata.status_code == 200
    assert file_metadata.json()["data"]["category"] == "resume"
    assert file_content.status_code == 200
    assert file_content.content.startswith(b"PK")

    second_project = await client.post(
        "/api/v1/recruitment-projects",
        json={"title": "另一个项目"},
        headers={"X-CSRF-Token": csrf},
    )
    second_project_id = second_project.json()["data"]["id"]
    assert (
        await client.get(
            f"/api/v1/recruitment-projects/{second_project_id}/candidates/{ready_candidate_id}"
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/recruitment-projects/{second_project_id}/match-runs/{match_run_id}/results"
        )
    ).status_code == 404

    await _login(client, other_hr.username, other_password)
    assert (
        await client.get(f"/api/v1/recruitment-projects/{project_id}")
    ).status_code == 404
    assert (await client.get(f"/api/v1/files/{ready_file_id}")).status_code == 404

    await _login(client, applicant.username, applicant_password)
    assert (
        await client.get(f"/api/v1/recruitment-projects/{project_id}")
    ).status_code == 404
    assert (await client.get(f"/api/v1/files/{ready_file_id}")).status_code == 404

    await _login(client, admin.username, admin_password)
    admin_project = await client.get(f"/api/v1/recruitment-projects/{project_id}")
    admin_run = await client.get(f"/api/v1/processing-runs/{candidate_run_id}")
    assert admin_project.status_code == 200
    assert admin_project.json()["data"]["latest_match_run"]["id"] == match_run_id
    assert admin_project.json()["data"]["candidate_counts"]["failed"] == 1
    assert admin_run.status_code == 200
    assert admin_run.json()["data"]["id"] == candidate_run_id
    assert set(candidate_ids) == {
        item["id"] for item in candidate_listing.json()["data"]
    }
