from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.catalog.models import CatalogVersionItem, JobRoleCapability
from app.core.errors import APIError
from app.matching import service as matching_service
from app.resumes.models import ResumeProfile, ResumeSkill
from app.resumes.service import get_visible_resume
from tests.matching_fixtures import build_matching_context


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
