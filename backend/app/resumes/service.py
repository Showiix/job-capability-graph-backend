from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Capability, CapabilityAlias
from app.discovery.mining import normalize_skill_label
from app.processing.models import ProcessingRun
from app.resumes.llm import LLMParseResult
from app.resumes.models import Resume, ResumeProfile, ResumeSkill
from app.resumes.parsing import (
    ValidatedParse,
    derive_highest_education,
    derive_total_experience_months,
    skill_rank,
)


@dataclass(frozen=True, slots=True)
class MappedResumeSkill:
    raw_name: str
    normalized_name: str
    capability_id: UUID | None
    proficiency: str | None
    explicit_experience_months: int | None
    evidence_strength: str
    evidence_quote: str
    evidence_start: int
    evidence_end: int
    mapping_method: str
    mapping_status: str
    confidence: float


@dataclass(frozen=True, slots=True)
class SkillMappingResult:
    skills: list[MappedResumeSkill]
    warnings: list[str]


async def map_resume_skills(
    db: AsyncSession,
    skills: list[dict],
) -> SkillMappingResult:
    warnings: list[str] = []
    by_name: dict[str, list[dict]] = defaultdict(list)
    for source in skills:
        normalized_name = normalize_skill_label(source["name"])
        if not normalized_name:
            warnings.append("SKILL_NAME_EMPTY")
            continue
        candidate = dict(source)
        candidate["normalized_name"] = normalized_name
        by_name[normalized_name].append(candidate)

    candidates = [
        max(values, key=skill_rank)
        for _name, values in sorted(by_name.items())
    ]

    # ponytail: full active-catalog scan is acceptable at ~30k rows;
    # add persisted normalized columns and indexes only after profiling shows
    # a bottleneck.
    capabilities = (
        await db.scalars(select(Capability).where(Capability.status == "active"))
    ).all()
    canonical: dict[str, list[Capability]] = defaultdict(list)
    for capability in capabilities:
        normalized = normalize_skill_label(capability.canonical_name)
        if normalized:
            canonical[normalized].append(capability)

    alias_rows = (
        await db.execute(
            select(CapabilityAlias, Capability)
            .join(Capability, Capability.id == CapabilityAlias.capability_id)
            .where(
                CapabilityAlias.status == "active",
                Capability.status == "active",
            )
        )
    ).all()
    aliases: dict[str, dict[UUID, Capability]] = defaultdict(dict)
    for alias, capability in alias_rows:
        normalized = normalize_skill_label(alias.alias)
        if normalized:
            aliases[normalized][capability.id] = capability

    mapped_with_sources: list[tuple[MappedResumeSkill, dict]] = []
    for candidate in candidates:
        normalized_name = candidate["normalized_name"]
        capability = None
        mapping_method = "unmapped"
        canonical_matches = canonical.get(normalized_name, [])
        if len(canonical_matches) == 1:
            capability = canonical_matches[0]
            mapping_method = "canonical_exact"
        elif len(canonical_matches) > 1:
            warnings.append(f"AMBIGUOUS_CAPABILITY_NAME:{normalized_name}")
        else:
            alias_matches = list(aliases.get(normalized_name, {}).values())
            if len(alias_matches) == 1:
                capability = alias_matches[0]
                mapping_method = "alias_exact"
            elif len(alias_matches) > 1:
                warnings.append(f"AMBIGUOUS_CAPABILITY_ALIAS:{normalized_name}")

        mapped = MappedResumeSkill(
            raw_name=candidate["name"],
            normalized_name=normalized_name,
            capability_id=capability.id if capability is not None else None,
            proficiency=candidate["proficiency"],
            explicit_experience_months=candidate["explicit_experience_months"],
            evidence_strength=candidate["evidence_strength"],
            evidence_quote=candidate["evidence_quote"],
            evidence_start=candidate["evidence_start"],
            evidence_end=candidate["evidence_end"],
            mapping_method=mapping_method,
            mapping_status="mapped" if capability is not None else "unmapped",
            confidence=float(candidate["confidence"]),
        )
        mapped_with_sources.append((mapped, candidate))

    selected = [
        pair for pair in mapped_with_sources if pair[0].capability_id is None
    ]
    by_capability: dict[UUID, list[tuple[MappedResumeSkill, dict]]] = defaultdict(list)
    for pair in mapped_with_sources:
        if pair[0].capability_id is not None:
            by_capability[pair[0].capability_id].append(pair)
    selected.extend(
        max(values, key=lambda pair: skill_rank(pair[1]))
        for values in by_capability.values()
    )

    return SkillMappingResult(
        skills=sorted(
            (pair[0] for pair in selected),
            key=lambda item: item.normalized_name,
        ),
        warnings=warnings,
    )


async def get_existing_extracted_profile(
    db: AsyncSession,
    resume_id: UUID,
    extraction_version: str,
) -> ResumeProfile | None:
    return await db.scalar(
        select(ResumeProfile).where(
            ResumeProfile.resume_id == resume_id,
            ResumeProfile.extraction_version == extraction_version,
            ResumeProfile.profile_source == "extracted",
        )
    )


async def complete_run_for_profile(
    db: AsyncSession,
    *,
    resume: Resume,
    run: ProcessingRun,
    profile: ResumeProfile,
) -> dict:
    counts = dict(
        (
            await db.execute(
                select(ResumeSkill.mapping_status, func.count())
                .where(ResumeSkill.profile_id == profile.id)
                .group_by(ResumeSkill.mapping_status)
            )
        ).all()
    )
    warnings = profile.structured_payload.get("validation_warnings", [])
    result = {
        "result_url": (
            f"/api/v1/resumes/{resume.id}/profiles/{profile.version_no}"
        ),
        "resume_id": str(resume.id),
        "profile_id": str(profile.id),
        "profile_version": profile.version_no,
        "mapped_skill_count": int(counts.get("mapped", 0)),
        "unmapped_skill_count": int(counts.get("unmapped", 0)),
        "validation_warning_count": len(warnings),
    }
    now = datetime.now(UTC)
    resume.parse_status = "ready"
    resume.latest_run_id = run.id
    run.status = "completed"
    run.current_stage = "completed"
    run.processed_count = 1
    run.success_count = 1
    run.failed_count = 0
    run.progress_percent = Decimal("100")
    run.heartbeat_at = now
    run.completed_at = now
    run.error_code = None
    run.error_message = None
    run.result_summary = result
    await db.commit()
    return result


async def persist_extracted_profile(
    db: AsyncSession,
    *,
    resume: Resume,
    run: ProcessingRun,
    extracted_text: str,
    extraction_method: str,
    validated: ValidatedParse,
    mapping: SkillMappingResult,
    llm_result: LLMParseResult,
    requested_model: str,
    current_month: date,
) -> ResumeProfile:
    resume_id = resume.id
    run_id = run.id
    extraction_version = run.pipeline_version
    try:
        locked_resume = await db.scalar(
            select(Resume).where(Resume.id == resume_id).with_for_update()
        )
        existing = await get_existing_extracted_profile(
            db,
            resume_id,
            extraction_version,
        )
        if existing is not None:
            await complete_run_for_profile(
                db,
                resume=locked_resume,
                run=run,
                profile=existing,
            )
            return existing

        version_no = (
            await db.scalar(
                select(func.max(ResumeProfile.version_no)).where(
                    ResumeProfile.resume_id == resume_id
                )
            )
            or 0
        ) + 1
        highest_education = derive_highest_education(validated.educations)
        total_experience, date_warnings = derive_total_experience_months(
            validated.experiences,
            current_month=current_month,
        )
        validation_warnings = [
            *validated.warnings,
            *mapping.warnings,
            *date_warnings,
        ]
        structured_payload = {
            "schema_version": "resume_parse_v1",
            "document_language": validated.document_language,
            "summary": validated.summary,
            "educations": validated.educations,
            "experiences": validated.experiences,
            "projects": validated.projects,
            "validation_warnings": validation_warnings,
            "llm_metadata": {
                "response_id": llm_result.response_id,
                "requested_model": requested_model,
                "returned_model": llm_result.returned_model,
                "status": llm_result.status,
                "input_tokens": llm_result.usage.get("input_tokens"),
                "output_tokens": llm_result.usage.get("output_tokens"),
                "total_tokens": llm_result.usage.get("total_tokens"),
                "provider_attempts": llm_result.provider_attempts,
                "prompt_version": "resume_parse_v1",
                "response_sha256": llm_result.response_sha256,
            },
        }
        profile = ResumeProfile(
            resume_id=resume_id,
            version_no=version_no,
            extraction_version=run.pipeline_version,
            profile_source="extracted",
            extracted_text=extracted_text,
            text_extraction_method=extraction_method,
            highest_education_level=highest_education,
            total_experience_months=total_experience,
            structured_payload=structured_payload,
            status="candidate",
            created_by_run_id=run_id,
            created_by_user_id=run.created_by_user_id,
        )
        db.add(profile)
        await db.flush()
        db.add_all(
            [
                ResumeSkill(
                    profile_id=profile.id,
                    capability_id=value.capability_id,
                    raw_name=value.raw_name,
                    normalized_name=value.normalized_name,
                    proficiency=value.proficiency,
                    explicit_experience_months=value.explicit_experience_months,
                    evidence_strength=value.evidence_strength,
                    evidence_quote=value.evidence_quote,
                    evidence_start=value.evidence_start,
                    evidence_end=value.evidence_end,
                    mapping_method=value.mapping_method,
                    mapping_status=value.mapping_status,
                    source="llm",
                    confidence=Decimal(str(value.confidence)),
                    user_confirmed=False,
                )
                for value in mapping.skills
            ]
        )
        await db.flush()
        await complete_run_for_profile(
            db,
            resume=locked_resume,
            run=run,
            profile=profile,
        )
        return profile
    except IntegrityError:
        await db.rollback()
        existing = await get_existing_extracted_profile(
            db,
            resume_id,
            extraction_version,
        )
        if existing is None:
            raise
        current_resume = await db.get(Resume, resume_id)
        current_run = await db.get(ProcessingRun, run_id)
        await complete_run_for_profile(
            db,
            resume=current_resume,
            run=current_run,
            profile=existing,
        )
        return existing
