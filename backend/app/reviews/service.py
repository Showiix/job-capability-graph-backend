from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import User
from app.catalog.models import Capability
from app.core.errors import APIError
from app.discovery.models import (
    CombinationEvidence,
    CombinationSkill,
    SkillCombinationCandidate,
)
from app.reviews import REVIEW_DISCLAIMER
from app.reviews.models import GraphChangeCandidate, ReviewDecision
from app.reviews.schemas import ReviewDecisionCreate, RoleDefinitionPayload

FINAL_STATUSES = {"approved", "rejected"}


async def create_review_proposal(
    db: AsyncSession,
    actor: User,
    candidate_id: UUID,
    *,
    request_id: str,
    ip_address: str | None,
) -> dict:
    candidate = await db.get(SkillCombinationCandidate, candidate_id)
    if candidate is None:
        raise APIError(
            404,
            "REVIEW_SOURCE_CANDIDATE_NOT_FOUND",
            "候选技能组合不存在",
        )
    existing = await db.scalar(
        select(GraphChangeCandidate).where(
            GraphChangeCandidate.source_candidate_id == candidate.id
        )
    )
    if existing is not None:
        return await get_review_proposal(db, existing.id)

    skill_rows = (
        await db.execute(
            select(CombinationSkill, Capability)
            .join(Capability, Capability.id == CombinationSkill.capability_id)
            .where(CombinationSkill.candidate_id == candidate.id)
            .order_by(Capability.canonical_name, Capability.id)
        )
    ).all()
    evidence_count = await db.scalar(
        select(func.count())
        .select_from(CombinationEvidence)
        .where(CombinationEvidence.candidate_id == candidate.id)
    )
    representative_count = await db.scalar(
        select(func.count())
        .select_from(CombinationEvidence)
        .where(
            CombinationEvidence.candidate_id == candidate.id,
            CombinationEvidence.representative.is_(True),
        )
    )
    if (
        len(skill_rows) < 2
        or any(capability.status != "active" for _, capability in skill_rows)
        or not evidence_count
    ):
        raise APIError(
            409,
            "REVIEW_PROPOSAL_SOURCE_INVALID",
            "候选缺少有效技能或证据，无法进入审核",
        )

    required_ids = [capability.id for _, capability in skill_rows]
    payload = RoleDefinitionPayload(
        role_name=candidate.suggested_name,
        required_capability_ids=required_ids,
        generation_source="deterministic_baseline",
        definition_status="needs_enrichment",
    ).model_dump(mode="json")
    proposal = GraphChangeCandidate(
        id=uuid4(),
        source_candidate_id=candidate.id,
        change_type="create_job_role",
        proposed_payload=payload,
        source_snapshot={
            "candidate_id": str(candidate.id),
            "discovery_run_id": str(candidate.discovery_run_id),
            "suggested_name": candidate.suggested_name,
            "skills": [
                {
                    "capability_id": str(capability.id),
                    "canonical_name": capability.canonical_name,
                    "skill_role": skill.skill_role,
                    "weight": float(skill.weight),
                    "frequency": float(skill.frequency),
                }
                for skill, capability in skill_rows
            ],
            "overall_candidate_score": float(candidate.overall_candidate_score),
        },
        evidence_summary={
            "support_job_count": candidate.support_job_count,
            "source_count": candidate.source_count,
            "company_count": candidate.company_count,
            "evidence_count": evidence_count,
            "representative_evidence_count": representative_count or 0,
        },
        confidence=candidate.overall_candidate_score,
        review_status="pending",
        created_by_user_id=actor.id,
    )
    db.add(proposal)
    candidate.status = "proposed_for_review"
    record_audit(
        db,
        action="review.proposal.create",
        resource_type="graph_change_candidate",
        resource_id=proposal.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"source_candidate_id": str(candidate.id)},
    )
    await db.commit()
    await db.refresh(proposal)
    return await get_review_proposal(db, proposal.id)


async def decide_review_proposal(
    db: AsyncSession,
    actor: User,
    proposal_id: UUID,
    payload: ReviewDecisionCreate,
    *,
    request_id: str,
    ip_address: str | None,
) -> dict:
    proposal = await _get_proposal(db, proposal_id)
    if proposal.review_status in FINAL_STATUSES:
        raise APIError(
            409,
            "REVIEW_PROPOSAL_ALREADY_FINAL",
            "审核提案已经进入终态",
        )
    if payload.decision in {"revise", "reject"} and not payload.comment:
        raise APIError(
            422,
            "REVIEW_DECISION_COMMENT_REQUIRED",
            "修改或不采纳时必须填写审核意见",
        )
    if payload.decision == "revise" and payload.after_payload is None:
        raise APIError(
            422,
            "REVIEW_DEFINITION_REQUIRED",
            "修改时必须提交岗位定义",
        )

    before_payload = deepcopy(proposal.proposed_payload)
    after_payload = before_payload
    if payload.decision in {"approve", "revise"} and payload.after_payload:
        after_payload = await _validated_payload(db, payload.after_payload)
        proposal.proposed_payload = after_payload

    reviewed_at = datetime.now(UTC)
    proposal.review_status = {
        "approve": "approved",
        "revise": "needs_revision",
        "reject": "rejected",
    }[payload.decision]
    proposal.reviewed_by_user_id = actor.id
    proposal.reviewed_at = reviewed_at
    db.add(
        ReviewDecision(
            id=uuid4(),
            graph_change_candidate_id=proposal.id,
            reviewer_user_id=actor.id,
            decision=payload.decision,
            before_payload=before_payload,
            after_payload=after_payload,
            comment=payload.comment,
        )
    )
    if proposal.source_candidate_id is not None:
        candidate = await db.get(
            SkillCombinationCandidate,
            proposal.source_candidate_id,
        )
        if candidate is not None:
            if payload.decision == "revise":
                candidate.status = "feedback_collected"
            elif payload.decision == "reject":
                candidate.status = "rejected"
    record_audit(
        db,
        action="review.proposal.decision",
        resource_type="graph_change_candidate",
        resource_id=proposal.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"decision": payload.decision},
    )
    await db.commit()
    await db.refresh(proposal)
    return await get_review_proposal(db, proposal.id)


async def list_review_proposals(
    db: AsyncSession,
    *,
    status: str | None,
    page: int,
    page_size: int,
) -> list[dict]:
    statement = select(GraphChangeCandidate)
    if status is not None:
        statement = statement.where(GraphChangeCandidate.review_status == status)
    proposals = (
        await db.scalars(
            statement.order_by(
                GraphChangeCandidate.created_at.desc(),
                GraphChangeCandidate.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_proposal_data(value, decisions=None) for value in proposals]


async def get_review_proposal(db: AsyncSession, proposal_id: UUID) -> dict:
    proposal = await _get_proposal(db, proposal_id)
    decisions = (
        await db.scalars(
            select(ReviewDecision)
            .where(ReviewDecision.graph_change_candidate_id == proposal.id)
            .order_by(ReviewDecision.created_at, ReviewDecision.id)
        )
    ).all()
    return _proposal_data(proposal, decisions=decisions)


async def _get_proposal(
    db: AsyncSession,
    proposal_id: UUID,
) -> GraphChangeCandidate:
    proposal = await db.get(GraphChangeCandidate, proposal_id)
    if proposal is None:
        raise APIError(404, "REVIEW_PROPOSAL_NOT_FOUND", "审核提案不存在")
    return proposal


async def _validated_payload(
    db: AsyncSession,
    payload: RoleDefinitionPayload,
) -> dict:
    required_ids = set(payload.required_capability_ids)
    bonus_ids = set(payload.bonus_capability_ids)
    if required_ids & bonus_ids:
        raise APIError(
            422,
            "REVIEW_CAPABILITY_OVERLAP",
            "必备技能和加分技能不能重复",
        )
    capability_ids = required_ids | bonus_ids
    active_ids = set(
        await db.scalars(
            select(Capability.id).where(
                Capability.id.in_(capability_ids),
                Capability.status == "active",
            )
        )
    )
    if active_ids != capability_ids:
        raise APIError(
            422,
            "REVIEW_CAPABILITY_INVALID",
            "岗位定义包含不存在或未启用的技能",
        )
    value = payload.model_dump(mode="json")
    value.update(
        generation_source="human_revision",
        definition_status="reviewed",
        disclaimer=REVIEW_DISCLAIMER,
    )
    return value


def _proposal_data(
    proposal: GraphChangeCandidate,
    *,
    decisions: list[ReviewDecision] | None,
) -> dict:
    value = {
        "id": proposal.id,
        "source_candidate_id": proposal.source_candidate_id,
        "change_type": proposal.change_type,
        "proposed_payload": proposal.proposed_payload,
        "source_snapshot": proposal.source_snapshot,
        "evidence_summary": proposal.evidence_summary,
        "confidence": float(proposal.confidence),
        "review_status": proposal.review_status,
        "created_by_user_id": proposal.created_by_user_id,
        "reviewed_by_user_id": proposal.reviewed_by_user_id,
        "reviewed_at": proposal.reviewed_at,
        "created_at": proposal.created_at,
        "updated_at": proposal.updated_at,
    }
    if decisions is not None:
        value["decisions"] = [
            {
                "id": decision.id,
                "reviewer_user_id": decision.reviewer_user_id,
                "decision": decision.decision,
                "before_payload": decision.before_payload,
                "after_payload": decision.after_payload,
                "comment": decision.comment,
                "created_at": decision.created_at,
            }
            for decision in decisions
        ]
    return value
