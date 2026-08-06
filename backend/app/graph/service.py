from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
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
from app.graph.models import GraphVersion
from app.graph.neo4j import (
    GraphPublishResult,
    publish_job_role_snapshot,
    relation_key,
)
from app.reviews.models import GraphChangeCandidate
from app.reviews.schemas import RoleDefinitionPayload

GraphPublisher = Callable[[dict, int], Awaitable[GraphPublishResult]]


async def create_graph_version(
    db: AsyncSession,
    actor: User,
    proposal_id: UUID,
    *,
    request_id: str | None,
    ip_address: str | None,
) -> GraphVersion:
    existing = await db.scalar(
        select(GraphVersion).where(GraphVersion.source_proposal_id == proposal_id)
    )
    if existing is not None:
        return existing

    proposal = await db.get(GraphChangeCandidate, proposal_id)
    if proposal is None:
        raise APIError(404, "GRAPH_SOURCE_PROPOSAL_NOT_FOUND", "审核提案不存在")
    if proposal.review_status != "approved":
        raise APIError(409, "GRAPH_PROPOSAL_NOT_APPROVED", "审核提案尚未通过")
    if proposal.change_type != "create_job_role":
        raise APIError(422, "GRAPH_PROPOSAL_TYPE_UNSUPPORTED", "审核提案类型不支持发布")

    try:
        definition = RoleDefinitionPayload.model_validate(proposal.proposed_payload)
    except ValidationError as error:
        raise APIError(
            422, "GRAPH_CAPABILITY_INVALID", "岗位定义格式或技能无效"
        ) from error

    required_ids = set(definition.required_capability_ids)
    bonus_ids = set(definition.bonus_capability_ids)
    if required_ids & bonus_ids:
        raise APIError(422, "GRAPH_CAPABILITY_INVALID", "必备技能和加分技能不能重复")

    capability_ids = required_ids | bonus_ids
    rows = (
        await db.execute(
            select(Capability, Domain)
            .join(Domain, Domain.id == Capability.domain_id)
            .where(Capability.id.in_(capability_ids))
        )
    ).all()
    capabilities_by_id = {
        capability.id: (capability, domain) for capability, domain in rows
    }
    if set(capabilities_by_id) != capability_ids or any(
        capability.status != "active" or domain.status != "active"
        for capability, domain in capabilities_by_id.values()
    ):
        raise APIError(
            422, "GRAPH_CAPABILITY_INVALID", "岗位定义包含不存在或未启用的技能"
        )

    required_domains = {
        capabilities_by_id[capability_id][0].domain_id
        for capability_id in definition.required_capability_ids
    }
    if len(required_domains) != 1:
        raise APIError(422, "GRAPH_DOMAIN_AMBIGUOUS", "必备技能必须属于同一技术域")
    role_domain_id = next(iter(required_domains))
    role_domain = capabilities_by_id[definition.required_capability_ids[0]][1]

    existing_role = await db.scalar(
        select(JobRole.id).where(
            JobRole.domain_id == role_domain_id,
            func.lower(JobRole.canonical_name) == definition.role_name.lower(),
        )
    )
    if existing_role is not None:
        raise APIError(409, "GRAPH_JOB_ROLE_EXISTS", "同一技术域已存在同名岗位")

    catalog_version_no = (
        await db.scalar(select(func.max(CatalogVersion.version_no))) or 0
    ) + 1
    graph_version_no = (
        await db.scalar(select(func.max(GraphVersion.version_no))) or 0
    ) + 1
    job_role_id = uuid4()
    snapshot = _build_snapshot(
        proposal,
        definition,
        role_domain,
        capabilities_by_id,
        job_role_id,
        graph_version_no,
    )
    catalog_version = CatalogVersion(
        id=uuid4(),
        version_no=catalog_version_no,
        status="draft",
        is_current=False,
        created_by_user_id=actor.id,
        summary={
            "source": "graph_publication",
            "source_proposal_id": str(proposal.id),
        },
    )
    version = GraphVersion(
        id=uuid4(),
        version_no=graph_version_no,
        source_proposal_id=proposal.id,
        catalog_version_id=catalog_version.id,
        job_role_id=job_role_id,
        status="draft",
        is_current=False,
        snapshot=snapshot,
        attempt_count=0,
        created_by_user_id=actor.id,
    )
    db.add(catalog_version)
    db.add(version)
    record_audit(
        db,
        action="graph.version.create",
        resource_type="graph_version",
        resource_id=version.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"source_proposal_id": str(proposal.id)},
    )
    await db.commit()
    await db.refresh(version)
    return version


async def publish_graph_version(
    db: AsyncSession,
    actor: User,
    version_id: UUID,
    *,
    request_id: str | None,
    ip_address: str | None,
    publisher: GraphPublisher = publish_job_role_snapshot,
) -> GraphVersion:
    actor_id = actor.id
    version = await _get_publishable_version(db, version_id)
    if version.status == "published":
        return version
    if version.status not in {"draft", "failed"}:
        raise APIError(409, "GRAPH_VERSION_NOT_PUBLISHABLE", "图谱版本当前不可发布")

    version.status = "publishing"
    version.attempt_count += 1
    version.last_error = None
    await db.commit()

    try:
        await publisher(deepcopy(version.snapshot), version.version_no)
    except Exception as error:
        await _mark_failed(
            db,
            actor_id,
            version_id,
            error,
            request_id=request_id,
            ip_address=ip_address,
        )
        raise APIError(
            502, "GRAPH_PUBLICATION_FAILED", "图谱发布失败，可重试"
        ) from None

    try:
        await _finalize_graph_version(
            db,
            actor,
            version_id,
            request_id=request_id,
            ip_address=ip_address,
        )
    except Exception as error:
        await db.rollback()
        await _mark_failed(
            db,
            actor_id,
            version_id,
            error,
            request_id=request_id,
            ip_address=ip_address,
        )
        raise APIError(
            502, "GRAPH_PUBLICATION_FAILED", "图谱发布失败，可重试"
        ) from None

    published = await db.get(GraphVersion, version_id)
    if published is None:
        raise APIError(404, "GRAPH_VERSION_NOT_FOUND", "图谱版本不存在")
    return published


async def _get_publishable_version(
    db: AsyncSession,
    version_id: UUID,
) -> GraphVersion:
    version = await db.scalar(
        select(GraphVersion).where(GraphVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise APIError(404, "GRAPH_VERSION_NOT_FOUND", "图谱版本不存在")
    return version


def _build_snapshot(
    proposal: GraphChangeCandidate,
    definition: RoleDefinitionPayload,
    role_domain: Domain,
    capabilities_by_id: dict[UUID, tuple[Capability, Domain]],
    job_role_id: UUID,
    graph_version_no: int,
) -> dict:
    job_role = {
        "id": str(job_role_id),
        "canonical_name": definition.role_name,
        "description": "；".join(definition.core_responsibilities) or None,
        "status": "active",
        "domain_relation_key": relation_key(
            "BELONGS_TO", str(job_role_id), str(role_domain.id)
        ),
    }
    capabilities = []
    for requirement_type, capability_ids, importance in (
        ("required", definition.required_capability_ids, 1.0),
        ("bonus", definition.bonus_capability_ids, 0.5),
    ):
        for capability_id in capability_ids:
            capability, domain = capabilities_by_id[capability_id]
            capability_value = {
                "id": str(capability.id),
                "canonical_name": capability.canonical_name,
                "skill_type": capability.skill_type,
                "status": capability.status,
                "requirement_type": requirement_type,
                "importance": importance,
                "domain": {
                    "id": str(domain.id),
                    "code": domain.code,
                    "name": domain.name,
                },
                "domain_relation_key": relation_key(
                    "BELONGS_TO", str(capability.id), str(domain.id)
                ),
                "role_relation_key": relation_key(
                    "REQUIRES" if requirement_type == "required" else "BONUS",
                    str(job_role_id),
                    str(capability.id),
                ),
            }
            capabilities.append(capability_value)
    return {
        "graph_version": graph_version_no,
        "source_proposal_id": str(proposal.id),
        "source_candidate_id": (
            str(proposal.source_candidate_id)
            if proposal.source_candidate_id is not None
            else None
        ),
        "domain": {
            "id": str(role_domain.id),
            "code": role_domain.code,
            "name": role_domain.name,
        },
        "job_role": job_role,
        "definition": definition.model_dump(mode="json"),
        "evidence_summary": deepcopy(proposal.evidence_summary),
        "capabilities": capabilities,
    }


async def _finalize_graph_version(
    db: AsyncSession,
    actor: User,
    version_id: UUID,
    *,
    request_id: str | None,
    ip_address: str | None,
) -> None:
    version = await db.get(GraphVersion, version_id, populate_existing=True)
    if version is None:
        raise APIError(404, "GRAPH_VERSION_NOT_FOUND", "图谱版本不存在")
    if version.status != "publishing":
        raise APIError(409, "GRAPH_VERSION_NOT_PUBLISHABLE", "图谱版本状态已变化")

    snapshot = version.snapshot
    definition = snapshot["definition"]
    role_value = snapshot["job_role"]
    role = await db.get(JobRole, version.job_role_id)
    if role is None:
        role = JobRole(
            id=version.job_role_id,
            domain_id=UUID(snapshot["domain"]["id"]),
            canonical_name=role_value["canonical_name"],
            description=role_value["description"],
            definition_payload=definition,
            status="active",
            source_type="manual",
        )
        db.add(role)
        await db.flush()
    elif role.status != "active":
        raise ValueError("preallocated job role is not active")

    existing_relations = {
        relation.capability_id: relation
        for relation in (
            await db.scalars(
                select(JobRoleCapability).where(
                    JobRoleCapability.job_role_id == version.job_role_id
                )
            )
        ).all()
    }
    for capability in snapshot["capabilities"]:
        relation = existing_relations.get(UUID(capability["id"]))
        if relation is None:
            db.add(
                JobRoleCapability(
                    job_role_id=version.job_role_id,
                    capability_id=UUID(capability["id"]),
                    requirement_type=capability["requirement_type"],
                    importance=Decimal(str(capability["importance"])),
                    source_candidate_id=(
                        UUID(snapshot["source_candidate_id"])
                        if snapshot["source_candidate_id"]
                        else None
                    ),
                )
            )
        else:
            relation.requirement_type = capability["requirement_type"]
            relation.importance = Decimal(str(capability["importance"]))
    await db.flush()

    catalog = await db.get(CatalogVersion, version.catalog_version_id)
    if catalog is None:
        raise ValueError("catalog version is missing")
    active_capability_ids = set(
        await db.scalars(select(Capability.id).where(Capability.status == "active"))
    )
    active_job_role_ids = set(
        await db.scalars(select(JobRole.id).where(JobRole.status == "active"))
    )
    existing_items = (
        await db.scalars(
            select(CatalogVersionItem).where(
                CatalogVersionItem.catalog_version_id == catalog.id
            )
        )
    ).all()
    existing_capability_ids = {
        item.capability_id for item in existing_items if item.capability_id
    }
    existing_job_role_ids = {
        item.job_role_id for item in existing_items if item.job_role_id
    }
    db.add_all(
        [
            CatalogVersionItem(
                id=uuid4(),
                catalog_version_id=catalog.id,
                item_type="capability",
                capability_id=capability_id,
                change_type="added",
            )
            for capability_id in active_capability_ids - existing_capability_ids
        ]
        + [
            CatalogVersionItem(
                id=uuid4(),
                catalog_version_id=catalog.id,
                item_type="job_role",
                job_role_id=job_role_id,
                change_type="added",
            )
            for job_role_id in active_job_role_ids - existing_job_role_ids
        ]
    )
    now = datetime.now(UTC)
    catalog_now = now.replace(tzinfo=None)
    await db.execute(
        update(CatalogVersion)
        .where(
            CatalogVersion.status == "published",
            CatalogVersion.is_current.is_(True),
            CatalogVersion.id != catalog.id,
        )
        .values(is_current=False)
    )
    catalog.status = "published"
    catalog.is_current = True
    catalog.published_at = catalog_now
    catalog.summary = {
        **catalog.summary,
        "active_capability_count": len(active_capability_ids),
        "active_job_role_count": len(active_job_role_ids),
    }
    await db.execute(
        update(GraphVersion)
        .where(
            GraphVersion.status == "published",
            GraphVersion.is_current.is_(True),
            GraphVersion.id != version.id,
        )
        .values(is_current=False)
    )
    proposal = await db.get(GraphChangeCandidate, version.source_proposal_id)
    if proposal is None:
        raise ValueError("source proposal is missing")
    proposal.review_status = "published"
    version.status = "published"
    version.is_current = True
    version.published_at = now
    version.last_error = None
    record_audit(
        db,
        action="graph.version.publish",
        resource_type="graph_version",
        resource_id=version.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={
            "source_proposal_id": str(version.source_proposal_id),
            "catalog_version_id": str(catalog.id),
        },
    )
    await db.commit()


async def _mark_failed(
    db: AsyncSession,
    actor_id: UUID,
    version_id: UUID,
    error: Exception,
    *,
    request_id: str | None,
    ip_address: str | None,
) -> None:
    version = await db.get(GraphVersion, version_id, populate_existing=True)
    if version is None:
        return
    version.status = "failed"
    version.last_error = type(error).__name__
    record_audit(
        db,
        action="graph.version.publish",
        resource_type="graph_version",
        resource_id=version.id,
        actor_user_id=actor_id,
        outcome="failed",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"error_type": type(error).__name__},
    )
    await db.commit()
