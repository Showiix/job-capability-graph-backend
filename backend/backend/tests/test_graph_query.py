from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.catalog.models import CatalogVersion, Domain, JobRole
from app.core.errors import APIError
from app.graph.models import GraphVersion
from app.graph.neo4j import relation_key
from app.graph.query import get_global_graph, get_job_role_graph
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
        published_at=datetime.now(UTC).replace(tzinfo=None),
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


class FakeAsyncDriver:
    def __init__(self, *responses: list[dict], error: Exception | None = None):
        self.responses = [deepcopy(response) for response in responses]
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, *, parameters_: dict):
        self.calls.append((query, deepcopy(parameters_)))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0), None, None


def _role_record(context, *, relation_id: str | None = None) -> dict:
    return {
        "role": {
            "id": str(context.role.id),
            "canonical_name": context.role.canonical_name,
            "description": context.role.description,
            "status": "active",
        },
        "domain": {
            "id": str(context.domain.id),
            "code": context.domain.code,
            "name": context.domain.name,
        },
        "relation_key": (
            relation_id
            if relation_id is not None
            else relation_key(
                "BELONGS_TO",
                str(context.role.id),
                str(context.domain.id),
            )
        ),
    }


def _capability_record(
    context,
    capability_id,
    name: str,
    *,
    requirement_type: str,
    role_id=None,
) -> dict:
    role_id = role_id or context.role.id
    return {
        "role_id": str(role_id),
        "requirement_relation_key": relation_key(
            requirement_type,
            str(role_id),
            str(capability_id),
        ),
        "requirement_type": requirement_type,
        "importance": 1.0 if requirement_type == "REQUIRES" else 0.5,
        "capability": {
            "id": str(capability_id),
            "canonical_name": name,
            "skill_type": "method",
            "status": "active",
        },
        "domain": {
            "id": str(context.domain.id),
            "code": context.domain.code,
            "name": context.domain.name,
        },
        "domain_relation_key": relation_key(
            "BELONGS_TO",
            str(capability_id),
            str(context.domain.id),
        ),
    }


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


async def test_global_graph_maps_filters_deduplicates_and_sorts(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    python_id = uuid4()
    testing_id = uuid4()
    python = _capability_record(
        context,
        python_id,
        "Python",
        requirement_type="REQUIRES",
    )
    testing = _capability_record(
        context,
        testing_id,
        "自动化测试",
        requirement_type="BONUS",
    )
    dangling = _capability_record(
        context,
        uuid4(),
        "不应返回",
        requirement_type="REQUIRES",
        role_id=uuid4(),
    )
    driver = FakeAsyncDriver(
        [_role_record(context)],
        [testing, python, deepcopy(python), dangling],
    )

    result = await get_global_graph(
        db_session,
        domain_id=context.domain.id,
        max_job_roles=30,
        max_capabilities=120,
        driver=driver,
    )

    assert result.graph_version.id == context.version.id
    assert [(node.type, node.name) for node in result.nodes] == [
        ("domain", "人工智能"),
        ("job_role", context.role.canonical_name),
        ("capability", "Python"),
        ("capability", "自动化测试"),
    ]
    assert {(edge.type, edge.source, edge.target) for edge in result.edges} == {
        ("belongs_to", context.role.id, context.domain.id),
        ("belongs_to", python_id, context.domain.id),
        ("belongs_to", testing_id, context.domain.id),
        ("bonus", context.role.id, testing_id),
        ("requires", context.role.id, python_id),
    }
    assert result.truncated is False
    assert len({edge.id for edge in result.edges}) == 5
    assert driver.calls[0][1] == {
        "domain_id": str(context.domain.id),
        "role_limit": 31,
    }
    assert driver.calls[1][1]["job_role_ids"] == [str(context.role.id)]
    assert driver.calls[1][1]["relation_limit"] == 1201


async def test_global_graph_sets_truncated_for_each_limit(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    second_role_id = uuid4()
    third_role_id = uuid4()
    roles = [
        _role_record(context),
        {
            **_role_record(context),
            "role": {
                **_role_record(context)["role"],
                "id": str(second_role_id),
                "canonical_name": "第二岗位",
            },
            "relation_key": relation_key(
                "BELONGS_TO", str(second_role_id), str(context.domain.id)
            ),
        },
        {
            **_role_record(context),
            "role": {
                **_role_record(context)["role"],
                "id": str(third_role_id),
                "canonical_name": "第三岗位",
            },
            "relation_key": relation_key(
                "BELONGS_TO", str(third_role_id), str(context.domain.id)
            ),
        },
    ]
    capabilities = [
        _capability_record(
            context,
            uuid4(),
            f"技能-{index:03d}",
            requirement_type="REQUIRES",
        )
        for index in range(42)
    ]
    driver = FakeAsyncDriver(roles, capabilities)

    result = await get_global_graph(
        db_session,
        domain_id=None,
        max_job_roles=1,
        max_capabilities=1,
        driver=driver,
    )

    assert len([node for node in result.nodes if node.type == "job_role"]) == 1
    assert len([node for node in result.nodes if node.type == "capability"]) == 1
    assert result.truncated is True
    assert driver.calls[0][1]["role_limit"] == 2
    assert driver.calls[1][1]["relation_limit"] == 41


async def test_global_graph_validates_domain_and_empty_projection(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    inactive = Domain(
        id=uuid4(),
        code=f"inactive-{uuid4().hex}",
        name="停用技术域",
        status="deprecated",
        sort_order=1,
    )
    db_session.add(inactive)
    await db_session.flush()

    with pytest.raises(APIError) as missing:
        await get_global_graph(
            db_session,
            domain_id=inactive.id,
            max_job_roles=30,
            max_capabilities=120,
            driver=FakeAsyncDriver(),
        )
    assert missing.value.code == "GRAPH_DOMAIN_NOT_FOUND"

    empty = await get_global_graph(
        db_session,
        domain_id=context.domain.id,
        max_job_roles=30,
        max_capabilities=120,
        driver=FakeAsyncDriver([]),
    )
    assert empty.nodes == []
    assert empty.edges == []
    assert empty.truncated is False

    with pytest.raises(APIError) as inconsistent:
        await get_global_graph(
            db_session,
            domain_id=None,
            max_job_roles=30,
            max_capabilities=120,
            driver=FakeAsyncDriver([]),
        )
    assert inconsistent.value.code == "GRAPH_PROJECTION_INCONSISTENT"


async def test_global_graph_rejects_missing_relation_key_and_sanitizes_driver_error(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    with pytest.raises(APIError) as missing_key:
        await get_global_graph(
            db_session,
            domain_id=None,
            max_job_roles=30,
            max_capabilities=120,
            driver=FakeAsyncDriver(
                [_role_record(context, relation_id="")],
                [],
            ),
        )
    assert missing_key.value.code == "GRAPH_PROJECTION_INCONSISTENT"

    with pytest.raises(APIError) as failed:
        await get_global_graph(
            db_session,
            domain_id=None,
            max_job_roles=30,
            max_capabilities=120,
            driver=FakeAsyncDriver(
                error=RuntimeError("bolt://neo4j:secret@internal:7687 QUERY")
            ),
        )
    assert failed.value.code == "GRAPH_READ_FAILED"
    assert "bolt" not in failed.value.message
    assert "secret" not in failed.value.message
    assert failed.value.details == {}


async def test_job_role_graph_returns_complete_local_subgraph(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    python_id = uuid4()
    cicd_id = uuid4()
    required = _capability_record(
        context,
        python_id,
        "Python",
        requirement_type="REQUIRES",
    )
    bonus = _capability_record(
        context,
        cicd_id,
        "CI/CD",
        requirement_type="BONUS",
    )
    role_record = _role_record(context)
    records = []
    for capability in (required, bonus):
        records.append(
            {
                **capability,
                "role": role_record["role"],
                "domain": role_record["domain"],
                "relation_key": role_record["relation_key"],
                "capability_domain": capability["domain"],
            }
        )
    driver = FakeAsyncDriver(records)

    result = await get_job_role_graph(
        db_session,
        context.role.id,
        driver=driver,
    )

    assert result.graph_version.id == context.version.id
    assert {node.id for node in result.nodes} == {
        context.domain.id,
        context.role.id,
        python_id,
        cicd_id,
    }
    assert {edge.type for edge in result.edges} == {
        "belongs_to",
        "requires",
        "bonus",
    }
    assert result.truncated is False
    assert driver.calls[0][1] == {"job_role_id": str(context.role.id)}


async def test_job_role_graph_allows_role_without_capabilities(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)
    empty_record = {
        **_role_record(context),
        "role_id": str(context.role.id),
        "requirement_relation_key": None,
        "requirement_type": None,
        "importance": None,
        "capability": None,
        "capability_domain": None,
        "domain_relation_key": None,
    }

    result = await get_job_role_graph(
        db_session,
        context.role.id,
        driver=FakeAsyncDriver([empty_record]),
    )

    assert [(node.type, node.id) for node in result.nodes] == [
        ("domain", context.domain.id),
        ("job_role", context.role.id),
    ]
    assert len(result.edges) == 1
    assert result.edges[0].type == "belongs_to"
    assert result.truncated is False


async def test_job_role_graph_validates_formal_role_and_current_version(
    db_session,
    user,
) -> None:
    domain = Domain(
        id=uuid4(),
        code=f"job-role-validation-{uuid4().hex}",
        name="岗位校验域",
        status="active",
        sort_order=0,
    )
    role = JobRole(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=f"待发布岗位-{uuid4().hex}",
        definition_payload={},
        status="active",
        source_type="manual",
    )
    db_session.add_all([domain, role])
    await db_session.flush()
    driver = FakeAsyncDriver(error=AssertionError("driver must not run"))

    with pytest.raises(APIError) as unpublished:
        await get_job_role_graph(db_session, role.id, driver=driver)
    assert unpublished.value.code == "GRAPH_VERSION_NOT_PUBLISHED"

    with pytest.raises(APIError) as missing:
        await get_job_role_graph(db_session, uuid4(), driver=driver)
    assert missing.value.code == "GRAPH_JOB_ROLE_NOT_FOUND"
    assert driver.calls == []


async def test_job_role_graph_rejects_missing_neo4j_projection(
    db_session,
    user,
) -> None:
    context = await _published_context(db_session, user)

    with pytest.raises(APIError) as error:
        await get_job_role_graph(
            db_session,
            context.role.id,
            driver=FakeAsyncDriver([]),
        )

    assert error.value.status_code == 503
    assert error.value.code == "GRAPH_PROJECTION_INCONSISTENT"
