from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.catalog.models import Capability, Domain
from app.discovery.models import DiscoveryRun, SkillCombinationCandidate
from app.processing.models import ProcessingRun
from app.reviews.models import GraphChangeCandidate, ReviewDecision


async def _context(db_session, user):
    value = uuid4().hex
    domain = Domain(
        id=uuid4(),
        code=f"review-{value}",
        name="Review",
        status="active",
        sort_order=0,
    )
    capabilities = [
        Capability(
            id=uuid4(),
            domain_id=domain.id,
            canonical_name=name,
            status="active",
            skill_type="method",
            source_type="manual",
        )
        for name in ("Python", "自动化测试")
    ]
    processing_run = ProcessingRun(
        id=uuid4(),
        run_type="discover_skill_combinations",
        subject_type="discovery_run",
        subject_id=uuid4(),
        created_by_user_id=user.id,
        owner_scope_type="admin_global",
        pipeline_version="cooccurrence_pairs_v1",
        input_snapshot={},
        result_summary={},
    )
    discovery_run = DiscoveryRun(
        id=processing_run.subject_id,
        processing_run_id=processing_run.id,
        input_batch_ids=[uuid4()],
        algorithm_version="cooccurrence_pairs_v1",
        extraction_version="source_tags_v1",
        parameters={},
        status="completed",
        created_by_user_id=user.id,
    )
    candidate = SkillCombinationCandidate(
        id=uuid4(),
        discovery_run_id=discovery_run.id,
        suggested_name="Python + 自动化测试",
        normalized_name="python + 自动化测试",
        definition_payload={},
        support_job_count=3,
        source_count=1,
        company_count=2,
        support_score=0.8,
        diversity_score=0.5,
        coherence_score=1,
        novelty_score=0,
        evidence_score=0.8,
        overall_candidate_score=0.75,
        status="candidate",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add_all(capabilities)
    await db_session.flush()
    db_session.add(processing_run)
    await db_session.flush()
    db_session.add(discovery_run)
    await db_session.flush()
    db_session.add(candidate)
    await db_session.flush()
    return candidate


def _proposal(candidate, user) -> GraphChangeCandidate:
    return GraphChangeCandidate(
        source_candidate_id=candidate.id,
        change_type="create_job_role",
        proposed_payload={"role_name": candidate.suggested_name},
        source_snapshot={"candidate_id": str(candidate.id)},
        evidence_summary={"support_job_count": candidate.support_job_count},
        confidence=candidate.overall_candidate_score,
        review_status="pending",
        created_by_user_id=user.id,
    )


async def test_source_candidate_has_at_most_one_proposal(db_session, user) -> None:
    candidate = await _context(db_session, user)
    db_session.add_all([_proposal(candidate, user), _proposal(candidate, user)])

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_proposal_enums_scores_and_json_are_constrained(
    db_session,
    user,
) -> None:
    candidate = await _context(db_session, user)
    invalid_values = (
        ("change_type", "update_everything"),
        ("review_status", "published"),
        ("confidence", 1.1),
        ("proposed_payload", []),
        ("source_snapshot", []),
        ("evidence_summary", []),
    )

    for field, value in invalid_values:
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                proposal = _proposal(candidate, user)
                setattr(proposal, field, value)
                db_session.add(proposal)
                await db_session.flush()


async def test_review_decision_enum_and_json_are_constrained(
    db_session,
    user,
) -> None:
    candidate = await _context(db_session, user)
    proposal = _proposal(candidate, user)
    db_session.add(proposal)
    await db_session.flush()
    invalid_values = (
        ("decision", "publish"),
        ("before_payload", []),
        ("after_payload", []),
    )

    for field, value in invalid_values:
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                decision = ReviewDecision(
                    graph_change_candidate_id=proposal.id,
                    reviewer_user_id=user.id,
                    decision="approve",
                    before_payload={},
                    after_payload={},
                )
                setattr(decision, field, value)
                db_session.add(decision)
                await db_session.flush()


async def test_proposal_survives_source_candidate_deletion(db_session, user) -> None:
    candidate = await _context(db_session, user)
    proposal = _proposal(candidate, user)
    db_session.add(proposal)
    await db_session.flush()

    await db_session.delete(candidate)
    await db_session.flush()
    await db_session.refresh(proposal)

    assert proposal.source_candidate_id is None


async def test_deleting_proposal_cascades_review_decisions(db_session, user) -> None:
    candidate = await _context(db_session, user)
    proposal = _proposal(candidate, user)
    db_session.add(proposal)
    await db_session.flush()
    db_session.add(
        ReviewDecision(
            graph_change_candidate_id=proposal.id,
            reviewer_user_id=user.id,
            decision="approve",
            before_payload={},
            after_payload={},
        )
    )
    await db_session.flush()

    await db_session.delete(proposal)
    await db_session.flush()

    count = await db_session.scalar(select(func.count()).select_from(ReviewDecision))
    assert count == 0
