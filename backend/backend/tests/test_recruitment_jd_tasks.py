from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.catalog.models import Capability, Domain
from app.llm.responses import ResponsesAPIError, StructuredResponseResult
from app.processing.models import ProcessingError, ProcessingRun
from app.recruitment.models import RecruitmentProject
from app.recruitment.schemas import RecruitmentJDParseResponse
from app.recruitment.tasks import run_parse_recruitment_jd


class FakeJDClient:
    def __init__(self, payload: dict) -> None:
        self.payload = RecruitmentJDParseResponse.model_validate(payload)

    async def parse_jd(self, **_kwargs):
        return StructuredResponseResult(
            payload=self.payload,
            response_id="resp_jd",
            returned_model="returned-model",
            status="completed",
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            provider_attempts=1,
            response_sha256="a" * 64,
        )


class FailingJDClient:
    async def parse_jd(self, **_kwargs):
        raise ResponsesAPIError("LLM_TIMEOUT", "request", True)


def _settings():
    return SimpleNamespace(
        llm_responses_url="https://provider.test/v1/responses",
        llm_api_key=SimpleNamespace(get_secret_value=lambda: "secret"),
        llm_model="test-model",
    )


async def _project_run(db_session, user, source_text: str):
    project = RecruitmentProject(
        id=uuid4(),
        owner_user_id=user.id,
        title="AI 招聘",
        jd_source_type="text",
        jd_source_text=source_text,
        jd_parse_status="processing",
        jd_draft_payload={},
        confirmed_requirement_snapshot={
            "schema_version": "recruitment_requirements_v1",
            "revision_no": 1,
        },
        confirmed_requirement_sha256="b" * 64,
        requirements_revision=1,
    )
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_recruitment_jd",
        subject_type="recruitment_project",
        subject_id=project.id,
        created_by_user_id=user.id,
        owner_scope_type="recruitment_project",
        owner_scope_id=project.id,
        status="pending",
        pipeline_version="recruitment_jd_parse_v1",
        total_count=1,
        progress_percent=Decimal("0"),
        input_snapshot={"source_type": "text"},
        result_summary={},
    )
    db_session.add(project)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    project.latest_jd_run_id = run.id
    await db_session.flush()
    return project, run


async def test_parse_jd_task_maps_grounded_skills_without_replacing_confirmation(
    db_session,
    user,
    monkeypatch,
) -> None:
    user.role = "hr"
    domain = Domain(
        id=uuid4(),
        code=f"jd-task-{uuid4().hex[:8]}",
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
    source_text = "负责基于 RAG 的企业知识库应用开发。熟练掌握 Python，了解新框架。"
    project, run = await _project_run(db_session, user, source_text)
    previous_confirmation = dict(project.confirmed_requirement_snapshot)
    monkeypatch.setattr("app.recruitment.tasks.get_settings", _settings)
    payload = {
        "job_title": "AI 应用开发工程师",
        "summary": "负责大模型应用开发",
        "responsibilities": [
            {
                "text": "负责 RAG 应用开发",
                "evidence_quote": "负责基于 RAG 的企业知识库应用开发",
            }
        ],
        "minimum_education_level": "bachelor",
        "recommended_experience_months": 24,
        "skills": [
            {
                "name": "Python",
                "requirement_type": "required",
                "importance": 1.0,
                "evidence_quote": "熟练掌握 Python",
                "confidence": 0.98,
            },
            {
                "name": "新框架",
                "requirement_type": "bonus",
                "importance": 0.5,
                "evidence_quote": "了解新框架",
                "confidence": 0.72,
            },
        ],
    }

    result = await run_parse_recruitment_jd(
        db_session,
        run.id,
        responses_client=FakeJDClient(payload),
    )

    await db_session.refresh(project)
    await db_session.refresh(run)
    assert result["mapped_requirement_count"] == 1
    assert project.jd_parse_status == "ready"
    assert project.jd_draft_payload["requirements"][0]["capability_id"] == str(
        capability.id
    )
    assert project.jd_draft_payload["unmapped_skills"][0]["raw_name"] == "新框架"
    assert project.confirmed_requirement_snapshot == previous_confirmation
    assert project.requirements_revision == 1
    assert run.status == "completed"
    assert run.progress_percent == Decimal("100")


async def test_parse_jd_task_records_safe_failure(
    db_session, user, monkeypatch
) -> None:
    user.role = "hr"
    project, run = await _project_run(db_session, user, "负责 Python 开发")
    monkeypatch.setattr("app.recruitment.tasks.get_settings", _settings)

    result = await run_parse_recruitment_jd(
        db_session,
        run.id,
        responses_client=FailingJDClient(),
    )

    await db_session.refresh(project)
    await db_session.refresh(run)
    error = await db_session.scalar(
        select(ProcessingError).where(ProcessingError.run_id == run.id)
    )
    assert result == {}
    assert project.jd_parse_status == "failed"
    assert run.status == "failed"
    assert run.error_code == "LLM_TIMEOUT"
    assert run.error_message == "JD 解析服务请求超时"
    assert error is not None and error.retryable is True
