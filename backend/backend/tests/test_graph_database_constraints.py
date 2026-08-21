from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.catalog.models import (
    Capability,
    CatalogVersion,
    Domain,
    JobRole,
    JobRoleCapability,
)
from app.graph.models import GraphVersion
from app.reviews.models import GraphChangeCandidate


async def _context(db_session, user):
    value = uuid4().hex
    domain = Domain(
        id=uuid4(),
        code=f"graph-{value}",
        name="Graph",
        status="active",
        sort_order=0,
    )
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        status="active",
        skill_type="language",
        source_type="manual",
    )
    role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="AI Engineer",
        description="Build AI systems",
        definition_payload={"role_name": "AI Engineer"},
        status="active",
        source_type="manual",
    )
    proposal = GraphChangeCandidate(
        id=uuid4(),
        change_type="create_job_role",
        proposed_payload={"role_name": "AI Test Engineer"},
        source_snapshot={},
        evidence_summary={"support_job_count": 3},
        confidence=0.8,
        review_status="approved",
        created_by_user_id=user.id,
    )
    catalog_version = CatalogVersion(
        id=uuid4(),
        version_no=1000,
        status="draft",
        is_current=False,
        created_by_user_id=user.id,
        summary={},
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add_all([capability, role, proposal, catalog_version])
    await db_session.flush()
    return {
        "domain": domain,
        "capability": capability,
        "role": role,
        "proposal": proposal,
        "catalog_version": catalog_version,
    }


def _graph_version(context, user, *, version_no: int = 1000) -> GraphVersion:
    return GraphVersion(
        id=uuid4(),
        version_no=version_no,
        source_proposal_id=context["proposal"].id,
        catalog_version_id=context["catalog_version"].id,
        job_role_id=uuid4(),
        status="draft",
        is_current=False,
        snapshot={},
        attempt_count=0,
        created_by_user_id=user.id,
    )


async def test_job_role_definition_must_be_json_object(db_session, user) -> None:
    context = await _context(db_session, user)
    context["role"].definition_payload = []

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_job_role_capability_is_unique_and_constrained(
    db_session,
    user,
) -> None:
    context = await _context(db_session, user)
    def relation() -> JobRoleCapability:
        return JobRoleCapability(
            job_role_id=context["role"].id,
            capability_id=context["capability"].id,
            requirement_type="required",
            importance=0.8,
            source_candidate_id=context["proposal"].id,
        )

    db_session.add_all([relation(), relation()])
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    ("field", "value"),
    (("requirement_type", "optional"), ("importance", 1.1)),
)
async def test_job_role_capability_values_are_constrained(
    db_session,
    user,
    field,
    value,
) -> None:
    context = await _context(db_session, user)
    relation = JobRoleCapability(
        job_role_id=context["role"].id,
        capability_id=context["capability"].id,
        requirement_type="required",
        importance=0.8,
        source_candidate_id=context["proposal"].id,
    )
    setattr(relation, field, value)
    db_session.add(relation)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("status", "abandoned"),
        ("attempt_count", -1),
        ("snapshot", []),
        ("version_no", 0),
    ),
)
async def test_graph_version_values_are_constrained(
    db_session,
    user,
    field,
    value,
) -> None:
    context = await _context(db_session, user)
    version = _graph_version(context, user)
    setattr(version, field, value)
    db_session.add(version)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    ("status", "published_at"),
    (("published", None), ("draft", datetime.now(UTC))),
)
async def test_graph_version_published_at_matches_status(
    db_session,
    user,
    status,
    published_at,
) -> None:
    context = await _context(db_session, user)
    version = _graph_version(context, user)
    version.status = status
    version.published_at = published_at
    db_session.add(version)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_graph_version_sources_are_unique(db_session, user) -> None:
    context = await _context(db_session, user)
    first = _graph_version(context, user)
    second = _graph_version(context, user)
    second.version_no += 1
    second.job_role_id = uuid4()
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_review_proposal_can_enter_published_state(db_session, user) -> None:
    context = await _context(db_session, user)
    context["proposal"].review_status = "published"

    await db_session.flush()

    assert context["proposal"].review_status == "published"
