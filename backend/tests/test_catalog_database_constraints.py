from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.catalog.models import (
    Capability,
    CapabilityAlias,
    CatalogVersion,
    CatalogVersionItem,
    Domain,
    JobRole,
)


async def test_domain_cannot_parent_itself(db_session) -> None:
    domain = Domain(
        id=uuid4(),
        code="ai",
        name="AI",
        status="active",
        sort_order=0,
    )
    db_session.add(domain)
    await db_session.flush()
    domain.parent_id = domain.id

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_capability_name_is_unique_in_domain(db_session) -> None:
    domain = Domain(id=uuid4(), code="data", name="Data", status="active", sort_order=0)
    db_session.add(domain)
    await db_session.flush()
    db_session.add_all(
        [
            Capability(
                id=uuid4(),
                domain_id=domain.id,
                canonical_name="Python",
                status="candidate",
                skill_type="language",
                source_type="manual",
            ),
            Capability(
                id=uuid4(),
                domain_id=domain.id,
                canonical_name="Python",
                status="candidate",
                skill_type="language",
                source_type="manual",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_alias_cannot_point_to_two_capabilities(db_session) -> None:
    domain = Domain(
        id=uuid4(), code="ai_alias", name="AI Alias", status="active", sort_order=0
    )
    first = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Machine Learning",
        status="candidate",
        skill_type="method",
        source_type="manual",
    )
    second = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="ML",
        status="candidate",
        skill_type="method",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add_all([first, second])
    await db_session.flush()
    db_session.add_all(
        [
            CapabilityAlias(
                id=uuid4(),
                capability_id=first.id,
                alias="ML",
                status="active",
            ),
            CapabilityAlias(
                id=uuid4(),
                capability_id=second.id,
                alias="ML",
                status="active",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_job_role_defaults_to_candidate(db_session) -> None:
    domain = Domain(id=uuid4(), code="role", name="Role", status="active", sort_order=0)
    role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="AI Engineer",
        source_type="manual",
    )
    db_session.add_all([domain, role])
    await db_session.flush()

    assert role.status == "candidate"


async def test_catalog_version_item_requires_one_target(db_session, user) -> None:
    version = CatalogVersion(
        id=uuid4(),
        version_no=1,
        status="draft",
        is_current=False,
        created_by_user_id=user.id,
        summary={},
    )
    db_session.add(version)
    await db_session.flush()
    db_session.add(
        CatalogVersionItem(
            id=uuid4(),
            catalog_version_id=version.id,
            item_type="capability",
            capability_id=None,
            job_role_id=None,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
