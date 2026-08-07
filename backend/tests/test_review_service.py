from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.auth.models import User
from app.catalog.models import Capability, Domain
from app.core.errors import APIError
from app.core.security import hash_password
from app.discovery.models import (
    CombinationEvidence,
    CombinationSkill,
    DiscoveryRun,
    SkillCombinationCandidate,
)
from app.files.models import StoredFile
from app.imports.models import (
    DataSource,
    ImportBatch,
    NormalizedJobPosting,
    RawJobPosting,
)
from app.processing.models import ProcessingRun
from app.reviews.models import GraphChangeCandidate, ReviewDecision
from app.reviews.schemas import ReviewDecisionCreate, RoleDefinitionPayload
from app.reviews.service import create_review_proposal, decide_review_proposal


@pytest_asyncio.fixture
async def review_context(db_session):
    actor = User(
        id=uuid4(),
        username="review_service_admin",
        username_normalized="review_service_admin",
        password_hash=hash_password("review-service-password"),
        display_name="Review Admin",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(actor)
    await db_session.flush()

    source = await db_session.scalar(
        select(DataSource).where(DataSource.code == "standard")
    )
    file_id = uuid4()
    stored_file = StoredFile(
        id=file_id,
        uploaded_by_user_id=actor.id,
        original_name="review.tsv",
        storage_key=f"reviews/{file_id}.tsv",
        media_type="text/tab-separated-values",
        extension="tsv",
        size_bytes=10,
        sha256=uuid4().hex * 2,
        category="market_jd",
        scan_status="not_required",
        status="attached",
    )
    batch = ImportBatch(
        id=uuid4(),
        source_id=source.id,
        file_id=file_id,
        uploaded_by_user_id=actor.id,
        collected_at=datetime.now(UTC),
        status="processed",
        total_rows=1,
        accepted_rows=1,
        batch_summary={},
    )
    raw = RawJobPosting(
        id=uuid4(),
        batch_id=batch.id,
        row_number=1,
        source_code="standard",
        job_name="AI Test Engineer",
        source_tags=["Python", "自动化测试"],
        raw_payload={},
        parse_warnings=[],
    )
    normalized = NormalizedJobPosting(
        id=uuid4(),
        raw_job_id=raw.id,
        version_no=1,
        normalization_version="rules_v1",
        normalized_title="AI Test Engineer",
        quality_score=90,
        quality_flags=[],
        is_current=True,
    )
    db_session.add(stored_file)
    await db_session.flush()
    db_session.add(batch)
    await db_session.flush()
    db_session.add(raw)
    await db_session.flush()
    db_session.add(normalized)
    await db_session.flush()

    domain = Domain(
        id=uuid4(),
        code="review-service",
        name="Review Service",
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
    docker = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Docker",
        status="active",
        skill_type="tool",
        source_type="manual",
    )
    deprecated = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Deprecated Skill",
        status="deprecated",
        skill_type="other",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add_all([python, testing, docker, deprecated])
    await db_session.flush()

    discovery_id = uuid4()
    processing_run = ProcessingRun(
        id=uuid4(),
        run_type="discover_skill_combinations",
        subject_type="discovery_run",
        subject_id=discovery_id,
        created_by_user_id=actor.id,
        owner_scope_type="admin_global",
        status="completed",
        pipeline_version="cooccurrence_pairs_v1",
        input_snapshot={},
        result_summary={},
    )
    discovery_run = DiscoveryRun(
        id=discovery_id,
        processing_run_id=processing_run.id,
        input_batch_ids=[batch.id],
        algorithm_version="cooccurrence_pairs_v1",
        extraction_version="source_tags_v1",
        parameters={},
        status="completed",
        summary={},
        created_by_user_id=actor.id,
    )
    candidate = SkillCombinationCandidate(
        id=uuid4(),
        discovery_run_id=discovery_run.id,
        suggested_name="Python + 自动化测试",
        normalized_name="python + 自动化测试",
        definition_payload={"novelty_status": "not_evaluated"},
        support_job_count=3,
        source_count=1,
        company_count=2,
        support_score=0.8,
        diversity_score=0.5,
        coherence_score=1,
        novelty_score=0,
        evidence_score=0.9,
        overall_candidate_score=0.8,
        status="candidate",
    )
    db_session.add(processing_run)
    await db_session.flush()
    db_session.add(discovery_run)
    await db_session.flush()
    db_session.add(candidate)
    await db_session.flush()
    db_session.add_all(
        [
            CombinationSkill(
                candidate_id=candidate.id,
                capability_id=python.id,
                skill_role="core",
                weight=1,
                frequency=1,
            ),
            CombinationSkill(
                candidate_id=candidate.id,
                capability_id=testing.id,
                skill_role="core",
                weight=1,
                frequency=1,
            ),
            CombinationEvidence(
                candidate_id=candidate.id,
                normalized_job_id=normalized.id,
                evidence_weight=0.9,
                representative=True,
            ),
        ]
    )
    await db_session.flush()
    return SimpleNamespace(
        actor=actor,
        candidate=candidate,
        python=python,
        testing=testing,
        docker=docker,
        deprecated=deprecated,
    )


async def _create(db_session, context):
    return await create_review_proposal(
        db_session,
        context.actor,
        context.candidate.id,
        request_id="request-create",
        ip_address="127.0.0.1",
    )


def _revised_payload(context, **overrides) -> RoleDefinitionPayload:
    values = {
        "role_name": "AI 自动化测试工程师",
        "core_responsibilities": ["建设 AI 产品自动化测试体系"],
        "required_capability_ids": [context.python.id, context.testing.id],
        "bonus_capability_ids": [context.docker.id],
        "industry_scenarios": ["AI 产品质量保障"],
        "generation_source": "human_revision",
        "definition_status": "reviewed",
    }
    values.update(overrides)
    return RoleDefinitionPayload(**values)


async def test_role_definition_payload_accepts_optional_match_policy(
    review_context,
) -> None:
    payload = _revised_payload(
        review_context,
        match_policy={
            "minimum_education_level": "bachelor",
            "recommended_experience_months": 24,
        },
    )

    assert payload.model_dump(mode="json")["match_policy"] == {
        "minimum_education_level": "bachelor",
        "recommended_experience_months": 24,
    }
    assert _revised_payload(review_context).model_dump(mode="json")[
        "match_policy"
    ] is None
    partial = _revised_payload(
        review_context,
        match_policy={"minimum_education_level": "master"},
    )
    assert partial.match_policy.minimum_education_level == "master"
    assert partial.match_policy.recommended_experience_months is None


@pytest.mark.parametrize(
    "match_policy",
    [
        {"minimum_education_level": "unknown"},
        {"minimum_education_level": "other"},
        {"recommended_experience_months": -1},
        {"recommended_experience_months": 601},
    ],
)
async def test_role_definition_payload_rejects_invalid_match_policy(
    review_context,
    match_policy,
) -> None:
    with pytest.raises(ValidationError):
        _revised_payload(review_context, match_policy=match_policy)


async def test_create_proposal_builds_baseline_and_is_idempotent(
    db_session,
    review_context,
) -> None:
    first = await _create(db_session, review_context)
    second = await _create(db_session, review_context)

    assert first["id"] == second["id"]
    assert first["review_status"] == "pending"
    assert first["proposed_payload"]["role_name"] == "Python + 自动化测试"
    assert first["proposed_payload"]["core_responsibilities"] == []
    assert set(first["proposed_payload"]["required_capability_ids"]) == {
        str(review_context.python.id),
        str(review_context.testing.id),
    }
    assert first["proposed_payload"]["generation_source"] == (
        "deterministic_baseline"
    )
    assert first["evidence_summary"] == {
        "support_job_count": 3,
        "source_count": 1,
        "company_count": 2,
        "evidence_count": 1,
        "representative_evidence_count": 1,
    }
    assert review_context.candidate.status == "proposed_for_review"
    assert await db_session.scalar(
        select(func.count()).select_from(GraphChangeCandidate)
    ) == 1
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "review.proposal.create"
        )
    ) == 1


async def test_create_proposal_requires_skills_and_evidence(
    db_session,
    review_context,
) -> None:
    await db_session.execute(
        CombinationEvidence.__table__.delete().where(
            CombinationEvidence.candidate_id == review_context.candidate.id
        )
    )
    await db_session.flush()

    with pytest.raises(APIError) as error:
        await _create(db_session, review_context)

    assert error.value.code == "REVIEW_PROPOSAL_SOURCE_INVALID"


async def test_revise_records_snapshots_and_feedback(
    db_session,
    review_context,
) -> None:
    proposal = await _create(db_session, review_context)
    result = await decide_review_proposal(
        db_session,
        review_context.actor,
        proposal["id"],
        ReviewDecisionCreate(
            decision="revise",
            after_payload=_revised_payload(review_context),
            comment="岗位名称和职责需要更明确",
        ),
        request_id="request-revise",
        ip_address="127.0.0.1",
    )

    assert result["review_status"] == "needs_revision"
    assert result["proposed_payload"]["role_name"] == "AI 自动化测试工程师"
    assert result["proposed_payload"]["generation_source"] == "human_revision"
    assert review_context.candidate.status == "feedback_collected"
    decision = await db_session.scalar(select(ReviewDecision))
    assert decision.before_payload["role_name"] == "Python + 自动化测试"
    assert decision.after_payload["role_name"] == "AI 自动化测试工程师"
    assert decision.comment == "岗位名称和职责需要更明确"


async def test_approve_can_confirm_edited_definition(
    db_session,
    review_context,
) -> None:
    proposal = await _create(db_session, review_context)
    result = await decide_review_proposal(
        db_session,
        review_context.actor,
        proposal["id"],
        ReviewDecisionCreate(
            decision="approve",
            after_payload=_revised_payload(review_context),
            comment="确认采纳",
        ),
        request_id="request-approve",
        ip_address=None,
    )

    assert result["review_status"] == "approved"
    assert result["proposed_payload"]["role_name"] == "AI 自动化测试工程师"
    assert result["reviewed_by_user_id"] == review_context.actor.id
    assert result["reviewed_at"] is not None


async def test_reject_requires_comment_and_terminal_state_is_read_only(
    db_session,
    review_context,
) -> None:
    proposal = await _create(db_session, review_context)
    with pytest.raises(APIError) as missing_comment:
        await decide_review_proposal(
            db_session,
            review_context.actor,
            proposal["id"],
            ReviewDecisionCreate(decision="reject"),
            request_id="request-reject-empty",
            ip_address=None,
        )
    assert missing_comment.value.code == "REVIEW_DECISION_COMMENT_REQUIRED"

    rejected = await decide_review_proposal(
        db_session,
        review_context.actor,
        proposal["id"],
        ReviewDecisionCreate(decision="reject", comment="证据不足"),
        request_id="request-reject",
        ip_address=None,
    )
    assert rejected["review_status"] == "rejected"
    assert review_context.candidate.status == "rejected"

    with pytest.raises(APIError) as terminal:
        await decide_review_proposal(
            db_session,
            review_context.actor,
            proposal["id"],
            ReviewDecisionCreate(decision="approve"),
            request_id="request-after-reject",
            ip_address=None,
        )
    assert terminal.value.code == "REVIEW_PROPOSAL_ALREADY_FINAL"


@pytest.mark.parametrize("kind", ["missing", "deprecated", "overlap"])
async def test_revised_definition_requires_valid_active_capabilities(
    db_session,
    review_context,
    kind,
) -> None:
    proposal = await _create(db_session, review_context)
    if kind == "missing":
        payload = _revised_payload(
            review_context,
            bonus_capability_ids=[uuid4()],
        )
        expected_code = "REVIEW_CAPABILITY_INVALID"
    elif kind == "deprecated":
        payload = _revised_payload(
            review_context,
            bonus_capability_ids=[review_context.deprecated.id],
        )
        expected_code = "REVIEW_CAPABILITY_INVALID"
    else:
        payload = _revised_payload(
            review_context,
            bonus_capability_ids=[review_context.python.id],
        )
        expected_code = "REVIEW_CAPABILITY_OVERLAP"

    with pytest.raises(APIError) as error:
        await decide_review_proposal(
            db_session,
            review_context.actor,
            proposal["id"],
            ReviewDecisionCreate(
                decision="revise",
                after_payload=payload,
                comment="调整技能",
            ),
            request_id="request-invalid-capability",
            ip_address=None,
        )

    assert error.value.code == expected_code
