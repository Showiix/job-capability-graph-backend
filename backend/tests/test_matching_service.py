import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.audit.models import AuditLog
from app.auth.models import User
from app.catalog.models import (
    Capability,
    CatalogVersion,
    CatalogVersionItem,
    Domain,
    JobRole,
    JobRoleCapability,
)
from app.core.errors import APIError
from app.files.models import StoredFile
from app.graph.models import GraphVersion
from app.matching import service as matching_service
from app.matching.models import MatchResult, MatchRun
from app.matching.scoring import MatchCatalogInconsistent
from app.processing.models import ProcessingRun
from app.resumes.models import Resume, ResumeProfile, ResumeSkill
from app.resumes.service import get_visible_resume
from app.reviews.models import GraphChangeCandidate
from tests.matching_fixtures import (
    add_catalog_job_role,
    build_matching_context,
    publish_next_graph_version,
)


async def test_load_match_watermark_allows_owner_and_locks_resume(
    db_session,
    monkeypatch,
) -> None:
    context = await build_matching_context(db_session)
    calls = []

    async def spy_visible_resume(db, resume_id, actor, *, for_update=False):
        calls.append(for_update)
        return await get_visible_resume(
            db,
            resume_id,
            actor,
            for_update=for_update,
        )

    monkeypatch.setattr(matching_service, "get_visible_resume", spy_visible_resume)

    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    assert calls == [True]
    assert watermark.resume.id == context.resume.id
    assert watermark.profile.id == context.profile.id
    assert watermark.graph.id == context.graph.id
    assert watermark.catalog.id == context.catalog.id


async def test_load_match_watermark_allows_admin(db_session) -> None:
    context = await build_matching_context(db_session)

    watermark = await matching_service.load_match_watermark(
        db_session,
        context.admin,
        context.resume.id,
    )

    assert watermark.resume.owner_user_id == context.applicant.id


@pytest.mark.parametrize(
    ("actor_name", "status_code", "code"),
    [
        ("hr", 403, "ROLE_NOT_ALLOWED"),
        ("other_applicant", 404, "RESOURCE_NOT_OWNED"),
    ],
)
async def test_load_match_watermark_enforces_role_and_owner(
    db_session,
    actor_name,
    status_code,
    code,
) -> None:
    context = await build_matching_context(db_session)

    with pytest.raises(APIError) as error:
        await matching_service.load_match_watermark(
            db_session,
            getattr(context, actor_name),
            context.resume.id,
        )

    assert error.value.status_code == status_code
    assert error.value.code == code


async def test_load_match_watermark_rejects_archived_resume(db_session) -> None:
    context = await build_matching_context(db_session)
    context.resume.parse_status = "archived"
    context.resume.archived_at = datetime.now(UTC)
    await db_session.flush()

    with pytest.raises(APIError) as error:
        await matching_service.load_match_watermark(
            db_session,
            context.applicant,
            context.resume.id,
        )

    assert error.value.status_code == 409
    assert error.value.code == "RESUME_ARCHIVED"


async def test_load_match_watermark_requires_confirmed_profile(db_session) -> None:
    context = await build_matching_context(db_session)
    context.profile.status = "candidate"
    context.profile.confirmed_at = None
    await db_session.flush()

    with pytest.raises(APIError) as error:
        await matching_service.load_match_watermark(
            db_session,
            context.applicant,
            context.resume.id,
        )

    assert error.value.status_code == 409
    assert error.value.code == "RESUME_PROFILE_NOT_CONFIRMED"


async def test_load_scoring_inputs_ignores_draft_profile_skills(db_session) -> None:
    context = await build_matching_context(db_session)
    draft = ResumeProfile(
        resume_id=context.resume.id,
        base_profile_id=context.profile.id,
        version_no=2,
        extraction_version=context.profile.extraction_version,
        profile_source="manual_revision",
        extracted_text=context.profile.extracted_text,
        text_extraction_method=context.profile.text_extraction_method,
        highest_education_level="doctor",
        total_experience_months=120,
        structured_payload={},
        status="draft",
        created_by_run_id=None,
        created_by_user_id=context.applicant.id,
    )
    db_session.add(draft)
    await db_session.flush()
    db_session.add(
        ResumeSkill(
            profile_id=draft.id,
            capability_id=context.capabilities["MLOps"].id,
            raw_name="MLOps",
            normalized_name="mlops",
            evidence_strength="work",
            mapping_method="manual",
            mapping_status="mapped",
            source="manual",
            confidence=Decimal("1"),
            user_confirmed=True,
        )
    )
    await db_session.flush()

    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )
    inputs = await matching_service.load_scoring_inputs(db_session, watermark)

    assert watermark.profile.id == context.profile.id
    assert watermark.profile.highest_education_level == "associate"
    assert context.capabilities["MLOps"].id not in inputs.profile.skills


async def test_load_match_watermark_requires_current_graph(db_session) -> None:
    context = await build_matching_context(db_session)
    context.graph.is_current = False
    await db_session.flush()

    with pytest.raises(APIError) as error:
        await matching_service.load_match_watermark(
            db_session,
            context.applicant,
            context.resume.id,
        )

    assert error.value.status_code == 404
    assert error.value.code == "GRAPH_VERSION_NOT_PUBLISHED"


async def test_load_match_watermark_rejects_inconsistent_catalog(db_session) -> None:
    context = await build_matching_context(db_session)
    context.catalog.is_current = False
    await db_session.flush()

    with pytest.raises(APIError) as error:
        await matching_service.load_match_watermark(
            db_session,
            context.applicant,
            context.resume.id,
        )

    assert error.value.status_code == 503
    assert error.value.code == "MATCH_CATALOG_INCONSISTENT"


async def test_load_scoring_inputs_uses_complete_catalog_not_graph_snapshot(
    db_session,
) -> None:
    context = await build_matching_context(db_session)
    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    inputs = await matching_service.load_scoring_inputs(db_session, watermark)

    assert context.graph.snapshot == {"job_role": {"id": str(context.job_roles[0].id)}}
    assert {value.job_role_id for value in inputs.job_roles} == {
        context.job_roles[0].id,
        context.job_roles[1].id,
    }
    assert set(inputs.profile.skills) == {
        context.capabilities["Python"].id,
        context.capabilities["PyTorch"].id,
        context.capabilities["Docker"].id,
    }


async def test_load_scoring_inputs_rejects_catalog_without_job_roles(
    db_session,
) -> None:
    context = await build_matching_context(db_session)
    await db_session.execute(
        delete(CatalogVersionItem).where(
            CatalogVersionItem.catalog_version_id == context.catalog.id,
            CatalogVersionItem.item_type == "job_role",
        )
    )
    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    with pytest.raises(APIError) as error:
        await matching_service.load_scoring_inputs(db_session, watermark)

    assert error.value.status_code == 409
    assert error.value.code == "MATCH_JOB_ROLE_NOT_AVAILABLE"


async def test_load_scoring_inputs_filters_inactive_capability(db_session) -> None:
    context = await build_matching_context(db_session)
    context.capabilities["Docker"].status = "deprecated"
    await db_session.flush()
    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    inputs = await matching_service.load_scoring_inputs(db_session, watermark)

    first_role = next(
        value
        for value in inputs.job_roles
        if value.job_role_id == context.job_roles[0].id
    )
    assert {value.canonical_name for value in first_role.capabilities} == {
        "Python",
        "PyTorch",
    }


async def test_load_scoring_inputs_requires_valid_required_capability(
    db_session,
) -> None:
    context = await build_matching_context(db_session)
    context.capabilities["Python"].status = "deprecated"
    context.capabilities["Kubernetes"].status = "deprecated"
    await db_session.flush()
    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    with pytest.raises(APIError) as error:
        await matching_service.load_scoring_inputs(db_session, watermark)

    assert error.value.status_code == 503
    assert error.value.code == "MATCH_CATALOG_INCONSISTENT"


async def test_load_scoring_inputs_rejects_zero_required_importance(
    db_session,
) -> None:
    context = await build_matching_context(db_session)
    for relation in await db_session.scalars(
        select(JobRoleCapability).where(
            JobRoleCapability.job_role_id == context.job_roles[1].id
        )
    ):
        relation.importance = Decimal("0")
    await db_session.flush()
    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    with pytest.raises(APIError) as error:
        await matching_service.load_scoring_inputs(db_session, watermark)

    assert error.value.status_code == 503
    assert error.value.code == "MATCH_CATALOG_INCONSISTENT"


async def test_load_scoring_inputs_rejects_zero_bonus_importance(
    db_session,
) -> None:
    context = await build_matching_context(db_session)
    relation = await db_session.get(
        JobRoleCapability,
        (context.job_roles[0].id, context.capabilities["Docker"].id),
    )
    relation.importance = Decimal("0")
    await db_session.flush()
    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    with pytest.raises(APIError) as error:
        await matching_service.load_scoring_inputs(db_session, watermark)

    assert error.value.status_code == 503
    assert error.value.code == "MATCH_CATALOG_INCONSISTENT"


async def test_load_scoring_inputs_rejects_invalid_match_policy(db_session) -> None:
    context = await build_matching_context(db_session)
    context.job_roles[0].definition_payload = {
        **context.job_roles[0].definition_payload,
        "match_policy": {"minimum_education_level": "unknown"},
    }
    await db_session.flush()
    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    with pytest.raises(APIError) as error:
        await matching_service.load_scoring_inputs(db_session, watermark)

    assert error.value.status_code == 503
    assert error.value.code == "MATCH_CATALOG_INCONSISTENT"


async def test_load_scoring_inputs_allows_no_mapped_skills(db_session) -> None:
    context = await build_matching_context(db_session)
    await db_session.execute(
        delete(ResumeSkill).where(
            ResumeSkill.profile_id == context.profile.id,
            ResumeSkill.mapping_status == "mapped",
        )
    )
    watermark = await matching_service.load_match_watermark(
        db_session,
        context.applicant,
        context.resume.id,
    )

    inputs = await matching_service.load_scoring_inputs(db_session, watermark)

    assert inputs.profile.skills == {}


async def test_create_recommendations_persists_complete_atomic_run(
    db_session,
) -> None:
    context = await build_matching_context(db_session)

    created = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.admin,
        context.resume.id,
        request_id="matching-create",
        ip_address="127.0.0.1",
    )

    assert created.reused is False
    assert created.run.owner_user_id == context.applicant.id
    assert created.run.resume_id == context.resume.id
    assert created.run.resume_profile_id == context.profile.id
    assert created.run.graph_version_id == context.graph.id
    assert created.run.catalog_version_id == context.catalog.id
    assert created.run.weight_version == "match_weights_v1"
    assert created.run.weight_snapshot["algorithm"] == "exact_capability_match_v1"
    assert created.run.result_count == 2
    assert (
        created.run.high_count + created.run.medium_count + created.run.low_count == 2
    )
    assert [value.rank for value in created.results] == [1, 2]
    stored = (
        await db_session.scalars(
            select(MatchResult)
            .where(MatchResult.match_run_id == created.run.id)
            .order_by(MatchResult.rank)
        )
    ).all()
    assert len(stored) == 2
    assert all(value.dimension_scores for value in stored)
    assert all(value.job_role_snapshot for value in stored)
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "job_recommendation.run.create",
            AuditLog.resource_id == created.run.id,
        )
    )
    assert audit.actor_user_id == context.admin.id
    assert audit.metadata_ == {
        "resume_id": str(context.resume.id),
        "resume_profile_id": str(context.profile.id),
        "graph_version_id": str(context.graph.id),
        "catalog_version_id": str(context.catalog.id),
        "weight_version": "match_weights_v1",
        "result_count": 2,
    }


async def test_create_recommendations_saves_all_but_returns_top_twenty(
    db_session,
) -> None:
    context = await build_matching_context(db_session)
    for index in range(19):
        await add_catalog_job_role(
            db_session,
            context,
            f"Additional Role {index:02d}",
        )

    created = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-top-twenty",
        ip_address=None,
    )

    assert created.run.result_count == 21
    assert len(created.results) == 20
    assert [value.rank for value in created.results] == list(range(1, 21))
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(MatchResult)
            .where(MatchResult.match_run_id == created.run.id)
        )
        == 21
    )


async def test_create_recommendations_allows_no_mapped_skills(db_session) -> None:
    context = await build_matching_context(db_session)
    await db_session.execute(
        delete(ResumeSkill).where(
            ResumeSkill.profile_id == context.profile.id,
            ResumeSkill.mapping_status == "mapped",
        )
    )

    created = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-no-skills",
        ip_address=None,
    )

    assert created.run.result_count == 2
    assert all(
        result.dimension_scores["required_skill_coverage"]["score"] == 0.0
        for result in created.results
    )
    assert all(
        result.dimension_scores["skill_evidence_quality"]["score"] == 0.0
        for result in created.results
    )
    no_bonus = next(
        result
        for result in created.results
        if result.job_role_id == context.job_roles[1].id
    )
    assert no_bonus.dimension_scores["bonus_skill_coverage"] == {
        "score": 100.0,
        "status": "not_required",
        "matched_count": 0,
        "total_count": 0,
        "matched_importance": 0.0,
        "total_importance": 0.0,
    }


async def test_create_recommendations_reuses_same_natural_key(db_session) -> None:
    context = await build_matching_context(db_session)
    first = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-first",
        ip_address=None,
    )
    second = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-second",
        ip_address=None,
    )

    assert first.reused is False
    assert second.reused is True
    assert second.run.id == first.run.id
    assert await db_session.scalar(select(func.count()).select_from(MatchRun)) == 1
    actions = (
        await db_session.scalars(
            select(AuditLog.action)
            .where(AuditLog.resource_id == first.run.id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    ).all()
    assert sorted(actions) == sorted(
        [
            "job_recommendation.run.create",
            "job_recommendation.run.reuse",
        ]
    )


async def test_new_confirmed_profile_creates_new_match_run(db_session) -> None:
    context = await build_matching_context(db_session)
    first = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-profile-one",
        ip_address=None,
    )
    now = datetime.now(UTC)
    context.profile.status = "superseded"
    replacement = ResumeProfile(
        resume_id=context.resume.id,
        base_profile_id=context.profile.id,
        version_no=2,
        extraction_version=context.profile.extraction_version,
        profile_source="manual_revision",
        extracted_text=context.profile.extracted_text,
        text_extraction_method=context.profile.text_extraction_method,
        highest_education_level="bachelor",
        total_experience_months=36,
        structured_payload={},
        status="confirmed",
        created_by_run_id=None,
        created_by_user_id=context.applicant.id,
        confirmed_at=now,
    )
    db_session.add(replacement)
    await db_session.flush()

    second = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-profile-two",
        ip_address=None,
    )

    assert second.reused is False
    assert second.run.id != first.run.id
    assert second.run.resume_profile_id == replacement.id


async def test_new_graph_version_creates_new_match_run(db_session) -> None:
    context = await build_matching_context(db_session)
    first = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-graph-one",
        ip_address=None,
    )
    graph, catalog = await publish_next_graph_version(db_session, context)

    second = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-graph-two",
        ip_address=None,
    )

    assert second.reused is False
    assert second.run.id != first.run.id
    assert second.run.graph_version_id == graph.id
    assert second.run.catalog_version_id == catalog.id


async def test_current_weight_version_does_not_reuse_legacy_run(db_session) -> None:
    context = await build_matching_context(db_session)
    legacy = MatchRun(
        owner_user_id=context.applicant.id,
        resume_id=context.resume.id,
        resume_profile_id=context.profile.id,
        graph_version_id=context.graph.id,
        catalog_version_id=context.catalog.id,
        weight_version="legacy_test_version",
        weight_snapshot={},
        result_count=0,
        high_count=0,
        medium_count=0,
        low_count=0,
    )
    db_session.add(legacy)
    await db_session.flush()

    created = await matching_service.create_or_reuse_recommendations(
        db_session,
        context.applicant,
        context.resume.id,
        request_id="matching-current-weight",
        ip_address=None,
    )

    assert created.reused is False
    assert created.run.id != legacy.id
    assert created.run.weight_version == "match_weights_v1"


async def test_create_recommendations_rolls_back_run_results_and_audit(
    db_session,
    monkeypatch,
) -> None:
    context = await build_matching_context(db_session)
    await db_session.commit()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(matching_service, "record_audit", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await matching_service.create_or_reuse_recommendations(
            db_session,
            context.applicant,
            context.resume.id,
            request_id="matching-rollback",
            ip_address=None,
        )

    assert await db_session.scalar(select(func.count()).select_from(MatchRun)) == 0
    assert await db_session.scalar(select(func.count()).select_from(MatchResult)) == 0
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "job_recommendation.run.create")
        )
        == 0
    )


async def test_create_recommendations_maps_catalog_error_and_rolls_back(
    db_session,
    monkeypatch,
) -> None:
    context = await build_matching_context(db_session)

    async def fail_catalog(*args, **kwargs):
        raise MatchCatalogInconsistent("invalid catalog")

    monkeypatch.setattr(matching_service, "load_scoring_inputs", fail_catalog)

    with pytest.raises(APIError) as error:
        await matching_service.create_or_reuse_recommendations(
            db_session,
            context.applicant,
            context.resume.id,
            request_id="matching-catalog-error",
            ip_address=None,
        )

    assert error.value.status_code == 503
    assert error.value.code == "MATCH_CATALOG_INCONSISTENT"
    assert await db_session.scalar(select(func.count()).select_from(MatchRun)) == 0


async def test_create_recommendations_concurrent_requests_reuse_one_complete_run(
    db_session,
) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    setup_session = AsyncSession(engine, expire_on_commit=False)
    context = await build_matching_context(setup_session)
    await setup_session.commit()
    ids = {
        "user_ids": [
            context.applicant.id,
            context.other_applicant.id,
            context.admin.id,
            context.hr.id,
        ],
        "resume_id": context.resume.id,
        "profile_id": context.profile.id,
        "catalog_id": context.catalog.id,
        "graph_id": context.graph.id,
        "domain_id": context.domain.id,
        "capability_ids": [value.id for value in context.capabilities.values()],
        "job_role_ids": [value.id for value in context.job_roles],
        "proposal_id": context.proposal.id,
        "file_id": context.resume.file_id,
        "processing_run_id": context.profile.created_by_run_id,
    }
    await setup_session.close()
    first_session = session_factory()
    second_session = session_factory()
    run_id = None

    async def run(session: AsyncSession, request_id: str):
        return await matching_service.create_or_reuse_recommendations(
            session,
            context.applicant,
            context.resume.id,
            request_id=request_id,
            ip_address=None,
        )

    try:
        first, second = await asyncio.gather(
            run(first_session, "matching-concurrent-one"),
            run(second_session, "matching-concurrent-two"),
        )
        assert {first.reused, second.reused} == {False, True}
        assert first.run.id == second.run.id
        run_id = first.run.id
        assert len(first.results) == len(second.results) == 2
        assert (
            await first_session.scalar(select(func.count()).select_from(MatchRun)) == 1
        )
        assert (
            await first_session.scalar(
                select(func.count())
                .select_from(MatchResult)
                .where(MatchResult.match_run_id == first.run.id)
            )
            == 2
        )
    finally:
        await first_session.close()
        await second_session.close()
        cleanup = AsyncSession(engine, expire_on_commit=False)
        try:
            if run_id is not None:
                await cleanup.execute(
                    delete(AuditLog).where(AuditLog.resource_id == run_id)
                )
                await cleanup.execute(
                    delete(MatchResult).where(MatchResult.match_run_id == run_id)
                )
                await cleanup.execute(delete(MatchRun).where(MatchRun.id == run_id))
            await cleanup.execute(
                delete(ResumeSkill).where(ResumeSkill.profile_id == ids["profile_id"])
            )
            await cleanup.execute(
                delete(ResumeProfile).where(ResumeProfile.id == ids["profile_id"])
            )
            await cleanup.execute(delete(Resume).where(Resume.id == ids["resume_id"]))
            await cleanup.execute(
                delete(ProcessingRun).where(
                    ProcessingRun.id == ids["processing_run_id"]
                )
            )
            await cleanup.execute(
                delete(CatalogVersionItem).where(
                    CatalogVersionItem.catalog_version_id == ids["catalog_id"]
                )
            )
            await cleanup.execute(
                delete(JobRoleCapability).where(
                    JobRoleCapability.job_role_id.in_(ids["job_role_ids"])
                )
            )
            await cleanup.execute(
                delete(GraphVersion).where(GraphVersion.id == ids["graph_id"])
            )
            await cleanup.execute(
                delete(CatalogVersion).where(CatalogVersion.id == ids["catalog_id"])
            )
            await cleanup.execute(
                delete(JobRole).where(JobRole.id.in_(ids["job_role_ids"]))
            )
            await cleanup.execute(
                delete(GraphChangeCandidate).where(
                    GraphChangeCandidate.id == ids["proposal_id"]
                )
            )
            await cleanup.execute(
                delete(Capability).where(Capability.id.in_(ids["capability_ids"]))
            )
            await cleanup.execute(delete(Domain).where(Domain.id == ids["domain_id"]))
            await cleanup.execute(
                delete(StoredFile).where(StoredFile.id == ids["file_id"])
            )
            await cleanup.execute(delete(User).where(User.id.in_(ids["user_ids"])))
            await cleanup.commit()
        finally:
            await cleanup.close()
            await engine.dispose()
