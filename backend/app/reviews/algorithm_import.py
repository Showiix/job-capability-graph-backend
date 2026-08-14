import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import User
from app.catalog.mapping import resolve_capability_labels
from app.catalog.models import Capability
from app.core.errors import APIError
from app.discovery.mining import normalize_skill_label
from app.reviews.models import GraphChangeCandidate
from app.reviews.schemas import RoleDefinitionPayload

MAX_ALGORITHM_RESULT_BYTES = 5 * 1024 * 1024


class AlgorithmSkill(BaseModel):
    model_config = ConfigDict(extra="allow")

    skill: Annotated[str, Field(min_length=1, max_length=200)]
    support_pct: Annotated[float, Field(ge=0, le=1)] | None = None
    support_pct_corrected: Annotated[float, Field(ge=0, le=1)] | None = None

    @property
    def support(self) -> float:
        if self.support_pct_corrected is not None:
            return self.support_pct_corrected
        return self.support_pct if self.support_pct is not None else 0.5


class AlgorithmIndustry(BaseModel):
    model_config = ConfigDict(extra="allow")

    industry: Annotated[str, Field(min_length=1, max_length=300)]


class AlgorithmJobDefinition(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    cluster_id: int | str
    role_name: Annotated[str, Field(alias="岗位名称", min_length=1, max_length=200)]
    responsibilities: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500)]],
        Field(alias="核心职责", max_length=20),
    ]
    required_skills: Annotated[
        list[AlgorithmSkill],
        Field(alias="必备技能", max_length=100),
    ]
    bonus_skills: Annotated[
        list[AlgorithmSkill],
        Field(alias="加分技能", default_factory=list, max_length=100),
    ]
    industries: Annotated[
        list[AlgorithmIndustry],
        Field(alias="典型行业应用场景", default_factory=list, max_length=20),
    ]
    source_traceability: dict[str, Any] = Field(default_factory=dict)
    manual_review: dict[str, Any] = Field(alias="人工优化", default_factory=dict)
    audit_findings: list[dict[str, Any]] = Field(alias="_audit", default_factory=list)


class AlgorithmJobDefinitionFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    generated_at: str | None = None
    source: str | None = None
    definitions: Annotated[
        list[AlgorithmJobDefinition],
        Field(min_length=1, max_length=1000),
    ]


async def import_algorithm_job_definitions(
    db: AsyncSession,
    actor: User,
    upload: UploadFile,
    *,
    request_id: str,
    ip_address: str | None,
) -> dict[str, Any]:
    content = await upload.read(MAX_ALGORITHM_RESULT_BYTES + 1)
    if not content:
        raise APIError(422, "ALGORITHM_RESULT_EMPTY", "算法结果文件不能为空")
    if len(content) > MAX_ALGORITHM_RESULT_BYTES:
        raise APIError(413, "ALGORITHM_RESULT_TOO_LARGE", "算法结果文件超过大小限制")
    if Path(upload.filename or "").suffix.lower() != ".json":
        raise APIError(422, "ALGORITHM_RESULT_TYPE_UNSUPPORTED", "仅支持 JSON 文件")

    try:
        raw_payload = json.loads(content)
        payload = AlgorithmJobDefinitionFile.model_validate(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        details = {}
        if isinstance(error, ValidationError):
            details["validation_errors"] = [
                {
                    "type": item["type"],
                    "location": list(item["loc"]),
                    "message": item["msg"],
                }
                for item in error.errors(include_url=False)
            ]
        raise APIError(
            422,
            "ALGORITHM_RESULT_INVALID",
            "算法结果文件格式无效",
            details,
        ) from error

    file_sha256 = hashlib.sha256(content).hexdigest()
    existing = (
        await db.scalars(
            select(GraphChangeCandidate).where(
                GraphChangeCandidate.source_candidate_id.is_(None),
                GraphChangeCandidate.source_snapshot["algorithm_import"][
                    "file_sha256"
                ].astext
                == file_sha256,
            )
        )
    ).all()
    if existing:
        return _result(
            file_sha256=file_sha256,
            total=len(payload.definitions),
            created=[],
            reused=[value.id for value in existing],
            skipped=[],
        )

    all_labels = [
        skill.skill
        for definition in payload.definitions
        for skill in [*definition.required_skills, *definition.bonus_skills]
    ]
    resolutions = await resolve_capability_labels(db, all_labels)
    resolved_by_label = {
        item.normalized_label: item for item in resolutions.resolutions
    }
    mapped_ids = {
        item.capability_id
        for item in resolutions.mapped
        if item.capability_id is not None
    }
    domain_by_capability = (
        dict(
            (
                await db.execute(
                    select(Capability.id, Capability.domain_id).where(
                        Capability.id.in_(mapped_ids)
                    )
                )
            ).all()
        )
        if mapped_ids
        else {}
    )

    created: list[UUID] = []
    skipped: list[dict[str, Any]] = []
    for definition in payload.definitions:
        mapped_required, unmapped_required = _map_skills(
            definition.required_skills,
            resolved_by_label,
            domain_by_capability,
        )
        mapped_bonus, unmapped_bonus = _map_skills(
            definition.bonus_skills,
            resolved_by_label,
            domain_by_capability,
        )
        required, bonus = _publishable_capabilities(mapped_required, mapped_bonus)
        if len(required) < 2:
            skipped.append(
                {
                    "cluster_id": definition.cluster_id,
                    "role_name": definition.role_name,
                    "reason": "INSUFFICIENT_SAME_DOMAIN_CAPABILITIES",
                    "mapped_required_count": len(mapped_required),
                    "unmapped_skills": [*unmapped_required, *unmapped_bonus],
                }
            )
            continue

        proposed_payload = RoleDefinitionPayload(
            role_name=definition.role_name,
            core_responsibilities=definition.responsibilities,
            required_capability_ids=[item[0] for item in required],
            bonus_capability_ids=[item[0] for item in bonus],
            industry_scenarios=[item.industry for item in definition.industries],
            generation_source="deterministic_baseline",
            definition_status="needs_enrichment",
        ).model_dump(mode="json")
        confidence = Decimal(
            str(round(sum(item[2] for item in required) / len(required), 4))
        )
        proposal = GraphChangeCandidate(
            id=uuid4(),
            source_candidate_id=None,
            change_type="create_job_role",
            proposed_payload=proposed_payload,
            source_snapshot={
                "algorithm_import": {
                    "file_sha256": file_sha256,
                    "filename": upload.filename,
                    "generated_at": payload.generated_at,
                    "source": payload.source,
                    "cluster_id": definition.cluster_id,
                    "audit_id": definition.manual_review.get("audit_id"),
                },
                "raw_definition": definition.model_dump(mode="json", by_alias=True),
                "mapping_warnings": list(resolutions.warnings),
                "unmapped_required_skills": unmapped_required,
                "unmapped_bonus_skills": unmapped_bonus,
            },
            evidence_summary={
                "total_jds": definition.source_traceability.get("total_jds", 0),
                "effective_jds": definition.source_traceability.get("effective_jds", 0),
                "unique_companies": definition.source_traceability.get(
                    "unique_companies", 0
                ),
                "mapped_required_count": len(required),
                "mapped_bonus_count": len(bonus),
                "unmapped_skill_count": len(unmapped_required) + len(unmapped_bonus),
                "algorithm_audit_issue_count": len(definition.audit_findings),
            },
            confidence=confidence,
            review_status="pending",
            created_by_user_id=actor.id,
        )
        db.add(proposal)
        created.append(proposal.id)

    if not created:
        raise APIError(
            422,
            "ALGORITHM_RESULT_NOT_IMPORTABLE",
            "算法结果中没有可进入审核的岗位定义",
            {"skipped": skipped[:50]},
        )

    record_audit(
        db,
        action="algorithm.job_definitions.import",
        resource_type="graph_change_candidate",
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "file_sha256": file_sha256,
            "filename": upload.filename,
            "total_count": len(payload.definitions),
            "created_count": len(created),
            "skipped_count": len(skipped),
        },
    )
    await db.commit()
    return _result(
        file_sha256=file_sha256,
        total=len(payload.definitions),
        created=created,
        reused=[],
        skipped=skipped,
    )


def _map_skills(
    skills: list[AlgorithmSkill],
    resolved_by_label: dict[str, Any],
    domain_by_capability: dict[UUID, UUID],
) -> tuple[list[tuple[UUID, UUID, float]], list[str]]:
    mapped: list[tuple[UUID, UUID, float]] = []
    unmapped: list[str] = []
    seen: set[UUID] = set()
    for skill in skills:
        resolution = resolved_by_label.get(normalize_skill_label(skill.skill))
        capability_id = resolution.capability_id if resolution is not None else None
        if capability_id is None or capability_id not in domain_by_capability:
            unmapped.append(skill.skill)
            continue
        if capability_id not in seen:
            mapped.append(
                (capability_id, domain_by_capability[capability_id], skill.support)
            )
            seen.add(capability_id)
    return mapped, unmapped


def _publishable_capabilities(
    required: list[tuple[UUID, UUID, float]],
    bonus: list[tuple[UUID, UUID, float]],
) -> tuple[list[tuple[UUID, UUID, float]], list[tuple[UUID, UUID, float]]]:
    by_domain: dict[UUID, list[tuple[UUID, UUID, float]]] = defaultdict(list)
    for item in required:
        by_domain[item[1]].append(item)
    if not by_domain:
        return [], []
    dominant_domain = min(
        by_domain,
        key=lambda domain_id: (-len(by_domain[domain_id]), str(domain_id)),
    )
    publishable_required = by_domain[dominant_domain][:20]
    required_ids = {item[0] for item in publishable_required}
    publishable_bonus: list[tuple[UUID, UUID, float]] = []
    bonus_ids: set[UUID] = set()
    off_domain_required = [
        value
        for domain_id, values in by_domain.items()
        if domain_id != dominant_domain
        for value in values
    ]
    for item in [*off_domain_required, *bonus]:
        if item[0] not in required_ids and item[0] not in bonus_ids:
            publishable_bonus.append(item)
            bonus_ids.add(item[0])
        if len(publishable_bonus) == 20:
            break
    return publishable_required, publishable_bonus


def _result(
    *,
    file_sha256: str,
    total: int,
    created: list[UUID],
    reused: list[UUID],
    skipped: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "file_sha256": file_sha256,
        "total_definitions": total,
        "created_count": len(created),
        "reused_count": len(reused),
        "skipped_count": len(skipped),
        "proposal_ids": [str(value) for value in [*created, *reused]],
        "skipped": skipped,
        "review_queue_url": "/api/v1/review-proposals?status=pending",
    }
