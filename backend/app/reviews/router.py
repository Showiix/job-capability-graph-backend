from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.api.dependencies import CSRF, DB, Staff
from app.reviews.schemas import ReviewDecisionCreate, ReviewProposalCreate
from app.reviews.service import (
    create_review_proposal,
    decide_review_proposal,
    get_review_proposal,
    list_review_proposals,
)

router = APIRouter(prefix="/review-proposals", tags=["reviews"])
ReviewStatus = Literal["pending", "needs_revision", "approved", "rejected"]


@router.post("", status_code=201)
async def create_proposal(
    request: Request,
    payload: ReviewProposalCreate,
    db: DB,
    actor: Staff,
    _csrf: CSRF,
) -> dict:
    return {
        "data": await create_review_proposal(
            db,
            actor,
            payload.candidate_id,
            request_id=request.state.request_id,
            ip_address=request.client.host if request.client else None,
        )
    }


@router.get("")
async def proposals(
    db: DB,
    actor: Staff,
    status: ReviewStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    return {
        "data": await list_review_proposals(
            db,
            status=status,
            page=page,
            page_size=page_size,
        )
    }


@router.get("/{proposal_id}")
async def proposal_detail(proposal_id: UUID, db: DB, actor: Staff) -> dict:
    return {"data": await get_review_proposal(db, proposal_id)}


@router.post("/{proposal_id}/decisions")
async def decide(
    proposal_id: UUID,
    request: Request,
    payload: ReviewDecisionCreate,
    db: DB,
    actor: Staff,
    _csrf: CSRF,
) -> dict:
    return {
        "data": await decide_review_proposal(
            db,
            actor,
            proposal_id,
            payload,
            request_id=request.state.request_id,
            ip_address=request.client.host if request.client else None,
        )
    }

