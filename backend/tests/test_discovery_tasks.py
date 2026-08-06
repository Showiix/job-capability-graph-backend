from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import func, select

from app.auth.models import User
from app.catalog.models import Capability, CapabilityAlias, Domain
from app.core.security import hash_password
from app.discovery.models import (
    CombinationEvidence,
    DiscoveryRun,
    JobAnalysisProfile,
    JobSkillCandidate,
    SkillCombinationCandidate,
)
from app.discovery.tasks import process_discovery_run
from app.files.models import StoredFile
from app.imports.models import (
    DataSource,
    ImportBatch,
    NormalizedJobPosting,
    RawJobPosting,
)
from app.processing.models import ProcessingError, ProcessingRun


@pytest_asyncio.fixture
async def discovery_admin(db_session) -> User:
    user = User(
        id=uuid4(),
        username="discovery_admin",
        username_normalized="discovery_admin",
        password_hash=hash_password("discovery-admin-password"),
        display_name="Discovery Admin",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _new_run(db_session, admin, batch_ids, **parameter_overrides):
    discovery_id = uuid4()
    processing_run = ProcessingRun(
        id=uuid4(),
        run_type="discover_skill_combinations",
        subject_type="discovery_run",
        subject_id=discovery_id,
        created_by_user_id=admin.id,
        owner_scope_type="admin_global",
        status="pending",
        pipeline_version="cooccurrence_pairs_v1",
        input_snapshot={"batch_ids": [str(value) for value in batch_ids]},
        result_summary={},
    )
    parameters = {
        "minimum_support_jobs": 3,
        "minimum_source_count": 2,
        "minimum_quality_score": 60,
        "maximum_candidates": 50,
    }
    parameters.update(parameter_overrides)
    discovery_run = DiscoveryRun(
        id=discovery_id,
        processing_run_id=processing_run.id,
        input_batch_ids=batch_ids,
        algorithm_version="cooccurrence_pairs_v1",
        extraction_version="source_tags_v1",
        parameters=parameters,
        status="pending",
        summary={},
        created_by_user_id=admin.id,
    )
    db_session.add(processing_run)
    await db_session.flush()
    db_session.add(discovery_run)
    await db_session.flush()
    return processing_run, discovery_run


@pytest_asyncio.fixture
async def discovery_context(db_session, discovery_admin):
    domain = Domain(
        id=uuid4(),
        code="discovery-testing",
        name="Discovery Testing",
        status="active",
        sort_order=0,
    )
    python = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        status="active",
        skill_type="language",
        source_type="manual",
    )
    testing = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="自动化测试",
        status="active",
        skill_type="method",
        source_type="manual",
    )
    sql = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="SQL",
        status="active",
        skill_type="language",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add_all([python, testing, sql])
    await db_session.flush()
    db_session.add(
        CapabilityAlias(
            id=uuid4(),
            capability_id=testing.id,
            alias="pytest",
            status="active",
        )
    )
    await db_session.flush()

    sources = {
        source.code: source
        for source in (
            await db_session.scalars(
                select(DataSource).where(DataSource.code.in_({"zhilian", "liepin"}))
            )
        ).all()
    }
    batches = []
    for index, source_code in enumerate(("zhilian", "liepin"), start=1):
        stored_file = StoredFile(
            id=uuid4(),
            uploaded_by_user_id=discovery_admin.id,
            original_name=f"{source_code}.tsv",
            storage_key=f"discovery/{source_code}-{uuid4()}.tsv",
            media_type="text/tab-separated-values",
            extension="tsv",
            size_bytes=10,
            sha256=f"{index}" * 64,
            category="market_jd",
            scan_status="not_required",
            status="attached",
        )
        batch = ImportBatch(
            id=uuid4(),
            source_id=sources[source_code].id,
            file_id=stored_file.id,
            uploaded_by_user_id=discovery_admin.id,
            collected_at=datetime(2026, 8, index, tzinfo=UTC),
            status="processed",
            total_rows=2,
            accepted_rows=2,
            batch_summary={},
        )
        db_session.add(stored_file)
        await db_session.flush()
        db_session.add(batch)
        await db_session.flush()
        batches.append(batch)

    job_specs = [
        (batches[0], 1, "zhilian", "A", 90, ["Python", "pytest", "未知技能"]),
        (batches[0], 2, "zhilian", "B", 80, ["Python", "自动化测试", "SQL"]),
        (batches[1], 1, "liepin", "C", 100, ["Python", "自动化测试"]),
        (batches[1], 2, "liepin", "D", 90, ["Python", "SQL"]),
    ]
    jobs = []
    for batch, row_number, source_code, company, quality, tags in job_specs:
        raw = RawJobPosting(
            id=uuid4(),
            batch_id=batch.id,
            row_number=row_number,
            source_code=source_code,
            source_url=f"https://example.test/{source_code}/{row_number}",
            job_name="Test Engineer",
            company_name=company,
            source_tags=tags,
            raw_payload={"tech_tags": tags},
            parse_warnings=[],
        )
        normalized = NormalizedJobPosting(
            id=uuid4(),
            raw_job_id=raw.id,
            version_no=1,
            normalization_version="rules_v1",
            normalized_title="Test Engineer",
            company_name=company,
            quality_score=quality,
            quality_flags=[],
            is_current=True,
        )
        db_session.add(raw)
        await db_session.flush()
        db_session.add(normalized)
        await db_session.flush()
        jobs.append(normalized)

    processing_run, discovery_run = await _new_run(
        db_session,
        discovery_admin,
        [batch.id for batch in batches],
    )
    return SimpleNamespace(
        admin=discovery_admin,
        batches=batches,
        capabilities=[python, testing, sql],
        jobs=jobs,
        processing_run=processing_run,
        discovery_run=discovery_run,
    )


async def test_worker_materializes_mapping_and_candidates(
    db_session,
    discovery_context,
) -> None:
    result = await process_discovery_run(
        db_session,
        discovery_context.processing_run.id,
    )

    assert result["candidate_count"] == 1
    assert result["mapped_skill_count"] == 9
    assert result["unmapped_skill_count"] == 1
    assert discovery_context.processing_run.status == "completed"
    assert discovery_context.discovery_run.status == "completed"


async def test_worker_reuses_existing_analysis_profile(
    db_session,
    discovery_context,
) -> None:
    await process_discovery_run(db_session, discovery_context.processing_run.id)
    first_count = await db_session.scalar(
        select(func.count()).select_from(JobAnalysisProfile)
    )
    second_processing, _ = await _new_run(
        db_session,
        discovery_context.admin,
        [batch.id for batch in discovery_context.batches],
    )

    await process_discovery_run(db_session, second_processing.id)

    assert await db_session.scalar(
        select(func.count()).select_from(JobAnalysisProfile)
    ) == first_count


async def test_worker_records_candidate_evidence(
    db_session,
    discovery_context,
) -> None:
    await process_discovery_run(db_session, discovery_context.processing_run.id)
    candidate = await db_session.scalar(select(SkillCombinationCandidate))
    evidence_ids = set(
        (
            await db_session.scalars(
                select(CombinationEvidence.normalized_job_id).where(
                    CombinationEvidence.candidate_id == candidate.id
                )
            )
        ).all()
    )

    assert evidence_ids == {job.id for job in discovery_context.jobs[:3]}


async def test_worker_completes_with_zero_candidates(
    db_session,
    discovery_context,
) -> None:
    discovery_context.discovery_run.parameters["minimum_support_jobs"] = 4

    result = await process_discovery_run(
        db_session,
        discovery_context.processing_run.id,
    )

    assert result["candidate_count"] == 0
    assert discovery_context.processing_run.status == "completed"
    assert discovery_context.discovery_run.status == "completed"


async def test_worker_honors_cancel_request(db_session, discovery_context) -> None:
    discovery_context.processing_run.cancel_requested = True
    await db_session.flush()

    result = await process_discovery_run(
        db_session,
        discovery_context.processing_run.id,
    )

    assert result["candidate_count"] == 0
    assert discovery_context.processing_run.status == "cancelled"
    assert discovery_context.discovery_run.status == "cancelled"
    assert await db_session.scalar(
        select(func.count()).select_from(SkillCombinationCandidate)
    ) == 0


async def test_worker_is_idempotent_after_completion(
    db_session,
    discovery_context,
) -> None:
    first = await process_discovery_run(
        db_session,
        discovery_context.processing_run.id,
    )
    counts_before = {
        model: await db_session.scalar(select(func.count()).select_from(model))
        for model in (
            JobAnalysisProfile,
            JobSkillCandidate,
            SkillCombinationCandidate,
            CombinationEvidence,
        )
    }

    second = await process_discovery_run(
        db_session,
        discovery_context.processing_run.id,
    )

    assert second == first
    assert counts_before == {
        model: await db_session.scalar(select(func.count()).select_from(model))
        for model in counts_before
    }


async def test_worker_clones_discovery_snapshot_for_processing_retry(
    db_session,
    discovery_context,
) -> None:
    discovery_context.processing_run.status = "failed"
    discovery_context.discovery_run.status = "failed"
    retry = ProcessingRun(
        id=uuid4(),
        run_type="discover_skill_combinations",
        subject_type="discovery_run",
        subject_id=discovery_context.discovery_run.id,
        retry_of_run_id=discovery_context.processing_run.id,
        created_by_user_id=discovery_context.admin.id,
        owner_scope_type="admin_global",
        status="pending",
        pipeline_version="cooccurrence_pairs_v1",
        input_snapshot=dict(discovery_context.processing_run.input_snapshot),
        result_summary={},
    )
    db_session.add(retry)
    await db_session.flush()

    result = await process_discovery_run(db_session, retry.id)
    cloned = await db_session.scalar(
        select(DiscoveryRun).where(DiscoveryRun.processing_run_id == retry.id)
    )

    assert result["candidate_count"] == 1
    assert cloned is not None
    assert cloned.id != discovery_context.discovery_run.id
    assert cloned.input_batch_ids == discovery_context.discovery_run.input_batch_ids
    assert retry.subject_id == cloned.id
    assert retry.status == "completed"


async def test_worker_fails_without_active_capabilities(
    db_session,
    discovery_context,
) -> None:
    for capability in discovery_context.capabilities:
        capability.status = "deprecated"
    await db_session.flush()

    await process_discovery_run(db_session, discovery_context.processing_run.id)

    error = await db_session.scalar(
        select(ProcessingError).where(
            ProcessingError.run_id == discovery_context.processing_run.id
        )
    )
    assert discovery_context.processing_run.status == "failed"
    assert discovery_context.discovery_run.status == "failed"
    assert discovery_context.processing_run.error_code == (
        "DISCOVERY_NO_ACTIVE_CAPABILITIES"
    )
    assert error is not None
    assert error.stage == "loading"
