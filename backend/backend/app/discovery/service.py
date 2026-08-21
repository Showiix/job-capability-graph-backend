from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import User
from app.catalog.models import Capability, CatalogVersion
from app.core.errors import APIError
from app.discovery import DISCOVERY_DISCLAIMER, DISCOVERY_LABEL
from app.discovery.models import (
    CombinationEvidence,
    CombinationSkill,
    DiscoveryRun,
    SkillCombinationCandidate,
)
from app.discovery.schemas import DiscoveryRunCreate
from app.imports.models import (
    ImportBatch,
    NormalizedJobPosting,
    RawJobPosting,
)
from app.processing.models import ProcessingRun
from app.worker import celery_app

ALGORITHM_VERSION = "cooccurrence_pairs_v1"
EXTRACTION_VERSION = "source_tags_v1"
SCORE_WEIGHTS = {
    "support": 0.35,
    "diversity": 0.20,
    "coherence": 0.25,
    "evidence": 0.20,
    "novelty": 0.0,
}


async def create_discovery_run(
    db: AsyncSession,
    actor: User,
    payload: DiscoveryRunCreate,
    *,
    request_id: str,
    ip_address: str | None,
) -> dict:
    batches = (
        await db.scalars(
            select(ImportBatch).where(ImportBatch.id.in_(payload.batch_ids))
        )
    ).all()
    if len(batches) != len(payload.batch_ids):
        raise APIError(404, "DISCOVERY_BATCH_NOT_FOUND", "导入批次不存在")
    if any(batch.status not in {"processed", "partial"} for batch in batches):
        raise APIError(409, "DISCOVERY_BATCH_NOT_READY", "导入批次尚未处理完成")

    source_count = await db.scalar(
        select(func.count(func.distinct(RawJobPosting.source_code))).where(
            RawJobPosting.batch_id.in_(payload.batch_ids)
        )
    )
    if payload.minimum_source_count > (source_count or 0):
        raise APIError(
            422,
            "DISCOVERY_SOURCE_THRESHOLD_INVALID",
            "最小来源数超过输入数据的实际来源数",
            {"actual_source_count": source_count or 0},
        )

    catalog_version_id = await db.scalar(
        select(CatalogVersion.id).where(
            CatalogVersion.status == "published",
            CatalogVersion.is_current.is_(True),
        )
    )
    discovery_id = uuid4()
    processing_run = ProcessingRun(
        id=uuid4(),
        run_type="discover_skill_combinations",
        subject_type="discovery_run",
        subject_id=discovery_id,
        created_by_user_id=actor.id,
        owner_scope_type="admin_global",
        status="pending",
        pipeline_version=ALGORITHM_VERSION,
        input_snapshot={
            "batch_ids": [str(value) for value in payload.batch_ids],
            **payload.model_dump(exclude={"batch_ids"}),
        },
        result_summary={},
    )
    parameters = {
        "algorithm": ALGORITHM_VERSION,
        **payload.model_dump(exclude={"batch_ids"}),
        "score_weights": SCORE_WEIGHTS,
    }
    discovery_run = DiscoveryRun(
        id=discovery_id,
        processing_run_id=processing_run.id,
        input_batch_ids=payload.batch_ids,
        current_catalog_version_id=catalog_version_id,
        algorithm_version=ALGORITHM_VERSION,
        extraction_version=EXTRACTION_VERSION,
        parameters=parameters,
        status="pending",
        summary={},
        created_by_user_id=actor.id,
    )
    db.add(processing_run)
    await db.flush()
    db.add(discovery_run)
    record_audit(
        db,
        action="discovery.create",
        resource_type="discovery_run",
        resource_id=discovery_run.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"processing_run_id": str(processing_run.id)},
    )
    await db.commit()
    try:
        task = celery_app.send_task(
            "app.discover_skill_combinations",
            args=[str(processing_run.id)],
        )
        processing_run.celery_task_id = task.id
        processing_run.enqueued_at = datetime.now(UTC)
    except Exception:
        processing_run.status = "enqueue_failed"
        processing_run.error_code = "TASK_ENQUEUE_FAILED"
        processing_run.error_message = "任务暂时无法投递，可稍后重试"
    await db.commit()
    return {
        "resource_id": discovery_run.id,
        "run_id": processing_run.id,
        "status": processing_run.status,
        "poll_url": f"/api/v1/processing-runs/{processing_run.id}",
    }


async def list_discovery_runs(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
) -> list[dict]:
    rows = (
        await db.execute(
            select(DiscoveryRun, ProcessingRun)
            .join(
                ProcessingRun,
                ProcessingRun.id == DiscoveryRun.processing_run_id,
            )
            .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [
        _run_data(discovery_run, processing_run)
        for discovery_run, processing_run in rows
    ]


async def get_discovery_run(db: AsyncSession, run_id: UUID) -> dict:
    row = (
        await db.execute(
            select(DiscoveryRun, ProcessingRun)
            .join(
                ProcessingRun,
                ProcessingRun.id == DiscoveryRun.processing_run_id,
            )
            .where(DiscoveryRun.id == run_id)
        )
    ).one_or_none()
    if row is None:
        raise APIError(404, "DISCOVERY_RUN_NOT_FOUND", "候选发现任务不存在")
    return _run_data(*row)


async def list_candidates(
    db: AsyncSession,
    *,
    discovery_run_id: UUID | None,
    page: int,
    page_size: int,
) -> list[dict]:
    query = select(SkillCombinationCandidate)
    if discovery_run_id is not None:
        query = query.where(
            SkillCombinationCandidate.discovery_run_id == discovery_run_id
        )
    candidates = (
        await db.scalars(
            query.order_by(
                SkillCombinationCandidate.overall_candidate_score.desc(),
                SkillCombinationCandidate.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_candidate_list_data(candidate) for candidate in candidates]


async def candidate_detail(db: AsyncSession, candidate_id: UUID) -> dict:
    candidate = await _get_candidate(db, candidate_id)
    rows = (
        await db.execute(
            select(CombinationSkill, Capability)
            .join(Capability, Capability.id == CombinationSkill.capability_id)
            .where(CombinationSkill.candidate_id == candidate.id)
            .order_by(Capability.canonical_name, Capability.id)
        )
    ).all()
    payload = dict(candidate.definition_payload)
    return {
        **_candidate_list_data(candidate),
        "definition_payload": payload,
        "label": DISCOVERY_LABEL,
        "disclaimer": payload.get("disclaimer", DISCOVERY_DISCLAIMER),
        "novelty_status": payload.get("novelty_status", "not_evaluated"),
        "scores": {
            "support": float(candidate.support_score),
            "diversity": float(candidate.diversity_score),
            "coherence": float(candidate.coherence_score),
            "novelty": float(candidate.novelty_score),
            "evidence": float(candidate.evidence_score),
            "overall": float(candidate.overall_candidate_score),
        },
        "skills": [
            {
                "capability_id": skill.capability_id,
                "canonical_name": capability.canonical_name,
                "skill_role": skill.skill_role,
                "weight": float(skill.weight),
                "frequency": float(skill.frequency),
            }
            for skill, capability in rows
        ],
    }


async def candidate_evidence(
    db: AsyncSession,
    candidate_id: UUID,
    *,
    page: int,
    page_size: int,
) -> list[dict]:
    candidate = await _get_candidate(db, candidate_id)
    rows = (
        await db.execute(
            select(
                CombinationEvidence,
                NormalizedJobPosting,
                RawJobPosting,
                ImportBatch,
            )
            .join(
                NormalizedJobPosting,
                NormalizedJobPosting.id == CombinationEvidence.normalized_job_id,
            )
            .join(
                RawJobPosting,
                RawJobPosting.id == NormalizedJobPosting.raw_job_id,
            )
            .join(ImportBatch, ImportBatch.id == RawJobPosting.batch_id)
            .where(CombinationEvidence.candidate_id == candidate.id)
            .order_by(
                CombinationEvidence.representative.desc(),
                CombinationEvidence.evidence_weight.desc(),
                NormalizedJobPosting.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [
        {
            "normalized_job_id": normalized.id,
            "batch_id": raw.batch_id,
            "job_title": normalized.normalized_title,
            "company_name": normalized.company_name or raw.company_name,
            "source_code": raw.source_code,
            "source_url": raw.source_url,
            "published_at": normalized.published_at,
            "collected_at": batch.collected_at,
            "quality_score": float(normalized.quality_score),
            "evidence_weight": float(evidence.evidence_weight),
            "representative": evidence.representative,
        }
        for evidence, normalized, raw, batch in rows
    ]


async def _get_candidate(
    db: AsyncSession,
    candidate_id: UUID,
) -> SkillCombinationCandidate:
    candidate = await db.get(SkillCombinationCandidate, candidate_id)
    if candidate is None:
        raise APIError(
            404,
            "DISCOVERY_CANDIDATE_NOT_FOUND",
            "候选技能组合不存在",
        )
    return candidate


def _run_data(discovery_run: DiscoveryRun, processing_run: ProcessingRun) -> dict:
    return {
        "id": discovery_run.id,
        "processing_run_id": processing_run.id,
        "input_batch_ids": discovery_run.input_batch_ids,
        "algorithm_version": discovery_run.algorithm_version,
        "extraction_version": discovery_run.extraction_version,
        "parameters": discovery_run.parameters,
        "status": discovery_run.status,
        "processing_status": processing_run.status,
        "summary": discovery_run.summary,
        "completed_at": discovery_run.completed_at,
        "created_at": discovery_run.created_at,
    }


def _candidate_list_data(candidate: SkillCombinationCandidate) -> dict:
    return {
        "id": candidate.id,
        "discovery_run_id": candidate.discovery_run_id,
        "label": DISCOVERY_LABEL,
        "suggested_name": candidate.suggested_name,
        "support_job_count": candidate.support_job_count,
        "source_count": candidate.source_count,
        "company_count": candidate.company_count,
        "overall_candidate_score": float(candidate.overall_candidate_score),
        "status": candidate.status,
        "created_at": candidate.created_at,
    }
