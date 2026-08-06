from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.audit.models import AuditLog
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
from app.graph.neo4j import GraphPublishResult, relation_key
from app.graph.service import create_graph_version, publish_graph_version
from app.reviews.models import GraphChangeCandidate


async def _context(db_session, user) -> dict:
    suffix = uuid4().hex
    domain = Domain(
        id=uuid4(),
        code=f"ai-{suffix}",
        name="人工智能",
        status="active",
        sort_order=0,
    )
    bonus_domain = Domain(
        id=uuid4(),
        code=f"engineering-{suffix}",
        name="软件工程",
        status="active",
        sort_order=1,
    )
    db_session.add_all([domain, bonus_domain])
    await db_session.flush()

    capabilities = [
        Capability(
            id=uuid4(),
            domain_id=domain.id,
            canonical_name=f"Python-{suffix}",
            skill_type="language",
            status="active",
            source_type="manual",
        ),
        Capability(
            id=uuid4(),
            domain_id=domain.id,
            canonical_name=f"自动化测试-{suffix}",
            skill_type="method",
            status="active",
            source_type="manual",
        ),
        Capability(
            id=uuid4(),
            domain_id=bonus_domain.id,
            canonical_name=f"CI/CD-{suffix}",
            skill_type="tool",
            status="active",
            source_type="manual",
        ),
    ]
    existing_role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"既有岗位-{suffix}",
        description="既有岗位",
        definition_payload={"role_name": "既有岗位"},
        status="active",
        source_type="manual",
    )
    proposal = GraphChangeCandidate(
        id=uuid4(),
        change_type="create_job_role",
        proposed_payload={
            "role_name": f"AI 自动化测试工程师-{suffix}",
            "core_responsibilities": ["建设 AI 产品自动化测试体系"],
            "required_capability_ids": [
                str(capabilities[0].id),
                str(capabilities[1].id),
            ],
            "bonus_capability_ids": [str(capabilities[2].id)],
            "industry_scenarios": ["AI 产品质量保障"],
            "generation_source": "human_revision",
            "definition_status": "reviewed",
            "disclaimer": "人工审核后发布",
        },
        source_snapshot={"candidate_id": str(uuid4())},
        evidence_summary={"support_job_count": 5, "source_count": 2},
        confidence=0.9,
        review_status="approved",
        created_by_user_id=user.id,
        reviewed_by_user_id=user.id,
        reviewed_at=datetime.now(UTC),
    )
    previous_proposal = GraphChangeCandidate(
        id=uuid4(),
        change_type="create_job_role",
        proposed_payload={"role_name": existing_role.canonical_name},
        source_snapshot={},
        evidence_summary={},
        confidence=0.8,
        review_status="published",
        created_by_user_id=user.id,
        reviewed_by_user_id=user.id,
        reviewed_at=datetime.now(UTC),
    )
    db_session.add_all([*capabilities, existing_role, proposal, previous_proposal])
    await db_session.flush()

    catalog_no = (
        await db_session.scalar(select(func.max(CatalogVersion.version_no))) or 0
    ) + 1
    previous_catalog = CatalogVersion(
        id=uuid4(),
        version_no=catalog_no,
        status="published",
        is_current=True,
        created_by_user_id=user.id,
        summary={"source": "test"},
        published_at=datetime.now(UTC).replace(tzinfo=None),
    )
    graph_no = (
        await db_session.scalar(select(func.max(GraphVersion.version_no))) or 0
    ) + 1
    previous_graph = GraphVersion(
        id=uuid4(),
        version_no=graph_no,
        source_proposal_id=previous_proposal.id,
        catalog_version_id=previous_catalog.id,
        job_role_id=existing_role.id,
        status="published",
        is_current=True,
        snapshot={"job_role": {"id": str(existing_role.id)}},
        attempt_count=1,
        created_by_user_id=user.id,
        published_at=datetime.now(UTC),
    )
    db_session.add_all([previous_catalog, previous_graph])
    await db_session.flush()
    return {
        "domain": domain,
        "bonus_domain": bonus_domain,
        "capabilities": capabilities,
        "existing_role": existing_role,
        "proposal": proposal,
        "previous_catalog": previous_catalog,
        "previous_graph": previous_graph,
    }


async def _successful_publish(snapshot: dict, version_no: int) -> GraphPublishResult:
    capabilities = snapshot["capabilities"]
    required_count = sum(
        item["requirement_type"] == "required" for item in capabilities
    )
    return GraphPublishResult(
        job_role_id=snapshot["job_role"]["id"],
        capability_count=len(capabilities),
        relation_count=len(capabilities),
        required_count=required_count,
        bonus_count=len(capabilities) - required_count,
    )


async def test_create_graph_version_freezes_an_idempotent_draft(
    db_session,
    user,
) -> None:
    context = await _context(db_session, user)

    version = await create_graph_version(
        db_session,
        user,
        context["proposal"].id,
        request_id="create-graph",
        ip_address="127.0.0.1",
    )
    repeated = await create_graph_version(
        db_session,
        user,
        context["proposal"].id,
        request_id="create-graph-again",
        ip_address="127.0.0.1",
    )

    assert repeated.id == version.id
    assert version.status == "draft"
    assert version.attempt_count == 0
    assert await db_session.get(JobRole, version.job_role_id) is None
    catalog = await db_session.get(CatalogVersion, version.catalog_version_id)
    assert catalog.status == "draft"
    assert version.snapshot["domain"]["id"] == str(context["domain"].id)
    assert version.snapshot["job_role"]["id"] == str(version.job_role_id)
    first_capability = version.snapshot["capabilities"][0]
    assert first_capability["role_relation_key"] == relation_key(
        "REQUIRES",
        str(version.job_role_id),
        first_capability["id"],
    )


async def test_create_graph_version_rejects_ambiguous_required_domain(
    db_session,
    user,
) -> None:
    context = await _context(db_session, user)
    context["capabilities"][1].domain_id = context["bonus_domain"].id
    await db_session.flush()

    with pytest.raises(APIError) as error:
        await create_graph_version(
            db_session,
            user,
            context["proposal"].id,
            request_id="ambiguous-domain",
            ip_address=None,
        )

    assert error.value.code == "GRAPH_DOMAIN_AMBIGUOUS"


async def test_publish_failure_keeps_postgres_draft_data_inactive(
    db_session,
    user,
) -> None:
    context = await _context(db_session, user)
    version = await create_graph_version(
        db_session,
        user,
        context["proposal"].id,
        request_id="create-before-failure",
        ip_address=None,
    )

    async def fail_publish(snapshot: dict, version_no: int):
        raise RuntimeError("bolt://internal-host/secret")

    with pytest.raises(APIError) as error:
        await publish_graph_version(
            db_session,
            user,
            version.id,
            request_id="publish-failure",
            ip_address=None,
            publisher=fail_publish,
        )

    failed = await db_session.get(GraphVersion, version.id, populate_existing=True)
    catalog = await db_session.get(
        CatalogVersion,
        version.catalog_version_id,
        populate_existing=True,
    )
    proposal = await db_session.get(
        GraphChangeCandidate,
        context["proposal"].id,
        populate_existing=True,
    )
    assert error.value.code == "GRAPH_PUBLICATION_FAILED"
    assert failed.status == "failed"
    assert failed.attempt_count == 1
    assert failed.last_error == "RuntimeError"
    assert "secret" not in failed.last_error
    assert await db_session.get(JobRole, version.job_role_id) is None
    assert catalog.status == "draft"
    assert proposal.review_status == "approved"


async def test_publish_success_finalizes_postgres_catalog_and_review(
    db_session,
    user,
) -> None:
    context = await _context(db_session, user)
    version = await create_graph_version(
        db_session,
        user,
        context["proposal"].id,
        request_id="create-before-success",
        ip_address=None,
    )
    published_snapshots: list[dict] = []

    async def capture_publish(snapshot: dict, version_no: int):
        published_snapshots.append(deepcopy(snapshot))
        return await _successful_publish(snapshot, version_no)

    published = await publish_graph_version(
        db_session,
        user,
        version.id,
        request_id="publish-success",
        ip_address="127.0.0.1",
        publisher=capture_publish,
    )

    role = await db_session.get(JobRole, version.job_role_id)
    relations = (
        await db_session.scalars(
            select(JobRoleCapability).where(
                JobRoleCapability.job_role_id == version.job_role_id
            )
        )
    ).all()
    catalog = await db_session.get(CatalogVersion, version.catalog_version_id)
    items = (
        await db_session.scalars(
            select(CatalogVersionItem).where(
                CatalogVersionItem.catalog_version_id == catalog.id
            )
        )
    ).all()
    proposal = await db_session.get(
        GraphChangeCandidate,
        context["proposal"].id,
    )
    await db_session.refresh(context["previous_catalog"])
    await db_session.refresh(context["previous_graph"])

    assert published.status == "published"
    assert published.is_current is True
    assert published.published_at is not None
    assert published.attempt_count == 1
    assert published_snapshots == [version.snapshot]
    assert role.status == "active"
    assert role.definition_payload == context["proposal"].proposed_payload
    assert {
        (value.requirement_type, float(value.importance)) for value in relations
    } == {
        ("required", 1.0),
        ("bonus", 0.5),
    }
    assert all(
        value.source_candidate_id == context["proposal"].id for value in relations
    )
    active_capability_ids = set(
        await db_session.scalars(
            select(Capability.id).where(Capability.status == "active")
        )
    )
    active_role_ids = set(
        await db_session.scalars(select(JobRole.id).where(JobRole.status == "active"))
    )
    assert {item.capability_id for item in items if item.capability_id} == (
        active_capability_ids
    )
    assert {item.job_role_id for item in items if item.job_role_id} == active_role_ids
    assert catalog.status == "published"
    assert catalog.is_current is True
    assert context["previous_catalog"].is_current is False
    assert context["previous_graph"].is_current is False
    assert proposal.review_status == "published"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "graph.version.publish",
                AuditLog.resource_id == version.id,
                AuditLog.outcome == "success",
            )
        )
        == 1
    )


async def test_failed_graph_version_can_retry_with_same_snapshot(
    db_session,
    user,
) -> None:
    context = await _context(db_session, user)
    version = await create_graph_version(
        db_session,
        user,
        context["proposal"].id,
        request_id="create-before-retry",
        ip_address=None,
    )

    async def fail_once(snapshot: dict, version_no: int):
        raise ConnectionError

    with pytest.raises(APIError):
        await publish_graph_version(
            db_session,
            user,
            version.id,
            request_id="first-attempt",
            ip_address=None,
            publisher=fail_once,
        )
    failed_snapshot = deepcopy(version.snapshot)

    published = await publish_graph_version(
        db_session,
        user,
        version.id,
        request_id="second-attempt",
        ip_address=None,
        publisher=_successful_publish,
    )

    assert published.status == "published"
    assert published.attempt_count == 2
    assert published.snapshot == failed_snapshot
    assert published.last_error is None
