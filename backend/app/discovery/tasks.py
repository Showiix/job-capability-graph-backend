import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Capability, CapabilityAlias
from app.discovery.mining import (
    CatalogEntry,
    JobSkillSet,
    build_catalog_index,
    map_skill_labels,
    mine_skill_pairs,
    normalize_skill_label,
)
from app.discovery.models import (
    CombinationEvidence,
    CombinationSkill,
    DiscoveryRun,
    JobAnalysisProfile,
    JobSkillCandidate,
    SkillCombinationCandidate,
)
from app.imports.models import NormalizedJobPosting, RawJobPosting
from app.infrastructure.database import SessionFactory
from app.processing.models import ProcessingError, ProcessingRun
from app.worker import celery_app

CHUNK_SIZE = 100
DISCLAIMER = "该结果是候选技能组合，不代表已经确认的长期市场趋势"


async def process_discovery_run(db: AsyncSession, processing_run_id: UUID) -> dict:
    processing_run = await db.get(ProcessingRun, processing_run_id)
    if processing_run is None:
        return _empty_result()
    discovery_run = await db.scalar(
        select(DiscoveryRun).where(
            DiscoveryRun.processing_run_id == processing_run.id
        )
    )
    if discovery_run is None:
        return await _fail_run(
            db,
            processing_run,
            None,
            "DISCOVERY_RUN_NOT_FOUND",
            "候选发现任务不存在",
        )
    if processing_run.status in {"completed", "failed", "cancelled"}:
        return dict(processing_run.result_summary)
    if processing_run.cancel_requested:
        return await _cancel_run(db, processing_run, discovery_run)

    now = datetime.now(UTC)
    processing_run.status = "running"
    processing_run.current_stage = "loading"
    processing_run.started_at = now
    processing_run.heartbeat_at = now
    processing_run.attempt_count += 1
    discovery_run.status = "running"
    await db.commit()

    catalog_entries, catalog_names = await _load_catalog(db)
    if not catalog_entries:
        return await _fail_run(
            db,
            processing_run,
            discovery_run,
            "DISCOVERY_NO_ACTIVE_CAPABILITIES",
            "标准技能库中没有 active Capability",
        )
    catalog = build_catalog_index(catalog_entries)
    active_capability_ids = set(catalog_names)

    parameters = discovery_run.parameters
    job_rows = (
        await db.execute(
            select(NormalizedJobPosting, RawJobPosting)
            .join(
                RawJobPosting,
                RawJobPosting.id == NormalizedJobPosting.raw_job_id,
            )
            .where(
                RawJobPosting.batch_id.in_(discovery_run.input_batch_ids),
                NormalizedJobPosting.is_current.is_(True),
                NormalizedJobPosting.duplicate_of_id.is_(None),
                NormalizedJobPosting.quality_score
                >= parameters.get("minimum_quality_score", 60),
            )
            .order_by(NormalizedJobPosting.id)
        )
    ).all()
    processing_run.total_count = len(job_rows)
    processing_run.current_stage = "mapping"
    processing_run.heartbeat_at = datetime.now(UTC)
    await db.execute(
        delete(SkillCombinationCandidate).where(
            SkillCombinationCandidate.discovery_run_id == discovery_run.id
        )
    )
    await db.commit()

    profiles = await _load_profiles(
        db,
        [job.id for job, _ in job_rows],
        discovery_run.extraction_version,
    )
    existing_skills = await _load_profile_skills(db, profiles.values())
    next_versions = await _next_profile_versions(
        db,
        [job.id for job, _ in job_rows],
    )
    mapped_skill_count = 0
    unmapped_skill_count = 0
    job_skill_sets: list[JobSkillSet] = []

    for index, (job, raw) in enumerate(job_rows, start=1):
        if index == 1 or index % CHUNK_SIZE == 0:
            if await _cancel_requested(db, processing_run.id):
                return await _cancel_run(db, processing_run, discovery_run)

        profile = profiles.get(job.id)
        if profile is None:
            profile = JobAnalysisProfile(
                id=uuid4(),
                normalized_job_id=job.id,
                version_no=next_versions.get(job.id, 1),
                extraction_version=discovery_run.extraction_version,
                status="candidate",
                structured_payload={"source_tags": list(raw.source_tags)},
                validation_errors=[],
                created_by_run_id=processing_run.id,
            )
            db.add(profile)
            mappings = map_skill_labels(
                [value for value in raw.source_tags if isinstance(value, str)],
                catalog,
            )
            profile_skills = []
            for mapping in mappings:
                skill = JobSkillCandidate(
                    id=uuid4(),
                    analysis_profile_id=profile.id,
                    capability_id=mapping.capability_id,
                    raw_name=mapping.raw_name,
                    normalized_name=mapping.normalized_name,
                    requirement_type="required",
                    importance=1,
                    mapping_method=mapping.mapping_method,
                    mapping_status=mapping.mapping_status,
                    extraction_source="algorithm",
                    confidence=1 if mapping.capability_id is not None else 0,
                )
                db.add(skill)
                profile_skills.append(skill)
        else:
            profile_skills = existing_skills.get(profile.id, [])

        capability_ids = []
        for skill in profile_skills:
            if skill.mapping_status == "mapped":
                mapped_skill_count += 1
                if skill.capability_id in active_capability_ids:
                    capability_ids.append(skill.capability_id)
            else:
                unmapped_skill_count += 1
        job_skill_sets.append(
            JobSkillSet(
                normalized_job_id=job.id,
                source_code=raw.source_code,
                company_name=job.company_name or raw.company_name,
                quality_score=job.quality_score,
                capability_ids=tuple(capability_ids),
            )
        )
        processing_run.processed_count = index
        processing_run.success_count = index
        processing_run.progress_percent = _progress(index, len(job_rows), 70)
        processing_run.heartbeat_at = datetime.now(UTC)
        if index % CHUNK_SIZE == 0:
            await db.commit()

    await db.commit()
    if await _cancel_requested(db, processing_run.id):
        return await _cancel_run(db, processing_run, discovery_run)

    processing_run.current_stage = "mining"
    processing_run.heartbeat_at = datetime.now(UTC)
    await db.commit()
    candidates = mine_skill_pairs(
        job_skill_sets,
        minimum_support_jobs=parameters.get("minimum_support_jobs", 3),
        minimum_source_count=parameters.get("minimum_source_count", 1),
        maximum_candidates=parameters.get("maximum_candidates", 50),
    )

    processing_run.current_stage = "persisting"
    processing_run.progress_percent = Decimal("90")
    processing_run.heartbeat_at = datetime.now(UTC)
    jobs_by_id = {job.id: job for job, _ in job_rows}
    for candidate_data in candidates:
        names = [catalog_names[value] for value in candidate_data.capability_ids]
        candidate = SkillCombinationCandidate(
            id=uuid4(),
            discovery_run_id=discovery_run.id,
            suggested_name=" + ".join(names),
            normalized_name=" + ".join(
                normalize_skill_label(name) for name in names
            ),
            definition_payload={
                "algorithm": discovery_run.algorithm_version,
                "capability_ids": [
                    str(value) for value in candidate_data.capability_ids
                ],
                "novelty_status": candidate_data.novelty_status,
                "disclaimer": DISCLAIMER,
            },
            support_job_count=candidate_data.support_job_count,
            source_count=candidate_data.source_count,
            company_count=candidate_data.company_count,
            support_score=candidate_data.support_score,
            diversity_score=candidate_data.diversity_score,
            coherence_score=candidate_data.coherence_score,
            novelty_score=candidate_data.novelty_score,
            evidence_score=candidate_data.evidence_score,
            overall_candidate_score=candidate_data.overall_candidate_score,
            status="candidate",
        )
        db.add(candidate)
        await db.flush()
        for capability_id in candidate_data.capability_ids:
            db.add(
                CombinationSkill(
                    candidate_id=candidate.id,
                    capability_id=capability_id,
                    skill_role="core",
                    weight=1,
                    frequency=1,
                )
            )
        ranked_evidence = sorted(
            candidate_data.support_job_ids,
            key=lambda job_id: (-jobs_by_id[job_id].quality_score, str(job_id)),
        )
        representative_ids = set(ranked_evidence[:3])
        for job_id in candidate_data.support_job_ids:
            db.add(
                CombinationEvidence(
                    candidate_id=candidate.id,
                    normalized_job_id=job_id,
                    evidence_weight=_evidence_weight(
                        jobs_by_id[job_id].quality_score
                    ),
                    representative=job_id in representative_ids,
                )
            )

    eligible_job_count = sum(
        len(set(job.capability_ids)) >= 2 for job in job_skill_sets
    )
    result = {
        "discovery_run_id": str(discovery_run.id),
        "analyzed_job_count": len(job_rows),
        "eligible_job_count": eligible_job_count,
        "mapped_skill_count": mapped_skill_count,
        "unmapped_skill_count": unmapped_skill_count,
        "candidate_count": len(candidates),
    }
    completed_at = datetime.now(UTC)
    processing_run.status = "completed"
    processing_run.current_stage = "completed"
    processing_run.processed_count = len(job_rows)
    processing_run.success_count = len(job_rows)
    processing_run.failed_count = 0
    processing_run.progress_percent = Decimal("100")
    processing_run.heartbeat_at = completed_at
    processing_run.completed_at = completed_at
    processing_run.result_summary = result
    discovery_run.status = "completed"
    discovery_run.summary = result
    discovery_run.completed_at = completed_at
    await db.commit()
    return result


async def _load_catalog(
    db: AsyncSession,
) -> tuple[list[CatalogEntry], dict[UUID, str]]:
    capabilities = (
        await db.scalars(
            select(Capability)
            .where(Capability.status == "active")
            .order_by(Capability.id)
        )
    ).all()
    if not capabilities:
        return [], {}
    aliases_by_capability: dict[UUID, list[str]] = defaultdict(list)
    for capability_id, alias in (
        await db.execute(
            select(CapabilityAlias.capability_id, CapabilityAlias.alias).where(
                CapabilityAlias.status == "active",
                CapabilityAlias.capability_id.in_(
                    [capability.id for capability in capabilities]
                ),
            )
        )
    ).all():
        aliases_by_capability[capability_id].append(alias)
    entries = [
        CatalogEntry(
            capability_id=capability.id,
            canonical_name=capability.canonical_name,
            aliases=tuple(sorted(aliases_by_capability[capability.id])),
        )
        for capability in capabilities
    ]
    return entries, {
        capability.id: capability.canonical_name for capability in capabilities
    }


async def _load_profiles(
    db: AsyncSession,
    job_ids: list[UUID],
    extraction_version: str,
) -> dict[UUID, JobAnalysisProfile]:
    if not job_ids:
        return {}
    profiles = (
        await db.scalars(
            select(JobAnalysisProfile).where(
                JobAnalysisProfile.normalized_job_id.in_(job_ids),
                JobAnalysisProfile.extraction_version == extraction_version,
            )
        )
    ).all()
    return {profile.normalized_job_id: profile for profile in profiles}


async def _load_profile_skills(
    db: AsyncSession,
    profiles,
) -> dict[UUID, list[JobSkillCandidate]]:
    profile_ids = [profile.id for profile in profiles]
    if not profile_ids:
        return {}
    result: dict[UUID, list[JobSkillCandidate]] = defaultdict(list)
    for skill in (
        await db.scalars(
            select(JobSkillCandidate)
            .where(JobSkillCandidate.analysis_profile_id.in_(profile_ids))
            .order_by(JobSkillCandidate.id)
        )
    ).all():
        result[skill.analysis_profile_id].append(skill)
    return result


async def _next_profile_versions(
    db: AsyncSession,
    job_ids: list[UUID],
) -> dict[UUID, int]:
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(
                JobAnalysisProfile.normalized_job_id,
                func.max(JobAnalysisProfile.version_no),
            )
            .where(JobAnalysisProfile.normalized_job_id.in_(job_ids))
            .group_by(JobAnalysisProfile.normalized_job_id)
        )
    ).all()
    return {job_id: version + 1 for job_id, version in rows}


async def _cancel_requested(db: AsyncSession, run_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(ProcessingRun.cancel_requested).where(ProcessingRun.id == run_id)
        )
    )


async def _cancel_run(
    db: AsyncSession,
    processing_run: ProcessingRun,
    discovery_run: DiscoveryRun,
) -> dict:
    result = {**_empty_result(), "discovery_run_id": str(discovery_run.id)}
    completed_at = datetime.now(UTC)
    processing_run.status = "cancelled"
    processing_run.current_stage = "cancelled"
    processing_run.completed_at = completed_at
    processing_run.result_summary = result
    discovery_run.status = "cancelled"
    discovery_run.completed_at = completed_at
    discovery_run.summary = result
    await db.commit()
    return result


async def _fail_run(
    db: AsyncSession,
    processing_run: ProcessingRun,
    discovery_run: DiscoveryRun | None,
    code: str,
    message: str,
) -> dict:
    result = _empty_result()
    failed_stage = processing_run.current_stage or "loading"
    if discovery_run is not None:
        result["discovery_run_id"] = str(discovery_run.id)
        discovery_run.status = "failed"
        discovery_run.summary = result
        discovery_run.completed_at = datetime.now(UTC)
    processing_run.status = "failed"
    processing_run.current_stage = "failed"
    processing_run.error_code = code
    processing_run.error_message = message
    processing_run.completed_at = datetime.now(UTC)
    processing_run.result_summary = result
    db.add(
        ProcessingError(
            run_id=processing_run.id,
            stage=failed_stage,
            error_code=code,
            message=message,
            retryable=False,
            details={},
        )
    )
    await db.commit()
    return result


def _empty_result() -> dict:
    return {
        "analyzed_job_count": 0,
        "eligible_job_count": 0,
        "mapped_skill_count": 0,
        "unmapped_skill_count": 0,
        "candidate_count": 0,
    }


def _progress(processed: int, total: int, ceiling: int) -> Decimal:
    if total == 0:
        return Decimal(ceiling)
    value = Decimal(processed * ceiling) / Decimal(total)
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _evidence_weight(quality_score: Decimal) -> Decimal:
    value = min(max(quality_score / Decimal(100), Decimal(0)), Decimal(1))
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


async def _run_with_session(run_id: str) -> dict:
    async with SessionFactory() as db:
        return await process_discovery_run(db, UUID(run_id))


@celery_app.task(name="app.discover_skill_combinations")
def discover_skill_combinations(run_id: str) -> dict:
    return asyncio.run(_run_with_session(run_id))
