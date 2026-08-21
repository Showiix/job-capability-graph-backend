from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from docx import Document
from pydantic import SecretStr
from sqlalchemy import func, select

from app.catalog.models import Capability, Domain
from app.files.models import StoredFile
from app.infrastructure.file_storage import FileStorage
from app.processing.models import ProcessingError, ProcessingRun
from app.recruitment.models import (
    CandidateProfile,
    CandidateSkill,
    RecruitmentCandidate,
    RecruitmentProject,
)
from app.recruitment.tasks import run_parse_recruitment_candidates
from app.resumes.llm import LLMParseResult
from app.resumes.parsing import DOCX_MEDIA_TYPE
from app.resumes.schemas import ResumeParseResponse


class FakeResumeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.payload = ResumeParseResponse.model_validate(
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

    async def parse_resume(self, **_kwargs):
        self.calls += 1
        return LLMParseResult(
            payload=self.payload,
            response_id=f"resp_{self.calls}",
            returned_model="fake-model",
            status="completed",
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            provider_attempts=1,
            response_sha256="a" * 64,
        )


def _settings():
    return SimpleNamespace(
        llm_responses_url="https://provider.test/v1/responses",
        llm_api_key=SecretStr("secret"),
        llm_model="test-model",
    )


def _write_docx(path, text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    document.save(path)
    return path.read_bytes()


async def _batch(db_session, user, tmp_path, *, invalid_second: bool = False):
    user.role = "hr"
    storage = FileStorage(tmp_path / "candidate-task-files")
    project = RecruitmentProject(
        id=uuid4(),
        owner_user_id=user.id,
        title="候选人任务",
        jd_parse_status="empty",
        jd_draft_payload={},
        confirmed_requirement_snapshot={},
    )
    db_session.add(project)
    await db_session.flush()
    candidates = []
    for index in range(2):
        file_id = uuid4()
        storage_key = f"resume/{file_id}.docx"
        path = storage.resolve(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            b"not-a-docx"
            if invalid_second and index == 1
            else _write_docx(path, "使用 Python 开发项目")
        )
        if invalid_second and index == 1:
            path.write_bytes(content)
        stored_file = StoredFile(
            id=file_id,
            uploaded_by_user_id=user.id,
            original_name=f"candidate-{index}.docx",
            storage_key=storage_key,
            media_type=DOCX_MEDIA_TYPE,
            extension="docx",
            size_bytes=len(content),
            sha256=sha256(content).hexdigest(),
            category="resume",
            scan_status="not_required",
            status="attached",
        )
        db_session.add(stored_file)
        await db_session.flush()
        candidate = RecruitmentCandidate(
            id=uuid4(),
            project_id=project.id,
            file_id=stored_file.id,
            display_name=f"候选人 {index}",
            parse_status="uploaded",
            created_by_user_id=user.id,
        )
        db_session.add(candidate)
        await db_session.flush()
        candidates.append(candidate)
    run = ProcessingRun(
        id=uuid4(),
        run_type="parse_recruitment_candidates",
        subject_type="recruitment_project",
        subject_id=project.id,
        created_by_user_id=user.id,
        owner_scope_type="recruitment_project",
        owner_scope_id=project.id,
        status="pending",
        pipeline_version="recruitment_candidate_parse_v1",
        total_count=2,
        input_snapshot={
            "candidate_ids": sorted(str(candidate.id) for candidate in candidates)
        },
        result_summary={},
    )
    db_session.add(run)
    await db_session.flush()
    for candidate in candidates:
        candidate.latest_run_id = run.id
    await db_session.flush()
    return storage, project, candidates, run


async def test_candidate_batch_task_persists_profiles_and_skills(
    db_session,
    user,
    tmp_path,
    monkeypatch,
) -> None:
    domain = Domain(
        id=uuid4(),
        code=f"candidate-task-{uuid4().hex[:8]}",
        name="软件工程",
        status="active",
        sort_order=0,
    )
    db_session.add(domain)
    await db_session.flush()
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        skill_type="language",
        status="active",
        source_type="manual",
    )
    db_session.add(capability)
    await db_session.flush()
    storage, _project, candidates, run = await _batch(db_session, user, tmp_path)
    client = FakeResumeClient()
    monkeypatch.setattr("app.recruitment.tasks.storage", storage)
    monkeypatch.setattr("app.recruitment.tasks.get_settings", _settings)

    result = await run_parse_recruitment_candidates(
        db_session,
        run.id,
        responses_client=client,
    )

    await db_session.refresh(run)
    assert result["success_candidate_ids"] == sorted(
        str(candidate.id) for candidate in candidates
    )
    assert run.status == "completed"
    assert run.success_count == 2
    assert client.calls == 2
    assert (
        await db_session.scalar(select(func.count()).select_from(CandidateProfile)) == 2
    )
    skills = (await db_session.scalars(select(CandidateSkill))).all()
    assert len(skills) == 2
    assert {skill.capability_id for skill in skills} == {capability.id}
    for candidate in candidates:
        await db_session.refresh(candidate)
        assert candidate.parse_status == "ready"


async def test_candidate_batch_task_keeps_success_and_reports_partial_failure(
    db_session,
    user,
    tmp_path,
    monkeypatch,
) -> None:
    storage, _project, candidates, run = await _batch(
        db_session,
        user,
        tmp_path,
        invalid_second=True,
    )
    client = FakeResumeClient()
    monkeypatch.setattr("app.recruitment.tasks.storage", storage)
    monkeypatch.setattr("app.recruitment.tasks.get_settings", _settings)

    result = await run_parse_recruitment_candidates(
        db_session,
        run.id,
        responses_client=client,
    )

    await db_session.refresh(run)
    statuses = {}
    for candidate in candidates:
        await db_session.refresh(candidate)
        statuses[str(candidate.id)] = candidate.parse_status
    errors = (
        await db_session.scalars(
            select(ProcessingError).where(ProcessingError.run_id == run.id)
        )
    ).all()
    assert sorted(statuses.values()) == ["failed", "ready"]
    assert run.status == "failed"
    assert run.error_code == "CANDIDATE_BATCH_PARTIAL_FAILURE"
    assert len(result["failed_candidates"]) == 1
    assert len(errors) == 1
    assert errors[0].item_type == "recruitment_candidate"
    assert errors[0].item_id in {candidate.id for candidate in candidates}
    assert client.calls == 1


async def test_candidate_batch_retry_skips_ready_candidate(
    db_session,
    user,
    tmp_path,
    monkeypatch,
) -> None:
    storage, project, candidates, run = await _batch(
        db_session,
        user,
        tmp_path,
        invalid_second=True,
    )
    first_client = FakeResumeClient()
    monkeypatch.setattr("app.recruitment.tasks.storage", storage)
    monkeypatch.setattr("app.recruitment.tasks.get_settings", _settings)
    await run_parse_recruitment_candidates(
        db_session,
        run.id,
        responses_client=first_client,
    )
    failed = next(
        candidate for candidate in candidates if candidate.parse_status == "failed"
    )
    failed_file = await db_session.get(StoredFile, failed.file_id)
    repaired = _write_docx(
        storage.resolve(failed_file.storage_key),
        "使用 Python 开发项目",
    )
    failed_file.size_bytes = len(repaired)
    failed_file.sha256 = sha256(repaired).hexdigest()
    retry = ProcessingRun(
        id=uuid4(),
        run_type="parse_recruitment_candidates",
        subject_type="recruitment_project",
        subject_id=project.id,
        retry_of_run_id=run.id,
        created_by_user_id=user.id,
        owner_scope_type="recruitment_project",
        owner_scope_id=project.id,
        status="pending",
        pipeline_version="recruitment_candidate_parse_v1",
        total_count=2,
        input_snapshot=dict(run.input_snapshot),
        result_summary={},
    )
    db_session.add(retry)
    await db_session.flush()
    retry_client = FakeResumeClient()

    await run_parse_recruitment_candidates(
        db_session,
        retry.id,
        responses_client=retry_client,
    )

    await db_session.refresh(retry)
    assert retry.status == "completed"
    assert retry_client.calls == 1
    assert (
        await db_session.scalar(select(func.count()).select_from(CandidateProfile)) == 2
    )


async def test_candidate_batch_honors_cancel_before_first_item(
    db_session,
    user,
    tmp_path,
    monkeypatch,
) -> None:
    storage, _project, candidates, run = await _batch(db_session, user, tmp_path)
    run.status = "cancel_requested"
    run.cancel_requested = True
    await db_session.flush()
    client = FakeResumeClient()
    monkeypatch.setattr("app.recruitment.tasks.storage", storage)
    monkeypatch.setattr("app.recruitment.tasks.get_settings", _settings)

    await run_parse_recruitment_candidates(
        db_session,
        run.id,
        responses_client=client,
    )

    await db_session.refresh(run)
    assert run.status == "cancelled"
    assert client.calls == 0
    assert (
        await db_session.scalar(select(func.count()).select_from(CandidateProfile)) == 0
    )
    for candidate in candidates:
        await db_session.refresh(candidate)
        assert candidate.parse_status == "uploaded"
