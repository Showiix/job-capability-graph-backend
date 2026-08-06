import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Domain
from app.core.errors import APIError
from app.graph.models import GraphVersion
from app.graph.schemas import GraphEdge, GraphNode, GraphReadData, GraphVersionRead
from app.infrastructure.neo4j import neo4j_driver

logger = logging.getLogger(__name__)

GLOBAL_ROLE_QUERY = """
MATCH (role:JobRole {status: 'active'})
      -[belongs:BELONGS_TO]->(domain:Domain)
WHERE $domain_id IS NULL OR domain.id = $domain_id
RETURN role {
         .id,
         .canonical_name,
         .description,
         .status
       } AS role,
       domain {
         .id,
         .code,
         .name
       } AS domain,
       belongs.relation_key AS relation_key
ORDER BY toLower(role.canonical_name), role.id
LIMIT $role_limit
"""

GLOBAL_CAPABILITY_QUERY = """
UNWIND $job_role_ids AS role_id
MATCH (role:JobRole {id: role_id, status: 'active'})
MATCH (role)-[requirement]->(capability:Capability {status: 'active'})
WHERE type(requirement) IN ['REQUIRES', 'BONUS']
MATCH (capability)-[belongs:BELONGS_TO]->(domain:Domain)
RETURN role.id AS role_id,
       requirement.relation_key AS requirement_relation_key,
       type(requirement) AS requirement_type,
       requirement.importance AS importance,
       capability {
         .id,
         .canonical_name,
         .skill_type,
         .status
       } AS capability,
       domain {
         .id,
         .code,
         .name
       } AS domain,
       belongs.relation_key AS domain_relation_key
ORDER BY toLower(capability.canonical_name),
         capability.id,
         role.id
LIMIT $relation_limit
"""


def _projection_inconsistent() -> APIError:
    return APIError(
        503,
        "GRAPH_PROJECTION_INCONSISTENT",
        "正式图谱投影不一致",
    )


async def _execute_read(driver, query: str, parameters: dict) -> list[Any]:
    try:
        records, _, _ = await driver.execute_query(
            query,
            parameters_=parameters,
        )
    except Exception as error:
        logger.warning("graph read failed: %s", type(error).__name__)
        raise APIError(503, "GRAPH_READ_FAILED", "图谱读取失败") from None
    return list(records)


async def _current_graph_version(db: AsyncSession) -> GraphVersion:
    version = await db.scalar(
        select(GraphVersion).where(
            GraphVersion.status == "published",
            GraphVersion.is_current.is_(True),
        )
    )
    if version is None:
        raise APIError(
            404,
            "GRAPH_VERSION_NOT_PUBLISHED",
            "当前尚无已发布图谱版本",
        )
    return version


def _version_data(version: GraphVersion) -> GraphVersionRead:
    if version.published_at is None:
        raise _projection_inconsistent()
    return GraphVersionRead(
        id=version.id,
        version_no=version.version_no,
        published_at=version.published_at,
    )


async def _require_active_domain(db: AsyncSession, domain_id: UUID) -> None:
    exists = await db.scalar(
        select(Domain.id).where(
            Domain.id == domain_id,
            Domain.status == "active",
        )
    )
    if exists is None:
        raise APIError(
            404,
            "GRAPH_DOMAIN_NOT_FOUND",
            "技术域不存在或未启用",
        )


def _uuid(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise _projection_inconsistent() from None


def _relation_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise _projection_inconsistent()
    return value


def _domain_node(value: dict) -> GraphNode:
    return GraphNode(
        id=_uuid(value.get("id")),
        type="domain",
        name=str(value["name"]),
        properties={"code": value["code"], "status": "active"},
    )


def _role_node(value: dict) -> GraphNode:
    return GraphNode(
        id=_uuid(value.get("id")),
        type="job_role",
        name=str(value["canonical_name"]),
        properties={
            "status": value["status"],
            "description": value.get("description"),
        },
    )


def _capability_node(value: dict) -> GraphNode:
    return GraphNode(
        id=_uuid(value.get("id")),
        type="capability",
        name=str(value["canonical_name"]),
        properties={
            "status": value["status"],
            "skill_type": value["skill_type"],
        },
    )


def _sorted_nodes(nodes: dict[tuple[str, UUID], GraphNode]) -> list[GraphNode]:
    type_order = {"domain": 0, "job_role": 1, "capability": 2}
    return sorted(
        nodes.values(),
        key=lambda node: (
            type_order[node.type],
            node.name.casefold(),
            str(node.id),
        ),
    )


def _sorted_edges(edges: dict[str, GraphEdge]) -> list[GraphEdge]:
    return sorted(
        edges.values(),
        key=lambda edge: (
            edge.type,
            str(edge.source),
            str(edge.target),
            edge.id,
        ),
    )


def _normalize_graph(
    version: GraphVersion,
    role_records: list[Any],
    capability_records: list[Any],
    *,
    max_capabilities: int | None,
    truncated: bool,
) -> GraphReadData:
    nodes: dict[tuple[str, UUID], GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    returned_role_ids: set[UUID] = set()

    try:
        for record in role_records:
            role = _role_node(dict(record["role"]))
            domain = _domain_node(dict(record["domain"]))
            nodes[(role.type, role.id)] = role
            nodes[(domain.type, domain.id)] = domain
            returned_role_ids.add(role.id)
            edge_id = _relation_id(record["relation_key"])
            edges.setdefault(
                edge_id,
                GraphEdge(
                    id=edge_id,
                    type="belongs_to",
                    source=role.id,
                    target=domain.id,
                ),
            )

        ordered_records = sorted(
            capability_records,
            key=lambda record: (
                str(record["capability"]["canonical_name"]).casefold(),
                str(record["capability"]["id"]),
                str(record["role_id"]),
            ),
        )
        selected_capability_ids: set[UUID] = set()
        for record in ordered_records:
            capability_id = _uuid(record["capability"]["id"])
            if capability_id in selected_capability_ids:
                continue
            if (
                max_capabilities is not None
                and len(selected_capability_ids) >= max_capabilities
            ):
                truncated = True
                continue
            selected_capability_ids.add(capability_id)

        for record in ordered_records:
            role_id = _uuid(record["role_id"])
            capability = _capability_node(dict(record["capability"]))
            if (
                role_id not in returned_role_ids
                or capability.id not in selected_capability_ids
            ):
                continue
            domain = _domain_node(dict(record["domain"]))
            nodes[(capability.type, capability.id)] = capability
            nodes[(domain.type, domain.id)] = domain

            domain_edge_id = _relation_id(record["domain_relation_key"])
            edges.setdefault(
                domain_edge_id,
                GraphEdge(
                    id=domain_edge_id,
                    type="belongs_to",
                    source=capability.id,
                    target=domain.id,
                ),
            )
            requirement_type = str(record["requirement_type"])
            if requirement_type not in {"REQUIRES", "BONUS"}:
                raise _projection_inconsistent()
            requirement_edge_id = _relation_id(
                record["requirement_relation_key"]
            )
            edges.setdefault(
                requirement_edge_id,
                GraphEdge(
                    id=requirement_edge_id,
                    type=(
                        "requires" if requirement_type == "REQUIRES" else "bonus"
                    ),
                    source=role_id,
                    target=capability.id,
                    properties={"importance": float(record["importance"])},
                ),
            )
    except APIError:
        raise
    except (KeyError, TypeError, ValueError):
        raise _projection_inconsistent() from None

    returned_ids = {node.id for node in nodes.values()}
    edges = {
        edge_id: edge
        for edge_id, edge in edges.items()
        if edge.source in returned_ids and edge.target in returned_ids
    }
    return GraphReadData(
        graph_version=_version_data(version),
        nodes=_sorted_nodes(nodes),
        edges=_sorted_edges(edges),
        truncated=truncated,
    )


async def get_global_graph(
    db: AsyncSession,
    *,
    domain_id: UUID | None,
    max_job_roles: int,
    max_capabilities: int,
    driver=neo4j_driver,
) -> GraphReadData:
    version = await _current_graph_version(db)
    if domain_id is not None:
        await _require_active_domain(db, domain_id)

    role_records = await _execute_read(
        driver,
        GLOBAL_ROLE_QUERY,
        {
            "domain_id": str(domain_id) if domain_id is not None else None,
            "role_limit": max_job_roles + 1,
        },
    )
    if not role_records:
        if domain_id is None:
            raise _projection_inconsistent()
        return GraphReadData(
            graph_version=_version_data(version),
            nodes=[],
            edges=[],
            truncated=False,
        )

    try:
        role_records = sorted(
            role_records,
            key=lambda record: (
                str(record["role"]["canonical_name"]).casefold(),
                str(record["role"]["id"]),
            ),
        )
    except (KeyError, TypeError):
        raise _projection_inconsistent() from None
    role_overflow = len(role_records) > max_job_roles
    role_records = role_records[:max_job_roles]
    job_role_ids = [str(record["role"]["id"]) for record in role_records]
    relation_limit = max_job_roles * 40 + 1
    capability_records = await _execute_read(
        driver,
        GLOBAL_CAPABILITY_QUERY,
        {
            "job_role_ids": job_role_ids,
            "relation_limit": relation_limit,
        },
    )
    relation_overflow = len(capability_records) >= relation_limit
    if relation_overflow:
        capability_records = capability_records[: relation_limit - 1]

    return _normalize_graph(
        version,
        role_records,
        capability_records,
        max_capabilities=max_capabilities,
        truncated=role_overflow or relation_overflow,
    )
