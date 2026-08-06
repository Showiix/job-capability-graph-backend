from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.catalog.models import CatalogVersion, Domain, JobRole
from app.core.errors import APIError
from app.graph.models import GraphVersion
from app.graph.query import get_global_graph
from app.graph.schemas import GraphEdge, GraphNode, GraphReadData, GraphVersionRead
from app.reviews.models import GraphChangeCandidate


async def _published_context(db_session, user):
    suffix = uuid4().hex
    domain = Domain(
        id=uuid4(),
        code=f"graph-read-{suffix}",
        name="人工智能",
        status="active",
        sort_order=0,
    )
    role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"AI 工程师-{suffix}",
        description="建设 AI 系统",
        definition_payload={"role_name": "AI 工程师"},
        status="active",
        source_type="manual",
    )
    proposal = GraphChangeCandidate(
        id=uuid4(),
        change_type="create_job_role",
        proposed_payload={"role_name": role.canonical_name},
        source_snapshot={},
        evidence_summary={},
        confidence=Decimal("0.9000"),
        review_status="published",
        created_by_user_id=user.id,
        reviewed_by_user_id=user.id,
        reviewed_at=datetime.now(UTC),
    )
    db_session.add_all([domain, role, proposal])
    await db_session.flush()
    catalog = CatalogVersion(
        id=uuid4(),
        version_no=(
            await db_session.scalar(select(func.max(CatalogVersion.version_no))) or 0
        )
        + 1,
        status="published",
        is_current=True,
        created_by_user_id=user.id,
        summary={"source": "graph_read_test"},
        published_at=datetime.now(UTC),
    )
    version = GraphVersion(
        id=uuid4(),
        version_no=(
            await db_session.scalar(select(func.max(GraphVersion.version_no))) or 0
        )
        + 1,
        source_proposal_id=proposal.id,
        catalog_version_id=catalog.id,
        job_role_id=role.id,
        status="published",
        is_current=True,
        snapshot={"job_role": {"id": str(role.id)}},
        attempt_count=1,
        created_by_user_id=user.id,
        published_at=datetime.now(UTC),
    )
    db_session.add_all([catalog, version])
    await db_session.flush()
    return SimpleNamespace(domain=domain, role=role, version=version)


def test_graph_read_schema_contract() -> None:
    version_id = uuid4()
    role_id = uuid4()
    capability_id = uuid4()
    value = GraphReadData(
        graph_version=GraphVersionRead(
            id=version_id,
            version_no=3,
            published_at=datetime(2026, 8, 6, tzinfo=UTC),
        ),
        nodes=[
            GraphNode(
                id=role_id,
                type="job_role",
                name="AI 自动化测试工程师",
                properties={"status": "active"},
            )
        ],
        edges=[
            GraphEdge(
                id="a" * 64,
                type="requires",
                source=role_id,
                target=capability_id,
                properties={"importance": 1.0},
            )
        ],
        truncated=False,
    )

    assert value.graph_version.id == version_id
    assert value.nodes[0].type == "job_role"
    assert value.edges[0].type == "requires"


async def test_global_graph_requires_current_published_version(
    db_session,
) -> None:
    class DriverMustNotRun:
        async def execute_query(self, query: str, *, parameters_: dict):
            raise AssertionError("Neo4j must not run without a current version")

    with pytest.raises(APIError) as error:
        await get_global_graph(
            db_session,
            domain_id=None,
            max_job_roles=30,
            max_capabilities=120,
            driver=DriverMustNotRun(),
        )

    assert error.value.status_code == 404
    assert error.value.code == "GRAPH_VERSION_NOT_PUBLISHED"
